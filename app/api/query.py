import asyncio
import json
from typing import List, Tuple

import tiktoken
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..config import (
    RERANKER_SERVICE_URL,
    RERANKER_MAX_TOKENS,
    RERANK_CLIENT_MAX_CONCURRENCY,
    DEFAULT_SEARCH_MODEL,
    EMBEDDING_DIMENSIONS,
    QUERY_TOP_K_BEFORE_RERANK,
    MAX_TOOL_STEPS,
    RAG_RERANK_TOP_K,
)
from ..embedding_client import embed_texts, DEFAULT_EMBEDDING_MODEL
from ..llm_client import (
    generate_answer, stream_answer,
    generate_answer_with_tools, stream_answer_with_tools
)
from ..tools.models import RunConfig, ToolMode, ToolSchema
from ..tools.selector import StrategySelector
from ..models import Chunk
from ..vector_db_client import query_embeddings, query_hybrid, qdrant_client, COLLECTION_NAME
from . import get_session_id


router = APIRouter()

_rerank_client_semaphore = asyncio.Semaphore(RERANK_CLIENT_MAX_CONCURRENCY)


@router.post("/query", summary="Query ingested documents")
async def query(
    data: dict = Body(...),
    session_id: str = Depends(get_session_id),
):
    q = data.get("query", "")
    top_k = data.get("top_k", QUERY_TOP_K_BEFORE_RERANK)
    embedding_model = data.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions = data.get("embedding_dimensions", EMBEDDING_DIMENSIONS)
    document_ids = data.get("document_ids", [])  # Optional filtering by document
    use_hybrid = data.get("use_hybrid", True)
    stream = bool(data.get("stream", False))
    llm_model = data.get("model", DEFAULT_SEARCH_MODEL)  # 添加模型参数支持
    
    # 新增工具相关参数
    tool_mode = data.get("tool_mode", "auto")  # "off" | "auto" | "json" | "react" | "harmony"
    tools_data = data.get("tools", [])  # 工具定义列表
    max_steps = data.get("max_steps", MAX_TOOL_STEPS)  # 最大执行步数
    query_type = data.get("query_type", "normal")  # 查询类型
    conversation_history = data.get("conversation_history", [])  # 消息历史
    
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
                        print(f"Invalid score type {type(score)}: {score}, treating as 0")
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
                for i, (chunk, _) in enumerate(all_reranked_hits[:RAG_RERANK_TOP_K]):
                    chunk_key = chunk.content[:100]
                    original_rank = original_ranks.get(chunk_key, "N/A")
                    new_rank = i + 1
                    ranking_changes.append([original_rank, new_rank])
                    print(f"Chunk {i+1}: Original rank {original_rank} -> New rank {new_rank}")

                print(f"Ranking changes: {ranking_changes}")
                print("=== End Rerank Ranking Changes ===")

                # final_hits now contains Chunk objects with their reranker scores
                final_hits = all_reranked_hits[:RAG_RERANK_TOP_K]

            except Exception as e:
                print(f"Reranking failed: {e}. Falling back to vector search results.")
                final_hits = hits[:RAG_RERANK_TOP_K]
        else:
            final_hits = hits[:RAG_RERANK_TOP_K]

        contexts = [chunk.content for chunk, _ in final_hits]
        
        # 构建工具配置
        try:
            tool_mode_enum = ToolMode(tool_mode)
        except ValueError:
            # 无效的工具模式，使用默认值
            tool_mode_enum = ToolMode.AUTO
        
        # 解析工具定义（前端传递的工具配置）
        tools_schemas = []
        for tool_data in tools_data:
            try:
                schema = ToolSchema(**tool_data)
                tools_schemas.append(schema)
            except Exception as e:
                print(f"解析工具定义失败: {e}")
        
        run_config = RunConfig(
            tool_mode=tool_mode_enum,
            tools=tools_schemas,
            max_steps=max_steps,
            model=llm_model
        )
        
        # 判断是否使用工具功能，纯代码
        use_tools = StrategySelector.should_use_tools(run_config, llm_model)
        
        # 检查是否是普通问答模式，如果是则使用智能编排器
        use_intelligent_orchestrator = (query_type == "normal" and use_tools)
        
        if not stream:
            # 非流式响应
            if use_tools:
                # 只有普通问答模式才传入消息历史
                history = conversation_history if query_type == "normal" else None
                result = await generate_answer_with_tools(
                    q, contexts, run_config, use_intelligent_orchestrator, history
                )
                sources = [
                    {"id": chunk.id, "chunk_id": chunk.chunk_id, "url": chunk.source.url, "title": chunk.source.title, "content": chunk.content, "score": score}
                    for chunk, score in final_hits
                ]
                return {
                    "answer": result["answer"],
                    "sources": sources,
                    "success": result["success"],
                    "tool_mode": result.get("tool_mode", tool_mode),
                    "steps": result.get("steps", [])
                }
            else:
                # 使用传统问答
                # 只有普通问答模式才传入消息历史
                history = conversation_history if query_type == "normal" else None
                answer = await generate_answer(q, contexts, model=llm_model, conversation_history=history)
                sources = [
                    {"id": chunk.id, "chunk_id": chunk.chunk_id, "url": chunk.source.url, "title": chunk.source.title, "content": chunk.content, "score": score}
                    for chunk, score in final_hits
                ]
                return {"answer": answer, "sources": sources, "success": True}
        else:
            # 流式响应
            async def event_generator():
                try:
                    if use_tools:
                        # 使用工具流式问答
                        # 只有普通问答模式才传入消息历史
                        history = conversation_history if query_type == "normal" else None
                        async for event in stream_answer_with_tools(
                            q, contexts, run_config, use_intelligent_orchestrator, history
                        ):
                            et = event.get("type")
                            if et == "reasoning":
                                yield f"data: {{\"type\": \"reasoning\", \"content\": {json.dumps(event['content'], ensure_ascii=False)} }}\n\n"
                            elif et == "content":
                                yield f"data: {{\"type\": \"content\", \"content\": {json.dumps(event['content'], ensure_ascii=False)} }}\n\n"
                            # 为 Harmony/JSON 统一透传工具相关事件
                            elif et in ("tool_call", "action"):
                                yield "data: " + json.dumps({
                                    "type": "tool_call",
                                    "name": event.get("name"),
                                    "tool_name": event.get("tool_name") or event.get("name"),
                                    "args": event.get("args", {})
                                }, ensure_ascii=False) + "\n\n"
                            elif et in ("tool_result", "observation"):
                                payload = {
                                    "type": "tool_result",
                                    "name": event.get("name"),
                                    "tool_name": event.get("tool_name") or event.get("name"),
                                    "result": event.get("result"),
                                    "success": event.get("success", True)
                                }
                                # 透传可观测性字段
                                if "latency_ms" in event:
                                    payload["latency_ms"] = event.get("latency_ms")
                                if "retries" in event:
                                    payload["retries"] = event.get("retries")
                                yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
                            elif et == "final_answer":
                                # 转发最终答案事件，便于前端立刻结束等待状态
                                yield "data: " + json.dumps({
                                    "type": "final_answer",
                                    "content": event.get("content", ""),
                                    "message": event.get("message", "")
                                }, ensure_ascii=False) + "\n\n"
                            elif et == "error":
                                yield "data: " + json.dumps({
                                    "type": "error",
                                    "message": event["message"]
                                }, ensure_ascii=False) + "\n\n"
                    else:
                        # 使用传统流式问答
                        # 只有普通问答模式才传入消息历史
                        history = conversation_history if query_type == "normal" else None
                        async for delta in stream_answer(q, contexts, model=llm_model, conversation_history=history):
                            if delta["type"] == "reasoning":
                                yield f"data: {{\"type\": \"reasoning\", \"content\": {json.dumps(delta['content'], ensure_ascii=False)} }}\n\n"
                            elif delta["type"] == "content":
                                yield f"data: {{\"type\": \"content\", \"content\": {json.dumps(delta['content'], ensure_ascii=False)} }}\n\n"
                    
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
