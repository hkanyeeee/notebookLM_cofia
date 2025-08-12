import asyncio
import tiktoken
import json
from fastapi import FastAPI, Body, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from typing import List, Annotated, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select


from .config import (
    DATABASE_URL,
    EMBEDDING_SERVICE_URL,
    LLM_SERVICE_URL,
    LLM_SERVICE_URL,
    RERANKER_SERVICE_URL,
    SEARXNG_QUERY_URL,
)
from .database import init_db, get_db
from .fetch_parse import fetch_html, extract_text, fetch_then_extract
from .chunking import chunk_text
from .embedding_client import embed_texts, DEFAULT_EMBEDDING_MODEL
from .llm_client import generate_answer
from .vector_db_client import add_embeddings, query_embeddings, delete_vector_db_data, query_hybrid
from .rerank_client import rerank, DEFAULT_RERANKER_TOP_K
from .models import Source, Chunk
import httpx

# Constants
RERANKER_MAX_TOKENS = 6144

app = FastAPI(title="NotebookLM-Py Backend")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，解决本地开发跨域问题
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- Dependency for Session ID --
async def get_session_id(x_session_id: Annotated[str, Header()]) -> str:
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header is required.")
    return x_session_id

# -- Lifespan Events --
@app.on_event("startup")
async def on_startup():
    print(f"Using DATABASE_URL: {DATABASE_URL}")
    try:
        await init_db()
        print("Database initialized successfully")
    except Exception as e:
        print(f"Database initialization failed: {e}")
        # Optionally, re-raise the exception to stop the app from starting
        # raise e

# -- API Endpoints --

async def stream_ingest_progress(data: dict, session_id: str, db: AsyncSession):
    """
    Streams the progress of ingesting a document from a URL.
    Yields Server-Sent Events (SSE) for progress updates.
    """
    url = data.get("url")
    if not url:
        yield f"data: {json.dumps({'type': 'error', 'message': 'URL must be provided.'})}\n\n"
        return

    embedding_model = data.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions = data.get("embedding_dimensions", 1024)
    
    try:
        # 1. Check if source already exists
        stmt = select(Source).where(Source.url == url, Source.session_id == session_id)
        result = await db.execute(stmt)
        existing_source = result.scalars().first()
        if existing_source:
            yield f"data: {json.dumps({'type': 'complete', 'document_id': str(existing_source.id), 'title': existing_source.title, 'message': 'Document already exists.'})}\n\n"
            return

        # 2. Fetch and Parse
        yield f"data: {json.dumps({'type': 'status', 'message': 'Fetching & parsing URL content...'})}\n\n"
        text = await fetch_then_extract(url)
        
        title = url.split('/')[-1]

        # 3. Chunk Text
        yield f"data: {json.dumps({'type': 'status', 'message': 'Chunking text...'})}\n\n"
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("Could not extract any content from the URL.")
        
        total_chunks = len(chunks)
        yield f"data: {json.dumps({'type': 'total_chunks', 'value': total_chunks})}\n\n"

        # 4. Create Source and Chunk objects in DB
        source = Source(url=url, title=title, session_id=session_id)
        db.add(source)
        await db.flush()

        chunk_objects = [
            Chunk(content=chunk_text, source_id=source.id, session_id=session_id)
            for chunk_text in chunks
        ]
        db.add_all(chunk_objects)
        await db.flush()
        # 提前提交，缩短事务占用时间，避免长时间写锁
        await db.commit()

        # 5. Embed and Add to Vector DB chunk by chunk
        for i, chunk_obj in enumerate(chunk_objects):
            # Embed
            embedding = (await embed_texts([chunk_obj.content], model=embedding_model, dimensions=embedding_dimensions))[0]
            
            # Add to vector DB
            await add_embeddings(source.id, [chunk_obj], [embedding])

            # Yield progress
            yield f"data: {json.dumps({'type': 'progress', 'value': i + 1})}\n\n"
            await asyncio.sleep(0.01) # Small delay to allow UI to update

        await db.commit()
        
        yield f"data: {json.dumps({'type': 'complete', 'document_id': str(source.id), 'title': title, 'message': f'Successfully ingested {total_chunks} chunks.'})}\n\n"

    except Exception as e:
        await db.rollback()
        error_message = f"Ingestion failed: {e.__class__.__name__}: {str(e)}"
        yield f"data: {json.dumps({'type': 'error', 'message': error_message})}\n\n"


@app.post("/ingest", summary="Ingest a document from a URL and stream progress")
async def ingest(
    data: dict = Body(...),
    session_id: str = Depends(get_session_id),
    db: AsyncSession = Depends(get_db)
):
    return StreamingResponse(
        stream_ingest_progress(data, session_id, db),
        media_type="text/event-stream"
    )


@app.post("/api/search/generate", summary="Generate web search queries from a topic using LLM")
async def generate_search_queries(
    data: dict = Body(...),
):
    """根据用户输入的课题，调用已配置的 LLM 服务生成 3 个搜索查询。
    返回 {queries: [str, str, str]}。
    """
    topic = data.get("topic", "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic cannot be empty")

    # 使用现有 LLM 服务，以系统提示约束返回 JSON
    prompt_system = (
        "你是搜索查询生成器。给定课题，产出3个多样化、可直接用于网页搜索的英文查询。"
        "返回JSON，键为queries，值为包含3个字符串的数组，不要夹杂多余文本。"
    )
    user_prompt = f"课题：{topic}\n请直接给出 JSON，如：{{'queries': ['...', '...', '...']}}"

    payload = {
        "model": "openai/gpt-oss-20b",
        "messages": [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{LLM_SERVICE_URL}/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            # 尝试解析为 JSON
            import json as _json
            import re as _re

            try:
                # 去掉可能的代码块包裹 ```json ... ``` / ``` ... ```
                content_stripped = content.strip()
                if content_stripped.startswith("```"):
                    content_stripped = _re.sub(r"^```(?:json)?\\s*|\\s*```$", "", content_stripped)

                # 如果包含 JSON 对象子串，只取第一个对象
                m = _re.search(r"\{[\s\S]*\}", content_stripped)
                json_candidate = m.group(0) if m else content_stripped

                # 先尝试严格 JSON
                parsed = _json.loads(json_candidate)
                queries = parsed.get("queries") or parsed.get("Queries")
                if not isinstance(queries, list):
                    raise ValueError("Invalid schema: queries not list")
                queries = [str(q).strip() for q in queries if str(q).strip()][:3]
                if not queries:
                    raise ValueError("Empty queries")
                # 填满 3 个
                while len(queries) < 3:
                    queries.append(topic)
                return {"queries": queries[:3]}
            except Exception:
                # 宽松处理：把单引号换成双引号再试一次
                try:
                    relaxed = json_candidate.replace("'", '"')
                    parsed2 = _json.loads(relaxed)
                    qs = parsed2.get("queries") or parsed2.get("Queries")
                    if isinstance(qs, list):
                        qs = [str(q).strip() for q in qs if str(q).strip()][:3]
                        while len(qs) < 3:
                            qs.append(topic)
                        return {"queries": qs[:3]}
                except Exception:
                    pass

                # 兜底：按行拆分，过滤可能的 JSON 包裹
                lines = [s.strip() for s in content.split("\n") if s.strip()]
                # 如果第一行就是一个对象字符串，尝试再解析一次
                if lines and (lines[0].startswith("{") and lines[0].endswith("}")):
                    try:
                        obj = _json.loads(lines[0].replace("'", '"'))
                        if isinstance(obj.get("queries"), list):
                            arr = [str(q).strip() for q in obj["queries"] if str(q).strip()]
                            return {"queries": (arr + [topic, f"{topic} 相关问题"])[:3]}
                    except Exception:
                        pass

                queries = lines[:3]
                if not queries:
                    queries = [topic, f"{topic} 关键点", f"{topic} 最新进展"]
                return {"queries": queries[:3]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generate queries failed: {e}")


@app.post("/api/search/searxng", summary="Search web via SearxNG for a given query")
async def search_searxng_api(data: dict = Body(...)):
    """调用 SearxNG /search 接口，按 Open WebUI 行为对齐：
    - 语言固定 en-US
    - time_range / categories 为空
    - 传递 pageno=1、theme=simple、image_proxy=0、safesearch=1
    - 设置与 Open WebUI 相同的请求头
    - 对返回 results 按 score 降序并截断至 count
    """
    query = data.get("query", "").strip()
    count = int(data.get("count", 4))
    if not query:
        raise HTTPException(status_code=400, detail="query cannot be empty")

    params = {
        "q": query,
        "format": "json",
        "pageno": 1,
        "safesearch": "1",
        "language": "en-US",
        "time_range": "",
        "categories": "",
        "theme": "simple",
        "image_proxy": 0,
    }

    headers = {
        "User-Agent": "Open WebUI (https://github.com/open-webui/open-webui) RAG Bot",
        "Accept": "text/html",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(SEARXNG_QUERY_URL, params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
            results = payload.get("results", [])
            # 对齐 Open WebUI：按 score 降序
            results_sorted = sorted(results, key=lambda x: x.get("score", 0), reverse=True)
            items = []
            for r in results_sorted[:max(1, count)]:
                title = r.get("title") or r.get("name") or "Untitled"
                url = r.get("url") or r.get("link")
                if not url:
                    continue
                items.append({"title": title, "url": url})
            return {"items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SearxNG request failed: {e}")

@app.delete("/api/documents/{document_id}", summary="Delete a single document and its associated data")
async def delete_document(
    document_id: int,
    session_id: str = Depends(get_session_id),
    db: AsyncSession = Depends(get_db)
):
    try:
        # 1. Find the source and verify it belongs to the current session
        stmt = select(Source).where(Source.id == document_id, Source.session_id == session_id)
        result = await db.execute(stmt)
        source_to_delete = result.scalars().first()

        if not source_to_delete:
            raise HTTPException(
                status_code=404, 
                detail=f"Document with id {document_id} not found or you don't have permission to delete it."
            )

        # 2. Delete from vector DB using the source_id
        await delete_vector_db_data([document_id])

        # 3. Delete from SQL database (cascading delete will handle chunks)
        await db.delete(source_to_delete)
        await db.commit()

        return {"success": True, "message": f"Successfully deleted document {document_id}"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {e}")


@app.post("/api/session/cleanup", summary="Clean up all data for a given session")
async def cleanup_session(
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db)
):
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required.")
    
    try:
        # 1. Find all source IDs for the session
        stmt = select(Source.id).where(Source.session_id == session_id)
        result = await db.execute(stmt)
        source_ids = result.scalars().all()

        if not source_ids:
            return {"success": True, "message": "No data found for the session."}

        # 2. Delete from vector DB
        await delete_vector_db_data(source_ids)

        # 3. Delete from SQL database (cascading delete will handle chunks)
        delete_stmt = Source.__table__.delete().where(Source.session_id == session_id)
        await db.execute(delete_stmt)
        await db.commit()

        return {"success": True, "message": f"Successfully cleaned up data for session {session_id}"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {e}")


@app.post("/query", summary="Query ingested documents")
async def query(
    data: dict = Body(...),
    session_id: str = Depends(get_session_id),
):
    q = data.get("query", "")
    top_k = data.get("top_k", 200)
    embedding_model = data.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions = data.get("embedding_dimensions", 1024)
    document_ids = data.get("document_ids", []) # Optional filtering by document
    use_hybrid = data.get("use_hybrid", True)
    source_ids_int = [int(id) for id in document_ids] if document_ids else None

    if not q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    try:
        query_embedding = (await embed_texts([q], model=embedding_model, dimensions=embedding_dimensions))[0]
        
        # 稠密 or 混合检索
        if use_hybrid:
            from .database import AsyncSessionLocal
            async with AsyncSessionLocal() as db:
                hits = await query_hybrid(
                    query_text=q,
                    query_embedding=query_embedding,
                    top_k=top_k,
                    session_id=session_id,
                    source_ids=source_ids_int,
                    hnsw_ef=256,
                    k_dense=min(50, top_k),
                    k_sparse=min(50, top_k),
                    db=db,
                )
        else:
            hits = await query_embeddings(
                query_embedding, 
                top_k=top_k, 
                session_id=session_id,
                source_ids=source_ids_int
            )

        final_hits = []
        if RERANKER_SERVICE_URL and hits:
            print(f"Reranking {len(hits)} hits...")
            try:
                # Use tiktoken to estimate token counts and create batches for reranking
                encoding = tiktoken.get_encoding("cl100k_base")
                query_tokens = len(encoding.encode(q))
                
                batches: List[List[Tuple[Chunk, float]]] = []
                current_batch: List[Tuple[Chunk, float]] = []
                current_batch_tokens = query_tokens

                for hit in hits:
                    # hit is a tuple of (Chunk, score)
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

                # Log rerank ranking changes
                print("=== Rerank Ranking Changes ===")
                ranking_changes = []
                
                # Create a mapping from chunk content to original rank
                original_ranks = {}
                for i, (chunk, _) in enumerate(hits):
                    # Use chunk content as key (assuming content is unique enough)
                    chunk_key = chunk.content[:100]  # Use first 100 chars as key
                    original_ranks[chunk_key] = i + 1
                
                # Find new ranks and log changes
                for i, (chunk, _) in enumerate(all_reranked_hits[:DEFAULT_RERANKER_TOP_K]):
                    chunk_key = chunk.content[:100]
                    original_rank = original_ranks.get(chunk_key, "N/A")
                    new_rank = i + 1
                    ranking_changes.append([original_rank, new_rank])
                    print(f"Chunk {i+1}: Original rank {original_rank} -> New rank {new_rank}")
                
                print(f"Ranking changes: {ranking_changes}")
                print("=== End Rerank Ranking Changes ===")

                # final_hits now contains Chunk objects with their reranker scores
                final_hits = all_reranked_hits[:DEFAULT_RERANKER_TOP_K]

            except Exception as e:
                print(f"Reranking failed: {e}. Falling back to vector search results.")
                final_hits = hits[:DEFAULT_RERANKER_TOP_K]
        else:
            final_hits = hits[:DEFAULT_RERANKER_TOP_K]

        contexts = [chunk.content for chunk, _ in final_hits]
        answer = await generate_answer(q, contexts)
        
        sources = [
            {"url": chunk.source.url, "content": chunk.content, "score": score} 
            for chunk, score in final_hits
        ]
        return {"answer": answer, "sources": sources, "success": True}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{e.__class__.__name__}: {str(e)}")


# -- Debug Endpoint --
@app.get("/debug/qdrant-points", summary="Get all points from Qdrant for debugging")
async def debug_qdrant_points():
    from .vector_db_client import qdrant_client, COLLECTION_NAME
    if not qdrant_client:
        raise HTTPException(status_code=503, detail="Qdrant client not available")

    try:
        # Use scroll to get all points. Might be slow for large dbs.
        points, _ = qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            limit=100,  # Limit to 100 points for now
            with_payload=True,
            with_vectors=False
        )
        payloads = [p.payload for p in points]
        return {"points_payload": payloads}
    except Exception as e:
        # Handle case where collection might not exist yet
        return {"error": str(e)}

