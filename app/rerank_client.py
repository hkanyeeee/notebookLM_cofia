import httpx
from typing import List, Tuple

from .config import RERANKER_SERVICE_URL
from .models import Chunk

RERANK_MODEL = "Qwen/Qwen3-Reranker-0.6B"
DEFAULT_RERANKER_TOP_K = 20

async def rerank(query: str, hits_batch: List[Tuple[Chunk, float]], model: str = RERANK_MODEL) -> List[Tuple[Chunk, float]]:
    """
    Reranks a BATCH of search hits using a custom reranker service.
    Returns a list of tuples, where each tuple contains the chunk and its new reranker score.
    Raises an exception on API or validation errors.
    """
    if not RERANKER_SERVICE_URL:
        # The caller should handle the case where the service is not configured.
        # Returning the original hits would be problematic due to different score meanings (distance vs. relevance).
        # We will assume the caller checks for the URL before calling.
        raise ValueError("RERANKER_SERVICE_URL is not configured.")

    documents = [hit[0].content for hit in hits_batch]
    
    payload = {
        "query": query,
        "documents": documents,
    }

    async with httpx.AsyncClient() as client:
        api_url = f"{RERANKER_SERVICE_URL.rstrip('/')}/rerank"
        
        response = await client.post(api_url, json=payload, timeout=180) # Increased timeout for potentially large batches
        response.raise_for_status() # Raises HTTPStatusError for 4xx/5xx responses
        
        data = response.json()
        scores = data.get('scores')

        if scores is None or len(scores) != len(hits_batch):
            raise ValueError(f"Reranker returned an invalid response. Number of scores does not match number of documents. Scores: {scores}")

        original_chunks = [hit[0] for hit in hits_batch]
        scored_chunks = list(zip(original_chunks, scores))
        
        return scored_chunks
