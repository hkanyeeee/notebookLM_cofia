# NotebookLM-cofia Project Context

## Project Overview

This is a Python-based backend service for a project named NotebookLM-cofia. It's built using the FastAPI framework. The service is designed to handle document ingestion, chunking, embedding, and storage in a vector database (Qdrant). It also provides capabilities for searching and querying these documents, likely to support a Retrieval-Augmented Generation (RAG) system.

A key feature is its "Tool Orchestration" system (`app/tools`), which implements a Reasoning-Action-Observation loop (similar to ReAct or Agent frameworks) to allow the LLM to use external tools (like web search) to answer queries. It supports multiple strategies for tool interaction (JSON Function Calling, ReAct, Harmony DSL).

The project uses SQLite as its primary relational database (via SQLAlchemy) for storing document metadata and chunked text. It integrates with external services for embeddings, LLMs, reranking, and web search (Searxng). It also includes integration with n8n, a workflow automation tool, via webhooks.

## Key Technologies

- **Language:** Python
- **Framework:** FastAPI
- **Database:** SQLite (SQLAlchemy for ORM)
- **Vector Store:** Qdrant
- **External Services:**
  - Custom Embedding Gateway
  - Custom LLM Service (e.g., LM Studio)
  - Searxng (for web search)
  - n8n (workflow automation)

## Architecture

- **Main App (`app/main.py`):** The FastAPI application entry point. Configures CORS, initializes the database and tool orchestrator, and includes various API routers.
- **Configuration (`app/config.py`):** Loads configuration from `.env` file and environment variables. Defines numerous settings for database, external services, chunking, RAG, web search, tools, etc.
- **Database (`app/database.py`, `app/models.py`):** Uses SQLAlchemy for async database operations. Models define `Source`, `Chunk`, and `WorkflowExecution`.
- **API (`app/api/`):** Contains routers for different functionalities:
  - `ingest.py`: Handles document ingestion from URLs.
  - `agenttic_ingest.py`: Alternative ingestion endpoint, possibly with tool orchestration.
  - `collections.py`, `documents.py`, `search.py`, `query.py`: Manage collections, documents, and perform search/query operations.
  - `webhook.py`, `n8n_workflow.py`: Handle callbacks and interactions with n8n.
- **Core Logic (`app/fetch_parse.py`, `app/chunking.py`, `app/embedding_client.py`, `app/vector_db_client.py`):** Utilities for fetching web content, chunking text, calling the embedding service, and interacting with Qdrant.
- **Tool Orchestration (`app/tools/`):** A dedicated subsystem for managing LLM tool usage.
  - `orchestrator.py`: The main controller for the Reason-Act-Observation loop.
  - `registry.py`: Registers and manages available tools.
  - `models.py`: Data structures for tools, steps, and configurations.
  - `strategies/`: Contains different implementations for interacting with tools (JSON, ReAct, Harmony).
  - Specific tools are likely defined elsewhere or registered dynamically.

## Building and Running

Based on the `readme` file and `requirements.txt`, the project is intended to be run in a Conda environment named `mlx` (though it uses standard Python packages).

1.  **Setup Environment:**
    - Create/activate a Python environment (e.g., using Conda or venv).
    - Install dependencies: `pip install -r requirements.txt`

2.  **Configuration:**
    - Configure environment variables in a `.env` file. Key variables include:
        - `DATABASE_URL` (e.g., `sqlite+aiosqlite:///./test.db`)
        - `EMBEDDING_SERVICE_URL` (URL of the embedding gateway)
        - `LLM_SERVICE_URL` (URL of the LLM service)
        - `QDRANT_HOST`, `QDRANT_PORT` (Qdrant connection details)
        - `SEARXNG_QUERY_URL` (URL of the Searxng instance)
        - `WEBHOOK_PREFIX` (Base URL for webhooks)
        - `N8N_*` variables (n8n integration settings)

3.  **Run the Application:**
    - The command from the `readme` is: `conda activate mlx && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
    - This starts the FastAPI development server on port 8000, reloading on code changes.

## Development Conventions

- The project uses SQLAlchemy for database interactions with an async setup.
- FastAPI is used for the web framework, leveraging Pydantic models for request/response validation.
- Configuration is managed centrally through `config.py` using environment variables and `.env` files.
- The codebase is structured into modules based on functionality (`api`, `tools`, core utilities).
- Tools are managed through a registry and orchestration system, allowing for modular addition of new capabilities.

## Docker Deployment

The project includes a `docker-compose.yml` file, suggesting it's designed for containerized deployment. This setup includes services for the backend, frontend, an embedding gateway, and n8n, all connected via a custom Docker network (`localnet`). The backend service configuration shows how various services are connected using environment variables.