# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a document ingestion and querying system (NotebookLM-Py) that allows users to ingest documents from URLs, store them in a database and vector store, and then query them using semantic search. It features both dense and sparse retrieval methods with hybrid search capabilities, and optional reranking.

## Code Structure

The codebase is organized into:
- Backend API: FastAPI application in `app/` directory with routers for ingest, search, documents and query operations
- Frontend: Vue.js application in `notebookLM_front/` directory 
- Database: Uses SQLAlchemy with async support and SQLite as default
- Vector Storage: Qdrant vector database for semantic search
- Supporting services: Embedding and reranking gateways

## Key Components

### Backend API (`app/`)
- `main.py`: FastAPI application with CORS middleware and router inclusion
- `config.py`: Configuration loading from environment variables and .env file
- `database.py`: Database initialization with SQLite and FTS5 support for BM25 search
- `models.py`: SQLAlchemy ORM models for Source and Chunk entities
- `api/` directory: API routers for:
  - `/ingest`: Document ingestion from URLs with streaming progress
  - `/search`: Search for documents by title
  - `/documents`: List documents and delete by ID
  - `/query`: Query ingested documents with hybrid search and optional reranking
- `vector_db_client.py`: Qdrant client for vector storage operations
- `embedding_client.py`: Client for embedding generation
- `rerank_client.py`: Client for reranking with optional gateway support
- `llm_client.py`: Client for LLM-based answer generation

### Frontend (`notebookLM_front/`)
- Vue 3 + Vite application for user interface
- Components for chat and sidebar functionality

### Supporting Files
- `docker-compose.yml`: Docker orchestration for backend and frontend
- `Dockerfile.backend`: Backend service Dockerfile with Playwright dependencies
- `rerank_gateway.py`: Gateway for load-balancing reranking requests across multiple backends

## Development Commands

### Backend
- `conda activate mlx && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` - Run backend locally
- `pip install -r requirements.txt` - Install Python dependencies

### Frontend
- `cd notebookLM_front && pnpm install` - Install frontend dependencies
- `cd notebookLM_front && pnpm dev` - Run frontend development server

### Docker
- `docker-compose up --build` - Build and run the full application in containers

## Key Technical Details

1. The system uses a hybrid search approach combining dense vector search (Qdrant) and sparse BM25 search (SQLite FTS5)
2. Concurrent processing for embedding generation with semaphore-based limits
3. Support for optional reranking with a gateway that can load-balance across multiple reranker instances
4. Session-based data isolation to support multiple users/contexts
5. Streaming progress updates during document ingestion
6. Integration with Playwright for web content extraction

## Environment Configuration

The system uses environment variables from `.env` file with fallback to OS environment variables. Key configuration includes:
- DATABASE_URL: Database connection string (SQLite by default)
- EMBEDDING_SERVICE_URL: URL for embedding service
- LLM_SERVICE_URL: URL for LLM service
- RERANKER_SERVICE_URL: URL for reranker service
- QDRANT_HOST/PORT: Qdrant vector database connection
- PROXY_URL: Optional proxy for web requests