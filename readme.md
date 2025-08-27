# NotebookLM-cofia

这是一个基于 Python 和 FastAPI 构建的后端服务，旨在为类似 NotebookLM 的应用提供强大的文档处理、检索增强生成 (RAG) 和智能工具调用能力。

## 核心功能

*   **文档摄取 (Ingestion):** 从 URL 摄取网页内容，自动提取正文、分块 (Chunking) 并生成向量嵌入 (Embeddings)。
*   **向量存储 (Vector Storage):** 使用 Qdrant 向量数据库存储文档块及其嵌入，支持高效的相似性搜索。
*   **检索增强生成 (RAG):** 根据用户查询，从向量库中检索最相关的文档片段，并将其作为上下文提供给大语言模型 (LLM) 以生成更精准的答案。
*   **智能工具编排 (Tool Orchestration):** 实现了一个类 Agent 的工具调用框架 (ReAct/JSON FC)，允许 LLM 根据需要调用外部工具（如网络搜索）来弥补知识缺口或执行特定任务。
*   **工作流集成 (n8n):** 通过 Webhook 与 n8n 工作流自动化平台集成，可以触发外部工作流或接收来自工作流的回调。

## 技术栈

*   **语言:** Python 3.10+
*   **框架:** FastAPI (异步 API)
*   **数据库:** SQLite (通过 SQLAlchemy async ORM)
*   **向量库:** Qdrant
*   **搜索引擎:** Searxng
*   **依赖管理:** pip / conda

## 快速开始

### 1. 环境准备

推荐使用 Conda 或 Python venv 创建虚拟环境。

```bash
# 使用 Conda (根据实际情况调整环境名称)
conda create -n notebooklm python=3.10
conda activate notebooklm

# 或使用 venv
# python -m venv venv
# source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate     # Windows
```

安装依赖:

```bash
pip install -r requirements.txt
```

### 2. 配置

在项目根目录创建 `.env` 文件，并根据需要配置环境变量。参考 `app/config.py` 了解所有可用配置项。

关键配置示例:

```env
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
EMBEDDING_SERVICE_URL=http://localhost:7998/v1 # 你的嵌入服务地址
LLM_SERVICE_URL=http://localhost:1234/v1       # 你的大模型服务地址 (如 LM Studio)
QDRANT_HOST=localhost
QDRANT_PORT=6333
SEARXNG_QUERY_URL=http://localhost:8080/search # 你的 Searxng 地址
```

### 3. 启动服务

开发模式下启动服务:

```bash
# 如果使用 Conda 环境，请先激活
# conda activate mlx # (如果 'mlx' 是你为项目创建的环境名)

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

服务将在 `http://localhost:8000` 启动。API 文档可通过 `http://localhost:8000/docs` 访问。

## Docker 部署

项目提供了 `docker-compose.yml` 文件，可以方便地使用 Docker Compose 进行部署。请确保已安装 Docker 和 Docker Compose。

1.  根据 `docker-compose.yml` 的注释，可能需要先创建 Docker 网络：
    ```bash
    docker network create localnet
    ```
2.  在 `.env` 文件中配置好相关环境变量。
3.  构建并启动服务：
    ```bash
    docker-compose up -d
    ```

## 项目结构

*   `app/`: 主应用代码
    *   `main.py`: FastAPI 应用入口。
    *   `config.py`: 配置加载。
    *   `database.py`: 数据库连接与初始化。
    *   `models.py`: SQLAlchemy 数据模型。
    *   `api/`: API 路由。
    *   `tools/`: 工具编排与执行逻辑。
    *   `fetch_parse.py`, `chunking.py`, `embedding_client.py`, `vector_db_client.py`: 核心处理逻辑模块。
*   `notebookLM_front/`: 前端代码 (如果存在)。
*   `requirements.txt`: Python 依赖。
*   `docker-compose.yml`: Docker Compose 配置。
*   `.env`: 环境变量配置文件 (需自行创建)。