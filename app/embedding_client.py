import httpx
from typing import List, Optional
import asyncio

from app.config import EMBEDDING_SERVICE_URL

DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-4B"

async def _embed_batch(texts: List[str], model: str, client: httpx.AsyncClient, dimensions: Optional[int] = None) -> List[List[float]]:
    """帮助函数，用于嵌入单批次的文本。"""
    url = f"{EMBEDDING_SERVICE_URL}/embeddings"
    payload = {
        "model": model,
        "input": texts,
        "encoding_format": "float",
    }
    if dimensions:
        payload["dimensions"] = dimensions
        
    response = await client.post(url, json=payload)
    response.raise_for_status()
    data = response.json()
    # OpenAI API 保证输出顺序与输入顺序一致
    return [item["embedding"] for item in data["data"]]

async def embed_texts(texts: List[str], model: str = DEFAULT_EMBEDDING_MODEL, batch_size: int = 5, dimensions: Optional[int] = None) -> List[List[float]]:
    """
    调用 embedding 服务接口，将文本列表转为向量列表。
    支持分批处理以避免单个请求过大。
    """
    all_embeddings = []
    async with httpx.AsyncClient(timeout=60, http2=False) as client:
        # 将文本列表分割成多个批次
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            print(f"正在处理批次 {i//batch_size + 1}/{(len(texts) + batch_size - 1)//batch_size}，包含 {len(batch)} 个chunks...")
            
            try:
                batch_embeddings = await _embed_batch(batch, model, client, dimensions=dimensions)
                all_embeddings.extend(batch_embeddings)
                await asyncio.sleep(0.1)  # 短暂休眠，避免请求过于频繁
            except httpx.HTTPStatusError as e:
                print(f"处理批次时出错: {e}")
                # 您可以在这里决定是跳过这个批次、重试还是中止
                # 为简单起见，我们暂时跳过
                continue

    return all_embeddings
