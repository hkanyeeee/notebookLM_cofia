import json
import hashlib
import uuid
from typing import List, Optional
from datetime import datetime
import httpx
import asyncio

from fastapi import APIRouter, Body, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete

from ..models import Source, Chunk, WorkflowExecution
from ..database import get_db
from ..fetch_parse import fetch_then_extract, fetch_html
from ..utils.link_extractor import extract_links_from_html
from ..utils.task_status import ingest_task_manager, TaskStatus
from app.config import LLM_SERVICE_URL, DEFAULT_INGEST_MODEL, SUBDOC_MAX_CONCURRENCY
from ..chunking import chunk_text
from ..embedding_client import embed_texts, DEFAULT_EMBEDDING_MODEL
from ..config import WEBHOOK_TIMEOUT, WEBHOOK_PREFIX, EMBEDDING_MAX_CONCURRENCY, EMBEDDING_BATCH_SIZE, EMBEDDING_DIMENSIONS, SUBDOC_USE_WEBHOOK_FALLBACK
from ..vector_db_client import add_embeddings


router = APIRouter()


class WebhookResponseData(BaseModel):
    """用于验证webhook返回数据结构的模型"""
    document_name: str
    collection_name: str
    url: str
    total_chunks: int
    source_id: Optional[str] = None
    session_id: Optional[str] = None
    task_name: str
    output: Optional[List[dict]] = None  # 添加output字段以包含sub_docs
    recursive_depth: Optional[int] = 1  # 添加递归深度字段，默认为1
    request_id: Optional[str] = None  # 请求ID
    webhook_url: Optional[str] = None  # webhook URL
    is_recursive: Optional[bool] = False  # 添加递归标记字段，默认为False
    
    @field_validator('total_chunks', mode='before')
    @classmethod
    def validate_total_chunks(cls, v):
        """确保total_chunks是整数类型"""
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                raise ValueError(f"无法将total_chunks转换为整数: {v}")
        return v
        
    @field_validator('recursive_depth', mode='before')
    @classmethod
    def validate_recursive_depth(cls, v):
        """确保recursive_depth是整数类型"""
        if v is None:
            return 2  # 默认值
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                raise ValueError(f"无法将recursive_depth转换为整数: {v}")
        return v


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
    parent_source_id: Optional[int] = None  # 添加父级Source ID字段
    session_id: Optional[str] = None
    task_name: Optional[str] = None
    is_recursive: Optional[bool] = False  # 添加递归标记字段，默认为False


async def process_sub_docs_concurrent(
    sub_docs_urls: List[str],
    recursive_depth: int,
    db: AsyncSession,
    parent_doc_name: Optional[str] = None,
    parent_collection_name: Optional[str] = None,
    parent_source_id: Optional[int] = None
) -> List[dict]:
    """
    并发处理子文档的递归摄取函数

    Args:
        sub_docs_urls: 子文档URL列表
        recursive_depth: 递归深度限制
        db: 数据库会话
        parent_doc_name: 父级文档名称
        parent_collection_name: 父级collection名称
        parent_source_id: 父级Source ID，用于将子文档内容添加到同一个collection

    Returns:
        List[dict]: 每个子文档的处理结果
    """
    results = []
    
    # 检查递归深度限制
    if recursive_depth <= 0:
        print(f"达到递归深度限制，跳过 {len(sub_docs_urls)} 个子文档的处理")
        return results
    
    # 使用信号量控制并发数量 - 子文档处理使用更高的并发数
    MAX_CONCURRENT_SUB_DOCS = min(SUBDOC_MAX_CONCURRENCY, len(sub_docs_urls))  # 使用配置的并发数，但不超过子文档总数
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUB_DOCS)
    
    # 并发处理所有子文档URL
    async def process_single_sub_doc(sub_url: str, parent_doc_name: str = None, parent_collection_name: str = None, parent_source_id: int = None) -> dict:
        async with semaphore:  # 使用信号量控制并发
            try:
                print(f"开始递归摄取子文档: {sub_url}")

                # 构造递归调用的请求数据
                sub_request_data = {
                    "url": sub_url,
                    "recursive_depth": recursive_depth - 1,  # 减少递归深度
                    "embedding_model": DEFAULT_EMBEDDING_MODEL,
                    "embedding_dimensions": EMBEDDING_DIMENSIONS,
                    "webhook_url": WEBHOOK_PREFIX + "/array2array",
                    "is_recursive": True,  # 标记为递归调用
                    "document_name": parent_doc_name,  # 传递父级文档名称
                    "collection_name": parent_collection_name,  # 传递父级collection名称
                    "parent_source_id": parent_source_id  # 传递父级Source ID
                }
                
                # 创建一个虚拟的BackgroundTasks实例用于递归调用
                dummy_background_tasks = BackgroundTasks()
                
                # 调用本模块的agenttic_ingest函数进行递归处理，参数顺序要正确
                result = await agenttic_ingest(dummy_background_tasks, sub_request_data, db)
                
                print(f"子文档摄取成功: {sub_url}")
                return {
                    "url": sub_url,
                    "success": True,
                    "result": result
                }
                
            except Exception as e:
                error_msg = f"子文档摄取失败 {sub_url}: {str(e)}"
                print(error_msg)
                return {
                    "url": sub_url,
                    "success": False,
                    "error": error_msg
                }
    
    # 使用asyncio.gather进行并发处理，但通过信号量控制最大并发数
    try:
        tasks = [process_single_sub_doc(url, parent_doc_name, parent_collection_name, parent_source_id) for url in sub_docs_urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)
    except Exception as e:
        print(f"并发处理子文档时出现异常: {str(e)}")
        # 降级到串行处理
        results = []
        for sub_url in sub_docs_urls:
            result = await process_single_sub_doc(sub_url, parent_doc_name, parent_collection_name, parent_source_id)
            results.append(result)
    
    return results


async def process_sub_docs_concurrent_with_tracking(
    sub_docs_urls: List[str],
    recursive_depth: int,
    db: AsyncSession,
    parent_doc_name: Optional[str] = None,
    parent_collection_name: Optional[str] = None,
    parent_source_id: Optional[int] = None,
    task_id: Optional[str] = None
) -> List[dict]:
    """
    并发处理子文档的递归摄取函数（带状态追踪）
    """
    results = []
    
    # 检查递归深度限制
    if recursive_depth <= 0:
        print(f"达到递归深度限制，跳过 {len(sub_docs_urls)} 个子文档的处理")
        return results
    
    # 使用信号量控制并发数量 - 子文档处理使用更高的并发数
    MAX_CONCURRENT_SUB_DOCS = min(SUBDOC_MAX_CONCURRENCY, len(sub_docs_urls))  # 使用配置的并发数，但不超过子文档总数
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUB_DOCS)
    
    # 并发处理所有子文档URL
    async def process_single_sub_doc_with_tracking(sub_url: str) -> dict:
        async with semaphore:
            # 更新状态为运行中
            if task_id:
                await ingest_task_manager.update_sub_doc_status(task_id, sub_url, TaskStatus.RUNNING)
            
            # 🔥 修复：为每个子文档创建独立的数据库会话，避免事务冲突
            from ..database import AsyncSessionLocal
            async with AsyncSessionLocal() as sub_db:
                try:
                    print(f"开始递归摄取子文档: {sub_url}")

                    # 构造递归调用的请求数据
                    sub_request_data = {
                        "url": sub_url,
                        "recursive_depth": recursive_depth - 1,  # 减少递归深度
                        "embedding_model": DEFAULT_EMBEDDING_MODEL,
                        "embedding_dimensions": EMBEDDING_DIMENSIONS,
                        "webhook_url": WEBHOOK_PREFIX + "/array2array",
                        "is_recursive": True,  # 标记为递归调用
                        "document_name": parent_doc_name,  # 传递父级文档名称
                        "collection_name": parent_collection_name,  # 传递父级collection名称
                        "parent_source_id": parent_source_id  # 传递父级Source ID
                    }
                    
                    # 创建一个虚拟的BackgroundTasks实例用于递归调用
                    dummy_background_tasks = BackgroundTasks()
                    
                    # 🔥 修复：使用独立的数据库会话进行递归调用
                    result = await agenttic_ingest(dummy_background_tasks, sub_request_data, sub_db)
                    
                    print(f"子文档摄取成功: {sub_url}")
                    
                    # 更新状态为完成
                    if task_id:
                        await ingest_task_manager.update_sub_doc_status(task_id, sub_url, TaskStatus.COMPLETED)
                    
                    return {
                        "url": sub_url,
                        "success": True,
                        "result": result
                    }
                    
                except Exception as e:
                    error_msg = f"子文档摄取失败 {sub_url}: {str(e)}"
                    print(error_msg)
                    
                    # 确保出错时也回滚子文档的数据库会话
                    try:
                        await sub_db.rollback()
                    except:
                        pass
                    
                    # 更新状态为失败
                    if task_id:
                        await ingest_task_manager.update_sub_doc_status(task_id, sub_url, TaskStatus.FAILED, error_msg)
                    
                    return {
                        "url": sub_url,
                        "success": False,
                        "error": error_msg
                    }
    
    # 使用asyncio.gather进行并发处理，但通过信号量控制最大并发数
    try:
        tasks = [process_single_sub_doc_with_tracking(url) for url in sub_docs_urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)
    except Exception as e:
        print(f"并发处理子文档时出现异常: {str(e)}")
        # 降级到串行处理
        results = []
        for sub_url in sub_docs_urls:
            result = await process_single_sub_doc_with_tracking(sub_url)
            results.append(result)
    
    return results


async def process_sub_docs_background(
    sub_docs_urls: List[str],
    recursive_depth: int,
    request_id: Optional[str] = None,
    parent_doc_name: Optional[str] = None,
    parent_collection_name: Optional[str] = None,
    parent_source_id: Optional[int] = None,
    parent_url: Optional[str] = None  # 新增：父文档URL，用于任务追踪
):
    """
    后台异步处理子文档的函数 - 不阻塞主响应

    Args:
        sub_docs_urls: 子文档URL列表
        recursive_depth: 递归深度限制
        request_id: 请求ID，用于日志追踪
        parent_doc_name: 父级文档名称
        parent_collection_name: 父级collection名称
        parent_source_id: 父级Source ID，用于将子文档内容添加到同一个collection
        parent_url: 父文档URL，用于任务追踪
    """
    task_id = request_id or f"subdoc_{hash(str(sub_docs_urls))}"
    
    try:
        # 创建任务状态追踪
        if parent_url and parent_doc_name and parent_collection_name:
            await ingest_task_manager.create_task(
                task_id=task_id,
                parent_url=parent_url,
                document_name=parent_doc_name,
                collection_name=parent_collection_name,
                sub_doc_urls=sub_docs_urls
            )
            await ingest_task_manager.start_task(task_id)
        
        print(f"[后台任务] 开始处理 {len(sub_docs_urls)} 个子文档，task_id: {task_id}")

        # 🔥 修复：不再需要共享数据库会话，每个子文档使用独立会话
        results = await process_sub_docs_concurrent_with_tracking(
            sub_docs_urls, recursive_depth, None, parent_doc_name, 
            parent_collection_name, parent_source_id, task_id
        )

        success_count = len([r for r in results if r.get('success')])
        print(f"[后台任务] 子文档处理完成，成功: {success_count}/{len(results)}, task_id: {task_id}")
        
        # 🔥 修复：不再需要统一提交，每个子文档会话已独立提交
        print(f"[后台任务] 所有子文档已独立处理和提交，处理了 {success_count} 个子文档")
                
    except Exception as e:
        error_msg = f"子文档处理异常: {str(e)}"
        print(f"[后台任务] {error_msg}, task_id: {task_id}")
        await ingest_task_manager.fail_task(task_id, error_msg)
        
        # 🔥 修复：不再需要统一回滚，每个子文档会话会自动管理事务


async def process_webhook_response(
    data: WebhookResponseData,
    db: AsyncSession,
    background_tasks: BackgroundTasks = None
):
    """
    处理webhook回调数据的专用函数 - 优化版本，子文档处理改为后台任务
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
    
    # 实现递归摄取逻辑：收集webhook响应中的子文档URL
    total_sub_docs = 0
    
    if data.output and isinstance(data.output, list):
        print(f"检测到响应数据，共 {len(data.output)} 个响应项")
        
        # 收集所有子文档URL，并进行去重处理
        all_sub_docs = []
        seen_urls = set()  # 用于跟踪已添加的URL，避免重复

        for i, output_item in enumerate(data.output):
            if isinstance(output_item, dict) and "response" in output_item:
                response_data = output_item.get("response", {})
                if isinstance(response_data, dict) and "sub_docs" in response_data:
                    sub_docs = response_data.get("sub_docs", [])
                    if isinstance(sub_docs, list):
                        print(f"响应项 {i} 包含 {len(sub_docs)} 个子文档")
                        total_sub_docs += len(sub_docs)

                        # 逐个检查并添加URL，避免重复
                        from urllib.parse import urlparse
                        def is_strict_child(child: str, base: str) -> bool:
                            try:
                                cu = urlparse(child)
                                bu = urlparse(base)
                                if cu.netloc != bu.netloc:
                                    return False
                                base_path = bu.path.rstrip('/')
                                url_path = cu.path.rstrip('/')
                                # 仅允许严格子路径，如 /docs/python/*
                                return url_path.startswith(base_path + '/')
                            except Exception:
                                return False

                        for url in sub_docs:
                            if url and is_strict_child(url, data.url) and url not in seen_urls:
                                all_sub_docs.append(url)
                                seen_urls.add(url)
                            elif url and not is_strict_child(url, data.url):
                                print(f"跳过兄弟/非子路径URL: {url}")
                            elif url in seen_urls:
                                print(f"跳过重复的子文档URL: {url}")
                    else:
                        print(f"响应项 {i} 的 sub_docs 不是列表格式: {type(sub_docs)}")
                else:
                    print(f"响应项 {i} 的 response 不包含 sub_docs 字段或格式不正确")
            else:
                print(f"响应项 {i} 不包含 response 字段或格式不正确")

        # 记录去重统计信息
        if all_sub_docs:
            duplicates_count = total_sub_docs - len(all_sub_docs)
            if duplicates_count > 0:
                print(f"去重完成：从 {total_sub_docs} 个原始URL中移除了 {duplicates_count} 个重复项，最终得到 {len(all_sub_docs)} 个唯一URL")
            else:
                print(f"去重完成：所有 {total_sub_docs} 个URL都是唯一的")
        
        if all_sub_docs:
            print(f"总共发现 {len(all_sub_docs)} 个子文档URL")
            
            # 从原始数据中获取递归深度参数，默认为1
            recursive_depth = 1
            if hasattr(data, 'recursive_depth') and isinstance(data.recursive_depth, int):
                recursive_depth = data.recursive_depth
            
            # 🚀 关键优化：将子文档处理作为后台任务异步执行，不阻塞响应
            # 获取Source ID（这里的data是webhook响应，需要通过document_name和collection找到对应的source_id）
            source_id = None
            if data.document_name:
                try:
                    from sqlalchemy.future import select
                    FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
                    stmt = select(Source).where(
                        Source.title == data.document_name,
                        Source.session_id == FIXED_SESSION_ID
                    ).order_by(Source.created_at.desc())  # 获取最新创建的source
                    result = await db.execute(stmt)
                    source = result.scalar_one_or_none()
                    if source:
                        source_id = source.id
                        print(f"找到父级Source ID: {source_id}")
                    else:
                        print(f"未找到匹配的Source，文档名称: {data.document_name}")
                except Exception as e:
                    print(f"查找父级Source失败: {e}")
                    
            if background_tasks:
                print("将子文档处理添加到后台任务队列...")
                background_tasks.add_task(
                    process_sub_docs_background,
                    all_sub_docs,
                    recursive_depth,
                    data.request_id,
                    data.document_name,
                    data.collection_name,
                    source_id
                )
            else:
                # 如果没有background_tasks，直接启动协程任务（不等待）
                print("启动子文档后台处理协程...")
                asyncio.create_task(
                    process_sub_docs_background(all_sub_docs, recursive_depth, data.request_id, data.document_name, data.collection_name, source_id)
                )
                
        else:
            print("未发现任何子文档URL")
    else:
        print("响应数据中未包含有效的response字段")
    
    # 更新工作流执行状态
    try:
        if data.request_id:
            from sqlalchemy import update
            stmt = update(WorkflowExecution).where(
                WorkflowExecution.execution_id == data.request_id
            ).values(
                status="success",
                stopped_at=datetime.now(pytz.timezone('Asia/Shanghai'))
            )
            await db.execute(stmt)
            await db.commit()
            print(f"工作流执行状态已更新为成功: {data.request_id}")
    except Exception as e:
        print(f"更新工作流执行状态失败: {e}")
    
    # 🚀 立即返回响应，不等待子文档处理完成
    return {
        "message": "Webhook响应处理成功，子文档处理已启动后台任务",
        "task_name": data.task_name,
        "document_name": data.document_name,
        "total_sub_docs": total_sub_docs,
        "sub_docs_processing": "后台处理中" if total_sub_docs > 0 else "无需处理",
        "success": True
    }


async def generate_document_names(url: str, model: str = None) -> dict:
    """
    使用大模型为文档和collection生成名称
    """
    # 创建一个专门用于文档名称生成的提示模板，避免使用query接口中的generate_answer函数
    # 通过调用llm_client的底层API实现，而不是复用generate_answer函数
    from ..config import DEFAULT_INGEST_MODEL
    from ..llm_client import chat_complete
    
    # 如果没有传入模型，使用默认模型
    if model is None:
        model = DEFAULT_INGEST_MODEL
    
    system_prompt = (
        "你是一个文档名称生成助手，专门负责为网页内容生成合适的中文标题和英文collection名称。\n"
        "要求：\n"
        "- 只输出一个JSON对象，不要包含多余解释或标点。\n"
        "- document_name 使用简洁准确的中文标题。\n"
        "- collection_name 全小写、使用下划线连接、只含英文字母数字下划线。"
    )
    user_prompt = (
        f"请为以下URL生成名称：\nURL: {url}\n\n"
        "返回JSON，包含：\n"
        "1. document_name: 文档的中文名称\n"
        "2. collection_name: 英文collection名称（小写+下划线）\n\n"
        "示例：{\\\"document_name\\\": \\\"机器学习入门指南\\\", \\\"collection_name\\\": \\\"machine_learning_guide\\\"}"
    )
    
    try:
        # 统一通过 llm_client 调用
        response_content = await chat_complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            timeout=300,
        )

        # 尝试解析JSON
        import re
        json_match = re.search(r'\{[\s\S]*\}', response_content.strip())
        if json_match:
            try:
                result = json.loads(json_match.group())
                # 结果基本校验与清理
                doc_name = str(result.get("document_name") or "").strip() or (url.split('/')[-1] or "未命名文档")
                coll_name = str(result.get("collection_name") or "").strip()
                # 规范化 collection_name：小写、下划线、去除非法字符
                import re as _re
                coll_name = _re.sub(r"[^a-z0-9_]", "_", coll_name.lower()) or f"doc_{hashlib.md5(url.encode()).hexdigest()[:8]}"
                return {"document_name": doc_name, "collection_name": coll_name}
            except Exception:
                pass
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
    background_tasks: BackgroundTasks,
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    统一的智能文档摄取接口：
    - 客户端请求：获取URL并使用大模型生成文档名称和collection名称，拉取并处理内容，创建新的向量库collection存储，发送webhook通知
    - webhook回调：处理工作流响应数据并执行递归摄取逻辑
    
    通过检测数据中是否包含 'task_name' 字段来判断请求类型
    """
    
    # 检测请求类型：如果包含 task_name 字段，说明是 webhook 回调
    # 需要考虑数据可能嵌套在 body 字段中的情况
    is_webhook_callback = 'task_name' in data or ('body' in data and isinstance(data.get('body'), dict) and 'task_name' in data['body'])
    
    if is_webhook_callback:
        # 处理 webhook 回调
        print("检测到webhook回调请求")
        try:
            # 如果数据嵌套在body中，提取body内容
            webhook_request_data = data
            if 'body' in data and isinstance(data.get('body'), dict) and 'task_name' in data['body']:
                print("检测到嵌套在body中的webhook数据，正在提取...")
                webhook_request_data = data['body']
            
            webhook_data = WebhookResponseData(**webhook_request_data)
            return await process_webhook_response(webhook_data, db, background_tasks)
        except Exception as e:
            error_message = f"Webhook回调处理失败: {e.__class__.__name__}: {str(e)}"
            print(error_message)
            print(f"原始数据: {data}")  # 添加原始数据日志以便调试
            raise HTTPException(status_code=500, detail=error_message)
    
    # 处理客户端请求
    print("检测到客户端摄取请求")
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL必须提供")

    model = data.get("model", DEFAULT_INGEST_MODEL)  # 获取模型参数，默认使用 DEFAULT_INGEST_MODEL
    embedding_model = data.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions = data.get("embedding_dimensions", EMBEDDING_DIMENSIONS)
    webhook_url = data.get("webhook_url", WEBHOOK_PREFIX + "/array2array")
    recursive_depth = data.get("recursive_depth", 2)  # 默认递归深度为2
    is_recursive = data.get("is_recursive", False)  # 检测是否为递归调用
    # 是否启用 webhook 兜底，可被请求参数覆盖
    use_webhook_fallback = data.get("webhook_fallback", SUBDOC_USE_WEBHOOK_FALLBACK)
    print(f"模型: {model}")
    try:
        # 1. 使用大模型生成文档名称和collection名称（仅在非递归调用时）
        print("正在生成文档名称...")
        if is_recursive:
            # 递归调用时，从数据中获取已有的文档名称和collection名称
            document_name = data.get("document_name")
            collection_name = data.get("collection_name")
            if not document_name or not collection_name:
                # 如果递归调用时缺少文档名称或collection名称，使用默认值
                document_name = document_name or f"子文档_{url.split('/')[-1] or '未命名'}"
                url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                collection_name = collection_name or f"subdoc_{url_hash}"
            print(f"检测到递归调用，使用已有的文档名称: {document_name}, collection名称: {collection_name}")
        else:
            # 非递归调用时，正常生成文档名称和collection名称
            names = await generate_document_names(url, model)
            document_name = names["document_name"]
            # 使用URL的hash生成稳定的collection名称，确保同一URL总是得到相同的collection_name
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            collection_name = f"collection_{url_hash}"
        
        print(f"文档名称: {document_name}")
        print(f"Collection名称: {collection_name}")

        # 2. 拉取并解析内容
        print("正在拉取网页内容...")
        text = await fetch_then_extract(url)
        # 仅获取HTML用于子文档链接提取，不用于分块存储
        raw_html = await fetch_html(url)

        # 3. 分块处理文本（仅处理plaintext）
        print("正在分块处理文本...")
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("无法从URL中提取任何内容")

        total_chunks = len(chunks)
        print(f"总共生成了 {total_chunks} 个文本块")

        # 4. 创建或获取Source对象 (支持UPSERT操作)
        FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
        
        # 首先检查是否已存在相同URL的Source记录（全局唯一约束，不考虑session_id）
        existing_source_stmt = select(Source).where(Source.url == url)
        existing_source_result = await db.execute(existing_source_stmt)
        existing_source = existing_source_result.scalars().first()
        
        # 检查是否为递归调用且提供了parent_source_id
        parent_source_id = data.get("parent_source_id")
        from datetime import datetime
        if is_recursive and parent_source_id:
            # 递归调用时，为每个子文档创建独立的Source记录
            print(f"递归调用：为子文档创建独立的Source记录，父级ID: {parent_source_id}")
            
            # 检查是否已存在相同URL的Source记录
            if existing_source:
                print(f"子文档已存在，更新现有的Source: {existing_source.title} (ID: {existing_source.id})")
                # 更新现有记录的信息
                existing_source.title = document_name
                existing_source.session_id = FIXED_SESSION_ID
                existing_source.created_at = datetime.now(pytz.timezone('Asia/Shanghai'))
                source = existing_source
                
                # 删除与现有Source相关的旧chunks，准备重新处理最新内容
                print("删除旧的chunks...")
                await db.execute(delete(Chunk).where(Chunk.source_id == source.id))
                await db.flush()
            else:
                print(f"为子文档创建新的Source记录: {document_name}")
                source = Source(url=url, title=document_name, session_id=FIXED_SESSION_ID)
        else:
            # 非递归调用时，检查是否存在相同URL的Source (UPSERT逻辑)
            if existing_source:
                print(f"非递归调用：更新现有Source: {existing_source.title} (ID: {existing_source.id})")
                # 更新现有记录的所有信息
                existing_source.title = document_name
                existing_source.session_id = FIXED_SESSION_ID  # 更新 session_id
                existing_source.created_at = datetime.now(pytz.timezone('Asia/Shanghai'))
                source = existing_source
                
                # 删除与现有Source相关的旧chunks，准备重新处理最新内容
                print("删除旧的chunks...")
                await db.execute(delete(Chunk).where(Chunk.source_id == source.id))
                await db.flush()
            else:
                print("非递归调用：创建新的Source对象")
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
        
        
        
        # 5. 将chunk对象保存到数据库
        print(f"正在保存chunk到数据库... (文本块: {len(chunk_objects)})")
        
        # 只有在创建新Source时才需要添加到数据库
        if not (is_recursive and parent_source_id and source.id):
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

        # 7. 提取子URL（本地解析优先）
        print("正在本地解析子文档URL...")
        try:
            extracted_sub_docs = extract_links_from_html(raw_html, url)
            # 严格过滤仅保留子路径，排除兄弟文档
            from urllib.parse import urlparse
            def is_strict_child(child: str, base: str) -> bool:
                try:
                    cu = urlparse(child)
                    bu = urlparse(base)
                    if cu.netloc != bu.netloc:
                        return False
                    base_path = bu.path.rstrip('/')
                    url_path = cu.path.rstrip('/')
                    return url_path.startswith(base_path + '/')
                except Exception:
                    return False
            extracted_sub_docs = [u for u in extracted_sub_docs if is_strict_child(u, url)]
            # 去重
            extracted_sub_docs = list(dict.fromkeys(extracted_sub_docs))
            print(f"本地解析到 {len(extracted_sub_docs)} 个潜在子文档URL")
        except Exception as e:
            print(f"本地解析子文档URL失败: {e}")
            extracted_sub_docs = []

        # 8. 本地子文档处理（异步后台，不阻塞响应）
        if recursive_depth > 0 and extracted_sub_docs:
            print("将本地解析的子文档加入后台处理任务...")
            
            # 生成任务ID
            task_id = f"ingest_{hashlib.md5(url.encode()).hexdigest()[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            if background_tasks:
                background_tasks.add_task(
                    process_sub_docs_background,
                    extracted_sub_docs,
                    recursive_depth,
                    task_id,  # 使用生成的task_id
                    document_name,
                    collection_name,
                    source.id,
                    url  # 添加parent_url参数
                )
            else:
                asyncio.create_task(
                    process_sub_docs_background(
                        extracted_sub_docs,
                        recursive_depth,
                        task_id,  # 使用生成的task_id
                        document_name,
                        collection_name,
                        source.id,
                        url  # 添加parent_url参数
                    )
                )

        # 9. 准备webhook数据（作为回退/补充渠道）
        import uuid
        from datetime import datetime
        
        # 生成request_id: url + 当前日期 + uuid
        # 对URL进行编码以处理特殊字符
        import urllib.parse
        encoded_url = urllib.parse.quote(url, safe=':/')
        request_id = f"{encoded_url}_{datetime.now().strftime('%Y%m%d')}_{str(uuid.uuid4())}"
        
        # 如果需要webhook识别子文档，临时分块HTML（不保存到数据库）
        temp_html_chunks = chunk_text(raw_html) if raw_html else []
        
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
                    "chunk_id": f"temp_html_{idx}",
                    "content": html_chunk,
                    "index": idx
                }
                for idx, html_chunk in enumerate(temp_html_chunks)
            ],
            "request_id": request_id,
            "recursive_depth": recursive_depth,  # 添加递归深度参数
        }

        # 10. 发送webhook（仅在递归深度大于0、且需要补充识别、且启用兜底时）
        if recursive_depth > 0 and not extracted_sub_docs and use_webhook_fallback:
            print("正在发送webhook进行子文档识别...")
            
            # 创建工作流执行记录
            try:
                workflow_execution = WorkflowExecution(
                    execution_id=request_id,  # 使用request_id作为临时execution_id
                    document_name=document_name,
                    status="running",
                    session_id=FIXED_SESSION_ID
                )
                db.add(workflow_execution)
                await db.commit()
                print(f"工作流执行记录已创建: {request_id}")
            except Exception as e:
                print(f"创建工作流执行记录失败: {e}")
                # 不阻塞webhook发送，继续执行
            
            # 直接向指定的webhook URL发送POST请求
            try:
                async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
                    response = await client.post(webhook_url, json=webhook_data)
                    response.raise_for_status()
                    print("Webhook发送成功")
            except Exception as e:
                print(f"Webhook发送失败: {e}")
                # 如果webhook发送失败，更新执行记录状态
                try:
                    from sqlalchemy import update
                    stmt = update(WorkflowExecution).where(
                        WorkflowExecution.execution_id == request_id
                    ).values(
                        status="error",
                        stopped_at=datetime.now(pytz.timezone('Asia/Shanghai'))
                    )
                    await db.execute(stmt)
                    await db.commit()
                except Exception as update_error:
                    print(f"更新工作流执行状态失败: {update_error}")
        else:
            if recursive_depth <= 0:
                print(f"递归深度为0，跳过子文档识别webhook")
            elif not use_webhook_fallback and not extracted_sub_docs:
                print("配置禁止 webhook 兜底，且本地未解析到子文档URL")
            else:
                print("已通过本地解析获得子文档URL，跳过webhook识别")

        # 准备返回结果
        result = {
            "success": True,
            "message": f"成功摄取文档，共处理了 {total_chunks} 个文本块",
            "document_name": document_name,
            "collection_name": collection_name,
            "total_chunks": total_chunks,
            "source_id": source.id  # 返回Source ID用于递归调用
        }
        
        # 如果启动了子文档后台任务，返回任务ID供前端监控
        if recursive_depth > 0 and extracted_sub_docs:
            result["sub_docs_task_id"] = task_id
            result["sub_docs_count"] = len(extracted_sub_docs)
            result["sub_docs_processing"] = True
        
        return result

    except Exception as e:
        error_message = f"摄取失败: {e.__class__.__name__}: {str(e)}"
        print(error_message)
        raise HTTPException(status_code=500, detail=error_message)


@router.get("/documents", summary="获取通过agentic ingest处理的文档列表")
async def get_agentic_ingest_documents(
    db: AsyncSession = Depends(get_db)
):
    """
    获取通过agentic ingest处理的文档列表
    返回所有使用固定session_id存储的文档
    """
    try:
        FIXED_SESSION_ID = "fixed_session_id_for_agenttic_ingest"
        
        # 查询数据库中的source记录
        stmt = select(Source).where(Source.session_id == FIXED_SESSION_ID)
        result = await db.execute(stmt)
        sources = result.scalars().all()
        
        documents = []
        for source in sources:
            documents.append({
                "id": source.id,
                "title": source.title,
                "url": source.url,
                "created_at": source.created_at.isoformat() if source.created_at else None
            })
        
        return {
            "success": True,
            "documents": documents,
            "total": len(documents)
        }
    
    except Exception as e:
        error_message = f"获取文档列表失败: {e.__class__.__name__}: {str(e)}"
        print(error_message)
        raise HTTPException(status_code=500, detail=error_message)


@router.post("/workflow_response", summary="工作流响应处理接口（兼容性端点）")
async def workflow_response(
    background_tasks: BackgroundTasks,
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    工作流响应处理接口 - 兼容性端点
    此端点将请求重定向到统一的 agenttic_ingest 接口进行处理
    """
    print("收到workflow_response请求，重定向到统一处理接口")
    return await agenttic_ingest(background_tasks, data, db)


# ========== 任务监控API端点 ==========

async def stream_ingest_progress(task_id: str):
    """流式返回摄取任务进度"""
    import json
    
    while True:
        status = await ingest_task_manager.get_task_status(task_id)
        if not status:
            # 任务不存在，可能已完成并被清理
            yield f"data: {json.dumps({'error': 'Task not found', 'task_id': task_id})}\n\n"
            break
            
        # 发送当前状态
        yield f"data: {json.dumps(status.to_dict())}\n\n"
        
        # 如果任务完成或失败，结束流
        if status.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.PARTIALLY_COMPLETED]:
            break
            
        await asyncio.sleep(2)  # 每2秒更新一次


@router.get("/api/ingest-progress/{task_id}", summary="获取摄取任务进度（流式）")
async def get_ingest_progress(task_id: str):
    """获取摄取任务进度的流式响应"""
    return StreamingResponse(
        stream_ingest_progress(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )


@router.get("/api/ingest-status/{task_id}", summary="获取摄取任务状态")
async def get_ingest_status(task_id: str):
    """获取摄取任务的当前状态"""
    status = await ingest_task_manager.get_task_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return {
        "success": True,
        "task_id": task_id,
        "status": status.to_dict()
    }


@router.get("/api/ingest-tasks", summary="获取所有活跃的摄取任务")
async def list_ingest_tasks():
    """获取所有活跃的摄取任务列表"""
    tasks = await ingest_task_manager.list_active_tasks()
    return {
        "success": True,
        "tasks": [task.to_dict() for task in tasks],
        "total": len(tasks)
    }


@router.delete("/api/ingest-task/{task_id}", summary="删除摄取任务")
async def delete_ingest_task(task_id: str):
    """删除指定的摄取任务（通常在任务完成后清理）"""
    success = await ingest_task_manager.remove_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return {
        "success": True,
        "message": f"任务 {task_id} 已删除"
    }
