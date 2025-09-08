from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from ..database import get_db
from ..models import Config
from ..config import (
    DATABASE_URL, EMBEDDING_SERVICE_URL, LLM_SERVICE_URL, RERANKER_SERVICE_URL,
    SEARXNG_QUERY_URL, QDRANT_HOST, QDRANT_PORT, QDRANT_URL, QDRANT_API_KEY,
    QDRANT_COLLECTION_NAME, RERANKER_MAX_TOKENS, RERANK_CLIENT_MAX_CONCURRENCY,
    EMBEDDING_MAX_CONCURRENCY, EMBEDDING_BATCH_SIZE, EMBEDDING_DIMENSIONS,
    WEBHOOK_TIMEOUT, WEBHOOK_PREFIX, DEFAULT_TOOL_MODE, MAX_TOOL_STEPS,
    WEB_SEARCH_RESULT_COUNT, WEB_SEARCH_MAX_QUERIES, WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_CONCURRENT_REQUESTS, WEB_SEARCH_TIMEOUT, MAX_WORDS_PER_QUERY,
    MAX_KNOWLEDGE_GAPS, MAX_KEYWORDS_PER_GAP, GAP_RECALL_TOP_K,
    SIMPLE_QUERY_MAX_QUERIES, SIMPLE_QUERY_RESULT_COUNT, SIMPLE_QUERY_MAX_RESULTS,
    SIMPLE_QUERY_MAX_WORDS_PER_QUERY, WEB_LOADER_ENGINE, PLAYWRIGHT_TIMEOUT,
    ENABLE_QUERY_GENERATION, QUERY_GENERATION_PROMPT_TEMPLATE, WEB_CACHE_ENABLED,
    WEB_CACHE_MAX_SIZE, WEB_CACHE_TTL_SECONDS, WEB_CACHE_MAX_CONTENT_SIZE,
    CHUNK_SIZE, CHUNK_OVERLAP, RAG_TOP_K, QUERY_TOP_K_BEFORE_RERANK, RAG_RERANK_TOP_K,
    LLM_DEFAULT_TIMEOUT, DEFAULT_SEARCH_MODEL, DEFAULT_INGEST_MODEL, DEFAULT_EMBEDDING_MODEL,
    REASONING_TIMEOUT, WEB_SEARCH_LLM_TIMEOUT, HTTP_PROXY, HTTPS_PROXY, PROXY_URL,
    N8N_BASE_URL, N8N_API_KEY, N8N_USERNAME, N8N_PASSWORD
)

router = APIRouter()

# 配置项定义
DEFAULT_CONFIGS = [
    {
        "key": "database_url",
        "value": DATABASE_URL,
        "type": "string",
        "description": "数据库连接URL",
        "default_value": DATABASE_URL,
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
        "key": "qdrant_url",
        "value": QDRANT_URL,
        "type": "string",
        "description": "Qdrant服务URL",
        "default_value": QDRANT_URL,
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


@router.get("/config/", summary="获取所有配置项")
async def get_configs(db: AsyncSession = Depends(get_db)):
    """
    获取所有配置项
    """
    try:
        # 先尝试从数据库中获取配置
        configs = await db.execute(select(Config))
        db_configs = configs.scalars().all()
        
        # 转换为字典格式
        config_dict = {}
        for config in db_configs:
            config_dict[config.key] = {
                "value": "******" if config.key in ['qdrant_api_key', 'n8n_password', 'n8n_api_key', 'http_proxy', 'https_proxy'] else config.value,
                "type": config.type,
                "description": config.description,
                "default_value": config.default_value,
                "is_hot_reload": config.is_hot_reload
            }
        
        # 添加默认配置项，如果数据库中没有对应的配置项
        for default_config in DEFAULT_CONFIGS:
            if default_config["key"] not in config_dict:
                config_dict[default_config["key"]] = {
                    "value": "******" if default_config["key"] in ['qdrant_api_key', 'n8n_password', 'n8n_api_key', 'http_proxy', 'https_proxy'] else default_config["value"],
                    "type": default_config["type"],
                    "description": default_config["description"],
                    "default_value": default_config["default_value"],
                    "is_hot_reload": default_config["is_hot_reload"]
                }
        
        return {
            "success": True,
            "config": config_dict
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.post("/config/", summary="保存配置项")
async def save_config(config_data: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    """
    保存配置项
    """
    try:
        # 检查并保存每个配置项
        for key, value in config_data.get("config", {}).items():
            # 查找是否已存在该配置项
            existing_config = await db.execute(
                select(Config).where(Config.key == key)
            )
            existing_config = existing_config.scalars().first()
            
            if existing_config:
                # 更新现有配置，只更新值，保留原有元数据
                try:
                    # 根据原来配置的类型进行转换
                    if existing_config.type == "integer":
                        converted_value = int(value)
                    elif existing_config.type == "float":
                        converted_value = float(value)
                    elif existing_config.type == "boolean":
                        converted_value = str(value).lower() in ('true', '1', 'yes', 'on')
                    else:
                        converted_value = str(value)
                    existing_config.value = str(converted_value)
                except (ValueError, TypeError):
                    # 如果转换失败，不更新该配置项，保持原值
                    print(f"警告：配置 {key} 的值 {value} 转换失败，保持原值")
                db.add(existing_config)
            else:
                # 创建新配置项（如果需要的话）
                # 检查是否有is_hot_reload参数，否则默认为False
                is_hot_reload = config_data.get("is_hot_reload", False)
                new_config = Config(
                    key=key,
                    value=str(value),
                    type="string",  # 默认类型
                    description=f"用户自定义配置项: {key}",
                    default_value=str(value),
                    is_hot_reload=is_hot_reload  # 使用传入的参数或默认值
                )
                db.add(new_config)
        
        await db.commit()
        
        return {
            "success": True,
            "message": "配置保存成功"
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"保存配置失败: {str(e)}")


@router.delete("/config/", summary="重置为默认配置")
async def reset_config(db: AsyncSession = Depends(get_db)):
    """
    重置所有配置项为默认值
    """
    try:
        # 删除所有配置项
        await db.execute(delete(Config))
        await db.commit()
        
        # 重新插入默认配置项
        for default_config in DEFAULT_CONFIGS:
            new_config = Config(
                key=default_config["key"],
                value=default_config["value"],
                type=default_config["type"],
                description=default_config["description"],
                default_value=default_config["default_value"],
                is_hot_reload=default_config["is_hot_reload"]
            )
            db.add(new_config)
        
        await db.commit()
        
        return {
            "success": True,
            "message": "配置已重置为默认值"
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"重置配置失败: {str(e)}")


@router.get("/config/validate", summary="验证配置")
async def validate_config(db: AsyncSession = Depends(get_db)):
    """
    验证配置的有效性
    """
    try:
        # 这里可以添加具体的验证逻辑，比如检查数据库连接、URL可达性等
        errors = []
        
        # 示例：简单验证某些关键配置项是否为空
        configs = await db.execute(select(Config))
        db_configs = configs.scalars().all()
        
        config_dict = {config.key: config for config in db_configs}
        
        # 检查必填项
        required_configs = ["database_url", "llm_service_url", "embedding_service_url"]
        for req_config in required_configs:
            if req_config not in config_dict or not config_dict[req_config].value:
                errors.append(f"必需配置项 {req_config} 为空")
        
        return {
            "success": True,
            "valid": len(errors) == 0,
            "errors": errors
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"验证配置失败: {str(e)}")


@router.post("/config/refresh", summary="刷新配置到运行时")
async def refresh_config(db: AsyncSession = Depends(get_db)):
    """
    手动刷新配置到运行时（用于热更新）
    """
    try:
        # 获取所有配置
        configs = await db.execute(select(Config))
        db_configs = configs.scalars().all()
        
        config_dict = {}
        for config in db_configs:
            config_dict[config.key] = {
                "value": config.value,
                "type": config.type,
                "is_hot_reload": config.is_hot_reload
            }
        
        return {
            "success": True,
            "message": "配置已刷新到运行时",
            "config": config_dict
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"刷新配置失败: {str(e)}")