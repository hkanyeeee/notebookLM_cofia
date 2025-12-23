# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project Overview

NotebookLM-cofia is a RAG (Retrieval-Augmented Generation) application with:
- **Backend**: Python FastAPI with async SQLAlchemy, SQLite (WAL mode), Qdrant vector DB
- **Frontend**: Vue 3 + TypeScript + Vite + Tailwind CSS + Pinia
- **Gateway Services**: Custom load balancers for LLM and embedding services

## Essential Commands

### Backend (Python)
```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run gateway services
python gateway_script/llm_gateway.py      # Port 7995
python gateway_script/embedding_gateway.py # Port 7998
```

### Frontend (Vue)
```bash
cd notebookLM_front
pnpm install
pnpm dev        # Development
pnpm build      # Production build
pnpm type-check # TypeScript checking
pnpm format     # Prettier formatting
```

### Docker
```bash
docker network create localnet  # Required first
docker compose build
docker-compose up -d
```

## Critical Non-Obvious Patterns

### Network Resources (Backend)
- **Never create new httpx clients or Playwright instances directly** - use singleton getters from `app.services.network`:
  - `get_httpx_client()` - returns shared httpx.AsyncClient
  - `get_playwright_context()` - returns shared BrowserContext
  - These are initialized in `app.main.app_lifespan()` and must be cleaned up properly

### Database Configuration
- SQLite uses **WAL mode** with custom PRAGMA settings (`app/database.py`):
  - `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=30000`
  - FTS5 virtual table `chunks_fts` auto-syncs with `chunks` table via triggers

### Tiktoken Cache
- Must set `os.environ["TIKTOKEN_CACHE_DIR"]` at startup (done in `app/main.py`)
- Default cache dir: `data/` (configurable via `TIKTOKEN_CACHE_DIR` env var)

### Tool Orchestration
- Tools registered in `app/tools/registry.py` via `register_all_tools()` called from `initialize_orchestrator()`
- Circuit breaker pattern: 3 consecutive errors mark backend as ERROR, auto-recover after 30s
- Tool execution supports timeout, retry with exponential backoff, and concurrency limits

### Query Modes
- `NORMAL`: Enables web search via `IntelligentOrchestrator` for gap analysis
- `DOCUMENT`: Vector search only, no web search, uses traditional RAG flow

### Gateway Load Balancing
- Both `llm_gateway.py` and `embedding_gateway.py` use custom weighted least-connections strategy
- Backend health tracked with error counts, response times, and automatic recovery
- Model name mapping supported via `MODEL_NAME_MAP` dict in gateway scripts

### Frontend Path Aliases
- Use `@/` for src imports (e.g., `import { foo } from '@/api/ingest'`)
- Configured in `notebookLM_front/vite.config.ts`

## Code Style

### Python
- Use `from app.config import ...` for config access (not direct env vars)
- Async patterns required for all DB and network operations
- Type hints encouraged

### TypeScript
- Prettier: no semicolons, single quotes, 100 char line width
- Vue 3 Composition API with `<script setup>`

## Environment Variables (Required)

Create `.env` in project root with:
- `DATABASE_URL` (e.g., `sqlite+aiosqlite:///./data/app.db`)
- `EMBEDDING_SERVICE_URL` (e.g., `http://localhost:7998/v1`)
- `LLM_SERVICE_URL` (e.g., `http://localhost:1234/v1`)
- `QDRANT_HOST`, `QDRANT_PORT`
- `SEARXNG_QUERY_URL` (for web search)

See `app/config.py` for all available options.
