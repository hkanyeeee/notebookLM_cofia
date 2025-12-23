# AGENTS.md - Ask Mode

This file provides guidance to agents when working with code in this repository.

## Project Documentation Rules (Non-Obvious Only)

### Architecture Overview
- **Query modes**: Two distinct query types - `NORMAL` (web search enabled via IntelligentOrchestrator) and `DOCUMENT` (vector search only, traditional RAG).
- **Tool orchestration**: Implements ReAct/JSON FC/Harmony strategies for LLM tool calling. Tools are registered centrally in `app/tools/registry.py`.
- **Gateway pattern**: Independent load balancer services (`llm_gateway.py`, `embedding_gateway.py`) handle backend selection with weighted least-connections strategy.

### Counterintuitive Organization
- **Network resources**: Not instantiated per-request. Singletons managed by `app/services/network.py` and initialized in app lifespan.
- **Database triggers**: SQLite FTS5 virtual table `chunks_fts` is auto-synced via triggers, not manual indexing.
- **Tool registration**: Happens at startup via `register_all_tools()` in `initialize_orchestrator()`, not lazy loading.

### Hidden Configuration
- **Tiktoken cache**: Must be set via environment variable before importing tiktoken (done in `app/main.py`).
- **Model name mapping**: Gateway scripts support `MODEL_NAME_MAP` dict for aliasing model names per backend URL.
- **Backend weights**: Load balancing weights are hardcoded in `_RAW_BACKEND_WEIGHTS` dict in gateway scripts.

### Key Entry Points
- Backend: `app/main.py` (FastAPI app with lifespan management)
- Tool orchestration: `app/tools/orchestrator.py` and `app/tools/intelligent_orchestrator.py`
- API routes: `app/api/query.py` (main query endpoint with NORMAL/DOCUMENT modes)
- Frontend: `notebookLM_front/src/main.ts` (Vue app entry point)
