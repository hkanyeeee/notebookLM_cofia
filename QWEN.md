# NotebookLM-cofia Project Context

## Project Overview

Python-based backend service using FastAPI for document ingestion, chunking, embedding, and storage in Qdrant vector database. Supports Retrieval-Augmented Generation (RAG) system with "Tool Orchestration" for LLM external tool usage.

## Key Technologies

- **Language:** Python
- **Framework:** FastAPI
- **Database:** SQLite (SQLAlchemy)
- **Vector Store:** Qdrant
- **External Services:**
  - Custom Embedding Gateway
  - Custom LLM Service (e.g., LM Studio)
  - Searxng (for web search)
  - n8n (workflow automation)

## Architecture

### Main App (`app/main.py`)
- FastAPI application entry point
- Configures CORS, initializes database and tool orchestrator
- Includes various API routers

### Configuration (`app/config.py`)
- Loads configuration from `.env` file and environment variables
- Defines settings for database, external services, chunking, RAG, web search, tools

### Database (`app/database.py`, `app/models.py`)
- Uses SQLAlchemy for async database operations
- Models: `Source`, `Chunk`, `WorkflowExecution`

### API (`app/api/`)
- `ingest.py`: Document ingestion from URLs
- `agenttic_ingest.py`: Alternative ingestion with tool orchestration, recursive document ingestion and webhook integration
- `collections.py`, `documents.py`, `search.py`, `query.py`: Manage collections, documents, search/query operations
- `webhook.py`, `n8n_workflow.py`: Handle callbacks and n8n interactions

### Core Logic (`app/fetch_parse.py`, `app/chunking.py`, `app/embedding_client.py`, `app/vector_db_client.py`)
- Web content fetching and parsing
- Text chunking
- Embedding service calls
- Qdrant interaction

### Tool Orchestration (`app/tools/`)
- `orchestrator.py`: Main controller for Reason-Act-Observation loop, supports streaming and non-streaming execution
- `registry.py`: Tools registry with concurrency control, retries, circuit breakers, parameter validation
- `models.py`: Data structures for tools, steps, configurations (tool schemas, calls, results, execution contexts)
- `strategies/`: Tool interaction implementations:
  - `json_fc.py`: JSON Function Calling strategy
  - `react.py`: ReAct strategy  
  - `harmony.py`: Harmony DSL strategy
- `web_search_tool.py`: Web search tool with LLM-powered query generation, SearxNG integration, advanced crawling, content deduplication, text chunking, vector embedding, hybrid search, caching
- `selector.py`: Tool strategy selector based on model capabilities
- `parsers.py`: Tool call parsers for different formats
- `formatters.py`: Tool result formatters
- `prompts.py`: Predefined prompt templates
- `query_decomposer.py`: Query decomposition for complex problems
- `reasoning_engine.py`: Reasoning engine for complex tasks and knowledge gap analysis
- `intelligent_orchestrator.py`: Intelligent orchestration for complex tool call workflows

## Building and Running

1. **Setup Environment:**
   - Create/activate Python environment (Conda or venv)
   - Install dependencies: `pip install -r requirements.txt`

2. **Configuration:**
   - Configure environment variables in `.env` file
   - Key variables: `DATABASE_URL`, `EMBEDDING_SERVICE_URL`, `LLM_SERVICE_URL`, `QDRANT_HOST`, `QDRANT_PORT`, `SEARXNG_QUERY_URL`, `WEBHOOK_PREFIX`, `N8N_*` variables

3. **Run the Application:**
   - Command: `conda activate mlx && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
   - Starts FastAPI development server on port 8000

## Docker Deployment

- Includes `docker-compose.yml` for containerized deployment
- Services: backend, frontend, embedding gateway, n8n
- All connected via custom Docker network (`localnet`)

## Qwen Added Memories
- Project Name: NotebookLM-cofia. Core Technology Stack: Python, FastAPI, SQLite (SQLAlchemy), Qdrant, Searxng. Core Functions: Document ingestion and indexing, RAG retrieval, ReAct framework-based tool orchestration (e.g., web search), and n8n workflow integration. Current working directory: /Users/hewenxin/code/notebookLM_cofia.
- Project configuration file: /Users/hewenxin/code/notebookLM_cofia/.env. Key service addresses: LLM_SERVICE_URL=http://192.168.31.98:1234/v1, EMBEDDING_SERVICE_URL=http://192.168.31.125:7998/v1, RERANKER_SERVICE_URL=http://192.168.31.125:7996, QDRANT_HOST=192.168.31.125, SEARXNG_QUERY_URL=http://192.168.31.125:8080/search. Database: DATABASE_URL=sqlite+aiosqlite:///./test.db. n8n integration: N8N_BASE_URL=http://n8n:5678/api/v1.
- Project startup command: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`. API documentation address: http://localhost:8000/docs.