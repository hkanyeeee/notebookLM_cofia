from fastapi import APIRouter, Body, HTTPException, Depends
from pydantic import BaseModel
import hashlib
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..models import Source, Chunk
from ..database import get_db

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


class WorkflowResponseData(BaseModel):
    """用于处理工作流响应数据的模型"""
    document_name: str
    collection_name: str
    url: str
    total_chunks: int
    chunks: List[dict]
    source_id: str
    session_id: str
    task_name: str


@router.post("/workflow_response", summary="处理工作流响应并执行数据库落库操作")
async def workflow_response(
    data: dict = Body(...),
):
    """
    处理工作流响应数据
    """
    print("Received workflow response data:")
    print(data)
    
    try:
        # 验证数据结构
        webhook_data = WebhookResponseData(**data)
        
        # 检查任务名称
        if webhook_data.task_name != "agenttic_ingest":
            return {
                "message": f"不支持的任务类型: {webhook_data.task_name}",
                "received_data": data
            }
        # 递归再循环调用？
        
    except Exception as e:
        error_message = f"workflow_response回调失败: {e.__class__.__name__}: {str(e)}"
        print(error_message)
        raise HTTPException(status_code=500, detail=error_message)