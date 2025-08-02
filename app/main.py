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
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("Database initialized successfully")
    except Exception as e:
        print(f"Database initialization failed: {e}")
        # 不要因为数据库初始化失败而阻止服务器启动

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "database_url": DATABASE_URL,
        "embedding_service_url": EMBEDDING_SERVICE_URL,
        "llm_service_url": LLM_SERVICE_URL
    }

@app.get("/test")
async def test():
    return {"message": "Server is running"}

@app.post("/ingest")
async def ingest(urls: List[str] = Body(...)):
    try:
        results = []
        for url in urls:
            try:
                html = await fetch_html(url)
                text = extract_text(html)
                chunks = chunk_text(text)
                print(chunks)
                print(len(chunks))
                # 检查embedding服务是否可用
                if not EMBEDDING_SERVICE_URL:
                    return {"status": "error", "message": "EMBEDDING_SERVICE_URL not configured"}
                
                embeddings = await embed_texts(chunks)
                await add_embeddings(url, chunks, embeddings)
                results.append({"url": url, "chunks": len(chunks)})
            except Exception as e:
                results.append({"url": url, "error": str(e)})
        
        return {"status": "success", "results": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/query")
async def query(q: str = Body(...), top_k: int = Body(10, embed=True)):
    try:
        # 生成查询 embedding
        query_embedding = (await embed_texts([q]))[0]
        # 向量检索相关片段
        hits = await query_embeddings(query_embedding, top_k=top_k)
        # 提取上下文文本
        contexts = [chunk.content for chunk, _ in hits]
        # 请求 LLM 生成答案
        answer = await generate_answer(q, contexts)
        # 构造来源列表
        sources = [{"url": chunk.url, "content": chunk.content, "distance": dist} for chunk, dist in hits]
        return {"answer": answer, "sources": sources}
    except Exception as e:
        return {"status": "error", "message": str(e), "traceback": str(e.__class__.__name__)}
