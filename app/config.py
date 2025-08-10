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

# Qdrant Configuration
QDRANT_HOST = get_config_value("QDRANT_HOST", "localhost")
QDRANT_PORT = get_config_value("QDRANT_PORT", "6333")
QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_PORT}"
QDRANT_API_KEY = get_config_value("QDRANT_API_KEY", None)

# Proxy configuration (optional)
HTTP_PROXY = get_config_value("HTTP_PROXY")
HTTPS_PROXY = get_config_value("HTTPS_PROXY")
PROXY_URL = get_config_value("PROXY_URL") or HTTP_PROXY or HTTPS_PROXY

print("--- Application Configuration ---")
print(f"DATABASE_URL: {DATABASE_URL}")
print(f"EMBEDDING_SERVICE_URL: {EMBEDDING_SERVICE_URL}")
print(f"LLM_SERVICE_URL: {LLM_SERVICE_URL}")
print(f"RERANKER_SERVICE_URL: {RERANKER_SERVICE_URL}")
print(f"QDRANT_URL: {QDRANT_URL}")
print(f"PROXY_URL: {PROXY_URL}")
print("-------------------------------")
