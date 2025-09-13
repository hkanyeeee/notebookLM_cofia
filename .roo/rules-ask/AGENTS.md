# Project Documentation Rules (Non-Obvious Only)

- "src/" contains VSCode extension code, not source for web apps (counterintuitive)
- Provider examples in src/api/providers/ are the canonical reference (docs are outdated)
- UI runs in VSCode webview with restrictions (no localStorage, limited APIs)
- Package.json scripts must be run from specific directories, not root
- Locales in root are for extension, webview-ui/src/i18n for UI (two separate systems)
- Build artifacts go in dist/ directory, not build/
- Configuration files are in .env and app/config.py
- API endpoints are defined in app/api/ directory
- Database schema is defined in app/models.py
- Tool definitions are in app/tools/ directory