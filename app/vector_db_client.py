import os
from typing import List, Tuple, Optional, Dict

from qdrant_client import QdrantClient, models
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Chunk, Source
from app.config import QDRANT_URL, QDRANT_API_KEY

# Qdrant Collection Name
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "notebooklm_prod")

# Global Qdrant Client
# Use a global client to avoid reconnecting on every request
try:
    qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=60)
    print("Qdrant client initialized successfully.")
except Exception as e:
    print(f"Failed to initialize Qdrant client: {e}")
    qdrant_client = None


async def ensure_collection_exists(vector_size: int):
    """
    Ensures that the Qdrant collection exists, creating it if necessary.
    This is more efficient than checking on every operation.
    """
    if not qdrant_client:
        raise ConnectionError("Qdrant client is not available.")
    try:
        # If collection exists, ensure HNSW config is updated to desired values
        qdrant_client.get_collection(collection_name=COLLECTION_NAME)
        qdrant_client.update_collection(
            collection_name=COLLECTION_NAME,
            hnsw_config=models.HnswConfigDiff(m=64, ef_construct=512),
        )
    except Exception:
        print(f"Collection '{COLLECTION_NAME}' not found. Creating it.")
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            hnsw_config=models.HnswConfigDiff(m=64, ef_construct=512),
        )
        print(f"Collection '{COLLECTION_NAME}' created.")


async def add_embeddings(source_id: int, chunks: List[Chunk], embeddings: List[List[float]]):
    """
    Adds embeddings to Qdrant with associated metadata (session_id, source_id, content).
    """
    if not qdrant_client:
        raise ConnectionError("Qdrant client is not available.")
    if not chunks:
        return

    vector_size = len(embeddings[0])
    await ensure_collection_exists(vector_size)
    
    points = [
        models.PointStruct(
            id=chunk.id, 
            vector=embedding,
            payload={
                "session_id": chunk.session_id,
                "source_id": chunk.source_id,
                "content": chunk.content
            }
        )
        for chunk, embedding in zip(chunks, embeddings) if chunk.id is not None
    ]

    if not points:
        print("No points to upsert.")
        return

    qdrant_client.upsert(
        collection_name=COLLECTION_NAME,
        points=points,
        wait=True 
    )
    print(f"Upserted {len(points)} points to Qdrant for source_id {source_id}.")


async def query_embeddings(
    query_embedding: List[float],
    top_k: int = 60,
    session_id: Optional[str] = None,
    source_ids: Optional[List[int]] = None,
    hnsw_ef: int = 256,
) -> List[Tuple[Chunk, float]]:
    """
    Queries Qdrant for similar vectors, filtering by session_id and optionally source_ids.
    """
    if not qdrant_client:
        raise ConnectionError("Qdrant client is not available.")
    
    # Build the filter based on provided session and source IDs
    query_filter = models.Filter(
        must=[
            models.FieldCondition(key="session_id", match=models.MatchValue(value=session_id))
        ]
    )

    if source_ids:
        query_filter.must.append(
            models.FieldCondition(key="source_id", match=models.MatchAny(any=source_ids))
        )

    search_result = qdrant_client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_embedding,
        query_filter=query_filter,
        limit=top_k,
        with_payload=True, # We need the payload to reconstruct the Chunk object
        search_params=models.SearchParams(hnsw_ef=hnsw_ef),
    )

    # Reconstruct Chunk objects from the payload
    hits = []
    for point in search_result:
        # Create a mock Source and Chunk object. The ORM relationships might not be fully loaded,
        # but we have the necessary data for the context.
        source = Source(id=point.payload['source_id'], session_id=point.payload['session_id'], url="", title="")
        chunk = Chunk(
            id=point.id, 
            content=point.payload['content'],
            source_id=point.payload['source_id'],
            session_id=point.payload['session_id'],
            source=source
        )
        hits.append((chunk, point.score))
        
    return hits


async def query_bm25(
    query_text: str,
    top_k: int,
    session_id: Optional[str],
    source_ids: Optional[List[int]],
    db: AsyncSession,
) -> List[Tuple[Chunk, float]]:
    """
    使用 SQLite FTS5 对 chunks.content 进行 BM25 检索，返回 (Chunk, score)。
    仅检索指定 session_id，且可选按 source_ids 过滤。
    """
    # 基于 FTS 的匹配先取一批候选，再关联原表限定 session/source
    # 注意：bm25(chunks_fts) 分数越小越好（更相关），此处取负数作为统一的“越大越好”分值
    base_sql = (
        "SELECT c.id, c.content, c.source_id, c.session_id, -bm25(chunks_fts) AS score "
        "FROM chunks_fts JOIN chunks c ON chunks_fts.rowid = c.id "
        "WHERE chunks_fts MATCH :q AND c.session_id = :sid"
    )
    params: Dict[str, object] = {"q": query_text, "sid": session_id}
    if source_ids:
        # 构造 IN 子句
        placeholders = ",".join([str(int(x)) for x in source_ids])
        base_sql += f" AND c.source_id IN ({placeholders})"
    base_sql += " ORDER BY score DESC LIMIT :k"
    params["k"] = int(top_k)

    try:
        result = await db.execute(text(base_sql), params)  # type: ignore[arg-type]
        rows = result.fetchall()
    except Exception as e:
        # 如果 FTS 表尚未创建或 SQLite 不支持 FTS5，则返回空结果，避免整个查询失败
        print(f"BM25 query failed: {e}")
        return []
    hits: List[Tuple[Chunk, float]] = []
    for row in rows:
        # row: (id, content, source_id, session_id, score)
        source = Source(id=row[2], session_id=row[3], url="", title="")
        chunk = Chunk(id=row[0], content=row[1], source_id=row[2], session_id=row[3], source=source)
        hits.append((chunk, float(row[4])))
    return hits


def reciprocal_rank_fusion(
    dense: List[Tuple[Chunk, float]],
    sparse: List[Tuple[Chunk, float]],
    k: int = 60,
    rrf_k: int = 60,
    alpha_dense: float = 1.0,
    alpha_sparse: float = 1.0,
) -> List[Tuple[Chunk, float]]:
    """
    对稠密与稀疏结果做 RRF 融合。返回 Top-k。
    - rrf_k: RRF 中的常数，默认 60
    - alpha_*: 稠密/稀疏权重
    分数越大越相关。
    """
    score_map: Dict[int, float] = {}
    chunk_map: Dict[int, Chunk] = {}

    for rank, (chunk, _) in enumerate(dense, start=1):
        if chunk.id is None:
            continue
        chunk_map[chunk.id] = chunk
        score_map[chunk.id] = score_map.get(chunk.id, 0.0) + alpha_dense * (1.0 / (rrf_k + rank))

    for rank, (chunk, _) in enumerate(sparse, start=1):
        if chunk.id is None:
            continue
        chunk_map[chunk.id] = chunk
        score_map[chunk.id] = score_map.get(chunk.id, 0.0) + alpha_sparse * (1.0 / (rrf_k + rank))

    fused = [(chunk_map[cid], sc) for cid, sc in score_map.items()]
    fused.sort(key=lambda x: x[1], reverse=True)
    return fused[:k]


async def query_hybrid(
    query_text: str,
    query_embedding: List[float],
    top_k: int = 60,
    session_id: Optional[str] = None,
    source_ids: Optional[List[int]] = None,
    hnsw_ef: int = 256,
    k_dense: int = 200,
    k_sparse: int = 200,
    rrf_k: int = 60,
    alpha_dense: float = 1.0,
    alpha_sparse: float = 1.0,
    db: Optional[AsyncSession] = None,
) -> List[Tuple[Chunk, float]]:
    """
    混合检索：稠密 Top-k_dense + 稀疏 Top-k_sparse，RRF 融合输出 Top-k。
    若提供 db，则走本地 FTS5 的稀疏检索；否则仅返回稠密结果。
    """
    dense_hits = await query_embeddings(
        query_embedding=query_embedding,
        top_k=k_dense,
        session_id=session_id,
        source_ids=source_ids,
        hnsw_ef=hnsw_ef,
    )

    sparse_hits: List[Tuple[Chunk, float]] = []
    if db is not None:
        sparse_hits = await query_bm25(
            query_text=query_text,
            top_k=k_sparse,
            session_id=session_id,
            source_ids=source_ids,
            db=db,
        )

    if not sparse_hits:
        return dense_hits[:top_k]

    fused = reciprocal_rank_fusion(
        dense=dense_hits,
        sparse=sparse_hits,
        k=top_k,
        rrf_k=rrf_k,
        alpha_dense=alpha_dense,
        alpha_sparse=alpha_sparse,
    )
    return fused


async def delete_vector_db_data(source_ids: List[int]):
    """
    Deletes vectors from Qdrant based on a list of source_ids.
    """
    if not qdrant_client:
        raise ConnectionError("Qdrant client is not available.")
    if not source_ids:
        return
        
    qdrant_client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_id",
                        match=models.MatchAny(any=source_ids),
                    )
                ]
            )
        ),
    )
    print(f"Deleted points from Qdrant for source_ids: {source_ids}")
