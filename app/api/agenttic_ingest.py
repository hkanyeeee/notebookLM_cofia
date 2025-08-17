import asyncio
import json
import hashlib
from typing import List
import httpx

from fastapi import APIRouter, Body, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..models import Source, Chunk
from ..database import get_db
from ..fetch_parse import fetch_then_extract
from ..chunking import chunk_text
from ..embedding_client import embed_texts, DEFAULT_EMBEDDING_MODEL
from ..llm_client import generate_answer
from ..config import EMBEDDING_MAX_CONCURRENCY, EMBEDDING_BATCH_SIZE
from . import get_session_id


router = APIRouter()


async def generate_document_names(url: str) -> dict:
    """
    使用大模型为文档和collection生成名称
    """
    prompt = f"""
请为以下URL的文档生成合适的中文名称和英文collection名称：

URL: {url}

请返回JSON格式，包含：
1. document_name: 文档的中文名称（简洁明了，适合显示给用户）
2. collection_name: 向量库collection的英文名称（小写，用下划线连接，适合作为数据库名称）

示例格式：
{{"document_name": "机器学习入门指南", "collection_name": "machine_learning_guide"}}
"""
    
    try:
        response = await generate_answer(prompt, [], "qwen3-30b-a3b-thinking-2507-mlx")
        # 尝试解析JSON
        import re
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return result
        else:
            # 如果无法解析，使用默认名称
            return {
                "document_name": url.split('/')[-1] or "未命名文档",
                "collection_name": f"doc_{hashlib.md5(url.encode()).hexdigest()[:8]}"
            }
    except Exception as e:
        print(f"生成文档名称失败: {e}")
        return {
            "document_name": url.split('/')[-1] or "未命名文档",
            "collection_name": f"doc_{hashlib.md5(url.encode()).hexdigest()[:8]}"
        }


async def add_embeddings_to_collection(
    collection_name: str, 
    source_id: int, 
    chunks: List[Chunk], 
    embeddings: List[List[float]]
):
    """
    将embeddings添加到指定collection
    """
    from ..vector_db_client import qdrant_client, models
    
    if not qdrant_client:
        raise ConnectionError("Qdrant客户端不可用")
    if not chunks:
        return

    vector_size = len(embeddings[0])
    
    # 确保collection存在，如果不存在则创建
    try:
        qdrant_client.get_collection(collection_name=collection_name)
        qdrant_client.update_collection(
            collection_name=collection_name,
            hnsw_config=models.HnswConfigDiff(m=64, ef_construct=512),
        )
    except Exception:
        print(f"Collection '{collection_name}' 不存在，正在创建。")
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            hnsw_config=models.HnswConfigDiff(m=64, ef_construct=512),
        )
        print(f"Collection '{collection_name}' 创建成功。")
    
    points = [
        models.PointStruct(
            id=chunk.id, 
            vector=embedding,
            payload={
                "session_id": chunk.session_id,
                "source_id": chunk.source_id,
                "content": chunk.content,
                "chunk_id": chunk.chunk_id
            }
        )
        for chunk, embedding in zip(chunks, embeddings) if chunk.id is not None
    ]

    if not points:
        print("没有要添加的点。")
        return

    qdrant_client.upsert(
        collection_name=collection_name,
        points=points,
        wait=True 
    )


async def send_webhook(webhook_url: str, data: dict):
    """
    发送webhook到指定URL
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(webhook_url, json=data)
            response.raise_for_status()
            print(f"Webhook发送成功: {response.status_code}")
    except Exception as e:
        print(f"Webhook发送失败: {e}")


@router.post("/agenttic-ingest", summary="智能文档摄取接口")
async def agenttic_ingest(
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """
    智能文档摄取接口：
    1. 获取URL并使用大模型生成文档名称和collection名称
    2. 拉取并处理内容
    3. 创建新的向量库collection存储
    4. 发送webhook通知
    """
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL必须提供")

    embedding_model = data.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions = data.get("embedding_dimensions", 1024)
    webhook_url = "http://192.168.31.125:5678/webhook-test/2d06e4c8-d45b-4ea1-b81b-bdf460c28f48"

    try:
        # 1. 使用大模型生成文档名称和collection名称
        print("正在生成文档名称...")
        names = await generate_document_names(url)
        document_name = names["document_name"]
        collection_name = names["collection_name"]
        
        print(f"文档名称: {document_name}")
        print(f"Collection名称: {collection_name}")

        # 2. 检查数据库中是否已存在该URL
        # 使用固定session_id值，因为我们不需要会话上下文
        FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
        stmt = select(Source).where(Source.url == url, Source.session_id == FIXED_SESSION_ID)
        result = await db.execute(stmt)
        existing_source = result.scalars().first()
        if existing_source:
            return {
                "success": True,
                "message": "文档已存在",
                "document_id": str(existing_source.id),
                "document_name": existing_source.title,
                "collection_name": collection_name
            }

        # 3. 拉取并解析内容
        print("正在拉取网页内容...")
        text = await fetch_then_extract(url)

        # 4. 分块处理文本
        print("正在分块处理文本...")
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("无法从URL中提取任何内容")

        total_chunks = len(chunks)
        print(f"总共生成了 {total_chunks} 个文本块")

        # 5. 创建Source和Chunk对象并存储到数据库
        # 使用固定session_id值，因为我们不需要会话上下文
        FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
        source = Source(url=url, title=document_name, session_id=FIXED_SESSION_ID)
        db.add(source)
        await db.flush()

        chunk_objects = []
        for index, chunkT in enumerate(chunks):
            # 生成唯一的chunk_id
            raw = f"{FIXED_SESSION_ID}|{url}|{index}".encode("utf-8", errors="ignore")
            generated_chunk_id = hashlib.md5(raw).hexdigest()
            chunk_obj = Chunk(
                chunk_id=generated_chunk_id,
                content=chunkT,
                source_id=source.id,
                session_id=FIXED_SESSION_ID,
            )
            chunk_objects.append(chunk_obj)
        
        db.add_all(chunk_objects)
        await db.flush()
        await db.commit()

        # 6. 生成embeddings并存储到新的collection
        print("正在生成embeddings...")
        MAX_PARALLEL = int(EMBEDDING_MAX_CONCURRENCY)
        BATCH_SIZE = int(EMBEDDING_BATCH_SIZE)

        chunk_batches = [
            chunk_objects[i: i + BATCH_SIZE]
            for i in range(0, len(chunk_objects), BATCH_SIZE)
        ]

        sem = asyncio.Semaphore(MAX_PARALLEL)

        async def embed_batch_worker(batch_index: int, batch_chunks: List[Chunk]):
            async with sem:
                texts = [c.content for c in batch_chunks]
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
                    print(f"Embedding批次 {batch_index} 失败或数量不匹配")
                    continue

                # 将该批结果写入指定的collection
                await add_embeddings_to_collection(collection_name, source.id, batch_chunks, embeddings)

                completed += len(batch_chunks)
                print(f"已完成 {completed}/{total_chunks} 个chunks")
                
            except Exception as e:
                print(f"Embedding任务失败: {e}")
                continue

        await db.commit()

        # 7. 准备webhook数据
        # 使用固定session_id值，因为我们不需要会话上下文
        FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
        webhook_data = {
            "document_name": document_name,
            "collection_name": collection_name,
            "url": url,
            "total_chunks": total_chunks,
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                    "index": idx
                }
                for idx, chunk in enumerate(chunk_objects)
            ],
            "source_id": str(source.id),
            "session_id": FIXED_SESSION_ID
        }

        # 8. 发送webhook
        print("正在发送webhook...")
        await send_webhook(webhook_url, webhook_data)

        return {
            "success": True,
            "message": f"成功摄取文档，共处理了 {total_chunks} 个文本块",
            "document_id": str(source.id),
            "document_name": document_name,
            "collection_name": collection_name,
            "total_chunks": total_chunks
        }

    except Exception as e:
        await db.rollback()
        error_message = f"摄取失败: {e.__class__.__name__}: {str(e)}"
        print(error_message)
        raise HTTPException(status_code=500, detail=error_message)
