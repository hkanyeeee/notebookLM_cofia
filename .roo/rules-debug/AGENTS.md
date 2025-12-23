# AGENTS.md - Debug Mode

This file provides guidance to agents when working with code in this repository.

## Project Debug Rules (Non-Obvious Only)

### Backend Debugging
- **Network resources**: httpx client and Playwright are singletons initialized in `app_lifespan()`. If you see connection errors, check if `initialize_network_resources()` was called.
- **Database locks**: SQLite uses WAL mode with 30s busy_timeout. If you see "database is locked" errors, check for long-running transactions or concurrent writes.
- **Tool execution failures**: Check `app/tools/registry.py` for circuit breaker status (3 consecutive errors = ERROR status). Backends auto-recover after 30s.
- **Gateway health**: Check `/health` endpoint on gateway services (port 7995 for LLM, 7998 for embedding) to see backend status and error counts.

### Frontend Debugging
- **Vue DevTools**: Enabled via `vite-plugin-vue-devtools` in development mode.
- **API calls**: All frontend API calls go through clients in `notebookLM_front/src/api/`. Check network tab for actual request URLs.
- **Pinia stores**: State is in `notebookLM_front/src/stores/`. Use Vue DevTools to inspect store state.

### Common Issues
- **Missing TIKTOKEN_CACHE_DIR**: If tiktoken fails to cache, check that `os.environ["TIKTOKEN_CACHE_DIR"]` is set before importing tiktoken in `app/main.py`.
- **Gateway backend unavailable**: If gateway returns 502, check `EMBEDDING_BACKENDS` or `LLM_BACKENDS` env vars and verify backend URLs are reachable.
- **Tool not found**: If tools fail to execute, verify `register_all_tools()` is called in `initialize_orchestrator()`.
