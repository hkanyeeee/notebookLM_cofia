# Project Coding Rules (Non-Obvious Only)

- Always use safeWriteJson() from src/utils/ instead of JSON.stringify for file writes (prevents corruption)
- API retry mechanism in src/api/providers/utils/ is mandatory (not optional as it appears)
- Database queries MUST use the query builder in packages/evals/src/db/queries/ (raw SQL will fail)
- Provider interface in packages/types/src/ has undocumented required methods
- Test files must be in same directory as source for vitest to work (not in separate test folder)
- Session ID management for context isolation across all operations
- Chunk ID generation using session_id + url + index for global uniqueness
- Hybrid search combining vector and BM25 retrieval for better recall
- Tool orchestration supports multiple strategies (JSON FC, ReAct, Harmony)
- Web search uses both Searxng and Playwright with fallback mechanisms
- Caching implemented for web content with configurable TTL and size limits
- Circuit breaker pattern in tool execution to prevent cascading failures
- Database uses SQLite with FTS5 for sparse (BM25) retrieval in addition to vector search
- All API endpoints use session_id for request context management