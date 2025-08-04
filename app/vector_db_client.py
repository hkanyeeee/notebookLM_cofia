import os
from typing import List, Tuple, Optional

from qdrant_client import QdrantClient, models
from sqlalchemy import select
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
        qdrant_client.get_collection(collection_name=COLLECTION_NAME)
    except Exception:
        print(f"Collection '{COLLECTION_NAME}' not found. Creating it.")
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
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
    top_k: int = 10,
    session_id: Optional[str] = None,
    source_ids: Optional[List[int]] = None
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
        with_payload=True # We need the payload to reconstruct the Chunk object
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
