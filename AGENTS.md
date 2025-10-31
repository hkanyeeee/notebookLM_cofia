# Repository Guidelines
FastAPI-based RAG backend; follow these notes to stay aligned with current patterns.

## Project Structure & Module Organization
- `app/` holds backend code: routers in `app/api`, shared schemas in `app/models`, services in `app/services`, and reusable helpers in `app/utils`.
- Tool execution for agents lives in `app/tools`; keep new clients parallel to `embedding_client.py` and `rerank_client.py`.
- Database and vector helpers sit in `app/database.py` and `app/vector_db_client.py`; extend them instead of issuing ad-hoc queries.
- `notebookLM_front/` hosts front-end prototypes, `gateway_script/` carries n8n automation, and runtime data belongs in `data/`.
- Maintenance scripts (e.g., `batch_delete_collections.py`, `preview_auto_ingest.py`) live at the repo root; document new scripts nearby.

## Build, Test, and Development Commands
- `pip install -r requirements.txt` — install backend dependencies inside a Python 3.10+ virtualenv.
- `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` — run the API locally with auto-reload.
- `python test_auto_ingest.py` — async ingestion smoke test; ensure the service is live first.
- `docker compose up -d` — start the stack from `docker-compose.yml`; follow with `docker compose logs -f backend` for diagnostics.

## Coding Style & Naming Conventions
- Use 4-space indentation, type hints where practical, and docstrings mirroring the existing bilingual tone.
- Modules and functions stay snake_case, classes PascalCase, constants UPPER_SNAKE_CASE; align new routers with patterns in `app/api`.
- Reuse shared clients in `app/services/network.py` or `app/tools` instead of spawning new HTTP or LLM adapters.
- Prefer explicit logs over silent failures; keep prints structured to ease debugging.

## Testing Guidelines
- Follow `test_auto_ingest.py` for integration checks: async `httpx` client, explicit payloads, clear console output.
- Add automated cases in a `tests/` package (create as needed) named `test_<feature>.py`; share fixtures for external services.
- Before pushing, run smoke tests relevant to your change (ingestion, retrieval, or tool orchestration).

## Commit & Pull Request Guidelines
- Imitate the existing history: short imperative subjects (English or Chinese) such as “Fix vector cleanup”.
- Reference linked issues or tickets, list manual test commands, and call out new environment keys or schema migrations.
- Pull requests should outline intent, include UI screenshots for `notebookLM_front/` changes, and note required external services.

## Environment & Configuration
- Store secrets in `.env`; mirror defaults and descriptions in `app/config.py`.
- Keep cache directories and data paths configurable via env vars, and refresh onboarding docs when adding new keys.
