# AGENTS.md - Code Mode

This file provides guidance to agents when working with code in this repository.

## Project Coding Rules (Non-Obvious Only)

### Backend (Python)
- **Network resources must use singletons**: Never create new httpx.AsyncClient() or Playwright instances directly. Use `get_httpx_client()` and `get_playwright_context()` from `app.services.network`. These are initialized in `app.main.app_lifespan()` and require proper cleanup.
- **Database operations must be async**: Use `AsyncSessionLocal()` from `app.database` for all DB operations. SQLite uses WAL mode with custom PRAGMA settings.
- **Tool registration**: Tools must be registered in `app/tools/registry.py` via `register_all_tools()` which is called from `initialize_orchestrator()` during app startup.
- **Config access**: Always use `from app.config import ...` for configuration values, never access `os.getenv()` directly in application code.
- **Tiktoken cache**: Must set `os.environ["TIKTOKEN_CACHE_DIR"]` at startup (done in `app/main.py`) before importing tiktoken.
- **Gateway scripts**: When modifying `llm_gateway.py` or `embedding_gateway.py`, preserve the circuit breaker pattern (3 errors = ERROR status, 30s recovery) and weighted load balancing logic.

### Frontend (Vue/TypeScript)
- **Path aliases**: Use `@/` for all src imports (e.g., `import { foo } from '@/api/ingest'`). Configured in `notebookLM_front/vite.config.ts`.
- **Vue 3 Composition API**: Use `<script setup>` syntax for all Vue components.
- **Pinia stores**: Located in `notebookLM_front/src/stores/`. Import stores directly, not via a barrel file.

### Gateway Scripts
- **Model name mapping**: Both gateways support `MODEL_NAME_MAP` dict for aliasing model names per backend URL. Add mappings directly in the script files.
- **Backend weights**: Load balancing uses weights defined in `_RAW_BACKEND_WEIGHTS` dict. Higher weight = higher priority/capacity.
- **Health tracking**: Both gateways track backend health via `BackendState` class with error counts and automatic recovery.

### File Organization
- Backend API routes in `app/api/` (each file is a router)
- Tool orchestration logic in `app/tools/`
- Gateway scripts in `gateway_script/` (independent services)
- Frontend stores in `notebookLM_front/src/stores/`
- Frontend API clients in `notebookLM_front/src/api/`
