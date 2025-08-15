import asyncio
import logging
import json
from typing import List, Tuple

import tiktoken
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..config import (
    RERANKER_SERVICE_URL,
    RERANKER_MAX_TOKENS,
    RERANK_CLIENT_MAX_CONCURRENCY,
)
from ..embedding_client import embed_texts, DEFAULT_EMBEDDING_MODEL
from ..llm_client import generate_answer, stream_answer
from ..models import Chunk
from ..vector_db_client import query_embeddings, query_hybrid, qdrant_client, COLLECTION_NAME
from ..rerank_client import DEFAULT_RERANKER_TOP_K
from . import get_session_id


router = APIRouter()

_rerank_client_semaphore = asyncio.Semaphore(RERANK_CLIENT_MAX_CONCURRENCY)


@router.post("/query", summary="Query ingested documents")
async def query(
    data: dict = Body(...),
    session_id: str = Depends(get_session_id),
):
    q = data.get("query", "")
    top_k = data.get("top_k", 200)
    embedding_model = data.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions = data.get("embedding_dimensions", 1024)
    document_ids = data.get("document_ids", [])  # Optional filtering by document
    use_hybrid = data.get("use_hybrid", True)
    stream = bool(data.get("stream", False))
    source_ids_int = [int(id) for id in document_ids] if document_ids else None

    if not q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    try:
        query_embedding = (await embed_texts([q], model=embedding_model, dimensions=embedding_dimensions))[0]

        # 稠密 or 混合检索
        if use_hybrid:
            from ..database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                hits = await query_hybrid(
                    query_text=q,
                    query_embedding=query_embedding,
                    top_k=top_k,
                    session_id=session_id,
                    source_ids=source_ids_int,
                    hnsw_ef=256,
                    k_dense=min(150, top_k),
                    k_sparse=min(50, top_k),
                    db=db,
                )
        else:
            hits = await query_embeddings(
                query_embedding,
                top_k=top_k,
                session_id=session_id,
                source_ids=source_ids_int,
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

                # Rerank batches with限流的并发控制，避免压满后端
                async def rerank_with_limit(batch):
                    async with _rerank_client_semaphore:
                        # Use gateway to handle reranking requests
                        from ..config import RERANKER_SERVICE_URL
                        import httpx
                        
                        documents = [hit[0].content for hit in batch]
                        payload = {
                            "query": q,
                            "documents": documents,
                        }
                        
                        async with httpx.AsyncClient() as client:
                            api_url = f"{RERANKER_SERVICE_URL.rstrip('/')}/rerank"
                            response = await client.post(api_url, json=payload, timeout=300)
                            response.raise_for_status()
                            
                            data = response.json()
                            scores = data.get('scores')
                            
                            if scores is None or len(scores) != len(batch):
                                raise ValueError(f"Reranker returned an invalid response. Number of scores does not match number of documents. Scores: {scores}")
                            
                            original_chunks = [hit[0] for hit in batch]
                            scored_chunks = list(zip(original_chunks, scores))
                            
                            return scored_chunks

                rerank_tasks = [asyncio.create_task(rerank_with_limit(batch)) for batch in batches]
                reranked_results_with_scores = await asyncio.gather(*rerank_tasks)

                # Flatten the list of lists and sort by the new score
                all_reranked_hits = [item for sublist in reranked_results_with_scores for item in sublist]
                
                # Ensure scores are numeric for sorting
                def safe_sort_key(item):
                    score = item[1]
                    try:
                        # Try to convert to float for comparison
                        return float(score)
                    except (ValueError, TypeError):
                        # If conversion fails, return a large number to push it to the end
                        logger.warning(f"Invalid score type {type(score)}: {score}, treating as 0")
                        return 0.0
                
                all_reranked_hits.sort(key=safe_sort_key, reverse=True)  # Sort by score, descending

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

        if not stream:
            answer = await generate_answer(q, contexts)
            sources = [
                {"id": chunk.id, "chunk_id": chunk.chunk_id, "url": chunk.source.url, "title": chunk.source.title, "content": chunk.content, "score": score}
                for chunk, score in final_hits
            ]
            return {"answer": answer, "sources": sources, "success": True}
        else:
            # 以 SSE 流式返回
            async def event_generator():
                try:
                    # 逐块输出模型增量
                    async for delta in stream_answer(q, contexts):
                        yield f"data: {{\"type\": \"delta\", \"content\": {json.dumps(delta, ensure_ascii=False)} }}\n\n"
                    # 输出 sources
                    sources = [
                        {"id": chunk.id, "chunk_id": chunk.chunk_id, "url": chunk.source.url, "title": chunk.source.title, "content": chunk.content, "score": score}
                        for chunk, score in final_hits
                    ]
                    yield "data: " + json.dumps({
                        "type": "sources",
                        "sources": sources,
                    }, ensure_ascii=False) + "\n\n"
                    # 完成
                    yield "data: {\"type\": \"complete\"}\n\n"
                except Exception as e:
                    yield "data: " + json.dumps({
                        "type": "error",
                        "message": f"{e.__class__.__name__}: {str(e)}",
                    }, ensure_ascii=False) + "\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{e.__class__.__name__}: {str(e)}")


@router.get("/debug/qdrant-points", summary="Get all points from Qdrant for debugging")
async def debug_qdrant_points():
    if not qdrant_client:
        raise HTTPException(status_code=503, detail="Qdrant client not available")

    try:
        # Use scroll to get all points. Might be slow for large dbs.
        points, _ = qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            limit=100,  # Limit to 100 points for now
            with_payload=True,
            with_vectors=False,
        )
        payloads = [p.payload for p in points]
        return {"points_payload": payloads}
    except Exception as e:
        # Handle case where collection might not exist yet
        return {"error": str(e)}
