import asyncio
import tiktoken
from fastapi import FastAPI, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List

from .config import DATABASE_URL, EMBEDDING_SERVICE_URL, LLM_SERVICE_URL, RERANKER_SERVICE_URL
from .database import engine, Base
from .fetch_parse import fetch_html, extract_text
from .chunking import chunk_text
from .embedding_client import embed_texts, DEFAULT_EMBEDDING_MODEL
from .llm_client import generate_answer
from .vector_db_client import add_embeddings, query_embeddings
from .rerank_client import rerank, DEFAULT_RERANKER_TOP_K

# Constants
RERANKER_MAX_TOKENS = 8192

app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    print(f"Using DATABASE_URL: {DATABASE_URL}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("Database initialized successfully")
    except Exception as e:
        print(f"Database initialization failed: {e}")

@app.post("/ingest")
async def ingest(data: dict = Body(...)):
    urls = data.get("urls", [])
    if isinstance(data.get("url"), str):
        urls = [data["url"]]
    
    embedding_model = data.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions = data.get("embedding_dimensions", 2560)

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
    top_k = data.get("top_k", 60)
    embedding_model = data.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions = data.get("embedding_dimensions", 2560)

    if not q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    try:
        query_embedding = (await embed_texts([q], model=embedding_model, dimensions=embedding_dimensions))[0]
        hits = await query_embeddings(query_embedding, top_k=top_k)

        final_hits = []
        if RERANKER_SERVICE_URL:
            print(f"Reranking {len(hits)} hits...")
            try:
                # Use tiktoken to estimate token counts and create batches
                encoding = tiktoken.get_encoding("cl100k_base")
                query_tokens = len(encoding.encode(q))
                
                batches = []
                current_batch = []
                current_batch_tokens = query_tokens

                for hit in hits:
                    hit_tokens = len(encoding.encode(hit[0].content))
                    if current_batch and current_batch_tokens + hit_tokens > RERANKER_MAX_TOKENS:
                        batches.append(current_batch)
                        current_batch = []
                        current_batch_tokens = query_tokens
                    
                    current_batch.append(hit)
                    current_batch_tokens += hit_tokens
                
                if current_batch:
                    batches.append(current_batch)

                print(f"Created {len(batches)} batches for reranking.")

                # Rerank batches concurrently
                rerank_tasks = [rerank(q, batch) for batch in batches]
                reranked_results_with_scores = await asyncio.gather(*rerank_tasks)
                
                # Flatten the list of lists and sort by the new score
                all_reranked_hits = [item for sublist in reranked_results_with_scores for item in sublist]
                all_reranked_hits.sort(key=lambda x: x[1], reverse=True) # Sort by score, descending

                # final_hits now contains Chunk objects with their reranker scores
                final_hits = all_reranked_hits[:DEFAULT_RERANKER_TOP_K]

            except Exception as e:
                print(f"Reranking failed: {e}. Falling back to vector search results.")
                # Fallback to original hits if reranking fails
                final_hits = hits[:DEFAULT_RERANKER_TOP_K]
        else:
            # No reranker configured, use original hits
            final_hits = hits[:DEFAULT_RERANKER_TOP_K]

        contexts = [chunk.content for chunk, _ in final_hits]
        answer = await generate_answer(q, contexts)
        
        # Note: The 'distance' is now a relevance score if reranked, or distance if not.
        sources = [{"url": chunk.url, "content": chunk.content, "score": score} for chunk, score in final_hits]
        return {"answer": answer, "sources": sources}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{e.__class__.__name__}: {str(e)}")
