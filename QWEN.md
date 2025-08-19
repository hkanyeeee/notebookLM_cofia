# NotebookLM-Py Project Documentation

## Project Overview

NotebookLM-Py is a document ingestion and querying system that allows users to ingest documents from URLs, store them in a database and vector store, and then query them using semantic search. It features both dense and sparse retrieval methods with hybrid search capabilities, and optional reranking.

## Architecture

The system is composed of:
- **Backend API**: FastAPI application with routers for ingest, search, documents and query operations
- **Frontend**: Vue.js application for user interface
- **Database**: Uses SQLAlchemy with async support and SQLite as default
- **Vector Storage**: Qdrant vector database for semantic search
- **Supporting services**: Embedding and reranking gateways

## Code Structure

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
  - `/webhook/send`: Send webhook notifications
  - `/workflow_response`: Demo endpoint to print incoming workflow response data
  - `/agenttic-ingest`: Smart document ingestion with webhook notifications
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
- `embedding_gateway.py`: Gateway for load-balancing embedding requests across multiple backends

## Key Technical Details

1. The system uses a hybrid search approach combining dense vector search (Qdrant) and sparse BM25 search (SQLite FTS5)
2. Concurrent processing for embedding generation with semaphore-based limits
3. Support for optional reranking with a gateway that can load-balance across multiple reranker instances
4. Session-based data isolation to support multiple users/contexts
5. Streaming progress updates during document ingestion
6. Integration with Playwright for web content extraction

## Environment Configuration

The system uses environment variables from `.env` file with fallback to OS environment variables. Key configuration includes:
- `DATABASE_URL`: Database connection string (SQLite by default)
- `EMBEDDING_SERVICE_URL`: URL for embedding service
- `LLM_SERVICE_URL`: URL for LLM service
- `RERANKER_SERVICE_URL`: URL for reranker service
- `QDRANT_HOST/PORT`: Qdrant vector database connection
- `PROXY_URL`: Optional proxy for web requests

## Development Commands

### Backend
- `conda activate mlx && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` - Run backend locally
- `pip install -r requirements.txt` - Install Python dependencies

### Frontend
- `cd notebookLM_front && pnpm install` - Install frontend dependencies
- `cd notebookLM_front && pnpm dev` - Run frontend development server

### Docker
- `docker-compose up --build` - Build and run the full application in containers

## Project Dependencies

The project uses Python 3.11 with the following key dependencies:
- FastAPI and Uvicorn for the backend API
- SQLAlchemy with async support for database operations
- Qdrant-client for vector storage
- Playwright for web content extraction
- BeautifulSoup4 and readability-lxml for content parsing
- Various other libraries for HTTP requests, embeddings, etc.

## API Endpoints

### Ingestion
- `POST /ingest`: Ingest a document from a URL and stream progress
- `POST /agenttic-ingest`: Smart document ingestion with webhook notifications

### Search
- `GET /search`: Search for documents by title
- `POST /query`: Query ingested documents with hybrid search and optional reranking

### Documents
- `GET /documents`: List all documents
- `DELETE /documents/{document_id}`: Delete a document by ID

### Webhook
- `POST /webhook/send`: Send webhook notifications to external services
- `POST /workflow_response`: Demo endpoint to print incoming workflow response data

## Data Flow

1. User submits a URL for ingestion
2. System fetches and parses the content using Playwright and readability-lxml
3. Content is chunked into smaller pieces
4. Each chunk is embedded using the embedding service
5. Embeddings are stored in Qdrant vector database
6. Document metadata is stored in SQLite database
7. When querying, system performs hybrid search combining vector and BM25 search
8. Optional reranking can be applied to improve results
9. Results are returned to the user through the frontend interface

## Docker Setup

The project uses Docker Compose for orchestration:
- Backend service with FastAPI
- Frontend service with Vue.js
- Embedding gateway for load balancing embedding requests
- Optional Qdrant vector database (can be external)
- n8n workflow automation tool

## Testing

The project includes test files:
- `test_agenttic_ingest.py`: Tests for agenttic ingestion
- Various cleanup scripts for database management

## Deployment

The application can be deployed using Docker Compose with the provided configuration. The backend is configured to run on port 8000, and the frontend on port 9001.