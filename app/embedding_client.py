import httpx
from typing import List
from app.config import EMBEDDING_SERVICE_URL

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

async def embed_texts(texts: List[str], model: str = DEFAULT_EMBEDDING_MODEL) -> List[List[float]]:
    """调用 LM Studio OpenAI 兼容 /v1/embeddings 接口，将文本列表转为向量列表。"""
    url = f"{EMBEDDING_SERVICE_URL}/embeddings"
    payload = {
        "model": model,
        "input": texts,
        "encoding_format": "float"
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        # OpenAI 返回格式：{"data": [{"embedding": [...], "index": 0}, ...]}
        return [item["embedding"] for item in data["data"]]