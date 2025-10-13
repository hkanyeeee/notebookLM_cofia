from typing import Annotated
from fastapi import Header, HTTPException



async def get_session_id(x_session_id: Annotated[str, Header()]) -> str:
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header is required.")
    return x_session_id



# Re-export routers for convenient import in app.main
from .ingest import router as ingest_router
from .documents import router as documents_router
from .search import router as search_router
from .query import router as query_router
from .models import router as models_router

__all__ = [
    "get_session_id",
    "ingest_router",
    "documents_router",
    "search_router",
    "query_router",
    "models_router",
]
