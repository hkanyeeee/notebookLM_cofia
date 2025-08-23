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
RERANKER_MAX_TOKENS = int(get_config_value("RERANKER_MAX_TOKENS", "3072"))
RERANK_CLIENT_MAX_CONCURRENCY = int(get_config_value("RERANK_CLIENT_MAX_CONCURRENCY", 4))

EMBEDDING_MAX_CONCURRENCY = int(get_config_value("EMBEDDING_MAX_CONCURRENCY", 4))
EMBEDDING_BATCH_SIZE = int(get_config_value("EMBEDDING_BATCH_SIZE", 4))
WEBHOOK_TIMEOUT = int(get_config_value("WEBHOOK_TIMEOUT", 30))
WEBHOOK_PREFIX = get_config_value("WEBHOOK_PREFIX", "http://192.168.31.125:5678/webhook")

# 工具相关配置
DEFAULT_TOOL_MODE = get_config_value("DEFAULT_TOOL_MODE", "auto")
MAX_TOOL_STEPS = int(get_config_value("MAX_TOOL_STEPS", "5"))

# Web 搜索相关配置
WEB_SEARCH_RESULT_COUNT = int(get_config_value("WEB_SEARCH_RESULT_COUNT", "3"))
WEB_SEARCH_MAX_QUERIES = int(get_config_value("WEB_SEARCH_MAX_QUERIES", "4"))
WEB_SEARCH_MAX_RESULTS = int(get_config_value("WEB_SEARCH_MAX_RESULTS", "8"))
WEB_SEARCH_CONCURRENT_REQUESTS = int(get_config_value("WEB_SEARCH_CONCURRENT_REQUESTS", "4"))
WEB_SEARCH_TIMEOUT = float(get_config_value("WEB_SEARCH_TIMEOUT", "30.0"))

# Web 爬取相关配置  
WEB_LOADER_ENGINE = get_config_value("WEB_LOADER_ENGINE", "safe_web")  # safe_web, playwright
PLAYWRIGHT_TIMEOUT = float(get_config_value("PLAYWRIGHT_TIMEOUT", "30.0"))

# 关键词生成配置
ENABLE_QUERY_GENERATION = get_config_value("ENABLE_QUERY_GENERATION", "true").lower() == "true"
QUERY_GENERATION_PROMPT_TEMPLATE = get_config_value(
    "QUERY_GENERATION_PROMPT_TEMPLATE", 
    "你是搜索查询生成器。给定课题，产出3个多样化、可直接用于网页搜索的、使用空格分割的英文关键词的组合，用于查询。返回JSON，键为queries，值为包含3个字符串的数组，不要夹杂多余文本。"
)

# 网页内容缓存配置
WEB_CACHE_ENABLED = get_config_value("WEB_CACHE_ENABLED", "true").lower() == "true"
WEB_CACHE_MAX_SIZE = int(get_config_value("WEB_CACHE_MAX_SIZE", "1000"))
WEB_CACHE_TTL_SECONDS = int(get_config_value("WEB_CACHE_TTL_SECONDS", "3600"))  # 1小时
WEB_CACHE_MAX_CONTENT_SIZE = int(get_config_value("WEB_CACHE_MAX_CONTENT_SIZE", "1048576"))  # 1MB

# 文档处理配置
CHUNK_SIZE = int(get_config_value("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(get_config_value("CHUNK_OVERLAP", "50"))

# RAG 相关配置
RAG_TOP_K = int(get_config_value("RAG_TOP_K", "12"))
RAG_RERANK_TOP_K = int(get_config_value("RAG_RERANK_TOP_K", "5"))

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
print(f"WEB_LOADER_ENGINE: {WEB_LOADER_ENGINE}")
print(f"ENABLE_QUERY_GENERATION: {ENABLE_QUERY_GENERATION}")
print(f"CHUNK_SIZE: {CHUNK_SIZE}")
print(f"RAG_TOP_K: {RAG_TOP_K}")
print("-------------------------------")
