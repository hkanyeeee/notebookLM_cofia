from fastapi import APIRouter, HTTPException, Body, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import List, Dict, Any, Optional
import json
import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Source, Chunk
from ..embedding_client import embed_texts
from ..vector_db_client import add_embeddings, qdrant_client, COLLECTION_NAME
from ..config import EMBEDDING_BATCH_SIZE, EMBEDDING_DIMENSIONS, DEFAULT_EMBEDDING_MODEL
from . import get_session_id

router = APIRouter()


class VectorFixStatus:
    """向量修复状态管理"""
    
    def __init__(self):
        self.active_tasks: Dict[str, Dict] = {}
    
    def start_task(self, task_id: str, total_collections: int):
        """开始任务"""
        self.active_tasks[task_id] = {
            'status': 'running',
            'total_collections': total_collections,
            'completed_collections': 0,
            'current_collection': None,
            'total_chunks': 0,
            'processed_chunks': 0,
            'errors': 0
        }
    
    def update_task(self, task_id: str, **kwargs):
        """更新任务状态"""
        if task_id in self.active_tasks:
            self.active_tasks[task_id].update(kwargs)
    
    def complete_task(self, task_id: str):
        """完成任务"""
        if task_id in self.active_tasks:
            self.active_tasks[task_id]['status'] = 'completed'
    
    def fail_task(self, task_id: str, error: str):
        """任务失败"""
        if task_id in self.active_tasks:
            self.active_tasks[task_id].update({
                'status': 'failed',
                'error': error
            })
    
    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        return self.active_tasks.get(task_id)


# 全局状态管理器
fix_status = VectorFixStatus()


async def get_collections_info(session_id: str, db: AsyncSession) -> List[Dict[str, Any]]:
    """获取所有集合信息"""
    try:
        # 使用固定的session_id，与agenttic_ingest保持一致
        FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
        
        # 获取所有Source
        sources_stmt = select(Source).where(Source.session_id == FIXED_SESSION_ID)
        sources_result = await db.execute(sources_stmt)
        sources = sources_result.scalars().all()

        collections = []
        for source in sources:
            # 获取每个source的chunks数量
            chunks_stmt = select(Chunk).where(
                Chunk.source_id == source.id,
                Chunk.session_id == FIXED_SESSION_ID
            )
            chunks_result = await db.execute(chunks_stmt)
            chunks_count = len(chunks_result.scalars().all())

            # 检查Qdrant中是否已有向量数据
            try:
                # 使用count API获取精确的向量数量
                count_result = qdrant_client.count(
                    collection_name=COLLECTION_NAME,
                    count_filter={
                        "must": [
                            {"key": "source_id", "match": {"value": source.id}},
                            {"key": "session_id", "match": {"value": FIXED_SESSION_ID}}
                        ]
                    }
                )
                qdrant_count = count_result.count
            except Exception as e:
                print(f"获取Qdrant计数失败: {e}")
                qdrant_count = 0

            collections.append({
                'id': source.id,
                'title': source.title,
                'chunks_count': chunks_count,
                'qdrant_count': qdrant_count,
                'needs_fix': chunks_count > 0 and qdrant_count == 0,
                'status': 'complete' if chunks_count == qdrant_count else ('missing' if qdrant_count == 0 else 'partial')
            })

        return collections

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取集合信息失败: {str(e)}")


async def fix_collection_vectors(
    collection_id: int, 
    session_id: str, 
    db: AsyncSession,
    task_id: str = None
) -> bool:
    """修复指定集合的向量数据"""
    try:
        # 使用固定的session_id，与agenttic_ingest保持一致
        FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
        
        # 1. 获取Collection信息
        source_stmt = select(Source).where(
            Source.id == collection_id,
            Source.session_id == FIXED_SESSION_ID
        )
        source_result = await db.execute(source_stmt)
        source = source_result.scalar_one_or_none()

        if not source:
            return False

        if task_id:
            fix_status.update_task(task_id, current_collection=source.title)

        # 2. 获取所有chunks
        chunks_stmt = select(Chunk).where(
            Chunk.source_id == source.id,
            Chunk.session_id == FIXED_SESSION_ID
        )
        chunks_result = await db.execute(chunks_stmt)
        chunks = chunks_result.scalars().all()

        if not chunks:
            return False

        if task_id:
            fix_status.update_task(task_id, total_chunks=fix_status.active_tasks[task_id]['total_chunks'] + len(chunks))

        # 3. 分批处理embeddings
        batch_size = EMBEDDING_BATCH_SIZE
        total_batches = (len(chunks) + batch_size - 1) // batch_size

        for batch_index in range(total_batches):
            start_idx = batch_index * batch_size
            end_idx = min((batch_index + 1) * batch_size, len(chunks))
            batch_chunks = chunks[start_idx:end_idx]

            # 提取文本内容
            batch_texts = [chunk.content for chunk in batch_chunks]

            try:
                # 生成embeddings
                embeddings = await embed_texts(
                    texts=batch_texts,
                    model=DEFAULT_EMBEDDING_MODEL,
                    batch_size=EMBEDDING_BATCH_SIZE,
                    dimensions=EMBEDDING_DIMENSIONS
                )

                if not embeddings or len(embeddings) != len(batch_chunks):
                    if task_id:
                        fix_status.update_task(task_id, errors=fix_status.active_tasks[task_id]['errors'] + 1)
                    continue

                # 存储到Qdrant
                await add_embeddings(source.id, batch_chunks, embeddings)
                
                if task_id:
                    current_processed = fix_status.active_tasks[task_id]['processed_chunks'] + len(batch_chunks)
                    fix_status.update_task(task_id, processed_chunks=current_processed)

            except Exception as e:
                if task_id:
                    fix_status.update_task(task_id, errors=fix_status.active_tasks[task_id]['errors'] + 1)
                continue

        if task_id:
            completed = fix_status.active_tasks[task_id]['completed_collections'] + 1
            fix_status.update_task(task_id, completed_collections=completed)

        return True

    except Exception as e:
        if task_id:
            fix_status.update_task(task_id, errors=fix_status.active_tasks[task_id]['errors'] + 1)
        return False


async def stream_fix_progress(task_id: str):
    """流式返回修复进度"""
    while True:
        status = fix_status.get_task_status(task_id)
        if not status:
            break
            
        # 发送当前状态
        yield f"data: {json.dumps(status)}\n\n"
        
        # 如果任务完成或失败，结束流
        if status['status'] in ['completed', 'failed']:
            break
            
        await asyncio.sleep(1)  # 每秒更新一次


@router.get("/vector-fix/collections/status", summary="获取所有集合的向量数据状态")
async def get_collections_status(
    session_id: str = Depends(get_session_id),
    db: AsyncSession = Depends(get_db)
):
    """获取所有集合的向量数据状态"""
    try:
        collections = await get_collections_info(session_id, db)
        
        # 统计信息
        total_collections = len(collections)
        needs_fix = len([c for c in collections if c['needs_fix']])
        total_chunks = sum(c['chunks_count'] for c in collections)
        missing_vectors = sum(c['chunks_count'] - c['qdrant_count'] for c in collections if c['chunks_count'] > c['qdrant_count'])
        
        return {
            'success': True,
            'collections': collections,
            'stats': {
                'total_collections': total_collections,
                'needs_fix': needs_fix,
                'total_chunks': total_chunks,
                'missing_vectors': missing_vectors
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vector-fix/collections/{collection_id}/fix", summary="修复指定集合的向量数据")
async def fix_collection(
    collection_id: int,
    background_tasks: BackgroundTasks,
    session_id: str = Depends(get_session_id),
    db: AsyncSession = Depends(get_db)
):
    """修复指定集合的向量数据"""
    import uuid
    task_id = str(uuid.uuid4())
    
    # 初始化任务状态
    fix_status.start_task(task_id, 1)
    
    # 添加后台任务
    async def fix_task():
        try:
            success = await fix_collection_vectors(collection_id, session_id, db, task_id)
            if success:
                fix_status.complete_task(task_id)
            else:
                fix_status.fail_task(task_id, f"Collection {collection_id} 修复失败")
        except Exception as e:
            fix_status.fail_task(task_id, str(e))
    
    background_tasks.add_task(fix_task)
    
    return {
        'success': True,
        'task_id': task_id,
        'message': f'Collection {collection_id} 向量数据修复已开始'
    }


@router.post("/vector-fix/collections/fix-all", summary="修复所有需要修复的集合")
async def fix_all_collections(
    background_tasks: BackgroundTasks,
    session_id: str = Depends(get_session_id),
    db: AsyncSession = Depends(get_db)
):
    """修复所有需要修复的集合"""
    import uuid
    task_id = str(uuid.uuid4())
    
    try:
        # 获取需要修复的集合
        collections = await get_collections_info(session_id, db)
        need_fix = [c for c in collections if c['needs_fix']]
        
        if not need_fix:
            return {
                'success': True,
                'message': '所有集合都已有向量数据，无需修复'
            }
        
        # 初始化任务状态
        fix_status.start_task(task_id, len(need_fix))
        
        # 添加后台任务
        async def fix_all_task():
            try:
                for collection in need_fix:
                    await fix_collection_vectors(collection['id'], session_id, db, task_id)
                fix_status.complete_task(task_id)
            except Exception as e:
                fix_status.fail_task(task_id, str(e))
        
        background_tasks.add_task(fix_all_task)
        
        return {
            'success': True,
            'task_id': task_id,
            'message': f'开始修复 {len(need_fix)} 个集合的向量数据'
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vector-fix/progress/{task_id}", summary="获取修复进度（流式）")
async def get_fix_progress(
    task_id: str,
    session_id: Optional[str] = None  # 通过URL参数传递，因为EventSource不支持自定义headers
):
    """获取修复进度的流式响应"""
    # EventSource无法传递自定义headers，这里暂时不强制要求session_id
    # 但建议前端通过URL参数传递用于日志记录和权限验证
    if session_id:
        print(f"进度查询 - Session ID: {session_id}, Task ID: {task_id}")
    
    return StreamingResponse(
        stream_fix_progress(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.get("/vector-fix/status/{task_id}", summary="获取修复任务状态")
async def get_fix_status(
    task_id: str,
    session_id: str = Depends(get_session_id)
):
    """获取修复任务的当前状态"""
    print(f"状态查询 - Session ID: {session_id}, Task ID: {task_id}")
    
    status = fix_status.get_task_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return {
        'success': True,
        'status': status
    }


@router.post("/vector-fix/collections/{collection_id}/verify", summary="验证集合的向量数据")
async def verify_collection(
    collection_id: int,
    session_id: str = Depends(get_session_id),
    db: AsyncSession = Depends(get_db)
):
    """验证指定集合的向量数据完整性"""
    try:
        # 使用固定的session_id，与agenttic_ingest保持一致
        FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
        
        result = {
            'collection_id': collection_id,
            'db_chunks': 0,
            'qdrant_points': 0,
            'status': 'unknown'
        }

        # 获取数据库中的chunks数量
        chunks_stmt = select(Chunk).where(
            Chunk.source_id == collection_id,
            Chunk.session_id == FIXED_SESSION_ID
        )
        chunks_result = await db.execute(chunks_stmt)
        chunks = chunks_result.scalars().all()
        result['db_chunks'] = len(chunks)

        # 获取Qdrant中的数据
        try:
            # 使用count API获取精确计数
            count_result = qdrant_client.count(
                collection_name=COLLECTION_NAME,
                count_filter={
                    "must": [
                        {"key": "source_id", "match": {"value": collection_id}},
                        {"key": "session_id", "match": {"value": FIXED_SESSION_ID}}
                    ]
                }
            )
            result['qdrant_points'] = count_result.count
        except Exception as e:
            print(f"获取Qdrant计数失败: {e}")
            result['qdrant_points'] = 0

        if result['db_chunks'] == result['qdrant_points']:
            result['status'] = 'complete'
        elif result['qdrant_points'] == 0:
            result['status'] = 'missing'
        else:
            result['status'] = 'partial'

        # 获取样本数据
        if result['qdrant_points'] > 0:
            try:
                sample_result = qdrant_client.scroll(
                    collection_name=COLLECTION_NAME,
                    scroll_filter={
                        "must": [
                            {"key": "source_id", "match": {"value": collection_id}},
                            {"key": "session_id", "match": {"value": FIXED_SESSION_ID}}
                        ]
                    },
                    limit=3,
                    with_payload=True
                )
                
                result['samples'] = []
                for point in sample_result[0]:
                    content_preview = point.payload.get('content', '')[:80] + "..."
                    result['samples'].append({
                        'id': point.id,
                        'content_preview': content_preview
                    })
            except Exception as e:
                print(f"获取样本数据失败: {e}")
                result['samples'] = []

        return {
            'success': True,
            'result': result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"验证失败: {str(e)}")
