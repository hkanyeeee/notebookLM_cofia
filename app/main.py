from fastapi import FastAPI
from .config import DATABASE_URL, EMBEDDING_SERVICE_URL, LLM_SERVICE_URL
from .database import engine, Base
from typing import List
from fastapi import Body
from app.fetch_parse import fetch_html, extract_text
from app.chunking import chunk_text
from app.embedding_client import embed_texts
from app.llm_client import generate_answer
from app.vector_db_client import add_embeddings, query_embeddings

app = FastAPI()

@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "database_url": DATABASE_URL,
        "embedding_service_url": EMBEDDING_SERVICE_URL,
        "llm_service_url": LLM_SERVICE_URL
    }

@app.post("/ingest")
async def ingest(urls: List[str] = Body(...)):
    results = []
    for url in urls:
        html = await fetch_html(url)
        text = extract_text(html)
        chunks = chunk_text(text)
        embeddings = await embed_texts(chunks)
        await add_embeddings(url, chunks, embeddings)
        results.append({"url": url, "chunks": len(chunks)})
    return {"status": "success", "results": results}


@app.post("/query")
async def query(q: str = Body(...)):
    # 生成查询 embedding
    query_embedding = (await embed_texts([q]))[0]
    # 向量检索相关片段
    hits = await query_embeddings(query_embedding)
    # 提取上下文文本
    contexts = [chunk.content for chunk, _ in hits]
    # 请求 LLM 生成答案
    answer = await generate_answer(q, contexts)
    # 构造来源列表
    sources = [{"url": chunk.url, "content": chunk.content, "distance": dist} for chunk, dist in hits]
    return {"answer": answer, "sources": sources}