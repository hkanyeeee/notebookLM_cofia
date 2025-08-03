from fastapi import FastAPI, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional

from .config import DATABASE_URL, EMBEDDING_SERVICE_URL, LLM_SERVICE_URL
from .database import engine, Base
from app.fetch_parse import fetch_html, extract_text
from app.chunking import chunk_text
from app.embedding_client import embed_texts, DEFAULT_EMBEDDING_MODEL
from app.llm_client import generate_answer
from app.vector_db_client import add_embeddings, query_embeddings

app = FastAPI()

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],  # 允许的前端域名
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有HTTP方法
    allow_headers=["*"],  # 允许所有请求头
)

@app.on_event("startup")
async def on_startup():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("Database initialized successfully")
    except Exception as e:
        print(f"Database initialization failed: {e}")

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
async def ingest(data: dict = Body(...)):
    urls = data.get("urls", [])
    if isinstance(data.get("url"), str):
        urls = [data["url"]]
    
    embedding_model = data.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions = data.get("embedding_dimensions")

    if not urls:
        raise HTTPException(status_code=400, detail="No URLs provided")
        
    try:
        results = []
        for url in urls:
            try:
                html = await fetch_html(url)
                text = extract_text(html)
                chunks = chunk_text(text)
                
                if not EMBEDDING_SERVICE_URL:
                    raise HTTPException(status_code=500, detail="EMBEDDING_SERVICE_URL not configured")
                
                embeddings = await embed_texts(
                    chunks, 
                    model=embedding_model, 
                    dimensions=embedding_dimensions
                )
                await add_embeddings(url, chunks, embeddings)
                results.append({"url": url, "chunks": len(chunks)})
            except Exception as e:
                results.append({"url": url, "error": str(e)})
        
        return {
            "success": True, 
            "document_id": str(len(results)), 
            "title": f"文档 - {len(results)} 个URL",
            "message": "文档摄取成功"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query")
async def query(data: dict = Body(...)):
    q = data.get("query", "")
    top_k = data.get("top_k", 20)
    embedding_model = data.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions = data.get("embedding_dimensions")

    if not q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
        
    try:
        query_embedding = (await embed_texts(
            [q], 
            model=embedding_model, 
            dimensions=embedding_dimensions
        ))[0]
        
        hits = await query_embeddings(query_embedding, top_k=top_k)
        
        contexts = [chunk.content for chunk, _ in hits]
        answer = await generate_answer(q, contexts)
        
        sources = [{"url": chunk.url, "content": chunk.content, "distance": dist} for chunk, dist in hits]
        return {"answer": answer, "sources": sources}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{e.__class__.__name__}: {str(e)}")
