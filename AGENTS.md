# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Build/Lint/Test Commands

- `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` - Run development server
- `docker compose build && docker-compose up -d` - Docker deployment
- `pip install -r requirements.txt` - Install Python dependencies
- `npm run dev` (in notebookLM_front/) - Run frontend development server
- `npm run build` (in notebookLM_front/) - Build frontend application

## Code Style Guidelines

- Use snake_case for Python files and variables
- Use CamelCase for class names
- All async functions should use type hints
- Configuration is driven by environment variables and .env file
- Database operations use SQLAlchemy async ORM with proper session management
- Tools are registered via register_all_tools() to avoid circular imports

## Project-Specific Patterns

- Session ID management for context isolation across all operations
- Chunk ID generation using session_id + url + index for global uniqueness
- Hybrid search combining vector and BM25 retrieval for better recall
- Tool orchestration supports multiple strategies (JSON FC, ReAct, Harmony)
- Web search uses both Searxng and Playwright with fallback mechanisms
- Caching implemented for web content with configurable TTL and size limits
- Circuit breaker pattern in tool execution to prevent cascading failures
- Database uses SQLite with FTS5 for sparse (BM25) retrieval in addition to vector search
- All API endpoints use session_id for request context management

## Testing

- Tests use pytest framework (tests/ directory exists but no specific test files provided)
- Core functionality tested through integration tests
- Tool execution and API endpoints are key test targets

## Key Gotchas

- Tool orchestrator must be initialized with LLM_SERVICE_URL before use
- Database initialization happens in app_lifespan context manager
- Web search tool requires SEARXNG_QUERY_URL to be configured
- Vector database operations require QDRANT_HOST and QDRANT_PORT configuration
- Tool registration happens in orchestrator initialization to avoid circular imports
- Chunk IDs must be globally unique across sessions for proper deduplication