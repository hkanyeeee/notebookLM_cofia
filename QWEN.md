# NotebookLM-Py Project Documentation

## Project Overview

NotebookLM-Py is a comprehensive document processing and retrieval system that allows users to ingest, process, and search through documents from URLs. It's built with a modern architecture that includes:

- A FastAPI backend for handling API requests
- A Vue.js frontend for user interaction
- Integration with embedding and reranking services
- Support for vector databases (Qdrant)
- Docker-based deployment

The system enables users to:
1. Ingest documents from URLs
2. Process and chunk content for embedding
3. Generate embeddings using external services
4. Store and search through documents using vector similarity

## Architecture

The system consists of several components:

1. **Backend API Server** (`app/main.py`): Built with FastAPI, handles all API endpoints for ingestion, search, document management, and query processing.

2. **Frontend Application** (`notebookLM_front/`): A Vue.js application providing the user interface for interacting with the system.

3. **Gateway Services**:
   - `embedding_gateway.py`: Routes embedding requests to multiple backend services
   - `rerank_gateway.py`: Routes reranking requests with load balancing and concurrency control

4. **Database**: Uses SQLite for local development, with support for other databases through SQLAlchemy.

5. **Vector Database**: Integrates with Qdrant for vector storage and similarity search.

## Key Features

- **Document Ingestion**: Streamed ingestion of documents from URLs with progress tracking
- **Text Chunking**: Automatic splitting of text into manageable chunks for embedding
- **Embedding Generation**: Integration with external embedding services via gateway
- **Search Functionality**: Vector-based similarity search through ingested documents
- **Document Management**: CRUD operations for managing ingested documents
- **Query Processing**: Natural language query processing with search results

## Technology Stack

### Backend
- Python 3.11
- FastAPI for API framework
- SQLAlchemy for database operations
- Uvicorn for ASGI server
- Qdrant client for vector storage
- Playwright for web scraping

### Frontend
- Vue 3 with TypeScript
- Element Plus UI components
- Pinia for state management
- Vite for build tooling

### Infrastructure
- Docker and Docker Compose for containerization
- Nginx for reverse proxy (in frontend)
- Qdrant for vector database

## Running the Application

### Development Environment Setup

1. **Prerequisites**:
   - Python 3.11
   - Node.js 20+
   - Docker and Docker Compose

2. **Backend Setup**:
   ```bash
   # Install Python dependencies
   pip install -r requirements.txt
   
   # Install Playwright Chromium
   python -m playwright install chromium
   ```

3. **Frontend Setup**:
   ```bash
   # Navigate to frontend directory
   cd notebookLM_front
   
   # Install Node.js dependencies
   pnpm install
   
   # Build the frontend
   pnpm build
   ```

4. **Running Services**:
   ```bash
   # Start all services with Docker Compose
   docker-compose up -d
   
   # Or start backend only (for development)
   conda activate mlx && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

### Docker Deployment

The project uses a multi-container setup with:
- `backend`: The main FastAPI application
- `frontend`: Vue.js frontend application
- `embedding-gateway`: Routes embedding requests to backend services
- `n8n`: Workflow automation tool (optional)

To run with Docker Compose:
```bash
docker-compose up -d
```

The frontend will be available at `http://localhost:9001` and the backend API at `http://localhost:8000`.

## API Endpoints

The backend exposes several API endpoints:

- `/ingest`: Ingest documents from URLs with progress streaming
- `/search`: Search through ingested documents using vector similarity
- `/documents`: Manage documents (list, get, delete)
- `/query`: Process natural language queries
- `/export`: Export documents or search results

## Development Conventions

1. **Code Style**: Python code follows PEP8 conventions with type hints
2. **Database Migrations**: SQLAlchemy is used for database operations
3. **Error Handling**: Comprehensive error handling with proper HTTP status codes
4. **Testing**: Unit tests are included in the test directory
5. **Documentation**: API endpoints are documented with FastAPI's automatic documentation

## Key Files and Directories

- `app/`: Main backend application code
  - `api/`: API route handlers
  - `models.py`: Database models
  - `database.py`: Database connection and initialization
  - `embedding_client.py`: Integration with embedding services
  - `vector_db_client.py`: Integration with vector database (Qdrant)
- `notebookLM_front/`: Frontend application
- `gateway_script/`: Gateway services for embedding and reranking
- `docker-compose.yml`: Docker orchestration configuration
- `Dockerfile.backend`: Backend Docker image definition
- `requirements.txt`: Python dependencies