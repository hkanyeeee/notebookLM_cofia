# Project Debug Rules (Non-Obvious Only)

- Webview dev tools accessed via Command Palette > "Developer: Open Webview Developer Tools" (not F12)
- IPC messages fail silently if not wrapped in try/catch in packages/ipc/src/
- Production builds require NODE_ENV=production or certain features break without error
- Database migrations must run from packages/evals/ directory, not root
- Extension logs only visible in "Extension Host" output channel, not Debug Console
- 工具执行时会自动注入模型参数到工具函数中
- 所有工具调用都支持超时和重试机制
- 工具注册在应用启动时完成，避免循环导入问题
- 向量数据库操作使用批处理并发执行以提高性能
- 文档摄取流程中，chunk_id 通过 session_id|url|index 生成以确保唯一性