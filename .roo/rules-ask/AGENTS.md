# Project Documentation Rules (Non-Obvious Only)

- "src/" contains VSCode extension code, not source for web apps (counterintuitive)
- Provider examples in src/api/providers/ are the canonical reference (docs are outdated)
- UI runs in VSCode webview with restrictions (no localStorage, limited APIs)
- Package.json scripts must be run from specific directories, not root
- Locales in root are for extension, webview-ui/src/i18n for UI (two separate systems)
- 项目根目录中的API文档通过 http://localhost:8000/docs 访问
- 文档摄取流程：fetch → parse → chunk → embed → store in Qdrant
- 工具调用采用编排器模式，支持多种策略（JSON Function Calling, ReAct, Harmony）