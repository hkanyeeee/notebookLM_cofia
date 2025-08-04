## 接口

1.  **Ingest 接口 (`/ingest`)**：接收一个或多个 URL，异步拉取网页内容，进行文本抽取、分块、调用 Embedding 服务生成向量，并将向量存入 Milvus，元数据（URL、文本块）存入 SQLite 数据库。
2.  **Query 接口 (`/query`)**：接收用户的查询（query），执行以下步骤：
    *   将查询文本转换为向量。
    *   在 Milvus 中进行向量相似度检索，获取初始的 top-k 个文本块。
    *   （可选）如果配置了 Reranker 服务，将检索到的文本块和原始查询发送给 Reranker 服务进行重排序，以提升结果的相关性。
    *   将最终排序后的文本块作为上下文，连同原始查询一起发送给大语言模型（LLM）。
    *   LLM 根据上下文生成最终答案。
    *   返回生成的答案以及相关的来源文本块（包含 URL、内容和相关性得分）。

------

## 核心思路

-   **Web 内容获取**: 使用 `httpx` 异步拉取网页，`BeautifulSoup` 抽取正文文本。
-   **文本处理**: 将抽取的文本进行分块（Chunking）。
-   **向量生成**: 调用外部的 Embedding 服务（地址通过 `EMBEDDING_SERVICE_URL` 配置）将文本块转换为向量。
-   **向量存储与检索**:
    -   使用 `Milvus` 作为向量数据库，存储和检索文本块的向量。
    -   使用 `SQLAlchemy` 操作 `SQLite` 数据库，存储每个文本块的元数据（ID, URL, 内容）。`Chunk.id` 作为 Milvus 中的主键，关联向量和元数据。
-   **结果重排序 (Reranking)**:
    -   在向量检索后，引入一个可选的 Reranker 服务（地址通过 `RERANKER_SERVICE_URL` 配置）。
    -   为了避免超出 Reranker 模型的 token 限制，使用 `tiktoken` 将检索结果分批处理。
    -   Reranker 服务会对每个批次的结果进行重排序，提高最终结果的质量。
-   **答案生成**: 调用外部的大语言模型服务（地址通过 `LLM_SERVICE_URL` 配置），基于检索和重排序后的上下文生成答案。
-   **API 服务**: 使用 `FastAPI` 搭建 RESTful API，提供 `/ingest` 和 `/query` 两个端点。
-   **异步处理**: 整个流程大量使用 `asyncio` 以实现高效的 I/O 操作。

------

## 依赖 (`requirements.txt`)

```txt
fastapi
uvicorn[standard]
httpx
beautifulsoup4
pymilvus
python-dotenv
numpy
sqlalchemy
aiosqlite
greenlet
tiktoken 
```
