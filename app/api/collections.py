from typing import List, Optional, AsyncGenerator
import hashlib
from fastapi import APIRouter, HTTPException, Depends, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import distinct
import json

from app.config import EMBEDDING_BATCH_SIZE

from ..models import Source, Chunk
from ..database import get_db
from ..vector_db_client import query_hybrid
from ..embedding_client import embed_texts
from ..llm_client import generate_answer, stream_answer

DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"

router = APIRouter()


class AgenticCollection(BaseModel):
    """Collection信息模型"""
    collection_id: str  # 使用source.id作为唯一标识
    collection_name: str  # 从title提取或生成的collection名称
    document_title: str  # 原始文档标题
    url: str
    created_at: Optional[str] = None


class CollectionQueryRequest(BaseModel):
    """Collection查询请求模型"""
    collection_id: str
    query: str
    top_k: int = 20
    model: Optional[str] = None  # 添加模型参数


class CollectionQueryResponse(BaseModel):
    """Collection查询响应模型"""
    success: bool
    results: List[dict] = []
    total_found: int = 0
    message: str = ""
    llm_answer: Optional[str] = None  # LLM生成的智能回答


@router.get("/collections", summary="获取所有可用的Collection列表")
async def get_collections_list(
    db: AsyncSession = Depends(get_db)
):
    """
    获取所有通过agenttic_ingest处理的collection列表
    返回简化的collection信息，供前端选择使用
    """
    try:
        FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
        
        # 查询所有agenttic_ingest处理的文档
        stmt = select(Source).where(Source.session_id == FIXED_SESSION_ID)
        result = await db.execute(stmt)
        sources = result.scalars().all()
        
        collections = []
        for source in sources:
            # 使用URL的hash生成稳定的collection名称，与agenttic_ingest.py保持一致
            url_hash = hashlib.md5(source.url.encode()).hexdigest()[:8]
            collection_name = f"collection_{url_hash}"
            
            collections.append(AgenticCollection(
                collection_id=str(source.id),
                collection_name=collection_name,
                document_title=source.title,
                url=source.url,
                created_at=source.created_at.isoformat() if hasattr(source, 'created_at') and source.created_at else None
            ))
        
        return {
            "success": True,
            "collections": collections,
            "total": len(collections)
        }
    
    except Exception as e:
        error_message = f"获取collection列表失败: {e.__class__.__name__}: {str(e)}"
        print(error_message)
        raise HTTPException(status_code=500, detail=error_message)


@router.post("/collections/query", summary="基于指定Collection进行查询")
async def query_collection(
    request: CollectionQueryRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    在指定的collection中进行向量搜索查询
    """
    try:
        FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
        
        # 验证collection_id是否存在
        source_stmt = select(Source).where(
            Source.id == int(request.collection_id),
            Source.session_id == FIXED_SESSION_ID
        )
        source_result = await db.execute(source_stmt)
        source = source_result.scalar_one_or_none()
        
        if not source:
            raise HTTPException(
                status_code=404, 
                detail=f"Collection ID {request.collection_id} 不存在"
            )
        
        # 查询该source下的所有chunks
        chunks_stmt = select(Chunk).where(
            Chunk.source_id == source.id,
            Chunk.session_id == FIXED_SESSION_ID
        )
        chunks_result = await db.execute(chunks_stmt)
        chunks = chunks_result.scalars().all()
        
        if not chunks:
            return CollectionQueryResponse(
                success=True,
                results=[],
                total_found=0,
                message=f"Collection '{source.title}' 中没有找到任何内容块"
            )
        
        # 使用向量搜索
        try:
            # 生成查询的embedding
            query_embeddings = await embed_texts(
                texts=[request.query],
                model=DEFAULT_EMBEDDING_MODEL,
                batch_size=EMBEDDING_BATCH_SIZE,
                dimensions=1024
            )
            
            if not query_embeddings or len(query_embeddings) == 0:
                raise Exception("无法生成查询的embedding向量")
            
            query_embedding = query_embeddings[0]
            
            # 调用混合搜索，限制在该source的chunks中
            FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
            search_hits = await query_hybrid(
                query_text=request.query,
                query_embedding=query_embedding,
                top_k=request.top_k,
                session_id=FIXED_SESSION_ID,
                source_ids=[source.id],  # 限制在特定source
                db=db
            )
            
            # 格式化搜索结果
            results = []
            contexts = []  # 收集上下文用于LLM生成回答
            for chunk, score in search_hits:
                results.append({
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                    "score": float(score),
                    "source_url": source.url,
                    "source_title": source.title
                })
                contexts.append(chunk.content)
            
            # 调用LLM生成智能回答
            llm_answer = ""
            if contexts:
                try:
                    # 传递模型参数，如果没有指定则使用默认模型
                    llm_answer = await generate_answer(request.query, contexts, model=request.model)
                except Exception as llm_error:
                    print(f"LLM生成回答失败: {llm_error}")
                    # LLM失败不影响搜索结果返回
            
            return CollectionQueryResponse(
                success=True,
                results=results,
                total_found=len(results),
                message=f"在Collection '{source.title}' 中找到 {len(results)} 个相关结果",
                llm_answer=llm_answer
            )
            
        except Exception as search_error:
            print(f"向量搜索失败: {search_error}")
            
            # 如果向量搜索失败，回退到文本搜索
            text_results = []
            text_contexts = []  # 收集文本搜索的上下文
            query_lower = request.query.lower()
            
            for chunk in chunks[:request.top_k]:  # 限制返回数量
                if query_lower in chunk.content.lower():
                    text_results.append({
                        "chunk_id": chunk.chunk_id,
                        "content": chunk.content[:500] + "..." if len(chunk.content) > 500 else chunk.content,
                        "score": 0.5,  # 文本匹配的默认分数
                        "source_url": source.url,
                        "source_title": source.title
                    })
                    text_contexts.append(chunk.content)
            
            # 调用LLM生成智能回答（文本搜索分支）
            llm_answer = ""
            if text_contexts:
                try:
                    # 传递模型参数，如果没有指定则使用默认模型
                    llm_answer = await generate_answer(request.query, text_contexts, model=request.model)
                except Exception as llm_error:
                    print(f"LLM生成回答失败（文本搜索分支）: {llm_error}")
            
            return CollectionQueryResponse(
                success=True,
                results=text_results,
                total_found=len(text_results),
                message=f"在Collection '{source.title}' 中通过文本匹配找到 {len(text_results)} 个结果（向量搜索不可用）",
                llm_answer=llm_answer
            )
    
    except HTTPException:
        raise
    except Exception as e:
        error_message = f"Collection查询失败: {e.__class__.__name__}: {str(e)}"
        print(error_message)
        raise HTTPException(status_code=500, detail=error_message)


@router.get("/collections/{collection_id}", summary="获取指定Collection的详细信息")
async def get_collection_detail(
    collection_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    获取指定collection的详细信息，包括chunks数量等统计信息
    """
    try:
        FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
        
        # 查询指定的source
        source_stmt = select(Source).where(
            Source.id == int(collection_id),
            Source.session_id == FIXED_SESSION_ID
        )
        source_result = await db.execute(source_stmt)
        source = source_result.scalar_one_or_none()
        
        if not source:
            raise HTTPException(
                status_code=404, 
                detail=f"Collection ID {collection_id} 不存在"
            )
        
        # 统计该source的chunks数量
        chunks_count_stmt = select(Chunk).where(
            Chunk.source_id == source.id,
            Chunk.session_id == FIXED_SESSION_ID
        )
        chunks_result = await db.execute(chunks_count_stmt)
        chunks = chunks_result.scalars().all()
        chunks_count = len(chunks)
        
        # 使用URL的hash生成稳定的collection名称，与agenttic_ingest.py保持一致
        url_hash = hashlib.md5(source.url.encode()).hexdigest()[:8]
        collection_name = f"collection_{url_hash}"
        
        return {
            "success": True,
            "collection": {
                "collection_id": str(source.id),
                "collection_name": collection_name,
                "document_title": source.title,
                "url": source.url,
                "chunks_count": chunks_count,
                "created_at": source.created_at.isoformat() if hasattr(source, 'created_at') and source.created_at else None
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        error_message = f"获取Collection详情失败: {e.__class__.__name__}: {str(e)}"
        print(error_message)
        raise HTTPException(status_code=500, detail=error_message)


@router.post("/collections/query-stream", summary="基于指定Collection进行流式查询")
async def query_collection_stream(
    request: CollectionQueryRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    在指定的collection中进行向量搜索，并流式返回LLM生成的智能回答
    """
    async def stream_response() -> AsyncGenerator[str, None]:
        try:
            FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
            
            # 验证collection_id是否存在
            source_stmt = select(Source).where(
                Source.id == int(request.collection_id),
                Source.session_id == FIXED_SESSION_ID
            )
            source_result = await db.execute(source_stmt)
            source = source_result.scalar_one_or_none()
            
            if not source:
                error_data = {
                    "error": f"Collection ID {request.collection_id} 不存在",
                    "type": "error"
                }
                yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                return
            
            # 查询该source下的所有chunks
            chunks_stmt = select(Chunk).where(
                Chunk.source_id == source.id,
                Chunk.session_id == FIXED_SESSION_ID
            )
            chunks_result = await db.execute(chunks_stmt)
            chunks = chunks_result.scalars().all()
            
            if not chunks:
                no_content_data = {
                    "message": f"Collection '{source.title}' 中没有找到任何内容块",
                    "type": "message"
                }
                yield f"data: {json.dumps(no_content_data, ensure_ascii=False)}\n\n"
                return
            
            # 先发送搜索开始的状态
            search_start_data = {"message": "开始搜索相关内容...", "type": "status"}
            yield f"data: {json.dumps(search_start_data, ensure_ascii=False)}\n\n"
            
            # 使用向量搜索
            contexts = []
            search_results = []
            
            try:
                # 生成查询的embedding
                query_embeddings = await embed_texts(
                    texts=[request.query],
                    model=DEFAULT_EMBEDDING_MODEL,
                    batch_size=EMBEDDING_BATCH_SIZE,
                    dimensions=1024
                )
                
                if query_embeddings and len(query_embeddings) > 0:
                    query_embedding = query_embeddings[0]
                    
                    # 调用混合搜索
                    search_hits = await query_hybrid(
                        query_text=request.query,
                        query_embedding=query_embedding,
                        top_k=request.top_k,
                        session_id=FIXED_SESSION_ID,
                        source_ids=[source.id],
                        db=db
                    )
                    
                    # 收集搜索结果和上下文
                    for chunk, score in search_hits:
                        search_results.append({
                            "chunk_id": chunk.chunk_id,
                            "content": chunk.content[:300] + "..." if len(chunk.content) > 300 else chunk.content,
                            "score": float(score),
                            "source_url": source.url,
                            "source_title": source.title
                        })
                        contexts.append(chunk.content)
                
            except Exception as search_error:
                print(f"向量搜索失败: {search_error}")
                # 回退到文本搜索
                query_lower = request.query.lower()
                for chunk in chunks[:request.top_k]:
                    if query_lower in chunk.content.lower():
                        search_results.append({
                            "chunk_id": chunk.chunk_id,
                            "content": chunk.content[:300] + "..." if len(chunk.content) > 300 else chunk.content,
                            "score": 0.5,
                            "source_url": source.url,
                            "source_title": source.title
                        })
                        contexts.append(chunk.content)
            
            # 发送搜索结果摘要
            search_summary = {
                "type": "search_results",
                "total_found": len(search_results),
                "message": f"找到 {len(search_results)} 个相关结果，处理中..."
            }
            yield f"data: {json.dumps(search_summary, ensure_ascii=False)}\n\n"
            
            # 流式生成LLM回答
            if contexts:
                try:
                    # 发送开始生成的状态
                    llm_start_data = {"type": "llm_start", "message": "开始生成智能回答..."}
                    yield f"data: {json.dumps(llm_start_data, ensure_ascii=False)}\n\n"
                    
                    # 流式获取LLM回答，传递模型参数
                    async for delta in stream_answer(request.query, contexts, model=request.model):
                        delta_data = {
                            "type": delta.get("type", "content"),
                            "content": delta.get("content", "")
                        }
                        yield f"data: {json.dumps(delta_data, ensure_ascii=False)}\n\n"
                    
                    # 发送参考来源数据
                    sources = [
                        {
                            "url": source.url,
                            "title": source.title,
                            "content": result["content"] if len(result["content"]) <= 300 else result["content"][:300] + "...",
                            "score": result["score"]
                        }
                        for result in search_results
                    ]
                    yield f"data: {json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"
                    
                    # 发送完成状态
                    complete_data = {"type": "complete", "message": "回答生成完成"}
                    yield f"data: {json.dumps(complete_data, ensure_ascii=False)}\n\n"
                    
                except Exception as llm_error:
                    print(f"LLM流式生成失败: {llm_error}")
                    error_data = {
                        "type": "error",
                        "message": f"生成智能回答时出错: {str(llm_error)}"
                    }
                    yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
            else:
                no_context_data = {
                    "type": "error",
                    "message": "没有找到相关内容，无法生成智能回答"
                }
                yield f"data: {json.dumps(no_context_data, ensure_ascii=False)}\n\n"
                
        except Exception as e:
            error_data = {
                "type": "error",
                "message": f"Collection查询失败: {str(e)}"
            }
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        stream_response(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream"
        }
    )
