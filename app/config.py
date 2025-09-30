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
QDRANT_COLLECTION_NAME = get_config_value("QDRANT_COLLECTION_NAME", "notebooklm_prod")
RERANKER_MAX_TOKENS = int(get_config_value("RERANKER_MAX_TOKENS", "8192"))
RERANK_CLIENT_MAX_CONCURRENCY = int(get_config_value("RERANK_CLIENT_MAX_CONCURRENCY", 4))

EMBEDDING_MAX_CONCURRENCY = int(get_config_value("EMBEDDING_MAX_CONCURRENCY", 4))
EMBEDDING_BATCH_SIZE = int(get_config_value("EMBEDDING_BATCH_SIZE", 4))
EMBEDDING_DIMENSIONS = int(get_config_value("EMBEDDING_DIMENSIONS", 1024))
WEBHOOK_TIMEOUT = int(get_config_value("WEBHOOK_TIMEOUT", 30))
WEBHOOK_PREFIX = get_config_value("WEBHOOK_PREFIX", "http://192.168.31.125:5678/webhook")

# 工具相关配置
DEFAULT_TOOL_MODE = get_config_value("DEFAULT_TOOL_MODE", "auto")
MAX_TOOL_STEPS = int(get_config_value("MAX_TOOL_STEPS", "8"))

# Web 搜索相关配置
WEB_SEARCH_RESULT_COUNT = int(get_config_value("WEB_SEARCH_RESULT_COUNT", "2"))  # 每个搜索关键词的结果控制在2个
WEB_SEARCH_MAX_QUERIES = int(get_config_value("WEB_SEARCH_MAX_QUERIES", "20"))  # 总搜索查询数量上限
WEB_SEARCH_MAX_RESULTS = int(get_config_value("WEB_SEARCH_MAX_RESULTS", "40"))  # 总结果数量上限
WEB_SEARCH_CONCURRENT_REQUESTS = int(get_config_value("WEB_SEARCH_CONCURRENT_REQUESTS", "10"))
WEB_SEARCH_TIMEOUT = float(get_config_value("WEB_SEARCH_TIMEOUT", "10.0"))

# 搜索关键词词数限制
MAX_WORDS_PER_QUERY = int(get_config_value("MAX_WORDS_PER_QUERY", "4"))  # 每个查询的最大词数

# 关键词限制与召回规模
MAX_KEYWORDS_PER_GAP = int(get_config_value("MAX_KEYWORDS_PER_GAP", "2"))  # 每个知识缺口的搜索关键词最多2个
GAP_RECALL_TOP_K = int(get_config_value("GAP_RECALL_TOP_K", "4"))  # 每个知识缺口召回top 4

# 简单查询专用搜索配置 - 针对"分类为简单查询，需要外部工具，直接获取信息"的场景
SIMPLE_QUERY_MAX_QUERIES = int(get_config_value("SIMPLE_QUERY_MAX_QUERIES", "4"))  # 简单查询的最大搜索关键词数量，更保守
SIMPLE_QUERY_RESULT_COUNT = int(get_config_value("SIMPLE_QUERY_RESULT_COUNT", "4"))  # 简单查询每个关键词返回的结果数量
SIMPLE_QUERY_MAX_RESULTS = int(get_config_value("SIMPLE_QUERY_MAX_RESULTS", "20"))  # 简单查询的最大总结果数量，更精简
SIMPLE_QUERY_MAX_WORDS_PER_QUERY = int(get_config_value("SIMPLE_QUERY_MAX_WORDS_PER_QUERY", "3"))  # 简单查询每个查询的最大词数，更简洁

# 普通问答：子问题数量上限（用于问题拆解阶段）
NORMAL_MAX_SUB_QUERIES = int(get_config_value("NORMAL_MAX_SUB_QUERIES", "5"))

# Web 爬取相关配置  
WEB_LOADER_ENGINE = get_config_value("WEB_LOADER_ENGINE", "safe_web")  # safe_web, playwright
PLAYWRIGHT_TIMEOUT = float(get_config_value("PLAYWRIGHT_TIMEOUT", "10.0"))
PLAYWRIGHT_MAX_CONCURRENCY = int(get_config_value("PLAYWRIGHT_MAX_CONCURRENCY", "4"))

# Playwright 拟真/持久化/stealth 配置
PLAYWRIGHT_HEADLESS = get_config_value("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
PLAYWRIGHT_PERSISTENT = get_config_value("PLAYWRIGHT_PERSISTENT", "false").lower() == "true"
PLAYWRIGHT_USER_DATA_DIR = get_config_value("PLAYWRIGHT_USER_DATA_DIR", ".pw_profile")
PLAYWRIGHT_STEALTH = get_config_value("PLAYWRIGHT_STEALTH", "false").lower() == "true"
PLAYWRIGHT_USER_AGENT = get_config_value("PLAYWRIGHT_USER_AGENT", (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
))
PLAYWRIGHT_LOCALE = get_config_value("PLAYWRIGHT_LOCALE", "zh-CN")
PLAYWRIGHT_TIMEZONE = get_config_value("PLAYWRIGHT_TIMEZONE", "Asia/Shanghai")
PLAYWRIGHT_VIEWPORT_WIDTH = int(get_config_value("PLAYWRIGHT_VIEWPORT_WIDTH", "1366"))
PLAYWRIGHT_VIEWPORT_HEIGHT = int(get_config_value("PLAYWRIGHT_VIEWPORT_HEIGHT", "814"))
# 以逗号分隔的额外 Chromium 启动参数
PLAYWRIGHT_EXTRA_ARGS = [
    arg.strip() for arg in (get_config_value("PLAYWRIGHT_EXTRA_ARGS", "--disable-blink-features=AutomationControlled,--use-fake-ui-for-media-stream,--use-fake-device-for-media-stream")).split(",")
    if arg.strip()
]

# Playwright 通用抓取稳定性配置（与站点无关的等待策略）
PLAYWRIGHT_WAIT_FOR_FONTS = get_config_value("PLAYWRIGHT_WAIT_FOR_FONTS", "true").lower() == "true"
PLAYWRIGHT_WAIT_FOR_DOM_STABLE = get_config_value("PLAYWRIGHT_WAIT_FOR_DOM_STABLE", "true").lower() == "true"
PLAYWRIGHT_DOM_STABLE_MS = int(get_config_value("PLAYWRIGHT_DOM_STABLE_MS", "400"))
PLAYWRIGHT_TEXT_STABLE_CHECKS = int(get_config_value("PLAYWRIGHT_TEXT_STABLE_CHECKS", "3"))
PLAYWRIGHT_TEXT_STABLE_INTERVAL_MS = int(get_config_value("PLAYWRIGHT_TEXT_STABLE_INTERVAL_MS", "500"))
PLAYWRIGHT_MIN_CHARS = int(get_config_value("PLAYWRIGHT_MIN_CHARS", "200"))
PLAYWRIGHT_MAX_NODES_CHECK = int(get_config_value("PLAYWRIGHT_MAX_NODES_CHECK", "200"))
PLAYWRIGHT_SCROLL_STEPS = int(get_config_value("PLAYWRIGHT_SCROLL_STEPS", "3"))
PLAYWRIGHT_SCROLL_INTERVAL_MS = int(get_config_value("PLAYWRIGHT_SCROLL_INTERVAL_MS", "500"))
# 逗号分隔的候选选择器，用于优先抓取正文区域
PLAYWRIGHT_CANDIDATE_SELECTORS = [
    s.strip() for s in get_config_value("PLAYWRIGHT_CANDIDATE_SELECTORS", "article,main,[role=main],.content,#content,.post,.entry,.article,.article-content").split(",") if s.strip()
]

# httpx 连接池/HTTP2 配置
HTTPX_HTTP2_ENABLED = get_config_value("HTTPX_HTTP2_ENABLED", "true").lower() == "true"
HTTPX_MAX_KEEPALIVE_CONNECTIONS = int(get_config_value("HTTPX_MAX_KEEPALIVE_CONNECTIONS", "32"))
HTTPX_MAX_CONNECTIONS = int(get_config_value("HTTPX_MAX_CONNECTIONS", "128"))

# tiktoken 缓存配置
TIKTOKEN_CACHE_DIR = get_config_value("TIKTOKEN_CACHE_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))

# 课题关键词生成配置
ENABLE_QUERY_GENERATION = get_config_value("ENABLE_QUERY_GENERATION", "true").lower() == "true"
QUERY_GENERATION_PROMPT_TEMPLATE = get_config_value(
    "QUERY_GENERATION_PROMPT_TEMPLATE", 
    """你是搜索查询优化专家。基于给定课题，生成适当数量的简洁搜索查询。

**要求：**
- 生成最多3个搜索查询，根据实际需要判断具体数量
- 优先使用英文关键词（搜索结果更多）
- 每个查询聚焦一个特定方面
- 保持查询简洁有效，不能超过 4 个关键词（刚才说的优先使用英文关键词），使用空格分割

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
QUERY_TOP_K_BEFORE_RERANK = int(get_config_value("QUERY_TOP_K_BEFORE_RERANK", "200"))
RAG_RERANK_TOP_K = int(get_config_value("RAG_RERANK_TOP_K", "12"))

# LLM 调用相关配置
LLM_DEFAULT_TIMEOUT = float(get_config_value("LLM_DEFAULT_TIMEOUT", "3600.0"))
DEFAULT_SEARCH_MODEL= get_config_value("DEFAULT_SEARCH_MODEL", "openai/gpt-oss-20b")
DEFAULT_INGEST_MODEL= get_config_value("DEFAULT_INGEST_MODEL", "qwen3-coder-30b-a3b-instruct")
DEFAULT_EMBEDDING_MODEL = get_config_value("DEFAULT_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")

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

# 子文档提取/递归相关配置
SUBDOC_USE_WEBHOOK_FALLBACK = get_config_value("SUBDOC_USE_WEBHOOK_FALLBACK", "true").lower() == "true"
SUBDOC_MAX_CONCURRENCY = int(get_config_value("SUBDOC_MAX_CONCURRENCY", "10"))  # 子文档并发处理数量
SUBDOC_MAX_RETRIES = int(get_config_value("SUBDOC_MAX_RETRIES", "2"))  # 子文档失败时的最大重试次数
SUBDOC_RETRY_BACKOFF_BASE = float(get_config_value("SUBDOC_RETRY_BACKOFF_BASE", "1.0"))  # 初始退避秒数
SUBDOC_RETRY_BACKOFF_FACTOR = float(get_config_value("SUBDOC_RETRY_BACKOFF_FACTOR", "2.0"))  # 指数退避因子
SUBDOC_RETRY_JITTER = float(get_config_value("SUBDOC_RETRY_JITTER", "0.3"))  # 抖动上限（0~该值内随机）

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
print(f"SUBDOC_USE_WEBHOOK_FALLBACK: {SUBDOC_USE_WEBHOOK_FALLBACK}")

# 工具相关配置
print(f"DEFAULT_TOOL_MODE: {DEFAULT_TOOL_MODE}")
print(f"MAX_TOOL_STEPS: {MAX_TOOL_STEPS}")

# Web 搜索相关配置
print(f"WEB_SEARCH_RESULT_COUNT: {WEB_SEARCH_RESULT_COUNT}")
print(f"WEB_SEARCH_MAX_QUERIES: {WEB_SEARCH_MAX_QUERIES}")
print(f"WEB_SEARCH_MAX_RESULTS: {WEB_SEARCH_MAX_RESULTS}")
print(f"MAX_KEYWORDS_PER_GAP: {MAX_KEYWORDS_PER_GAP}")
print(f"GAP_RECALL_TOP_K: {GAP_RECALL_TOP_K}")
print(f"MAX_WORDS_PER_QUERY: {MAX_WORDS_PER_QUERY}")
print(f"WEB_LOADER_ENGINE: {WEB_LOADER_ENGINE}")
print(f"PLAYWRIGHT_MAX_CONCURRENCY: {PLAYWRIGHT_MAX_CONCURRENCY}")
print(f"PLAYWRIGHT_WAIT_FOR_FONTS: {PLAYWRIGHT_WAIT_FOR_FONTS}")
print(f"PLAYWRIGHT_WAIT_FOR_DOM_STABLE: {PLAYWRIGHT_WAIT_FOR_DOM_STABLE}")
print(f"PLAYWRIGHT_DOM_STABLE_MS: {PLAYWRIGHT_DOM_STABLE_MS}")
print(f"PLAYWRIGHT_TEXT_STABLE_CHECKS: {PLAYWRIGHT_TEXT_STABLE_CHECKS}")
print(f"PLAYWRIGHT_TEXT_STABLE_INTERVAL_MS: {PLAYWRIGHT_TEXT_STABLE_INTERVAL_MS}")
print(f"PLAYWRIGHT_MIN_CHARS: {PLAYWRIGHT_MIN_CHARS}")
print(f"PLAYWRIGHT_MAX_NODES_CHECK: {PLAYWRIGHT_MAX_NODES_CHECK}")
print(f"HTTPX_HTTP2_ENABLED: {HTTPX_HTTP2_ENABLED}")
print(f"HTTPX_MAX_KEEPALIVE_CONNECTIONS: {HTTPX_MAX_KEEPALIVE_CONNECTIONS}")
print(f"HTTPX_MAX_CONNECTIONS: {HTTPX_MAX_CONNECTIONS}")
print(f"TIKTOKEN_CACHE_DIR: {TIKTOKEN_CACHE_DIR}")
print(f"ENABLE_QUERY_GENERATION: {ENABLE_QUERY_GENERATION}")
print(f"CHUNK_SIZE: {CHUNK_SIZE}")
print(f"RAG_TOP_K: {RAG_TOP_K}")
print(f"NORMAL_MAX_SUB_QUERIES: {NORMAL_MAX_SUB_QUERIES}")
print("-------------------------------")
