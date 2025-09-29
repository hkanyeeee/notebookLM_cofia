## Project Overview

This is a Python/FastAPI backend service designed for NotebookLM-like applications, providing document processing, Retrieval-Augmented Generation (RAG), and intelligent tool orchestration capabilities.

Key features include:
- Document ingestion from URLs with content extraction, chunking, and embedding generation
- Vector storage using Qdrant for efficient similarity search
- RAG implementation that retrieves relevant document chunks based on user queries
- Tool orchestration framework supporting multiple modes (JSON Function Calling, ReAct, Harmony)
- Integration with n8n workflow automation platform via webhooks

## Architecture & Structure

The application follows a modular FastAPI structure:

```
app/
├── main.py              # FastAPI app entry point and lifespan management
├── config.py            # Configuration loading from .env file
├── database.py          # Database initialization with SQLAlchemy async ORM
├── models.py            # SQLAlchemy data models (Source, Chunk, etc.)
├── api/                 # API routes organized by functionality:
│   ├── ingest.py        # Document ingestion endpoints
│   ├── auto_ingest.py   # Auto ingestion endpoints
│   ├── collections.py   # Collection management
│   ├── search.py        # Search endpoints
│   ├── documents.py     # Document management
│   ├── query.py         # Query processing with RAG and tools
│   ├── models.py        # Model information endpoints
│   ├── webhook.py       # Webhook handling for n8n integration
│   └── n8n_workflow.py  # N8N workflow endpoints
├── tools/               # Tool orchestration system:
│   ├── orchestrator.py  # Main tool orchestrator with strategies
│   ├── models.py        # Tool execution models and data structures
│   ├── registry.py      # Tool registration and management
│   ├── selector.py      # Strategy selection logic
│   ├── strategies/      # Different execution strategies (JSON FC, ReAct, Harmony)
│   └── utils/           # Utility functions for tools
├── fetch_parse.py       # Web content fetching and parsing utilities
├── chunking.py          # Document chunking logic
├── embedding_client.py  # Embedding generation client
└── vector_db_client.py  # Qdrant vector database operations
```

## Common Development Tasks

### Running the Application
1. Set up Python virtual environment (conda or venv)
2. Install dependencies: `pip install -r requirements.txt`
3. Create `.env` file with required configuration variables
4. Start development server: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

### Key Configuration Variables
- DATABASE_URL: SQLite database connection string
- EMBEDDING_SERVICE_URL: URL for embedding generation service
- LLM_SERVICE_URL: URL for large language model service
- QDRANT_HOST/QDRANT_PORT: Qdrant vector DB configuration
- SEARXNG_QUERY_URL: Searxng search engine endpoint

### Testing & Debugging
- Tests are typically run with pytest or similar frameworks (not explicitly configured in this project)
- Use `http://localhost:8000/docs` to access interactive API documentation
- Check logs for runtime errors and initialization issues

## Development Notes

This is an asynchronous FastAPI application using SQLAlchemy async ORM. The tool orchestration system implements multiple execution strategies including JSON Function Calling, ReAct, and Harmony modes. Vector operations are handled via Qdrant client with optimized configurations.

The codebase has a strong focus on RAG capabilities with hybrid dense/sparse retrieval using both vector search and BM25.