import httpx
from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Body, HTTPException

from ..config import WEBHOOK_TIMEOUT

router = APIRouter()

# 定义WebhookData模型用于数据验证
class WebhookData(BaseModel):
    document_name: str = Field(..., description="文档的中文名称")
    collection_name: str = Field(..., description="向量库collection的英文名称")
    url: str = Field(..., description="文档URL")
    total_chunks: int = Field(..., description="总块数")
    task_name: Optional[str] = Field(None, description="任务名称标识")
    prompt: Optional[str] = Field(None, description="提示词")
    data_list: Optional[List] = Field(None, description="数据列表")
    request_id: Optional[str] = Field(None, description="请求ID")

# 定义验证结果类型
class ValidationResult:
    def __init__(self, is_valid: bool, error_message: str = ""):
        self.is_valid = is_valid
        self.error_message = error_message

async def send_webhook(webhook_url: str, data: dict):
    """
    发送webhook到指定URL
    """
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
            response = await client.post(webhook_url, json=data)
            response.raise_for_status()
            return {"status": "success", "status_code": response.status_code}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def validate_webhook_data(data: dict) -> tuple[bool, str]:
    """
    验证webhook数据的完整性与类型
    """
    try:
        # 使用Pydantic模型验证数据
        webhook_data = WebhookData(**data)
        return True, ""
    except Exception as e:
        return False, str(e)

def sanitize_webhook_data(data: dict) -> dict:
    """
    清理和标准化webhook数据
    """
    # 添加任务名标识
    if "task_name" not in data:
        data["task_name"] = "agenttic_ingest"
    
    # 确保所有字段都存在且类型正确
    if "document_name" not in data:
        data["document_name"] = ""
    if "collection_name" not in data:
        data["collection_name"] = ""
    if "url" not in data:
        data["url"] = ""
    if "total_chunks" not in data:
        data["total_chunks"] = 0
    if "chunks" not in data:
        data["chunks"] = []
    if "source_id" not in data:
        data["source_id"] = ""
    if "session_id" not in data:
        data["session_id"] = ""
    if "prompt" not in data:
        data["prompt"] = ""
    if "data_list" not in data:
        data["data_list"] = []
    if "request_id" not in data:
        data["request_id"] = ""
    
    return data

@router.post("/webhook/send", summary="发送Webhook")
async def send_webhook_endpoint(
    webhook_url: str = Body(..., description="Webhook URL"),
    data: dict = Body(..., description="要发送的数据")
):
    """
    发送Webhook到指定URL
    """
    # 验证和清理webhook数据
    is_valid, error_message = validate_webhook_data(data)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Webhook数据验证失败: {error_message}")
    
    data = sanitize_webhook_data(data)
    
    try:
        result = await send_webhook(webhook_url, data)
        if result["status"] == "error":
            raise HTTPException(status_code=500, detail=f"Webhook发送失败: {result['message']}")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发送Webhook时发生错误: {str(e)}")