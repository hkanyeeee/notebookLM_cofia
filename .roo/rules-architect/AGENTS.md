# AGENTS.md - Architect Mode

This file provides guidance to agents when working with code in this repository.

## Project Architecture Rules (Non-Obvious Only)

### Backend Architecture
- **Singleton network resources**: httpx client and Playwright are singletons managed by `app.services.network`. This is intentional for connection pooling and resource efficiency.
- **Async-first design**: All database and network operations must be async. SQLite uses WAL mode to support concurrent reads/writes.
- **Tool orchestration**: Centralized registry pattern with circuit breaker for fault tolerance. Tools execute with timeout, retry, and concurrency limits.
- **Query mode separation**: `NORMAL` mode uses IntelligentOrchestrator with web search; `DOCUMENT` mode uses traditional RAG with vector search only.

### Gateway Architecture
- **Independent services**: `llm_gateway.py` and `embedding_gateway.py` are standalone FastAPI apps, not part of the main backend.
- **Load balancing strategy**: Weighted least-connections with health tracking. Higher weight = higher capacity allocation.
- **Circuit breaker**: 3 consecutive errors mark backend as ERROR, auto-recover after 30s. Client errors (4xx) don't affect health status.

### Frontend Architecture
- **Vue 3 Composition API**: All components use `<script setup>` syntax with reactive state management via Pinia stores.
- **Path aliasing**: `@/` maps to `src/` directory for clean imports.
- **API abstraction**: All backend communication goes through client modules in `notebookLM_front/src/api/`.

### Hidden Coupling
- **Tool registration timing**: `register_all_tools()` must be called before `ToolOrchestrator` initialization to avoid circular imports.
- **Tiktoken cache**: Must be set before first tiktoken import, done in `app/main.py` app_lifespan.
- **Gateway backend URLs**: Hardcoded defaults in scripts but configurable via env vars. Model name mapping is per-backend.

### Performance Considerations
- **SQLite WAL mode**: Enables concurrent reads with a single writer. Custom PRAGMA settings (journal_mode=WAL, synchronous=NORMAL, busy_timeout=30000).
- **Connection pooling**: httpx client uses configured limits (HTTPX_MAX_CONNECTIONS, HTTPX_MAX_KEEPALIVE_CONNECTIONS).
- **FTS5 triggers**: Auto-sync vector search results with full-text search via SQLite triggers, not manual indexing.
