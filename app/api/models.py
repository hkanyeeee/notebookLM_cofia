from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException
import httpx
from ..config import LLM_SERVICE_URL

router = APIRouter()

@router.get("/models", summary="获取可用的LLM模型列表")
async def get_models() -> Dict[str, Any]:
    """
    从LLM服务获取可用的模型列表
    """
    if not LLM_SERVICE_URL:
        raise HTTPException(status_code=503, detail="LLM服务URL未配置")
    
    try:
        url = f"{LLM_SERVICE_URL}/models"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            
            # 兼容OpenAI格式的响应
            models = []
            if "data" in data and isinstance(data["data"], list):
                # OpenAI格式: {"data": [{"id": "model_name", ...}, ...]}
                models = [{"id": model.get("id", ""), "name": model.get("id", "")} for model in data["data"]]
            elif isinstance(data, dict) and "models" in data:
                # 自定义格式: {"models": [...]}
                models = data["models"]
            elif isinstance(data, list):
                # 直接数组格式
                models = [{"id": model, "name": model} if isinstance(model, str) else model for model in data]
            
            return {
                "success": True,
                "models": models
            }
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"无法连接到LLM服务: {str(e)}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"LLM服务返回错误: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取模型列表失败: {str(e)}")
