# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Build/Testing Commands
- Start development server: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- Run tests: `python test_agenttic_ingest.py`
- Frontend build: `cd notebookLM_front && npm run build`
- Frontend development: `cd notebookLM_front && npm run dev`

## Critical Project-Specific Rules
- **Chunk ID Format**: `chunk_id` must be generated as `session_id|url|index` (e.g., `session123|https://example.com|0`). **Do not use other formats**.
- **Web Search Tool**: `web_search` requires `query` parameter. `filter_list` (array of domains) is optional but **must be provided as an array**.
- **.env Configuration**: Service URLs (e.g., `LLM_SERVICE_URL`, `EMBEDDING_SERVICE_URL`) are **critical**. Example: `LLM_SERVICE_URL=http://192.168.31.98:1234/v1`.
- **Web Search Caching**: Enable via `WEB_CACHE_ENABLED=True` and configure `WEB_CACHE_MAX_SIZE`, `WEB_CACHE_TTL_SECONDS`, `WEB_CACHE_MAX_CONTENT_SIZE`.
- **Recursive Ingestion**: `/agenttic-ingest` API uses `recursive_depth` (default: 0) for sub-document crawling.

## Code Style & Conventions
- **Vector Database**: Always use `vector_db_client` module. **Never use raw SQL**.
- **Tool Parameters**: Verify required parameters (e.g., `web_search` requires `query`).