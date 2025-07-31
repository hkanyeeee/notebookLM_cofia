import os
import numpy as np
import faiss
from typing import List, Tuple
from sqlalchemy import select
from app.database import get_db
from app.models import Chunk

# FAISS 索引文件路径
INDEX_PATH = "./data/faiss.index"

def _get_index(dim: int):
    """加载或创建 FAISS 索引，使用 IndexIDMap 来支持自定义 ID"""
    if not hasattr(_get_index, "index"):
        if os.path.exists(INDEX_PATH):
            idx = faiss.read_index(INDEX_PATH)
            if not isinstance(idx, faiss.IndexIDMap):
                idx = faiss.IndexIDMap(idx)
        else:
            idx = faiss.IndexIDMap(faiss.IndexFlatL2(dim))
        _get_index.index = idx
    return _get_index.index

def _save_index():
    """将 FAISS 索引写回磁盘"""
    faiss.write_index(_get_index.index, INDEX_PATH)

async def add_embeddings(url: str, chunks: List[str], embeddings: List[List[float]]) -> None:
    """将 embeddings 存入 FAISS，并将 Chunk 元数据存入 SQLite"""
    # 插入元数据到 SQLite
    async for session in get_db():
        models = [Chunk(url=url, content=chunk) for chunk in chunks]
        session.add_all(models)
        await session.flush()
        ids = [model.id for model in models]
        await session.commit()
        break
    # 添加 vectors 到 FAISS
    dim = len(embeddings[0])
    idx = _get_index(dim)
    np_emb = np.array(embeddings, dtype="float32")
    idx.add_with_ids(np_emb, np.array(ids, dtype="int64"))
    _save_index()

async def query_embeddings(query_embedding: List[float], top_k: int = 5) -> List[Tuple[Chunk, float]]:
    """根据 query vector 从 FAISS 检索，返回最相似的 Chunk 及距离"""
    dim = len(query_embedding)
    idx = _get_index(dim)
    vec = np.array(query_embedding, dtype="float32").reshape(1, -1)
    distances, ids = idx.search(vec, top_k)

    id_list = ids[0].tolist()
    # 查询元数据
    async for session in get_db():
        stmt = select(Chunk).where(Chunk.id.in_(id_list))
        res = await session.execute(stmt)
        chunks = res.scalars().all()
        break
    # 按搜索结果顺序构建输出
    id_to_chunk = {chunk.id: chunk for chunk in chunks}
    result: List[Tuple[Chunk, float]] = []
    for i, cid in enumerate(id_list):
        if cid in id_to_chunk:
            result.append((id_to_chunk[cid], float(distances[0][i])))
    return result