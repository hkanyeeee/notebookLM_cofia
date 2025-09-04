# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## 项目技术栈
- Python 3.10+
- FastAPI (异步API框架)
- SQLite (通过 SQLAlchemy async ORM)
- Qdrant 向量数据库
- Searxng 搜索引擎
- 前端使用 Vue 3 + TypeScript

## 构建/测试/Lint 命令
- 启动开发服务器: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- 运行测试: `python test_agenttic_ingest.py` (测试 /agenttic-ingest 接口)
- 前端构建: `cd notebookLM_front && npm run build`
- 前端开发: `cd notebookLM_front && npm run dev`

## 项目特定模式和约定
- 工具调用采用编排器模式，支持多种策略（JSON Function Calling, ReAct, Harmony）
- 工具注册通过 `tool_registry` 管理，所有工具在应用启动时初始化
- 文档摄取流程：fetch → parse → chunk → embed → store in Qdrant
- 使用 `asyncio.Semaphore` 控制工具并发执行
- 工具执行包含超时、重试和断路器机制
- 所有API路由都使用 `session_id` 进行会话管理
- 向量数据库操作通过 `vector_db_client` 模块处理

## 代码风格
- 使用 Python 3.10+ 特性（如类型提示）
- API路由使用 FastAPI 装饰器
- 异步函数使用 `async/await` 语法
- 工具参数验证通过 `ToolCallValidator` 进行
- 使用 SQLAlchemy 异步 ORM 操作数据库

## 关键组件说明
- `app/tools/orchestrator.py`: 工具编排器，协调工具执行流程
- `app/tools/registry.py`: 工具注册表，管理可用工具及其执行函数
- `app/api/ingest.py`: 文档摄取API，处理URL内容的获取、解析和向量化
- `app/vector_db_client.py`: 向量数据库客户端，处理嵌入向量的存储和检索
- `app/tools/strategies/`: 工具调用策略实现目录

## 特殊注意事项
- 工具执行时会自动注入模型参数到工具函数中
- 所有工具调用都支持超时和重试机制
- 工具注册在应用启动时完成，避免循环导入问题
- 向量数据库操作使用批处理并发执行以提高性能
- 文档摄取流程中，chunk_id 通过 session_id|url|index 生成以确保唯一性