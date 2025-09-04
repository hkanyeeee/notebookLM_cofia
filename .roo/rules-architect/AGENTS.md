# Project Architecture Rules (Non-Obvious Only)

- Providers MUST be stateless - hidden caching layer assumes this
- Webview and extension communicate through specific IPC channel patterns only
- Database migrations cannot be rolled back - forward-only by design
- React hooks required because external state libraries break webview isolation
- Monorepo packages have circular dependency on types package (intentional)
- 工具调用采用编排器模式，支持多种策略（JSON Function Calling, ReAct, Harmony）
- 工具注册通过 `tool_registry` 管理，所有工具在应用启动时初始化
- 文档摄取流程：fetch → parse → chunk → embed → store in Qdrant
- 使用 `asyncio.Semaphore` 控制工具并发执行
- 所有API路由都使用 `session_id` 进行会话管理