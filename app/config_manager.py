"""
配置管理器 - 负责配置的加载、监听和热更新
"""
import asyncio
import logging
from typing import Dict, Any, Callable, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from .models import Config
from .config import (
    EMBEDDING_SERVICE_URL, LLM_SERVICE_URL, RERANKER_SERVICE_URL,
    SEARXNG_QUERY_URL, QDRANT_URL, QDRANT_HOST, QDRANT_PORT, QDRANT_API_KEY,
    QDRANT_COLLECTION_NAME, DEFAULT_TOOL_MODE, MAX_TOOL_STEPS,
    WEB_SEARCH_RESULT_COUNT, WEB_SEARCH_MAX_QUERIES, WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_CONCURRENT_REQUESTS, WEB_SEARCH_TIMEOUT, MAX_WORDS_PER_QUERY,
    MAX_KNOWLEDGE_GAPS, MAX_KEYWORDS_PER_GAP, GAP_RECALL_TOP_K,
    SIMPLE_QUERY_MAX_QUERIES, SIMPLE_QUERY_RESULT_COUNT, SIMPLE_QUERY_MAX_RESULTS,
    SIMPLE_QUERY_MAX_WORDS_PER_QUERY, WEB_LOADER_ENGINE, PLAYWRIGHT_TIMEOUT,
    ENABLE_QUERY_GENERATION, QUERY_GENERATION_PROMPT_TEMPLATE,
    WEB_CACHE_ENABLED, WEB_CACHE_MAX_SIZE, WEB_CACHE_TTL_SECONDS,
    WEB_CACHE_MAX_CONTENT_SIZE, CHUNK_SIZE, CHUNK_OVERLAP,
    RAG_TOP_K, QUERY_TOP_K_BEFORE_RERANK, RAG_RERANK_TOP_K, LLM_DEFAULT_TIMEOUT,
    DEFAULT_SEARCH_MODEL, DEFAULT_INGEST_MODEL, DEFAULT_EMBEDDING_MODEL,
    REASONING_TIMEOUT, WEB_SEARCH_LLM_TIMEOUT, HTTP_PROXY, HTTPS_PROXY, PROXY_URL,
    N8N_BASE_URL, N8N_API_KEY, N8N_USERNAME, N8N_PASSWORD, WEBHOOK_TIMEOUT, WEBHOOK_PREFIX
)
from .tools.orchestrator import get_orchestrator, initialize_orchestrator
from .embedding_client import embed_texts
from .vector_db_client import qdrant_client

logger = logging.getLogger(__name__)

# 全局配置存储
_config_cache: Dict[str, Any] = {}
_config_callbacks: Dict[str, Callable] = {}

def get_config_value(key: str, default: Any = None) -> Any:
    """获取配置值"""
    return _config_cache.get(key, default)

def set_config_value(key: str, value: Any):
    """设置配置值"""
    _config_cache[key] = value

def register_config_callback(key: str, callback: Callable):
    """注册配置变更回调函数"""
    _config_callbacks[key] = callback

# 定义所有默认配置项
DEFAULT_CONFIGS = [
    {
        "key": "database_url",
        "value": None,
        "type": "string",
        "description": "数据库连接URL",
        "default_value": None,
        "is_hot_reload": False
    },
    {
        "key": "embedding_service_url",
        "value": EMBEDDING_SERVICE_URL,
        "type": "string",
        "description": "嵌入服务URL",
        "default_value": EMBEDDING_SERVICE_URL,
        "is_hot_reload": True
    },
    {
        "key": "llm_service_url",
        "value": LLM_SERVICE_URL,
        "type": "string",
        "description": "LLM服务URL",
        "default_value": LLM_SERVICE_URL,
        "is_hot_reload": True
    },
    {
        "key": "reranker_service_url",
        "value": RERANKER_SERVICE_URL,
        "type": "string",
        "description": "重排序服务URL",
        "default_value": RERANKER_SERVICE_URL,
        "is_hot_reload": True
    },
    {
        "key": "searxng_query_url",
        "value": SEARXNG_QUERY_URL,
        "type": "string",
        "description": "Searxng搜索引擎URL",
        "default_value": SEARXNG_QUERY_URL,
        "is_hot_reload": True
    },
    {
        "key": "qdrant_url",
        "value": QDRANT_URL,
        "type": "string",
        "description": "Qdrant服务URL",
        "default_value": QDRANT_URL,
        "is_hot_reload": False  # 注意：Qdrant URL 不应热更新，因为需要重建客户端
    },
    {
        "key": "qdrant_host",
        "value": QDRANT_HOST,
        "type": "string",
        "description": "Qdrant主机地址",
        "default_value": QDRANT_HOST,
        "is_hot_reload": False
    },
    {
        "key": "qdrant_port",
        "value": QDRANT_PORT,
        "type": "string",
        "description": "Qdrant端口",
        "default_value": QDRANT_PORT,
        "is_hot_reload": False
    },
    {
        "key": "qdrant_api_key",
        "value": QDRANT_API_KEY,
        "type": "string",
        "description": "Qdrant API密钥",
        "default_value": QDRANT_API_KEY,
        "is_hot_reload": False
    },
    {
        "key": "qdrant_collection_name",
        "value": QDRANT_COLLECTION_NAME,
        "type": "string",
        "description": "Qdrant集合名称",
        "default_value": QDRANT_COLLECTION_NAME,
        "is_hot_reload": False
    },
    {
        "key": "reranker_max_tokens",
        "value": str(RERANKER_MAX_TOKENS),
        "type": "integer",
        "description": "重排序最大token数",
        "default_value": str(RERANKER_MAX_TOKENS),
        "is_hot_reload": True
    },
    {
        "key": "rerank_client_max_concurrency",
        "value": str(RERANK_CLIENT_MAX_CONCURRENCY),
        "type": "integer",
        "description": "重排序客户端最大并发数",
        "default_value": str(RERANK_CLIENT_MAX_CONCURRENCY),
        "is_hot_reload": True
    },
    {
        "key": "embedding_max_concurrency",
        "value": str(EMBEDDING_MAX_CONCURRENCY),
        "type": "integer",
        "description": "嵌入服务最大并发数",
        "default_value": str(EMBEDDING_MAX_CONCURRENCY),
        "is_hot_reload": True
    },
    {
        "key": "embedding_batch_size",
        "value": str(EMBEDDING_BATCH_SIZE),
        "type": "integer",
        "description": "嵌入服务批处理大小",
        "default_value": str(EMBEDDING_BATCH_SIZE),
        "is_hot_reload": True
    },
    {
        "key": "embedding_dimensions",
        "value": str(EMBEDDING_DIMENSIONS),
        "type": "integer",
        "description": "嵌入向量维度数",
        "default_value": str(EMBEDDING_DIMENSIONS),
        "is_hot_reload": True
    },
    {
        "key": "webhook_timeout",
        "value": str(WEBHOOK_TIMEOUT),
        "type": "integer",
        "description": "Webhook超时时间（秒）",
        "default_value": str(WEBHOOK_TIMEOUT),
        "is_hot_reload": True
    },
    {
        "key": "webhook_prefix",
        "value": WEBHOOK_PREFIX,
        "type": "string",
        "description": "Webhook前缀URL",
        "default_value": WEBHOOK_PREFIX,
        "is_hot_reload": True
    },
    {
        "key": "default_tool_mode",
        "value": DEFAULT_TOOL_MODE,
        "type": "string",
        "description": "默认工具模式（off/auto/json/react/harmony）",
        "default_value": DEFAULT_TOOL_MODE,
        "is_hot_reload": True
    },
    {
        "key": "max_tool_steps",
        "value": str(MAX_TOOL_STEPS),
        "type": "integer",
        "description": "最大工具调用步数",
        "default_value": str(MAX_TOOL_STEPS),
        "is_hot_reload": True
    },
    {
        "key": "web_search_result_count",
        "value": str(WEB_SEARCH_RESULT_COUNT),
        "type": "integer",
        "description": "网络搜索结果数量",
        "default_value": str(WEB_SEARCH_RESULT_COUNT),
        "is_hot_reload": True
    },
    {
        "key": "web_search_max_queries",
        "value": str(WEB_SEARCH_MAX_QUERIES),
        "type": "integer",
        "description": "网络搜索最大查询数量",
        "default_value": str(WEB_SEARCH_MAX_QUERIES),
        "is_hot_reload": True
    },
    {
        "key": "web_search_max_results",
        "value": str(WEB_SEARCH_MAX_RESULTS),
        "type": "integer",
        "description": "网络搜索最大结果数量",
        "default_value": str(WEB_SEARCH_MAX_RESULTS),
        "is_hot_reload": True
    },
    {
        "key": "web_search_concurrent_requests",
        "value": str(WEB_SEARCH_CONCURRENT_REQUESTS),
        "type": "integer",
        "description": "网络搜索并发请求数",
        "default_value": str(WEB_SEARCH_CONCURRENT_REQUESTS),
        "is_hot_reload": True
    },
    {
        "key": "web_search_timeout",
        "value": str(WEB_SEARCH_TIMEOUT),
        "type": "float",
        "description": "网络搜索超时时间（秒）",
        "default_value": str(WEB_SEARCH_TIMEOUT),
        "is_hot_reload": True
    },
    {
        "key": "max_words_per_query",
        "value": str(MAX_WORDS_PER_QUERY),
        "type": "integer",
        "description": "每个查询最大词数",
        "default_value": str(MAX_WORDS_PER_QUERY),
        "is_hot_reload": True
    },
    {
        "key": "max_knowledge_gaps",
        "value": str(MAX_KNOWLEDGE_GAPS),
        "type": "integer",
        "description": "最大知识缺口数量",
        "default_value": str(MAX_KNOWLEDGE_GAPS),
        "is_hot_reload": True
    },
    {
        "key": "max_keywords_per_gap",
        "value": str(MAX_KEYWORDS_PER_GAP),
        "type": "integer",
        "description": "每个知识缺口最大关键词数量",
        "default_value": str(MAX_KEYWORDS_PER_GAP),
        "is_hot_reload": True
    },
    {
        "key": "gap_recall_top_k",
        "value": str(GAP_RECALL_TOP_K),
        "type": "integer",
        "description": "知识缺口召回Top K",
        "default_value": str(GAP_RECALL_TOP_K),
        "is_hot_reload": True
    },
    {
        "key": "simple_query_max_queries",
        "value": str(SIMPLE_QUERY_MAX_QUERIES),
        "type": "integer",
        "description": "简单查询最大搜索关键词数量",
        "default_value": str(SIMPLE_QUERY_MAX_QUERIES),
        "is_hot_reload": True
    },
    {
        "key": "simple_query_result_count",
        "value": str(SIMPLE_QUERY_RESULT_COUNT),
        "type": "integer",
        "description": "简单查询每个关键词返回结果数量",
        "default_value": str(SIMPLE_QUERY_RESULT_COUNT),
        "is_hot_reload": True
    },
    {
        "key": "simple_query_max_results",
        "value": str(SIMPLE_QUERY_MAX_RESULTS),
        "type": "integer",
        "description": "简单查询最大总结果数量",
        "default_value": str(SIMPLE_QUERY_MAX_RESULTS),
        "is_hot_reload": True
    },
    {
        "key": "simple_query_max_words_per_query",
        "value": str(SIMPLE_QUERY_MAX_WORDS_PER_QUERY),
        "type": "integer",
        "description": "简单查询每个查询最大词数",
        "default_value": str(SIMPLE_QUERY_MAX_WORDS_PER_QUERY),
        "is_hot_reload": True
    },
    {
        "key": "web_loader_engine",
        "value": WEB_LOADER_ENGINE,
        "type": "string",
        "description": "网页加载引擎（safe_web/playwright）",
        "default_value": WEB_LOADER_ENGINE,
        "is_hot_reload": True
    },
    {
        "key": "playwright_timeout",
        "value": str(PLAYWRIGHT_TIMEOUT),
        "type": "float",
        "description": "Playwright超时时间（秒）",
        "default_value": str(PLAYWRIGHT_TIMEOUT),
        "is_hot_reload": True
    },
    {
        "key": "enable_query_generation",
        "value": str(ENABLE_QUERY_GENERATION).lower(),
        "type": "boolean",
        "description": "是否启用查询生成",
        "default_value": str(ENABLE_QUERY_GENERATION).lower(),
        "is_hot_reload": True
    },
    {
        "key": "query_generation_prompt_template",
        "value": QUERY_GENERATION_PROMPT_TEMPLATE,
        "type": "string",
        "description": "查询生成提示模板",
        "default_value": QUERY_GENERATION_PROMPT_TEMPLATE,
        "is_hot_reload": True
    },
    {
        "key": "web_cache_enabled",
        "value": str(WEB_CACHE_ENABLED).lower(),
        "type": "boolean",
        "description": "是否启用网页缓存",
        "default_value": str(WEB_CACHE_ENABLED).lower(),
        "is_hot_reload": True
    },
    {
        "key": "web_cache_max_size",
        "value": str(WEB_CACHE_MAX_SIZE),
        "type": "integer",
        "description": "网页缓存最大大小",
        "default_value": str(WEB_CACHE_MAX_SIZE),
        "is_hot_reload": True
    },
    {
        "key": "web_cache_ttl_seconds",
        "value": str(WEB_CACHE_TTL_SECONDS),
        "type": "integer",
        "description": "网页缓存TTL（秒）",
        "default_value": str(WEB_CACHE_TTL_SECONDS),
        "is_hot_reload": True
    },
    {
        "key": "web_cache_max_content_size",
        "value": str(WEB_CACHE_MAX_CONTENT_SIZE),
        "type": "integer",
        "description": "网页缓存最大内容大小",
        "default_value": str(WEB_CACHE_MAX_CONTENT_SIZE),
        "is_hot_reload": True
    },
    {
        "key": "chunk_size",
        "value": str(CHUNK_SIZE),
        "type": "integer",
        "description": "文档分块大小",
        "default_value": str(CHUNK_SIZE),
        "is_hot_reload": True
    },
    {
        "key": "chunk_overlap",
        "value": str(CHUNK_OVERLAP),
        "type": "integer",
        "description": "文档分块重叠大小",
        "default_value": str(CHUNK_OVERLAP),
        "is_hot_reload": True
    },
    {
        "key": "rag_top_k",
        "value": str(RAG_TOP_K),
        "type": "integer",
        "description": "RAG召回Top K",
        "default_value": str(RAG_TOP_K),
        "is_hot_reload": True
    },
    {
        "key": "query_top_k_before_rerank",
        "value": str(QUERY_TOP_K_BEFORE_RERANK),
        "type": "integer",
        "description": "重排序前查询Top K",
        "default_value": str(QUERY_TOP_K_BEFORE_RERANK),
        "is_hot_reload": True
    },
    {
        "key": "rag_rerank_top_k",
        "value": str(RAG_RERANK_TOP_K),
        "type": "integer",
        "description": "重排序后保留Top K",
        "default_value": str(RAG_RERANK_TOP_K),
        "is_hot_reload": True
    },
    {
        "key": "llm_default_timeout",
        "value": str(LLM_DEFAULT_TIMEOUT),
        "type": "float",
        "description": "LLM默认超时时间（秒）",
        "default_value": str(LLM_DEFAULT_TIMEOUT),
        "is_hot_reload": True
    },
    {
        "key": "default_search_model",
        "value": DEFAULT_SEARCH_MODEL,
        "type": "string",
        "description": "默认搜索模型",
        "default_value": DEFAULT_SEARCH_MODEL,
        "is_hot_reload": True
    },
    {
        "key": "default_ingest_model",
        "value": DEFAULT_INGEST_MODEL,
        "type": "string",
        "description": "默认处理模型",
        "default_value": DEFAULT_INGEST_MODEL,
        "is_hot_reload": True
    },
    {
        "key": "default_embedding_model",
        "value": DEFAULT_EMBEDDING_MODEL,
        "type": "string",
        "description": "默认嵌入模型",
        "default_value": DEFAULT_EMBEDDING_MODEL,
        "is_hot_reload": True
    },
    {
        "key": "reasoning_timeout",
        "value": str(REASONING_TIMEOUT),
        "type": "float",
        "description": "推理超时时间（秒）",
        "default_value": str(REASONING_TIMEOUT),
        "is_hot_reload": True
    },
    {
        "key": "web_search_llm_timeout",
        "value": str(WEB_SEARCH_LLM_TIMEOUT),
        "type": "float",
        "description": "网络搜索LLM超时时间（秒）",
        "default_value": str(WEB_SEARCH_LLM_TIMEOUT),
        "is_hot_reload": True
    },
    {
        "key": "http_proxy",
        "value": HTTP_PROXY,
        "type": "string",
        "description": "HTTP代理地址",
        "default_value": HTTP_PROXY,
        "is_hot_reload": False
    },
    {
        "key": "https_proxy",
        "value": HTTPS_PROXY,
        "type": "string",
        "description": "HTTPS代理地址",
        "default_value": HTTPS_PROXY,
        "is_hot_reload": False
    },
    {
        "key": "proxy_url",
        "value": PROXY_URL,
        "type": "string",
        "description": "代理URL",
        "default_value": PROXY_URL,
        "is_hot_reload": False
    },
    {
        "key": "n8n_base_url",
        "value": N8N_BASE_URL,
        "type": "string",
        "description": "N8N基础URL",
        "default_value": N8N_BASE_URL,
        "is_hot_reload": True
    },
    {
        "key": "n8n_api_key",
        "value": N8N_API_KEY,
        "type": "string",
        "description": "N8N API密钥",
        "default_value": N8N_API_KEY,
        "is_hot_reload": False
    },
    {
        "key": "n8n_username",
        "value": N8N_USERNAME,
        "type": "string",
        "description": "N8N用户名",
        "default_value": N8N_USERNAME,
        "is_hot_reload": False
    },
    {
        "key": "n8n_password",
        "value": N8N_PASSWORD,
        "type": "string",
        "description": "N8N密码",
        "default_value": N8N_PASSWORD,
        "is_hot_reload": False
    }
]

async def load_config_from_db(db: AsyncSession) -> Dict[str, Any]:
    """
    从数据库加载配置到内存中
    """
    # 先准备默认配置字典，作为兜底
    default_configs: Dict[str, Any] = {}
    for config_def in DEFAULT_CONFIGS:
        default_configs[config_def["key"]] = config_def["value"]

    try:
        # 查询所有配置项
        result = await db.execute(select(Config))
        configs = result.scalars().all()
        
        config_dict = {}
        for config in configs:
            # 根据类型转换值
            if config.type == "integer":
                try:
                    value = int(config.value)
                except (ValueError, TypeError):
                    value = config.default_value
            elif config.type == "float":
                try:
                    value = float(config.value)
                except (ValueError, TypeError):
                    value = config.default_value
            elif config.type == "boolean":
                value = config.value.lower() in ('true', '1', 'yes', 'on')
            else:
                value = config.value
            
            config_dict[config.key] = value
            set_config_value(config.key, value)
        
        # 检查并添加缺失的配置项
        for key, default_value in default_configs.items():
            if key not in config_dict:
                config_dict[key] = default_value
                set_config_value(key, default_value)
                
        return config_dict
    except Exception as e:
        logger.error(f"加载配置失败: {e}")
        # 如果数据库出错，使用默认值
        return default_configs

async def notify_config_change(key: str, new_value: Any):
    """
    通知配置变更
    """
    try:
        # 调用注册的回调函数
        if key in _config_callbacks:
            callback = _config_callbacks[key]
            await callback(new_value)
    except Exception as e:
        logger.error(f"执行配置回调失败 {key}: {e}")

async def start_config_monitoring(db: AsyncSession):
    """
    启动配置监控（轮询方式）
    """
    logger.info("启动配置监控...")
    
    # 初始加载配置
    await load_config_from_db(db)
    
    # 每隔一段时间检查配置变更（10秒间隔）
    while True:
        try:
            # 查询数据库中所有配置项
            result = await db.execute(select(Config))
            configs = result.scalars().all()
            
            config_dict = {}
            for config in configs:
                # 根据类型转换值，保持与初始加载一致的类型处理
                if config.type == "integer":
                    try:
                        value = int(config.value)
                    except (ValueError, TypeError):
                        value = config.default_value
                elif config.type == "float":
                    try:
                        value = float(config.value)
                    except (ValueError, TypeError):
                        value = config.default_value
                elif config.type == "boolean":
                    value = config.value.lower() in ('true', '1', 'yes', 'on')
                else:
                    value = config.value
                
                config_dict[config.key] = value
            
            # 检查变更并通知
            for key, new_value in config_dict.items():
                old_value = get_config_value(key)
                if old_value != new_value:
                    set_config_value(key, new_value)
                    await notify_config_change(key, new_value)
            
            # 等待一段时间再检查
            await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"配置监控出错: {e}")
            await asyncio.sleep(10)  # 出错后也等待，避免频繁错误

# 配置更新回调函数实现
async def update_embedding_service_url(new_value: str):
    """更新嵌入服务URL的回调"""
    logger.info(f"嵌入服务URL已更新为: {new_value}")
    # 可以在这里更新嵌入服务相关的设置或重启相关服务
    
async def update_llm_service_url(new_value: str):
    """更新LLM服务URL的回调"""
    logger.info(f"LLM服务URL已更新为: {new_value}")
    # 重新初始化工具编排器，使其使用新的LLM服务URL
    try:
        from .tools.orchestrator import initialize_orchestrator
        # 重新初始化编排器以使用新URL
        initialize_orchestrator(new_value)
        logger.info("工具编排器已重新初始化")
    except Exception as e:
        logger.error(f"重新初始化工具编排器失败: {e}")

async def update_qdrant_url(new_value: str):
    """更新Qdrant URL的回调"""
    logger.info(f"Qdrant URL已更新为: {new_value}")
    # 重新创建Qdrant客户端
    try:
        from .vector_db_client import create_qdrant_client, qdrant_client
        # 更新全局客户端实例
        # 读取可能更新的 API Key（若未配置，则回退到默认配置）
        api_key = get_config_value("qdrant_api_key", QDRANT_API_KEY)
        new_client = create_qdrant_client(new_value, api_key)
        if new_client:
            # 使用新客户端替换旧客户端（需要在模块级变量中进行处理）
            # 因为直接修改模块变量比较复杂，建议通过一个更新函数来处理
            logger.info("Qdrant客户端已重新创建")
    except Exception as e:
        logger.error(f"更新Qdrant客户端失败: {e}")

async def update_default_tool_mode(new_value: str):
    """更新默认工具模式的回调"""
    logger.info(f"默认工具模式已更新为: {new_value}")
    # 可以在这里触发相关设置的变更（如更新编排器参数等）

# 注册回调函数
register_config_callback("embedding_service_url", update_embedding_service_url)
register_config_callback("llm_service_url", update_llm_service_url)
register_config_callback("qdrant_url", update_qdrant_url)
register_config_callback("default_tool_mode", update_default_tool_mode)