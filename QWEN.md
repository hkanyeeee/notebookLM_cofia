# NotebookLM-Py Project Context

## Project Overview

This is a Python-based backend project for a NotebookLM-like application. It leverages FastAPI for the web API, SQLAlchemy for database interactions (primarily with SQLite), and integrates with external services for embedding, LLM reasoning, reranking, and web search (Searxng). The core idea is to ingest documents (from URLs), process them (chunking, embedding), store them (SQLite for metadata, Qdrant for vectors), and then use them for Retrieval-Augmented Generation (RAG) to answer user queries, potentially using tools for web search or other actions.

Key features include:
- Document ingestion via URL with progress streaming.
- Text chunking, embedding, and storage in a vector database (Qdrant).
- A tool orchestration system that can perform multi-step reasoning and actions (like web search) to answer complex queries.
- Integration with n8n for workflow execution.
- Webhook support for asynchronous processing.

The project is designed to be run in a containerized environment (Docker Compose) but can also be run locally.

## Directory Structure

```
notebookLM_cofia/
├── app/                  # Main Python application code
│   ├── api/              # FastAPI routers for different functionalities (ingest, search, collections, etc.)
│   ├── tools/            # Tool orchestration system (Reason-Act-Observation loop)
│   ├── config.py         # Centralized configuration loading from .env
│   ├── database.py       # Database setup and session management
│   ├── models.py         # SQLAlchemy data models
│   ├── main.py           # FastAPI application entry point and lifespan management
│   ├── fetch_parse.py    # Utilities for fetching and parsing web content
│   ├── chunking.py       # Text chunking logic
│   ├── embedding_client.py # Client for calling the embedding service
│   ├── vector_db_client.py # Client for interacting with the Qdrant vector database
│   ├── llm_client.py     # Client for calling the LLM service
│   ├── rerank_client.py  # Client for calling the reranker service
│   └── cache.py          # Caching utilities (e.g., for web content)
├── notebookLM_front/     # (Likely) Frontend application code (not analyzed)
├── gateway_script/       # (Likely) Scripts for the embedding gateway (not analyzed)
├── data/                 # (Likely created at runtime) Persistent data directory for Docker
├── tests/                # (Likely) Test scripts (test_*.py)
├── Dockerfile.backend    # Dockerfile for the backend service
├── docker-compose.yml    # Docker Compose configuration for all services
├── requirements.txt      # Python dependencies
├── readme               # Brief startup instructions
└── .env                 # Environment variables (not committed)
```

## Key Technologies & Components

- **FastAPI**: The core web framework.
- **SQLAlchemy (Async)**: ORM for database interactions. Uses SQLite (`test.db`) by default.
- **Qdrant**: Vector database for storing and searching document embeddings.
- **Searxng**: External service for web search capabilities.
- **n8n**: Workflow automation tool, integrated via webhooks and API calls.
- **Playwright/Trafilatura**: Libraries for web page fetching and parsing.
- **Docker/Docker Compose**: For containerized deployment.

## Configuration (app/config.py)

Configuration is primarily loaded from a `.env` file in the project root. Key configuration variables include:
- Database URL (`DATABASE_URL`)
- Service URLs for Embedding, LLM, Reranker (`EMBEDDING_SERVICE_URL`, `LLM_SERVICE_URL`, `RERANKER_SERVICE_URL`)
- Qdrant connection details (`QDRANT_HOST`, `QDRANT_PORT`)
- Searxng query URL (`SEARXNG_QUERY_URL`)
- Webhook prefix for n8n callbacks (`WEBHOOK_PREFIX`)
- Concurrency and batch size settings for embedding (`EMBEDDING_MAX_CONCURRENCY`, `EMBEDDING_BATCH_SIZE`)
- Tool orchestration settings (`DEFAULT_TOOL_MODE`, `MAX_TOOL_STEPS`)
- Web search limitations and configurations (`WEB_SEARCH_RESULT_COUNT`, `WEB_SEARCH_MAX_QUERIES`, etc.)
- Chunking settings (`CHUNK_SIZE`, `CHUNK_OVERLAP`)
- RAG settings (`RAG_TOP_K`, `RAG_RERANK_TOP_K`)

## Data Models (app/models.py)

- `Source`: Represents a document ingested from a URL. Has a one-to-many relationship with `Chunk`.
- `Chunk`: Represents a segment of text from a `Source`.
- `WorkflowExecution`: Tracks the execution status of n8n workflows.

## Core API Endpoints (app/api/)

- `/ingest`: Ingests a document from a URL, chunking, embedding, and storing it. Streams progress via Server-Sent Events (SSE).
- `/agenttic_ingest`: Alternative ingestion endpoint, likely involving more complex processing or tool usage.
- `/collections`: Manages document collections/sessions (listing, creating, deleting).
- `/search`: Performs semantic search on ingested documents using Qdrant.
- `/documents`: Manages individual documents within collections (listing, deleting).
- `/query`: The main endpoint for querying the system. Uses RAG and can invoke the tool orchestrator.
- `/export`: Exports data, potentially in PDF format via n8n workflows.
- `/models`: Retrieves available models from the LLM service.
- `/webhook`: Handles incoming webhooks, likely from n8n.
- `/n8n_workflow`: Manages n8n workflow execution.

## Tool Orchestration (app/tools/)

A sophisticated system implementing a "Reason-Act-Observation" loop. It can use different strategies (JSON Function Calling, ReAct, Harmony) to decide which tools to use and how to interpret their results. Tools include web search and potentially others. The orchestrator is initialized in `app/main.py` during application startup.

## Building and Running

### Local Development

1.  **Setup Environment**: Ensure Python (likely 3.8+) is installed.
2.  **Install Dependencies**: `pip install -r requirements.txt`.
3.  **Configure**: Create a `.env` file based on the variables used in `app/config.py`. You'll need to provide URLs for your Qdrant, embedding, LLM, and Searxng services.
4.  **Run**: `conda activate mlx && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` (as per the `readme`). Note: The `conda activate mlx` part might be specific to the developer's setup; the core command is `uvicorn app.main:app ...`.

### Docker Compose (Recommended)

1.  **Setup Network**: `docker network create localnet`.
2.  **Configure**: Review and adjust the environment variables in `docker-compose.yml` and the `.env` file.
3.  **Build & Run**: `docker-compose up --build`.
    - This will start services for the backend, frontend, embedding gateway, and n8n.
    - The backend will be accessible on port 8000.
    - The frontend will be accessible on port 9001.
    - n8n will be accessible on port 5678.

## Development Conventions

- **Asynchronous Programming**: Heavy use of `async`/`await` throughout the backend for I/O-bound operations (database, HTTP requests).
- **FastAPI Structure**: Clear separation of concerns using routers (`app/api/`) and dependency injection (e.g., `Depends(get_db)`, `Depends(get_session_id)`).
- **Environment-based Configuration**: Centralized configuration management via `.env` and `app/config.py`.
- **SQLAlchemy ORM**: Used for database interactions, with models defined in `app/models.py`.
- **Streaming Responses**: Used for long-running processes like document ingestion to provide real-time feedback.
- **Modular Tool System**: Tools and orchestration strategies are modular and extensible.