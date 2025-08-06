import asyncio
import tiktoken
import json
from fastapi import FastAPI, Body, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from typing import List, Annotated, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select


from .config import DATABASE_URL, EMBEDDING_SERVICE_URL, LLM_SERVICE_URL, RERANKER_SERVICE_URL
from .database import init_db, get_db
from .fetch_parse import fetch_html, extract_text, fetch_then_extract
from .chunking import chunk_text
from .embedding_client import embed_texts, DEFAULT_EMBEDDING_MODEL
from .llm_client import generate_answer
from .vector_db_client import add_embeddings, query_embeddings, delete_vector_db_data
from .rerank_client import rerank, DEFAULT_RERANKER_TOP_K
from .models import Source, Chunk

# Constants
RERANKER_MAX_TOKENS = 8192

app = FastAPI(title="NotebookLM-Py Backend")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
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
    embedding_dimensions = data.get("embedding_dimensions", 2560)
    
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
    top_k = data.get("top_k", 60)
    embedding_model = data.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions = data.get("embedding_dimensions", 2560)
    document_ids = data.get("document_ids", []) # Optional filtering by document
    source_ids_int = [int(id) for id in document_ids] if document_ids else None

    if not q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    try:
        query_embedding = (await embed_texts([q], model=embedding_model, dimensions=embedding_dimensions))[0]
        
        # IMPORTANT: Pass session_id and document_ids to vector DB query
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

