# Project Architecture Rules (Non-Obvious Only)

- Providers MUST be stateless - hidden caching layer assumes this
- Webview and extension communicate through specific IPC channel patterns only
- Database migrations cannot be rolled back - forward-only by design
- React hooks required because external state libraries break webview isolation
- Monorepo packages have circular dependency on types package (intentional)
- Tool orchestrator must be initialized with LLM_SERVICE_URL before use
- Database initialization happens in app_lifespan context manager
- Web search tool requires SEARXNG_QUERY_URL to be configured
- Vector database operations require QDRANT_HOST and QDRANT_PORT configuration
- Tool registration happens in orchestrator initialization to avoid circular imports
- Chunk IDs must be globally unique across sessions for proper deduplication
- Session ID management for context isolation across all operations
- Hybrid search combining vector and BM25 retrieval for better recall