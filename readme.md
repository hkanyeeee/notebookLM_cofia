# NotebookLM-cofia

这是一个基于 Python 和 FastAPI 构建的后端服务，旨在为类似 NotebookLM 的应用提供强大的文档处理、检索增强生成 (RAG) 和智能工具调用能力。

## 核心功能

*   **文档摄取 (Ingestion):** 从 URL 摄取网页内容，自动提取正文、分块 (Chunking) 并生成向量嵌入 (Embeddings)。
*   **向量存储 (Vector Storage):** 使用 Qdrant 向量数据库存储文档块及其嵌入，支持高效的相似性搜索。
*   **检索增强生成 (RAG):** 根据用户查询，从向量库中检索最相关的文档片段，并将其作为上下文提供给大语言模型 (LLM) 以生成更精准的答案。
*   **智能工具编排 (Tool Orchestration):** 实现了一个类 Agent 的工具调用框架 (ReAct/JSON FC)，允许 LLM 根据需要调用外部工具（如网络搜索）来弥补知识缺口或执行特定任务。

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

#### 必须配置的配置项

以下配置项是项目运行的核心依赖，必须由用户根据实际环境进行配置：

*   `DATABASE_URL` - 数据库连接地址
*   `EMBEDDING_SERVICE_URL` - 嵌入服务地址
*   `LLM_SERVICE_URL` - 大语言模型服务地址
*   `QDRANT_HOST` - Qdrant向量数据库主机地址
*   `QDRANT_PORT` - Qdrant向量数据库端口
*   `SEARXNG_QUERY_URL` - Searxng搜索引擎地址

#### 可选配置项

这些配置项都有合理的默认值，用户可根据需要调整：

*   大部分配置项（如并发数、批处理大小、超时时间等）都有默认值
*   `QDRANT_API_KEY` - Qdrant API密钥
*   `RERANKER_SERVICE_URL` - 重排序服务地址

#### 关键外部服务依赖

以下内容需要用户根据自己的环境进行配置：

*   **API密钥和认证信息** - 所有外部服务的访问地址
*   **数据库连接字符串** - `DATABASE_URL`
*   **网络相关配置** - 代理设置等
*   **功能开关配置** - 各种功能的启用/禁用选项

#### 配置示例

```env
# 必需配置项
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
EMBEDDING_SERVICE_URL=http://localhost:7998/v1 # 你的嵌入服务地址
LLM_SERVICE_URL=http://localhost:1234/v1       # 你的大模型服务地址 (如 LM Studio)
QDRANT_HOST=localhost
QDRANT_PORT=6333
SEARXNG_QUERY_URL=http://localhost:8080/search # 你的 Searxng 地址

# 可选配置项
# QDRANT_API_KEY=your_qdrant_api_key
# RERANKER_SERVICE_URL=http://localhost:7996/v1
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
    docker compose build
    docker-compose up -d
    ```

### Docker 环境变量配置详解

在使用 Docker Compose 部署时，`docker-compose.yml` 文件中的 `environment` 部分定义了大量环境变量，用于配置服务的行为。以下是这些变量的详细说明：

#### 数据库与向量库配置

*   `DATABASE_URL`: SQLite 数据库文件路径。默认为 `sqlite+aiosqlite:///data/app.db`。
*   `QDRANT_HOST`: Qdrant 向量数据库服务主机地址。默认为 `qdrant` (Docker 服务名)。
*   `QDRANT_PORT`: Qdrant 服务端口。默认为 `6333`。
*   `QDRANT_API_KEY`: (可选) Qdrant API 密钥，用于认证。
*   `QDRANT_COLLECTION_NAME`: Qdrant 中用于存储嵌入的集合名称。默认为 `notebooklm_prod`。

#### 外部服务地址

*   `EMBEDDING_SERVICE_URL`: 嵌入服务网关地址。默认为 `http://embedding-gateway:7998/v1` (Docker 服务名)。
*   `LLM_SERVICE_URL`: 大语言模型 (LLM) 服务地址。默认为 `http://host.docker.internal:1234/v1` (指向宿主机)。
*   `RERANKER_SERVICE_URL`: (可选) 重排序服务地址。
*   `SEARXNG_QUERY_URL`: Searxng 搜索引擎地址。默认为 `http://host.docker.internal:8080/search` (指向宿主机)。

#### 嵌入与重排序配置

*   `EMBEDDING_MAX_CONCURRENCY`: 嵌入服务客户端的最大并发请求数。默认为 `4`。
*   `EMBEDDING_BATCH_SIZE`: 发送给嵌入服务的批量大小。默认为 `4`。
*   `EMBEDDING_DIMENSIONS`: 嵌入向量的维度。默认为 `1024`。
*   `RERANKER_MAX_TOKENS`: 重排序器处理的最大 token 数。默认为 `8192`。
*   `RERANK_CLIENT_MAX_CONCURRENCY`: 重排序客户端的最大并发请求数。默认为 `4`。

#### 工具编排配置

*   `DEFAULT_TOOL_MODE`: 默认工具调用模式 (如 `auto`, `json_fc`, `react`)。默认为 `auto`。
*   `MAX_TOOL_STEPS`: 工具调用的最大步数。默认为 `8`。

#### Web 搜索配置

*   `WEB_SEARCH_RESULT_COUNT`: 每个搜索关键词返回的最大结果数。默认为 `2`。
*   `WEB_SEARCH_MAX_QUERIES`: 一次请求中生成的最大搜索查询数量。默认为 `20`。
*   `WEB_SEARCH_MAX_RESULTS`: 一次请求中累积的最大搜索结果总数。默认为 `40`。
*   `WEB_SEARCH_CONCURRENT_REQUESTS`: 并发执行的搜索请求数。默认为 `10`。
*   `WEB_SEARCH_TIMEOUT`: 单个搜索请求的超时时间（秒）。默认为 `10.0` 秒。
*   `MAX_WORDS_PER_QUERY`: 每个搜索查询的最大词数。默认为 `4`。

#### 知识缺口分析配置

*   `MAX_KEYWORDS_PER_GAP`: 为每个知识缺口生成的最大搜索关键词数量。默认为 `2`。
*   `GAP_RECALL_TOP_K`: 为每个知识缺口从向量库中召回的初始文档片段数量。默认为 `4`。

#### Web 爬取配置

*   `WEB_LOADER_ENGINE`: Web 内容爬取引擎。可选 `safe_web` 或 `playwright`。默认为 `safe_web`。
*   `PLAYWRIGHT_TIMEOUT`: 使用 Playwright 爬取时的超时时间（秒）。默认为 `10.0` 秒。

#### 查询生成配置

*   `ENABLE_QUERY_GENERATION`: 是否启用查询生成功能。默认为 `true`。
*   `QUERY_GENERATION_PROMPT_TEMPLATE`: 查询生成使用的 LLM 提示词模板。

#### Web 缓存配置

*   `WEB_CACHE_ENABLED`: 是否启用网页内容缓存。默认为 `true`。
*   `WEB_CACHE_MAX_SIZE`: 缓存的最大条目数。默认为 `1000`。
*   `WEB_CACHE_TTL_SECONDS`: 缓存条目的生存时间（秒）。默认为 `3600` (1小时)。
*   `WEB_CACHE_MAX_CONTENT_SIZE`: 缓存单个网页内容的最大字节数。默认为 `1048576` (1MB)。

#### 文档处理配置

*   `CHUNK_SIZE`: 文档分块的大小（字符数）。默认为 `1000`。
*   `CHUNK_OVERLAP`: 文档分块的重叠大小（字符数）。默认为 `100`。

#### RAG 配置

*   `RAG_TOP_K`: 最终提供给 LLM 的相关文档片段数量。默认为 `15`。
*   `QUERY_TOP_K_BEFORE_RERANK`: 在重排序之前的初始检索文档片段数量。默认为 `200`。
*   `RAG_RERANK_TOP_K`: 重排序后保留的文档片段数量。默认为 `15`。

#### LLM 配置

*   `LLM_DEFAULT_TIMEOUT`: LLM 调用的默认超时时间（秒）。默认为 `3600.0` 秒。
*   `DEFAULT_SEARCH_MODEL`: 默认用于搜索和工具调用的 LLM 模型名称。默认为 `openai/gpt-oss-20b`。
*   `DEFAULT_INGEST_MODEL`: 默认用于文档摄取（如生成查询）的 LLM 模型名称。默认为 `qwen3-coder-30b-a3b-instruct`。
*   `DEFAULT_EMBEDDING_MODEL`: 默认用于生成嵌入的模型名称。默认为 `Qwen/Qwen3-Embedding-0.6B`。

#### 推理引擎配置

*   `REASONING_TIMEOUT`: 推理引擎（如工具调用）的超时时间（秒）。默认为 `3600.0` 秒。
*   `WEB_SEARCH_LLM_TIMEOUT`: 用于生成 Web 搜索关键词的 LLM 调用超时时间（秒）。默认为 `1800.0` 秒。

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