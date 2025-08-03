import os
from typing import List, Tuple

import numpy as np  # 仅用于类型提示，可按需移除
from sqlalchemy import select

from app.database import get_db
from app.models import Chunk
from app.config import MILVUS_HOST, MILVUS_PORT

# ---------------- Milvus ----------------
from pymilvus import (
    connections,
    FieldSchema,
    CollectionSchema,
    DataType,
    Collection,
    utility,
)

COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "chunk_embeddings")


def _connect_if_needed() -> None:
    """确保与 Milvus 建立连接。"""
    try:
        if not connections.has_connection("default"):
            print(f"正在连接 Milvus: {MILVUS_HOST}:{MILVUS_PORT}")
            connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
            print("Milvus 连接成功")
    except Exception as e:
        print(f"Milvus 连接失败: {e}")
        raise e


def _get_collection(dim: int) -> Collection:
    """获取（或创建）Milvus collection。"""
    _connect_if_needed()

    if COLLECTION_NAME in utility.list_collections():
        col = Collection(name=COLLECTION_NAME)
        # 校验维度是否匹配
        existing_dim = next(
            f.params["dim"] for f in col.schema.fields if f.name == "embedding"
        )
        if existing_dim != dim:
            raise ValueError(
                f"现有 Milvus collection 维度为 {existing_dim}，与当前嵌入向量维度 {dim} 不一致"
            )
    else:
        id_field = FieldSchema(
            name="id", dtype=DataType.INT64, is_primary=True, auto_id=False
        )
        emb_field = FieldSchema(
            name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim
        )
        schema = CollectionSchema(fields=[id_field, emb_field], description="Chunk embeddings")
        col = Collection(name=COLLECTION_NAME, schema=schema)
        # 创建向量索引，提高检索性能（IVF_FLAT + L2）
        index_params = {"metric_type": "L2", "index_type": "IVF_FLAT", "params": {"nlist": 2048}}
        col.create_index(field_name="embedding", index_params=index_params)
    # 加载到内存，用于搜索
    if utility.load_state(COLLECTION_NAME) != "Loaded":
        col.load()
    return col


async def add_embeddings(url: str, chunks: List[str], embeddings: List[List[float]]) -> None:
    """将嵌入向量写入 Milvus，并把元数据写入 SQLite。"""
    # 1. metadata -> SQLite
    async for session in get_db():
        try:
            models = [Chunk(url=url, content=c) for c in chunks]
            session.add_all(models)
            await session.flush()
            ids = [m.id for m in models]  # 作为 Milvus 主键
            await session.commit()
            
            # 2. vectors -> Milvus
            try:
                dim = len(embeddings[0])
                col = _get_collection(dim)
                entities = [ids, embeddings]
                col.insert(entities)
                col.flush()
                print(f"Entities in collection after insert: {col.num_entities}")
            except Exception as e:
                print(f"Milvus 插入失败: {e}")
                # 如果 Milvus 插入失败，回滚 SQLite 事务
                await session.rollback()
                raise e
            break
        except Exception as e:
            print(f"数据库操作失败: {e}")
            await session.rollback()
            raise e


async def query_embeddings(query_embedding: List[float], top_k: int = 5) -> List[Tuple[Chunk, float]]:
    """按向量相似度查询 Milvus，返回 (Chunk, distance) 列表。"""
    dim = len(query_embedding)
    col = _get_collection(dim)
    
    print(f"Entities in collection before search: {col.num_entities}")

    search_params = {"metric_type": "L2", "params": {"nprobe": 10}}
    results = col.search(
        data=[query_embedding],
        anns_field="embedding",
        param=search_params,
        limit=top_k,
        output_fields=["id"],
    )
    hits = results[0]
    if not hits:
        return []
        
    id_list = [hit.id for hit in hits]
    distance_list = [hit.distance for hit in hits]

    # 3. metadata from SQLite
    async for session in get_db():
        stmt = select(Chunk).where(Chunk.id.in_(id_list))
        res = await session.execute(stmt)
        chunks = res.scalars().all()
        break

    id_to_chunk = {chunk.id: chunk for chunk in chunks}
    return [
        (id_to_chunk[cid], float(dist))
        for cid, dist in zip(id_list, distance_list)
        if cid in id_to_chunk
    ]
