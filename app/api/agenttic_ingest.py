import json
import hashlib
from typing import List, Optional
import httpx
import asyncio

from fastapi import APIRouter, Body, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..models import Source, Chunk
from ..database import get_db
from ..fetch_parse import fetch_then_extract, fetch_html
from ..chunking import chunk_text
from ..embedding_client import embed_texts, DEFAULT_EMBEDDING_MODEL
from ..config import WEBHOOK_TIMEOUT, WEBHOOK_PREFIX, EMBEDDING_MAX_CONCURRENCY, EMBEDDING_BATCH_SIZE
from ..vector_db_client import add_embeddings


router = APIRouter()


class WebhookResponseData(BaseModel):
    """用于验证webhook返回数据结构的模型"""
    document_name: str
    collection_name: str
    url: str
    total_chunks: int
    chunks: List[dict]
    source_id: str
    session_id: str
    task_name: str


class UnifiedIngestRequest(BaseModel):
    """统一的摄取请求模型，支持客户端请求和webhook回调"""
    # 客户端请求必需字段
    url: str
    
    # 客户端请求可选字段
    embedding_model: Optional[str] = None
    embedding_dimensions: Optional[int] = None
    webhook_url: Optional[str] = None
    recursive_depth: Optional[int] = None
    
    # webhook回调专有字段
    document_name: Optional[str] = None
    collection_name: Optional[str] = None
    total_chunks: Optional[int] = None
    chunks: Optional[List[dict]] = None
    source_id: Optional[str] = None
    session_id: Optional[str] = None
    task_name: Optional[str] = None


async def process_webhook_response(
    data: WebhookResponseData,
    db: AsyncSession
):
    """
    处理webhook回调数据的专用函数
    """
    print("处理webhook响应数据...")
    print(f"任务名称: {data.task_name}")
    print(f"文档名称: {data.document_name}")
    print(f"Collection名称: {data.collection_name}")
    print(f"总块数: {data.total_chunks}")
    
    # 检查任务名称
    if data.task_name != "agenttic_ingest":
        return {
            "message": f"不支持的任务类型: {data.task_name}",
            "task_name": data.task_name,
            "success": False
        }
    
    # TODO: 在这里实现递归摄取逻辑
    # 根据webhook响应中的子文档URL进行递归处理
    
    return {
        "message": "Webhook响应处理成功",
        "task_name": data.task_name,
        "document_name": data.document_name,
        "success": True
    }


async def generate_document_names(url: str) -> dict:
    """
    使用大模型为文档和collection生成名称
    """
    # 创建一个专门用于文档名称生成的提示模板，避免使用query接口中的generate_answer函数
    # 通过调用llm_client的底层API实现，而不是复用generate_answer函数
    import httpx
    from ..config import LLM_SERVICE_URL
    
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
        # 使用LLM服务的底层API直接调用，绕过generate_answer函数
        url = f"{LLM_SERVICE_URL}/chat/completions"
        
        payload = {
            "model": "qwen3-30b-a3b-thinking-2507-mlx",
            "messages": [
                {"role": "system", "content": "你是一个文档名称生成助手，专门负责为网页内容生成合适的中文标题和英文collection名称。"},
                {"role": "user", "content": prompt},
            ],
        }

        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            # 获取模型返回的内容
            message = (data.get("choices") or [{}])[0].get("message", {})
            response_content = message.get("content") or ""
            
            # 尝试解析JSON
            import re
            json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
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


@router.post("/agenttic-ingest", summary="智能文档摄取接口（统一处理客户端请求和webhook回调）")
async def agenttic_ingest(
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    统一的智能文档摄取接口：
    - 客户端请求：获取URL并使用大模型生成文档名称和collection名称，拉取并处理内容，创建新的向量库collection存储，发送webhook通知
    - webhook回调：处理工作流响应数据并执行递归摄取逻辑
    
    通过检测数据中是否包含 'chunks' 字段来判断请求类型
    """
    
    # 检测请求类型：如果包含 chunks 字段，说明是 webhook 回调
    is_webhook_callback = 'chunks' in data and 'task_name' in data
    
    if is_webhook_callback:
        # 处理 webhook 回调
        print("检测到webhook回调请求")
        try:
            webhook_data = WebhookResponseData(**data)
            return await process_webhook_response(webhook_data, db)
        except Exception as e:
            error_message = f"Webhook回调处理失败: {e.__class__.__name__}: {str(e)}"
            print(error_message)
            raise HTTPException(status_code=500, detail=error_message)
    
    # 处理客户端请求
    print("检测到客户端摄取请求")
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL必须提供")

    embedding_model = data.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions = data.get("embedding_dimensions", 1024)
    webhook_url = data.get("webhook_url", WEBHOOK_PREFIX + "/array2array")
    recursive_depth = data.get("recursive_depth", 1)  # 默认递归深度为1

    try:
        # 1. 使用大模型生成文档名称和collection名称
        print("正在生成文档名称...")
        names = await generate_document_names(url)
        document_name = names["document_name"]
        collection_name = names["collection_name"]
        
        print(f"文档名称: {document_name}")
        print(f"Collection名称: {collection_name}")

        # 2. 拉取并解析内容
        print("正在拉取网页内容...")
        text = await fetch_then_extract(url)
        raw_html = await fetch_html(url)

        # 3. 分块处理文本
        print("正在分块处理文本...")
        chunks = chunk_text(text)
        raw_html_chunks = chunk_text(raw_html)
        if not chunks:
            raise ValueError("无法从URL中提取任何内容")

        total_chunks = len(chunks)
        print(f"总共生成了 {total_chunks} 个文本块")

        # 4. 创建Source和Chunk对象
        FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
        
        # 创建Source对象
        source = Source(url=url, title=document_name, session_id=FIXED_SESSION_ID)
        
        # 创建Chunk对象列表
        chunk_objects = []
        for index, text in enumerate(chunks):
            # 生成唯一的chunk_id
            raw = f"{FIXED_SESSION_ID}|{url}|{index}".encode("utf-8", errors="ignore")
            generated_chunk_id = hashlib.md5(raw).hexdigest()
            chunk_obj = Chunk(
                chunk_id=generated_chunk_id,
                content=text,
                source_id=None,  # 在数据库中暂时不设置source_id
                session_id=FIXED_SESSION_ID,
            )
            chunk_objects.append(chunk_obj)
        
        # 创建raw_html_chunk对象列表
        raw_html_chunk_objects = []
        for index, html in enumerate(raw_html_chunks):
            # 生成唯一的chunk_id
            raw = f"{FIXED_SESSION_ID}|{url}|{index}".encode("utf-8", errors="ignore")
            generated_chunk_id = hashlib.md5(raw).hexdigest()
            raw_html_chunk_obj = Chunk(
                chunk_id=generated_chunk_id,
                content=html,
                source_id=None,  # 在数据库中暂时不设置source_id
                session_id=FIXED_SESSION_ID,
            )
            raw_html_chunk_objects.append(raw_html_chunk_obj)
        
        
        # 5. 将chunk对象保存到数据库
        print("正在保存chunk到数据库...")
        db.add(source)
        await db.flush()
        
        # 为每个chunk设置source_id
        for chunk in chunk_objects:
            chunk.source_id = source.id
        
        db.add_all(chunk_objects)
        await db.flush()
        # 提前提交，缩短事务占用时间，避免长时间写锁
        await db.commit()
        
        # 6. 为所有chunk生成嵌入向量并存储到Qdrant
        print("正在生成嵌入...")
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

        # 等待所有嵌入任务完成
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
            except Exception as e:
                print(f"Embedding task failed: {e}")
                # 不中断整体流程，继续其他批次

        # 7. 准备webhook数据
        import uuid
        from datetime import datetime
        
        # 生成request_id: url + 当前日期 + uuid
        # 对URL进行编码以处理特殊字符
        import urllib.parse
        encoded_url = urllib.parse.quote(url, safe=':/')
        request_id = f"{encoded_url}_{datetime.now().strftime('%Y%m%d')}_{str(uuid.uuid4())}"
        
        webhook_data = {
            "document_name": document_name,
            "collection_name": collection_name,
            "url": url,
            "total_chunks": total_chunks,
            "task_name": "agenttic_ingest",
            "prompt": 
            f"你正在阅读一个网页的部分html，这个网页的url是{url}，内容是某个开源框架文档。现在我需要你识别这个文档下面的的子文档。比如：https://lmstudio.ai/docs/python/getting-started/project-setup是https://lmstudio.ai/docs/python的子文档。子文档的URL有可能在HTML中以a标签的href，button的跳转link等等形式存在，你需要调用你的编程知识进行识别，使用{url}进行拼接。最终将识别出来的子文档URL以数组的形式放在sub_docs属性联合chunk_id、index返回，注意：如果没有发现任何子文档，那么返回空数组",
            "data_list": [
                {
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                    "index": idx
                }
                for idx, chunk in enumerate([raw_html_chunk_objects[0]])
                # for idx, chunk in enumerate(raw_html_chunk_objects)
            ],
            "request_id": request_id,
            "recursive_depth": recursive_depth,  # 添加递归深度参数
        }

        # 8. 发送webhook
        print("正在发送webhook...")
        # 直接向指定的webhook URL发送POST请求
        try:
            async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
                response = await client.post(webhook_url, json=webhook_data)
                response.raise_for_status()
                print("Webhook发送成功")
        except Exception as e:
            print(f"Webhook发送失败: {e}")

        return {
            "success": True,
            "message": f"成功摄取文档，共处理了 {total_chunks} 个文本块",
            "document_name": document_name,
            "collection_name": collection_name,
            "total_chunks": total_chunks
        }

    except Exception as e:
        error_message = f"摄取失败: {e.__class__.__name__}: {str(e)}"
        print(error_message)
        raise HTTPException(status_code=500, detail=error_message)


@router.post("/workflow_response", summary="工作流响应处理接口（兼容性端点）")
async def workflow_response(
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    工作流响应处理接口 - 兼容性端点
    此端点将请求重定向到统一的 agenttic_ingest 接口进行处理
    """
    print("收到workflow_response请求，重定向到统一处理接口")
    return await agenttic_ingest(data, db)
