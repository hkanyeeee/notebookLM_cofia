import asyncio
import tiktoken
from fastapi import FastAPI, Body, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Annotated
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select


from .config import DATABASE_URL, EMBEDDING_SERVICE_URL, LLM_SERVICE_URL, RERANKER_SERVICE_URL
from .database import init_db, get_db
from .fetch_parse import fetch_html, extract_text
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

@app.post("/ingest", summary="Ingest a document from a URL")
async def ingest(
    data: dict = Body(...),
    session_id: str = Depends(get_session_id),
    db: AsyncSession = Depends(get_db)
):
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL must be provided.")

    embedding_model = data.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions = data.get("embedding_dimensions", 2560)
    
    try:
        # Check if source already exists for this session
        stmt = select(Source).where(Source.url == url, Source.session_id == session_id)
        result = await db.execute(stmt)
        source = result.scalars().first()

        if source:
            return {
                "success": True,
                "document_id": str(source.id),
                "title": source.title,
                "message": "Document already exists for this session."
            }

        # Fetch, parse, and create source
        html = await fetch_html(url)
        text = extract_text(html)
        title = extract_text(html, selector='title') or url.split('/')[-1]

        source = Source(url=url, title=title, session_id=session_id)
        db.add(source)
        await db.flush() # Flush to get the source.id for chunks

        # Chunk text
        chunks = chunk_text(text)
        if not chunks:
            await db.rollback()
            raise HTTPException(status_code=400, detail="Could not extract any content from the URL.")

        # Create Chunk objects
        chunk_objects = [
            Chunk(content=chunk_text, source_id=source.id, session_id=session_id)
            for chunk_text in chunks
        ]
        db.add_all(chunk_objects)

        # Embed chunks
        embeddings = await embed_texts(
            [c.content for c in chunk_objects], 
            model=embedding_model, 
            dimensions=embedding_dimensions
        )
        
        # Add to vector DB with session_id in metadata
        await add_embeddings(source.id, chunk_objects, embeddings)
        
        await db.commit()

        return {
            "success": True, 
            "document_id": str(source.id), 
            "title": source.title,
            "message": f"Successfully ingested {len(chunks)} chunks from {url}."
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e.__class__.__name__}: {str(e)}")


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

    if not q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    try:
        query_embedding = (await embed_texts([q], model=embedding_model, dimensions=embedding_dimensions))[0]
        
        # IMPORTANT: Pass session_id and document_ids to vector DB query
        hits = await query_embeddings(
            query_embedding, 
            top_k=top_k, 
            session_id=session_id,
            source_ids=document_ids
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

