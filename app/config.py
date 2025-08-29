from dotenv import dotenv_values
import os

# Load variables directly from project-root .env file
# Use os.getenv as a fallback for containerized environments
config = dotenv_values(".env")

def get_config_value(key: str, default: str = None) -> str:
    """Gets value from .env file or falls back to environment variables."""
    return config.get(key) or os.getenv(key, default)

DATABASE_URL = get_config_value("DATABASE_URL")
EMBEDDING_SERVICE_URL = get_config_value("EMBEDDING_SERVICE_URL")
LLM_SERVICE_URL = get_config_value("LLM_SERVICE_URL")
RERANKER_SERVICE_URL = get_config_value("RERANKER_SERVICE_URL")
SEARXNG_QUERY_URL = get_config_value("SEARXNG_QUERY_URL", "http://192.168.31.125:8080/search")

# Qdrant Configuration
QDRANT_HOST = get_config_value("QDRANT_HOST", "localhost")
QDRANT_PORT = get_config_value("QDRANT_PORT", "6333")
QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_PORT}"
QDRANT_API_KEY = get_config_value("QDRANT_API_KEY", None)
RERANKER_MAX_TOKENS = int(get_config_value("RERANKER_MAX_TOKENS", "8192"))
RERANK_CLIENT_MAX_CONCURRENCY = int(get_config_value("RERANK_CLIENT_MAX_CONCURRENCY", 4))

EMBEDDING_MAX_CONCURRENCY = int(get_config_value("EMBEDDING_MAX_CONCURRENCY", 4))
EMBEDDING_BATCH_SIZE = int(get_config_value("EMBEDDING_BATCH_SIZE", 4))
WEBHOOK_TIMEOUT = int(get_config_value("WEBHOOK_TIMEOUT", 30))
WEBHOOK_PREFIX = get_config_value("WEBHOOK_PREFIX", "http://192.168.31.125:5678/webhook")

# 工具相关配置
DEFAULT_TOOL_MODE = get_config_value("DEFAULT_TOOL_MODE", "auto")
MAX_TOOL_STEPS = int(get_config_value("MAX_TOOL_STEPS", "5"))

# Web 搜索相关配置
WEB_SEARCH_RESULT_COUNT = int(get_config_value("WEB_SEARCH_RESULT_COUNT", "2"))  # 每个搜索关键词的结果控制在2个
WEB_SEARCH_MAX_QUERIES = int(get_config_value("WEB_SEARCH_MAX_QUERIES", "10"))  # 总搜索查询数量上限
WEB_SEARCH_MAX_RESULTS = int(get_config_value("WEB_SEARCH_MAX_RESULTS", "30"))  # 总结果数量上限
WEB_SEARCH_CONCURRENT_REQUESTS = int(get_config_value("WEB_SEARCH_CONCURRENT_REQUESTS", "4"))
WEB_SEARCH_TIMEOUT = float(get_config_value("WEB_SEARCH_TIMEOUT", "10.0"))

# 知识缺口和关键词限制
MAX_KNOWLEDGE_GAPS = int(get_config_value("MAX_KNOWLEDGE_GAPS", "8"))  # 用于网络搜索的知识缺口最多8个
MAX_KEYWORDS_PER_GAP = int(get_config_value("MAX_KEYWORDS_PER_GAP", "3"))  # 每个知识缺口的搜索关键词最多3个
GAP_RECALL_TOP_K = int(get_config_value("GAP_RECALL_TOP_K", "5"))  # 每个知识缺口召回top 5

# Web 爬取相关配置  
WEB_LOADER_ENGINE = get_config_value("WEB_LOADER_ENGINE", "safe_web")  # safe_web, playwright
PLAYWRIGHT_TIMEOUT = float(get_config_value("PLAYWRIGHT_TIMEOUT", "10.0"))

# 关键词生成配置
ENABLE_QUERY_GENERATION = get_config_value("ENABLE_QUERY_GENERATION", "true").lower() == "true"
QUERY_GENERATION_PROMPT_TEMPLATE = get_config_value(
    "QUERY_GENERATION_PROMPT_TEMPLATE", 
    """你是搜索查询优化专家。基于给定课题，生成适当数量的简洁搜索查询。

**要求：**
- 生成最多4个搜索查询，根据实际需要判断具体数量
- 优先使用英文关键词（搜索结果更多）
- 每个查询聚焦一个特定方面
- 保持查询简洁有效

返回JSON：{"queries": ["查询1", "查询2", ...]}"""
)

# 网页内容缓存配置
WEB_CACHE_ENABLED = get_config_value("WEB_CACHE_ENABLED", "true").lower() == "true"
WEB_CACHE_MAX_SIZE = int(get_config_value("WEB_CACHE_MAX_SIZE", "1000"))
WEB_CACHE_TTL_SECONDS = int(get_config_value("WEB_CACHE_TTL_SECONDS", "3600"))  # 1小时
WEB_CACHE_MAX_CONTENT_SIZE = int(get_config_value("WEB_CACHE_MAX_CONTENT_SIZE", "1048576"))  # 1MB

# 文档处理配置
CHUNK_SIZE = int(get_config_value("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(get_config_value("CHUNK_OVERLAP", "100"))

# RAG 相关配置
RAG_TOP_K = int(get_config_value("RAG_TOP_K", "12"))
RAG_RERANK_TOP_K = int(get_config_value("RAG_RERANK_TOP_K", "12"))

# LLM 调用相关配置
LLM_DEFAULT_TIMEOUT = float(get_config_value("LLM_DEFAULT_TIMEOUT", "3600.0"))
DEFAULT_SEARCH_MODEL= get_config_value("DEFAULT_SEARCH_MODEL", "openai/gpt-oss-20b")
DEFAULT_INGEST_MODEL= get_config_value("DEFAULT_INGEST_MODEL", "qwen/qwen3-coder-30b")

# 思考引擎LLM配置
REASONING_TIMEOUT = float(get_config_value("REASONING_TIMEOUT", "3600.0"))

# Web搜索关键词生成LLM配置
WEB_SEARCH_LLM_TIMEOUT = float(get_config_value("WEB_SEARCH_LLM_TIMEOUT", "1800.0"))  # 30分钟

# Proxy configuration (optional)
HTTP_PROXY = get_config_value("HTTP_PROXY")
HTTPS_PROXY = get_config_value("HTTPS_PROXY")
PROXY_URL = get_config_value("PROXY_URL") or HTTP_PROXY or HTTPS_PROXY

# N8N Configuration
N8N_BASE_URL = get_config_value("N8N_BASE_URL", "http://localhost:5678/api/v1")
N8N_API_KEY = get_config_value("N8N_API_KEY")
N8N_USERNAME = get_config_value("N8N_USERNAME")
N8N_PASSWORD = get_config_value("N8N_PASSWORD")

print("--- Application Configuration ---")
print(f"DATABASE_URL: {DATABASE_URL}")
print(f"EMBEDDING_SERVICE_URL: {EMBEDDING_SERVICE_URL}")
print(f"LLM_SERVICE_URL: {LLM_SERVICE_URL}")
print(f"RERANKER_SERVICE_URL: {RERANKER_SERVICE_URL}")
print(f"RERANKER_MAX_TOKENS: {RERANKER_MAX_TOKENS}")
print(f"RERANK_CLIENT_MAX_CONCURRENCY: {RERANK_CLIENT_MAX_CONCURRENCY}")

print(f"EMBEDDING_MAX_CONCURRENCY: {EMBEDDING_MAX_CONCURRENCY}")
print(f"EMBEDDING_BATCH_SIZE: {EMBEDDING_BATCH_SIZE}")

print(f"QDRANT_URL: {QDRANT_URL}")
print(f"PROXY_URL: {PROXY_URL}")
print(f"SEARXNG_QUERY_URL: {SEARXNG_QUERY_URL}")
print(f"WEBHOOK_PREFIX: {WEBHOOK_PREFIX}")

# 工具相关配置
print(f"DEFAULT_TOOL_MODE: {DEFAULT_TOOL_MODE}")
print(f"MAX_TOOL_STEPS: {MAX_TOOL_STEPS}")

# Web 搜索相关配置
print(f"WEB_SEARCH_RESULT_COUNT: {WEB_SEARCH_RESULT_COUNT}")
print(f"WEB_SEARCH_MAX_QUERIES: {WEB_SEARCH_MAX_QUERIES}")
print(f"WEB_SEARCH_MAX_RESULTS: {WEB_SEARCH_MAX_RESULTS}")
print(f"MAX_KNOWLEDGE_GAPS: {MAX_KNOWLEDGE_GAPS}")
print(f"MAX_KEYWORDS_PER_GAP: {MAX_KEYWORDS_PER_GAP}")
print(f"GAP_RECALL_TOP_K: {GAP_RECALL_TOP_K}")
print(f"WEB_LOADER_ENGINE: {WEB_LOADER_ENGINE}")
print(f"ENABLE_QUERY_GENERATION: {ENABLE_QUERY_GENERATION}")
print(f"CHUNK_SIZE: {CHUNK_SIZE}")
print(f"RAG_TOP_K: {RAG_TOP_K}")
print("-------------------------------")
