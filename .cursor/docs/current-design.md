## 接口

1. **Ingest 接口**：接收网址数组，拉取网页内容，做文本抽取、分块、embedding，存到向量库（用 FAISS + 本地 metadata 存储）。
2. **Query 接口**：接收 query，向量检索相关 chunk，用大模型（示例用 OpenAI ChatCompletion）总结并返回答案（附带来源）。

------

## 核心思路

- 用 `httpx` 异步拉取网页，`BeautifulSoup` 抽取正文文案。
- 192.168.31.125:8020 做 embedding。
- 用 FAISS 做向量检索，metadata 用 SQLite 维护每个 chunk 的原始 URL / 内容 / id。
- 用192.168.31.231:1234部署的大模型，request做基于检索结果的 query 总结。
- 提供两个 REST endpoint：`/ingest` 和 `/query`。

------

## 依赖（requirements.txt）

```txt
fastapi
uvicorn[standard]
httpx
beautifulsoup4
faiss-cpu
python-dotenv
```

------

## 