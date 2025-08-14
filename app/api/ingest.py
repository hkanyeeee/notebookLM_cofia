import asyncio
import json
from typing import List

from fastapi import APIRouter, Body, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..models import Source, Chunk
from ..database import get_db
from ..fetch_parse import fetch_then_extract
from ..chunking import chunk_text
from ..embedding_client import embed_texts, DEFAULT_EMBEDDING_MODEL
from ..vector_db_client import add_embeddings
from ..config import EMBEDDING_MAX_CONCURRENCY, EMBEDDING_BATCH_SIZE
from . import get_session_id


router = APIRouter()


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

        title = url.split('/')[-1] or url

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

        chunk_objects = []
        for index, text in enumerate(chunks):
            chunk_obj = Chunk(
                chunk_id=str(index),
                content=text, 
                source_id=source.id, 
                session_id=session_id
            )
            chunk_objects.append(chunk_obj)
        
        db.add_all(chunk_objects)
        await db.flush()
        # 提前提交，缩短事务占用时间，避免长时间写锁
        await db.commit()

        # 5. 并发地进行嵌入与落库（按批并发、完成即写入并推送进度）
        MAX_PARALLEL = int(EMBEDDING_MAX_CONCURRENCY)
        BATCH_SIZE = int(EMBEDDING_BATCH_SIZE)

        # 分批构造任务：每个任务只发起一次 /embeddings 请求（将 batch_size 传为该批大小）
        chunk_batches = [
            chunk_objects[i: i + BATCH_SIZE]
            for i in range(0, len(chunk_objects), BATCH_SIZE)
        ]

        sem = asyncio.Semaphore(MAX_PARALLEL)

        async def embed_batch_worker(batch_index: int, batch_chunks: List[Chunk]):
            async with sem:
                texts = [c.content for c in batch_chunks]
                # 让每个任务只发一次请求
                embeddings = await embed_texts(
                    texts,
                    model=embedding_model,
                    batch_size=len(texts),
                    dimensions=embedding_dimensions,
                )
                return batch_index, embeddings

        tasks = [
            asyncio.create_task(embed_batch_worker(idx, batch))
            for idx, batch in enumerate(chunk_batches)
        ]

        completed = 0
        for coro in asyncio.as_completed(tasks):
            try:
                batch_index, embeddings = await coro
                batch_chunks = chunk_batches[batch_index]
                if not embeddings or len(embeddings) != len(batch_chunks):
                    # 本批失败或数量不一致：跳过并记录
                    print(
                        f"Embedding batch {batch_index} failed or size mismatch: got {len(embeddings) if embeddings else 0}, expected {len(batch_chunks)}"
                    )
                    continue

                # 将该批结果写入向量库
                await add_embeddings(source.id, batch_chunks, embeddings)

                # 推送每条完成的进度
                for _ in batch_chunks:
                    completed += 1
                    yield f"data: {json.dumps({'type': 'progress', 'value': completed})}\n\n"
                    await asyncio.sleep(0.005)
            except Exception as e:
                print(f"Embedding task failed: {e}")
                # 不中断整体流程，继续其他批次

        await db.commit()

        yield f"data: {json.dumps({'type': 'complete', 'document_id': str(source.id), 'title': title, 'message': f'Successfully ingested {total_chunks} chunks.'})}\n\n"

    except Exception as e:
        await db.rollback()
        error_message = f"Ingestion failed: {e.__class__.__name__}: {str(e)}"
        yield f"data: {json.dumps({'type': 'error', 'message': error_message})}\n\n"


@router.post("/ingest", summary="Ingest a document from a URL and stream progress")
async def ingest(
    data: dict = Body(...),
    session_id: str = Depends(get_session_id),
    db: AsyncSession = Depends(get_db),
):
    return StreamingResponse(
        stream_ingest_progress(data, session_id, db),
        media_type="text/event-stream",
    )
