# Project Debug Rules (Non-Obvious Only)

- Webview dev tools accessed via Command Palette > "Developer: Open Webview Developer Tools" (not F12)
- IPC messages fail silently if not wrapped in try/catch in packages/ipc/src/
- Production builds require NODE_ENV=production or certain features break without error
- Database migrations must run from packages/evals/ directory, not root
- Extension logs only visible in "Extension Host" output channel, not Debug Console
- Tool orchestrator must be initialized with LLM_SERVICE_URL before use
- Database initialization happens in app_lifespan context manager
- Web search tool requires SEARXNG_QUERY_URL to be configured
- Vector database operations require QDRANT_HOST and QDRANT_PORT configuration
- Tool registration happens in orchestrator initialization to avoid circular imports
- Chunk IDs must be globally unique across sessions for proper deduplication