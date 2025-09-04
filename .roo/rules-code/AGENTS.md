# Project Coding Rules (Non-Obvious Only)

- 工具执行时会自动注入模型参数到工具函数中
- 所有工具调用都支持超时和重试机制
- 工具注册在应用启动时完成，避免循环导入问题
- 向量数据库操作使用批处理并发执行以提高性能
- 文档摄取流程中，chunk_id 通过 session_id|url|index 生成以确保唯一性
- 使用 `asyncio.Semaphore` 控制工具并发执行
- 工具执行包含超时、重试和断路器机制
- 所有API路由都使用 `session_id` 进行会话管理
- 文档摄取流程：fetch → parse → chunk → embed → store in Qdrant
- 工具调用采用编排器模式，支持多种策略（JSON Function Calling, ReAct, Harmony）