from dotenv import dotenv_values

# Load variables directly from project-root .env file
config = dotenv_values(".env")
DATABASE_URL = config.get("DATABASE_URL")
EMBEDDING_SERVICE_URL = config.get("EMBEDDING_SERVICE_URL")
LLM_SERVICE_URL = config.get("LLM_SERVICE_URL")
MILVUS_HOST = config.get("MILVUS_HOST")
MILVUS_PORT = config.get("MILVUS_PORT")