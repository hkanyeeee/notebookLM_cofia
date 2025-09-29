# Repository Guidelines

This document provides a quick reference for contributors working on the **NotebookLM** project. It covers the repository layout, build and test commands, coding style, testing conventions, and pull‑request workflow.

## Project Structure & Module Organization
- `app/` – Python FastAPI backend (models, routers, services).  All API endpoints live under `app/api`.  Configuration lives in `app/config.py`.
- `notebookLM_front/` – Vue 3 + TypeScript front‑end.  Source files are in `src/`, build artifacts go to `dist/`.
- `data/` – SQLite database used by the backend (created at runtime).
- `scripts/` – helper utilities and Docker compose definitions.

## Build, Test, Development Commands
### Backend (Python)
```bash
# Install dependencies
pip install -r requirements.txt

# Run locally with auto‑reload
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Or build via Docker:
```bash
docker-compose up --build
```

### Frontend (Vue)
```bash
cd notebookLM_front
npm install   # or pnpm i
npm run dev   # hot‑reload development server
npm run build # production assets in dist/
```

### Tests
Backend tests use **pytest**.  From the repo root:
```bash
pytest            # runs all Python tests
# or for a specific module
pytest app/api/test_auto_ingest.py
```
## Coding Style & Naming Conventions
- **Python**: 4‑space indentation, PEP 8 compliant.  Use type hints where appropriate.  File names are snake_case; modules under `app/` mirror the API structure (`api/*.py`).
- **Vue/TS**: Single‑file components in `src/components`.  Class names use PascalCase, props and data camelCase.  Run `npm run format` (Prettier) before committing.

## Commit & Pull Request Guidelines
- Follow **Conventional Commits**: `feat:`, `fix:`, `docs:`, etc.
- Include a concise description and link to the related issue (e.g., `#123`).
- For UI changes, attach screenshots or a short GIF.
- PRs should be reviewed by at least one other contributor before merging.  Ensure tests pass locally.

## Environment Variables
Most configuration is injected via Docker Compose (`docker-compose.yml`) or an optional `.env` file in the repo root.  Refer to `app/config.py` for supported keys and defaults.

