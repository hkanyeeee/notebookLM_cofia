from typing import List, Optional, AsyncGenerator
import hashlib
from fastapi import APIRouter, HTTPException, Depends, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import distinct
import json
from urllib.parse import urlparse

from app.config import EMBEDDING_BATCH_SIZE

from ..models import Source, Chunk
from ..database import get_db
from ..vector_db_client import query_hybrid
from ..embedding_client import embed_texts
from ..llm_client import generate_answer, stream_answer

DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"

router = APIRouter()


def determine_parent_url(url: str) -> str:
    """
    确定URL的父级collection归属
    
    对于文档网站的子页面，归属到其父级路径：
    - https://lmstudio.ai/docs/python/* -> https://lmstudio.ai/docs/python
    - https://example.com/docs/guide/* -> https://example.com/docs/guide
    
    Args:
        url: 要分析的URL
        
    Returns:
        str: 父级URL
    """
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split('/') if p]
    
    # 特殊处理已知的文档站点结构
    if 'lmstudio.ai' in parsed.netloc and 'docs' in path_parts:
        # 对于 lmstudio.ai/docs/python/* -> lmstudio.ai/docs/python
        if len(path_parts) >= 2 and path_parts[0] == 'docs' and path_parts[1] == 'python':
            return f"{parsed.scheme}://{parsed.netloc}/docs/python"
        # 对于其他docs子页面，归属到各自的子section
        elif len(path_parts) >= 2 and path_parts[0] == 'docs':
            return f"{parsed.scheme}://{parsed.netloc}/docs/{path_parts[1]}"
    
    # 通用逻辑：多级路径归属到其父级（至少保留2级路径）
    if len(path_parts) > 2:
        # 保留前两级路径作为父级
        parent_path = '/' + '/'.join(path_parts[:2])
        return f"{parsed.scheme}://{parsed.netloc}{parent_path}"
    
    # 默认返回原URL（根级文档）
    return url


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
        
        # 按collection进行分组：子文档归属到父文档的collection
        collection_groups = {}
        
        for source in sources:
            # 为每个source确定其所属的collection
            parent_url = determine_parent_url(source.url)
            parent_url_hash = hashlib.md5(parent_url.encode()).hexdigest()[:8]
            collection_name = f"collection_{parent_url_hash}"
            
            if collection_name not in collection_groups:
                collection_groups[collection_name] = {
                    'parent_url': parent_url,
                    'sources': []
                }
            
            collection_groups[collection_name]['sources'].append(source)
        
        collections = []
        for collection_name, group_data in collection_groups.items():
            # 找到主文档（URL最短的通常是父文档）
            main_source = min(group_data['sources'], key=lambda s: len(s.url))
            
            # 计算该collection的总文档数和chunks数
            total_sources = len(group_data['sources'])
            
            collections.append(AgenticCollection(
                collection_id=collection_name,  # 使用collection_name作为ID
                collection_name=collection_name,
                document_title=f"{main_source.title} ({total_sources}个文档)",
                url=main_source.url,
                created_at=main_source.created_at.isoformat() if hasattr(main_source, 'created_at') and main_source.created_at else None
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
        
        # 验证collection_id并获取该collection下的所有sources
        all_sources_stmt = select(Source).where(Source.session_id == FIXED_SESSION_ID)
        all_sources_result = await db.execute(all_sources_stmt)
        all_sources = all_sources_result.scalars().all()
        
        # 找到属于指定collection的所有sources（兼容数值ID）
        collection_sources = []
        if request.collection_id.isdigit():
            # 视作父source.id，找到其父分组
            parent_source = next((s for s in all_sources if str(s.id) == request.collection_id), None)
            if parent_source:
                parent_url = determine_parent_url(parent_source.url)
                for s in all_sources:
                    if determine_parent_url(s.url) == parent_url:
                        collection_sources.append(s)
        else:
            for source in all_sources:
                parent_url = determine_parent_url(source.url)
                parent_url_hash = hashlib.md5(parent_url.encode()).hexdigest()[:8]
                collection_name = f"collection_{parent_url_hash}"
                if collection_name == request.collection_id:
                    collection_sources.append(source)
        
        if not collection_sources:
            raise HTTPException(
                status_code=404, 
                detail=f"Collection ID {request.collection_id} 不存在"
            )
        
        # 查询该collection下所有sources的chunks
        source_ids = [s.id for s in collection_sources]
        chunks_stmt = select(Chunk).where(
            Chunk.source_id.in_(source_ids),
            Chunk.session_id == FIXED_SESSION_ID
        )
        chunks_result = await db.execute(chunks_stmt)
        chunks = chunks_result.scalars().all()
        
        if not chunks:
            main_source = min(collection_sources, key=lambda s: len(s.url))
            return CollectionQueryResponse(
                success=True,
                results=[],
                total_found=0,
                message=f"Collection '{main_source.title}' 中没有找到任何内容块"
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
            
            # 调用混合搜索，限制在该collection的所有sources中
            search_hits = await query_hybrid(
                query_text=request.query,
                query_embedding=query_embedding,
                top_k=request.top_k,
                session_id=FIXED_SESSION_ID,
                source_ids=source_ids,  # 限制在collection的所有sources
                db=db
            )
            
            # 创建source映射，用于快速查找
            source_map = {s.id: s for s in collection_sources}
            
            # 格式化搜索结果
            results = []
            contexts = []  # 收集上下文用于LLM生成回答
            for chunk, score in search_hits:
                source = source_map.get(chunk.source_id)
                results.append({
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                    "score": float(score),
                    "source_url": source.url if source else "Unknown",
                    "source_title": source.title if source else "Unknown"
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
            
            # 选择主文档用于UI展示
            main_source = min(collection_sources, key=lambda s: len(s.url))
            return CollectionQueryResponse(
                success=True,
                results=results,
                total_found=len(results),
                message=f"在Collection '{main_source.title}' 中找到 {len(results)} 个相关结果",
                llm_answer=llm_answer
            )
            
        except Exception as search_error:
            print(f"向量搜索失败: {search_error}")
            
            # 如果向量搜索失败，回退到文本搜索
            text_results = []
            text_contexts = []  # 收集文本搜索的上下文
            query_lower = request.query.lower()
            main_source = min(collection_sources, key=lambda s: len(s.url))
            
            for chunk in chunks[:request.top_k]:  # 限制返回数量
                if query_lower in chunk.content.lower():
                    source = source_map.get(chunk.source_id)
                    text_results.append({
                        "chunk_id": chunk.chunk_id,
                        "content": chunk.content[:500] + "..." if len(chunk.content) > 500 else chunk.content,
                        "score": 0.5,  # 文本匹配的默认分数
                        "source_url": source.url if source else "Unknown",
                        "source_title": source.title if source else "Unknown"
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
                message=f"在Collection '{main_source.title}' 中通过文本匹配找到 {len(text_results)} 个结果（向量搜索不可用）",
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
        
        # 获取该collection下的所有sources
        all_sources_stmt = select(Source).where(Source.session_id == FIXED_SESSION_ID)
        all_sources_result = await db.execute(all_sources_stmt)
        all_sources = all_sources_result.scalars().all()
        
        # 找到属于指定collection的所有sources
        collection_sources = []
        for source in all_sources:
            parent_url = determine_parent_url(source.url)
            parent_url_hash = hashlib.md5(parent_url.encode()).hexdigest()[:8]
            collection_name = f"collection_{parent_url_hash}"
            
            if collection_name == collection_id:
                collection_sources.append(source)
        
        if not collection_sources:
            raise HTTPException(
                status_code=404, 
                detail=f"Collection ID {collection_id} 不存在"
            )
        
        # 统计该collection所有sources的chunks数量
        source_ids = [s.id for s in collection_sources]
        chunks_count_stmt = select(Chunk).where(
            Chunk.source_id.in_(source_ids),
            Chunk.session_id == FIXED_SESSION_ID
        )
        chunks_result = await db.execute(chunks_count_stmt)
        chunks = chunks_result.scalars().all()
        chunks_count = len(chunks)
        
        # 找到主文档（URL最短的通常是父文档）
        main_source = min(collection_sources, key=lambda s: len(s.url))
        
        return {
            "success": True,
            "collection": {
                "collection_id": collection_id,
                "collection_name": collection_id,
                "document_title": f"{main_source.title} ({len(collection_sources)}个文档)",
                "url": main_source.url,
                "chunks_count": chunks_count,
                "source_count": len(collection_sources),
                "created_at": main_source.created_at.isoformat() if hasattr(main_source, 'created_at') and main_source.created_at else None
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        error_message = f"获取Collection详情失败: {e.__class__.__name__}: {str(e)}"
        print(error_message)
        raise HTTPException(status_code=500, detail=error_message)


@router.delete("/collections/{collection_id}", summary="删除指定的Collection")
async def delete_collection(
    collection_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    删除指定的collection，包括相关的source和chunks数据
    """
    try:
        FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
        
        # 根据ID类型删除：
        # - 如果是数值（老格式）：删除该source
        # - 如果是分组ID（如 collection_xxx）：删除该分组下所有sources
        sources_to_delete = []
        if collection_id.isdigit():
            source_stmt = select(Source).where(
                Source.id == int(collection_id),
                Source.session_id == FIXED_SESSION_ID
            )
            source_result = await db.execute(source_stmt)
            source = source_result.scalar_one_or_none()
            if not source:
                raise HTTPException(status_code=404, detail=f"Collection ID {collection_id} 不存在")
            sources_to_delete = [source]
        else:
            # 分组删除：找到所有属于该collection_id的sources
            all_stmt = select(Source).where(Source.session_id == FIXED_SESSION_ID)
            all_result = await db.execute(all_stmt)
            all_sources = all_result.scalars().all()

            from urllib.parse import urlparse
            def determine_parent_url(url: str) -> str:
                parsed = urlparse(url)
                parts = [p for p in parsed.path.split('/') if p]
                if 'docs' in parts and len(parts) >= 2:
                    return f"{parsed.scheme}://{parsed.netloc}/{'/'.join(parts[:2])}"
                if len(parts) > 2:
                    return f"{parsed.scheme}://{parsed.netloc}/{'/'.join(parts[:2])}"
                return url

            import hashlib
            for s in all_sources:
                parent = determine_parent_url(s.url)
                parent_hash = hashlib.md5(parent.encode()).hexdigest()[:8]
                name = f"collection_{parent_hash}"
                if name == collection_id:
                    sources_to_delete.append(s)

            if not sources_to_delete:
                raise HTTPException(status_code=404, detail=f"Collection ID {collection_id} 不存在")

        # 删除相关chunks与sources
        deleted_chunks = 0
        for src in sources_to_delete:
            chunks_stmt = select(Chunk).where(
                Chunk.source_id == src.id,
                Chunk.session_id == FIXED_SESSION_ID
            )
            chunks_result = await db.execute(chunks_stmt)
            chunks = chunks_result.scalars().all()
            for chunk in chunks:
                await db.delete(chunk)
            deleted_chunks += len(chunks)
            await db.delete(src)
        
        # 提交事务
        await db.commit()
        
        return {
            "success": True,
            "message": f"Collection '{collection_id}' 已成功删除",
            "deleted_chunks_count": deleted_chunks
        }
    
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        error_message = f"删除Collection失败: {e.__class__.__name__}: {str(e)}"
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
            # 兼容字符串型分组ID（collection_xxx）与数值ID
            from urllib.parse import urlparse
            import hashlib
            if request.collection_id.isdigit():
                source_stmt = select(Source).where(
                    Source.id == int(request.collection_id),
                    Source.session_id == FIXED_SESSION_ID
                )
                source_result = await db.execute(source_stmt)
                sources = [s for s in [source_result.scalar_one_or_none()] if s]
            else:
                # 根据分组ID收集sources
                all_stmt = select(Source).where(Source.session_id == FIXED_SESSION_ID)
                all_result = await db.execute(all_stmt)
                all_sources = all_result.scalars().all()

                def determine_parent_url(url: str) -> str:
                    parsed = urlparse(url)
                    parts = [p for p in parsed.path.split('/') if p]
                    if 'docs' in parts and len(parts) >= 2:
                        return f"{parsed.scheme}://{parsed.netloc}/{'/'.join(parts[:2])}"
                    if len(parts) > 2:
                        return f"{parsed.scheme}://{parsed.netloc}/{'/'.join(parts[:2])}"
                    return url

                sources = []
                for s in all_sources:
                    parent = determine_parent_url(s.url)
                    parent_hash = hashlib.md5(parent.encode()).hexdigest()[:8]
                    name = f"collection_{parent_hash}"
                    if name == request.collection_id:
                        sources.append(s)

            # 统一命名，避免后续与事件payload的'sources'键冲突
            collection_sources = sources

            if not collection_sources:
                error_data = {"error": f"Collection ID {request.collection_id} 不存在", "type": "error"}
                yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                return
            
            # 查询该集合下的所有chunks
            source_ids = [s.id for s in collection_sources]
            chunks_stmt = select(Chunk).where(
                Chunk.source_id.in_(source_ids),
                Chunk.session_id == FIXED_SESSION_ID
            )
            chunks_result = await db.execute(chunks_stmt)
            chunks = chunks_result.scalars().all()
            
            if not chunks:
                no_content_data = {"message": f"Collection '{request.collection_id}' 中没有找到任何内容块", "type": "message"}
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
                        source_ids=source_ids,
                        db=db
                    )
                    
                    # 收集搜索结果和上下文
                    for chunk, score in search_hits:
                        search_results.append({
                            "chunk_id": chunk.chunk_id,
                            "content": chunk.content[:300] + "..." if len(chunk.content) > 300 else chunk.content,
                            "score": float(score),
                            "source_url": next((s.url for s in collection_sources if s.id == chunk.source_id), "Unknown"),
                            "source_title": next((s.title for s in collection_sources if s.id == chunk.source_id), "Unknown")
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
                            "source_url": next((s.url for s in collection_sources if s.id == chunk.source_id), "Unknown"),
                            "source_title": next((s.title for s in collection_sources if s.id == chunk.source_id), "Unknown")
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
                    event_sources = []
                    for result in search_results:
                        event_sources.append({
                            "url": result.get("source_url", ""),
                            "title": result.get("source_title", ""),
                            "content": result["content"] if len(result["content"]) <= 300 else result["content"][:300] + "...",
                            "score": result["score"]
                        })
                    yield f"data: {json.dumps({'type': 'sources', 'sources': event_sources}, ensure_ascii=False)}\n\n"
                    
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
