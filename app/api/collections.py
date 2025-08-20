from typing import List, Optional
import hashlib
from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import distinct

from ..models import Source, Chunk
from ..database import get_db
from ..vector_db_client import query_hybrid
from ..embedding_client import embed_texts

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


class CollectionQueryResponse(BaseModel):
    """Collection查询响应模型"""
    success: bool
    results: List[dict] = []
    total_found: int = 0
    message: str = ""


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
                batch_size=1,
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
            for chunk, score in search_hits:
                results.append({
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                    "score": float(score),
                    "source_url": source.url,
                    "source_title": source.title
                })
            
            return CollectionQueryResponse(
                success=True,
                results=results,
                total_found=len(results),
                message=f"在Collection '{source.title}' 中找到 {len(results)} 个相关结果"
            )
            
        except Exception as search_error:
            print(f"向量搜索失败: {search_error}")
            
            # 如果向量搜索失败，回退到文本搜索
            text_results = []
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
            
            return CollectionQueryResponse(
                success=True,
                results=text_results,
                total_found=len(text_results),
                message=f"在Collection '{source.title}' 中通过文本匹配找到 {len(text_results)} 个结果（向量搜索不可用）"
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
