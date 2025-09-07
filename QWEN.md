# NotebookLM-cofia Project Documentation

## Overview

NotebookLM-cofia is a Python-based backend service built with FastAPI that provides powerful document processing, Retrieval-Augmented Generation (RAG), and intelligent tool orchestration capabilities. It's designed to support applications similar to NotebookLM by enabling users to ingest documents from URLs, store them in vector databases, perform semantic search, and integrate with external tools through an agent-like framework.

## Core Features

*   **Document Ingestion:** Extracts content from web URLs, chunks the text, and generates vector embeddings
*   **Vector Storage:** Uses Qdrant vector database to store document chunks and their embeddings for efficient similarity search
*   **Retrieval-Augmented Generation (RAG):** Retrieves relevant document fragments based on user queries and provides them as context to large language models (LLMs)
*   **Intelligent Tool Orchestration:** Implements a ReAct/JSON Function Calling framework that allows LLMs to call external tools (like web search) to fill knowledge gaps or perform specific tasks
*   **Workflow Integration:** Integrates with n8n workflow automation platform via Webhooks

## Technology Stack

*   **Language:** Python 3.10+
*   **Framework:** FastAPI (asynchronous API)
*   **Database:** SQLite (via SQLAlchemy async ORM)
*   **Vector Database:** Qdrant
*   **Search Engine:** Searxng
*   **Dependency Management:** pip / conda

## Project Structure

```
notebookLM-cofia/
├── app/                    # Main application code
│   ├── main.py             # FastAPI application entry point
│   ├── config.py           # Configuration loading
│   ├── database.py         # Database connection and initialization
│   ├── models.py           # SQLAlchemy data models
│   ├── api/                # API routes
│   │   ├── ingest.py       # Document ingestion endpoints
│   │   ├── agenttic_ingest.py  # Agent-based ingestion
│   │   ├── collections.py  # Collections management
│   │   ├── search.py       # Search endpoints
│   │   ├── documents.py    # Documents management
│   │   ├── query.py        # Query processing
│   │   ├── models.py       # Model endpoints
│   │   ├── webhook.py      # Webhook endpoints
│   │   ├── n8n_workflow.py # n8n workflow integration
│   │   └── vector_fix.py   # Vector database fixes
│   ├── tools/              # Tool orchestration and execution logic
│   │   ├── orchestrator.py # Tool orchestrator
│   │   ├── web_search_tool.py  # Web search tool implementation
│   │   └── strategies/     # Different execution strategies (JSON, ReAct, Harmony)
├── notebookLM_front/       # Frontend code (if exists)
├── scripts/                # Utility scripts
├── requirements.txt        # Python dependencies
├── docker-compose.yml      # Docker Compose configuration
├── Dockerfile.backend      # Backend Dockerfile
├── .env                    # Environment variables
└── readme.md               # Project documentation
```

## Building and Running

### Quick Start

1. Create a virtual environment:
   ```bash
   conda create -n notebooklm python=3.10
   conda activate notebooklm
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment variables in `.env` file (refer to `readme.md` for details)

4. Start the service:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

### Docker Deployment

The project provides a `docker-compose.yml` file for easy deployment using Docker Compose:

1. Create the required network:
   ```bash
   docker network create localnet
   ```

2. Configure environment variables in `.env` file

3. Build and start services:
   ```bash
   docker compose build
   docker-compose up -d
   ```

## Development Conventions

*   **Chunk ID Format:** `chunk_id` must be generated as `session_id|url|index` (e.g., `session123|https://example.com|0`). Do not use other formats.
*   **Web Search Tool:** `web_search` requires `query` parameter. `filter_list` (array of domains) is optional but must be provided as an array.
*   **Database Performance:** Use PRAGMA journal_mode=WAL, synchronous=NORMAL, busy_timeout=30000 in database connections for better concurrency.
*   **Vector Database Usage:** Always use `vector_db_client` module. Never use raw SQL.
*   **Tool Parameters:** Verify required parameters (e.g., `web_search` requires `query`).

## Testing

Run tests with:
```bash
python test_agenttic_ingest.py
```

## Key Configuration Options

The application uses a comprehensive configuration system that supports both environment variables and `.env` file settings. Key configuration options include:

*   Database connection (`DATABASE_URL`)
*   Embedding service URL (`EMBEDDING_SERVICE_URL`)
*   LLM service URL (`LLM_SERVICE_URL`)
*   Qdrant database configuration (`QDRANT_HOST`, `QDRANT_PORT`, etc.)
*   Searxng search engine URL (`SEARXNG_QUERY_URL`)
*   Tool orchestration settings (`DEFAULT_TOOL_MODE`, `MAX_TOOL_STEPS`)
*   Web search parameters (`WEB_SEARCH_RESULT_COUNT`, `WEB_SEARCH_MAX_QUERIES`, etc.)
*   Document processing settings (`CHUNK_SIZE`, `CHUNK_OVERLAP`)
*   RAG configuration (`RAG_TOP_K`, `QUERY_TOP_K_BEFORE_RERANK`, etc.)

## API Endpoints

The service exposes several key endpoints:

*   `/ingest` - Ingest a document from a URL
*   `/agenttic-ingest` - Agent-based document ingestion
*   `/search` - Search for documents
*   `/query` - Query the system with RAG
*   `/collections` - Manage collections
*   `/documents` - Manage documents
*   `/webhook` - Webhook endpoints for n8n integration

## Tool Orchestration

The system implements a sophisticated tool orchestration framework that supports multiple execution strategies:
*   JSON Function Calling (JSON)
*   ReAct (Reason → Act → Observe)
*   Harmony (a hybrid approach)

Tools can be registered and executed in a controlled manner, with support for:
*   Tool selection based on model capabilities
*   Execution timeouts
*   Step limits
*   Conversation history management

## Web Search Integration

The web search tool integrates with Searxng to:
*   Generate search queries from user input
*   Perform concurrent searches across multiple keywords
*   Crawl and extract content from web pages
*   Process documents (chunking, embedding)
*   Store results in vector database for retrieval
*   Support content deduplication and caching

## Cache Management

The system implements a web content cache to improve performance:
*   Configurable maximum size
*   Time-to-live settings
*   Content size limits
*   Automatic cleanup of old entries

## Data Models

The application uses SQLAlchemy models for data persistence:

1. **Source**: Represents a source document with URL, title, and session ID
2. **Chunk**: Represents a chunk of text from a source document with content and chunk ID
3. **WorkflowExecution**: Tracks n8n workflow executions

## Key Implementation Details

*   Uses asynchronous programming with FastAPI and SQLAlchemy async ORM
*   Implements proper database connection management with SQLite-specific optimizations (WAL mode, busy_timeout)
*   Supports concurrent processing of embeddings and database operations
*   Implements streaming responses for long-running operations
*   Provides comprehensive error handling and logging
*   Uses a modular architecture that separates concerns between ingestion, processing, storage, and retrieval