# NotebookLM-cofia Project Documentation

## Project Overview

NotebookLM-cofia is a Python-based backend service built with FastAPI that provides powerful document processing, Retrieval-Augmented Generation (RAG), and intelligent tool orchestration capabilities for applications similar to NotebookLM.

The system is designed to:
- Ingest documents from URLs, extract content, chunk it, and generate vector embeddings
- Store document chunks in Qdrant vector database for efficient similarity search
- Implement RAG to provide context-aware responses based on document retrieval
- Enable tool orchestration through a ReAct/JSON Function Calling framework that allows LLMs to call external tools
- Integrate with n8n workflow automation platform via webhooks

## Core Technologies

- **Language:** Python 3.10+
- **Framework:** FastAPI (asynchronous API)
- **Database:** SQLite (via SQLAlchemy async ORM)
- **Vector Database:** Qdrant
- **Search Engine:** Searxng
- **Dependency Management:** pip / conda
- **Containerization:** Docker with Docker Compose

## Project Structure

```
notebookLM_cofia/
├── app/                    # Main application code
│   ├── api/                # API routes
│   │   ├── ingest.py       # Document ingestion endpoints
│   │   ├── agenttic_ingest.py  # Agent-based ingestion
│   │   ├── collections.py  # Vector collection management
│   │   ├── search.py       # Search endpoints
│   │   ├── documents.py    # Document management
│   │   ├── query.py        # Query processing
│   │   ├── models.py       # Model endpoints
│   │   ├── webhook.py      # Webhook handling
│   │   ├── n8n_workflow.py # n8n workflow integration
│   │   └── vector_fix.py   # Vector database fixes
│   ├── tools/              # Tool orchestration logic
│   ├── config.py           # Configuration loading
│   ├── database.py         # Database connection and initialization
│   ├── models.py           # SQLAlchemy data models
│   ├── main.py             # FastAPI application entry point
│   ├── embedding_client.py # Embedding service client
│   ├── vector_db_client.py # Qdrant client
│   ├── fetch_parse.py      # Web content fetching and parsing
│   ├── chunking.py         # Document chunking logic
│   └── rerank_client.py    # Reranking service client
├── notebookLM_front/       # Frontend code (React-based)
├── gateway_script/         # Gateway scripts for embedding and reranking
├── docker-compose.yml      # Docker Compose configuration
├── Dockerfile.backend      # Backend Dockerfile
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (not committed)
├── readme.md               # Project documentation
└── ...
```

## Building and Running

### Development Setup

1. Create a virtual environment:
```bash
# Using Conda (recommended)
conda create -n notebooklm python=3.10
conda activate notebooklm

# Or using venv
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\\Scripts\\activate     # Windows
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root with required configuration variables:
```env
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
EMBEDDING_SERVICE_URL=http://localhost:7998/v1
LLM_SERVICE_URL=http://localhost:1234/v1
QDRANT_HOST=localhost
QDRANT_PORT=6333
SEARXNG_QUERY_URL=http://localhost:8080/search
```

4. Start the service:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API documentation will be available at `http://localhost:8000/docs`.

### Docker Deployment

The project includes a `docker-compose.yml` file for easy deployment:

1. Create the required Docker network:
```bash
docker network create localnet
```

2. Configure environment variables in `.env` file (or use defaults from docker-compose.yml)

3. Build and start services:
```bash
docker compose build
docker-compose up -d
```

## Key Features

### Document Ingestion
- Web content ingestion from URLs
- Automatic content extraction using readability-lxml and trafilatura
- Document chunking with configurable overlap
- Vector embedding generation

### Vector Storage and Search
- Qdrant vector database integration
- Efficient similarity search for document retrieval
- Configurable collection names and storage parameters

### Retrieval-Augmented Generation (RAG)
- Context-aware response generation
- Configurable top-k retrieval parameters
- Optional reranking functionality

### Tool Orchestration
- ReAct/JSON Function Calling framework for LLM tool usage
- Configurable tool modes (auto, json_fc, react)
- Maximum tool steps configuration

### n8n Integration
- Webhook endpoints for n8n workflow automation
- Configurable webhook URLs and timeouts

## Configuration

The application uses a combination of `.env` file and environment variables for configuration. Key settings include:

- Database connection (`DATABASE_URL`)
- External service URLs (embedding, LLM, Qdrant, Searxng)
- Vector database settings (host, port, API key, collection name)
- Tool orchestration parameters
- Web search configuration
- RAG settings (top-k values, chunking parameters)
- LLM model configurations

## Development Conventions

- Uses FastAPI for asynchronous API development
- Implements SQLAlchemy async ORM for database operations
- Follows modular structure with clear separation of concerns
- Uses environment variables for configuration management
- Includes comprehensive API documentation via FastAPI's built-in Swagger UI