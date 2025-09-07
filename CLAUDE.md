# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based backend service built with FastAPI that provides document processing, retrieval-augmented generation (RAG), and intelligent tool orchestration capabilities for applications similar to NotebookLM.

Key features include:
- Document ingestion from URLs with automatic chunking and vector embeddings
- Vector storage using Qdrant database
- Retrieval-augmented generation (RAG) for context-aware responses
- Intelligent tool orchestration (ReAct/JSON FC) allowing LLM to call external tools
- Integration with n8n workflow automation platform via webhooks

## Architecture & Structure

The codebase is organized into the following main components:

### Core Application Structure
- `app/main.py`: FastAPI application entry point with lifespan manager
- `app/config.py`: Configuration loading from .env files and environment variables
- `app/database.py`: Database connection and initialization using SQLAlchemy async ORM
- `app/models.py`: SQLAlchemy data models

### API Routes
- `app/api/ingest.py`: Document ingestion endpoints
- `app/api/agenttic_ingest.py`: Agenttic-specific ingestion
- `app/api/collections.py`: Collection management
- `app/api/search.py`: Search functionality
- `app/api/documents.py`: Document operations
- `app/api/query.py`: Query processing
- `app/api/models.py`: Model endpoints
- `app/api/webhook.py`: Webhook handling for n8n integration
- `app/api/n8n_workflow.py`: n8n workflow integration
- `app/api/vector_fix.py`: Vector database fix operations

### Core Processing Modules
- `app/fetch_parse.py`: Web content fetching and parsing
- `app/chunking.py`: Document chunking logic
- `app/embedding_client.py`: Embedding generation client
- `app/vector_db_client.py`: Qdrant vector database interactions

### Tool Orchestration System
- `app/tools/` directory contains the tool orchestration framework:
  - `orchestrator.py`: Main orchestrator managing tool execution cycles
  - `models.py`: Tool execution models and data structures
  - `selector.py`: Strategy selection logic
  - `registry.py`: Tool registration system
  - Strategies: `json_fc.py`, `react.py`, `harmony.py` for different execution approaches

## Development Commands

### Setup & Installation
```bash
# Create virtual environment
conda create -n notebooklm python=3.10
conda activate notebooklm

# Install dependencies
pip install -r requirements.txt
```

### Running the Application
```bash
# Development mode with hot-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Access API documentation at http://localhost:8000/docs
```

### Configuration
Create a `.env` file in the project root with required variables:
- `DATABASE_URL`: Database connection string
- `EMBEDDING_SERVICE_URL`: Embedding service address
- `LLM_SERVICE_URL`: LLM service address
- `QDRANT_HOST`, `QDRANT_PORT`: Qdrant vector database configuration
- `SEARXNG_QUERY_URL`: Searxng search engine address

### Docker Deployment
```bash
# Build and start services
docker compose build
docker-compose up -d
```

## Key Technical Details

The system uses async/await patterns throughout for efficient I/O operations. It integrates with several external services:
- Qdrant for vector storage and similarity search
- Searxng for web search capabilities
- Various LLM services for embeddings, reasoning, and tool calling
- n8n for workflow automation integration

The tool orchestration system supports multiple execution strategies (JSON Function Calling, ReAct, Harmony) and can dynamically select the appropriate strategy based on the LLM model being used.