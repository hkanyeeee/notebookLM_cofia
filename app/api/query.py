import asyncio
import json
from typing import List, Tuple
from enum import Enum

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
from ..tools.intelligent_orchestrator import IntelligentOrchestrator
from ..models import Chunk
from ..vector_db_client import query_embeddings, query_hybrid, qdrant_client, COLLECTION_NAME
from . import get_session_id


class QueryType(str, Enum):
    """查询类型枚举"""
    NORMAL = "normal"           # 普通问答模式，启用web search，需要问题定性、拆解和工具使用
    DOCUMENT = "document"       # 文档问答模式，不启用web search，使用当前查询逻辑
    COLLECTION = "collection"   # collection问答模式，不启用web search，但针对特定向量库进行查询


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
    
    # 查询类型处理
    query_type_str = data.get("query_type", "normal")
    try:
        query_type = QueryType(query_type_str.lower())
    except ValueError:
        # 无效的查询类型，使用默认值
        query_type = QueryType.NORMAL
        
    conversation_history = data.get("conversation_history", [])  # 消息历史
    
    # Collection特定参数
    collection_id = data.get("collection_id")  # 用于COLLECTION类型的特定collection ID
    
    source_ids_int = [int(id) for id in document_ids] if document_ids else None

    if not q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    try:
        # 根据查询类型分发到不同的处理逻辑
        if query_type == QueryType.NORMAL:
            return await _handle_normal_query(
                q, top_k, embedding_model, embedding_dimensions, source_ids_int,
                use_hybrid, stream, llm_model, tool_mode, tools_data, max_steps,
                conversation_history, session_id
            )
        elif query_type == QueryType.DOCUMENT:
            return await _handle_document_query(
                q, top_k, embedding_model, embedding_dimensions, source_ids_int,
                use_hybrid, stream, llm_model, tool_mode, tools_data, max_steps,
                conversation_history, session_id
            )
        elif query_type == QueryType.COLLECTION:
            return await _handle_collection_query(
                q, top_k, embedding_model, embedding_dimensions, collection_id,
                use_hybrid, stream, llm_model, conversation_history, session_id
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported query type: {query_type}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{e.__class__.__name__}: {str(e)}")


async def _handle_normal_query(
    q: str, top_k: int, embedding_model: str, embedding_dimensions: int,
    source_ids_int: List[int], use_hybrid: bool, stream: bool, llm_model: str,
    tool_mode: str, tools_data: List[dict], max_steps: int,
    conversation_history: List[dict], session_id: str
):
    """
    处理NORMAL类型查询：启用web search，使用智能编排器进行问题分析、拆解和工具使用
    """
    # 构建工具配置
    try:
        tool_mode_enum = ToolMode(tool_mode)
    except ValueError:
        tool_mode_enum = ToolMode.AUTO
    
    # 解析工具定义
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
    
    # NORMAL模式使用智能编排器，启用完整的问题拆解和工具调用
    intelligent_orchestrator = IntelligentOrchestrator()
    
    # 获取基础上下文 - 这里可以是空的，让智能编排器自己搜索
    contexts = []  # NORMAL模式主要依靠web search获取信息
    
    if stream:
        # 流式处理
        async def event_generator():
            try:
                async for event in intelligent_orchestrator.process_query_intelligently_stream(
                    q, contexts, run_config, conversation_history
                ):
                    et = event.get("type")
                    if et == "reasoning":
                        yield f"data: {{\"type\": \"reasoning\", \"content\": {json.dumps(event['content'], ensure_ascii=False)} }}\n\n"
                    elif et == "content":
                        yield f"data: {{\"type\": \"content\", \"content\": {json.dumps(event['content'], ensure_ascii=False)} }}\n\n"
                    elif et in ("tool_call", "action"):
                        yield "data: " + json.dumps({
                            "type": "tool_call",
                            "name": event.get("name"),
                            "tool_name": event.get("tool_name") or event.get("name"),
                            "args": event.get("args", {})
                        }, ensure_ascii=False) + "\n\n"
                    elif et in ("tool_result", "observation"):
                        yield "data: " + json.dumps({
                            "type": "tool_result",
                            "name": event.get("name"),
                            "tool_name": event.get("tool_name") or event.get("name"),
                            "result": event.get("result"),
                            "success": event.get("success", True),
                            "latency_ms": event.get("latency_ms"),
                            "retries": event.get("retries")
                        }, ensure_ascii=False) + "\n\n"
                    elif et == "final_answer":
                        yield "data: " + json.dumps({
                            "type": "final_answer",
                            "content": event.get("content", "")
                        }, ensure_ascii=False) + "\n\n"
                    elif et == "error":
                        yield "data: " + json.dumps({
                            "type": "error",
                            "message": event["message"]
                        }, ensure_ascii=False) + "\n\n"
                
                # NORMAL模式的sources主要来自web search，暂时返回空的sources
                yield "data: " + json.dumps({
                    "type": "sources",
                    "sources": []
                }, ensure_ascii=False) + "\n\n"
                
                yield "data: {\"type\": \"complete\"}\n\n"
            except Exception as e:
                yield "data: " + json.dumps({
                    "type": "error",
                    "message": f"{e.__class__.__name__}: {str(e)}"
                }, ensure_ascii=False) + "\n\n"
        
        return StreamingResponse(event_generator(), media_type="text/event-stream")
    else:
        # 非流式处理
        result = await intelligent_orchestrator.process_query_intelligently(
            q, contexts, run_config, conversation_history
        )
        return {
            "answer": result["answer"],
            "sources": [],  # NORMAL模式的sources主要来自web search
            "success": result["success"],
            "tool_mode": tool_mode,
            "steps": result.get("steps", []),
            "query_type": "normal"
        }


async def _handle_document_query(
    q: str, top_k: int, embedding_model: str, embedding_dimensions: int,
    source_ids_int: List[int], use_hybrid: bool, stream: bool, llm_model: str,
    tool_mode: str, tools_data: List[dict], max_steps: int,
    conversation_history: List[dict], session_id: str
):
    """
    处理DOCUMENT类型查询：不启用web search，使用现有的向量检索逻辑
    """
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
    
    # DOCUMENT模式不使用工具（不启用web search）
    if stream:
        # 流式响应
        async def event_generator():
            try:
                # 使用传统流式问答，不传入对话历史
                async for delta in stream_answer(q, contexts, model=llm_model):
                    if delta["type"] == "reasoning":
                        yield f"data: {{\"type\": \"reasoning\", \"content\": {json.dumps(delta['content'], ensure_ascii=False)} }}\n\n"
                    elif delta["type"] == "content":
                        yield f"data: {{\"type\": \"content\", \"content\": {json.dumps(delta['content'], ensure_ascii=False)} }}\n\n"
                
                # 输出 sources（防御性：chunk.source 可能为 None）
                sources = []
                for chunk, score in final_hits:
                    src = getattr(chunk, "source", None)
                    if not src:
                        # 跳过无来源的孤立 chunk，避免 AttributeError
                        continue
                    sources.append({
                        "id": chunk.id,
                        "chunk_id": chunk.chunk_id,
                        "url": src.url,
                        "title": src.title,
                        "content": chunk.content,
                        "score": score,
                    })
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
    else:
        # 非流式响应
        # 使用传统问答，不传入对话历史
        answer = await generate_answer(q, contexts, model=llm_model)
        sources = []
        for chunk, score in final_hits:
            src = getattr(chunk, "source", None)
            if not src:
                continue
            sources.append({
                "id": chunk.id,
                "chunk_id": chunk.chunk_id,
                "url": src.url,
                "title": src.title,
                "content": chunk.content,
                "score": score,
            })
        return {
            "answer": answer,
            "sources": sources,
            "success": True,
            "query_type": "document"
        }


async def _handle_collection_query(
    q: str, top_k: int, embedding_model: str, embedding_dimensions: int,
    collection_id: str, use_hybrid: bool, stream: bool, llm_model: str,
    conversation_history: List[dict], session_id: str
):
    """
    处理COLLECTION类型查询：针对特定collection进行查询，不启用web search
    """
    if not collection_id:
        raise HTTPException(status_code=400, detail="collection_id is required for COLLECTION query type")

    try:
        # 将collection_id转换为source_id用于查询
        collection_source_id = int(collection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid collection_id format")

    # 使用固定的session_id与auto_ingest保持一致
    FIXED_SESSION_ID = "fixed_session_id_for_auto_ingest"

    query_embedding = (await embed_texts([q], model=embedding_model, dimensions=embedding_dimensions))[0]

    # 针对特定collection查询
    if use_hybrid:
        from ..database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            hits = await query_hybrid(
                query_text=q,
                query_embedding=query_embedding,
                top_k=top_k,
                session_id=FIXED_SESSION_ID,  # 使用固定session_id
                source_ids=[collection_source_id],  # 只查询指定的collection
                hnsw_ef=256,
                k_dense=min(150, top_k),
                k_sparse=min(50, top_k),
                db=db,
            )
    else:
        hits = await query_embeddings(
            query_embedding,
            top_k=top_k,
            session_id=FIXED_SESSION_ID,  # 使用固定session_id
            source_ids=[collection_source_id],  # 只查询指定的collection
        )

    final_hits = []
    if RERANKER_SERVICE_URL and hits:
        print(f"Reranking {len(hits)} hits for collection {collection_id}...")
        try:
            # 简化的reranking逻辑，为collection查询优化
            encoding = tiktoken.get_encoding("cl100k_base")
            documents = [hit[0].content for hit in hits]
            
            # 直接进行reranking
            from ..config import RERANKER_SERVICE_URL
            import httpx
            
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
                
                if scores and len(scores) == len(hits):
                    original_chunks = [hit[0] for hit in hits]
                    scored_chunks = list(zip(original_chunks, scores))
                    scored_chunks.sort(key=lambda x: float(x[1]) if isinstance(x[1], (int, float)) else 0, reverse=True)
                    final_hits = scored_chunks[:RAG_RERANK_TOP_K]
                else:
                    final_hits = hits[:RAG_RERANK_TOP_K]

        except Exception as e:
            print(f"Reranking failed for collection: {e}. Falling back to vector search results.")
            final_hits = hits[:RAG_RERANK_TOP_K]
    else:
        final_hits = hits[:RAG_RERANK_TOP_K]

    contexts = [chunk.content for chunk, _ in final_hits]
    
    # 检查是否找到相关内容
    if not contexts:
        # 没有找到相关内容，返回提示信息
        error_message = f"在Collection中没有找到与查询 '{q}' 相关的内容。请尝试使用不同的关键词或确认Collection中包含相关数据。"
        if stream:
            async def error_event_generator():
                yield "data: " + json.dumps({
                    "type": "error",
                    "message": error_message
                }, ensure_ascii=False) + "\n\n"
            return StreamingResponse(error_event_generator(), media_type="text/event-stream")
        else:
            return {
                "answer": error_message,
                "sources": [],
                "success": False,
                "query_type": "collection",
                "collection_id": collection_id
            }
    
    # COLLECTION模式不使用工具（不启用web search）
    if stream:
        # 流式响应
        async def event_generator():
            try:
                # 使用传统流式问答，不传入对话历史
                async for delta in stream_answer(q, contexts, model=llm_model):
                    if delta["type"] == "reasoning":
                        yield f"data: {{\"type\": \"reasoning\", \"content\": {json.dumps(delta['content'], ensure_ascii=False)} }}\n\n"
                    elif delta["type"] == "content":
                        yield f"data: {{\"type\": \"content\", \"content\": {json.dumps(delta['content'], ensure_ascii=False)} }}\n\n"
                
                # 输出 sources（防御性：chunk.source 可能为 None）
                sources = []
                for chunk, score in final_hits:
                    src = getattr(chunk, "source", None)
                    if not src:
                        continue
                    sources.append({
                        "id": chunk.id,
                        "chunk_id": chunk.chunk_id,
                        "url": src.url,
                        "title": src.title,
                        "content": chunk.content,
                        "score": score,
                    })
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
    else:
        # 非流式响应
        # 使用传统问答，不传入对话历史
        answer = await generate_answer(q, contexts, model=llm_model)
        sources = []
        for chunk, score in final_hits:
            src = getattr(chunk, "source", None)
            if not src:
                continue
            sources.append({
                "id": chunk.id,
                "chunk_id": chunk.chunk_id,
                "url": src.url,
                "title": src.title,
                "content": chunk.content,
                "score": score,
            })
        return {
            "answer": answer,
            "sources": sources,
            "success": True,
            "query_type": "collection",
            "collection_id": collection_id
        }


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
