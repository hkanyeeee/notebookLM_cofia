from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db
from ..models import Source, Chunk
from ..vector_db_client import delete_vector_db_data
from . import get_session_id


router = APIRouter()


@router.delete("/documents/{document_id}", summary="Delete a single document and its associated data")
async def delete_document(
    document_id: int,
    session_id: str = Depends(get_session_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        # 1. Find the source and verify it belongs to the current session
        stmt = select(Source).where(Source.id == document_id, Source.session_id == session_id)
        result = await db.execute(stmt)
        source_to_delete = result.scalars().first()

        if not source_to_delete:
            raise HTTPException(
                status_code=404,
                detail=f"Document with id {document_id} not found or you don't have permission to delete it.",
            )

        # 2. Delete from vector DB using the source_id
        await delete_vector_db_data([document_id])

        # 3. Delete from SQL database
        # 若未触发 ORM 级联，显式删除 chunks 以防遗留
        await db.execute(Chunk.__table__.delete().where(Chunk.source_id == document_id))
        await db.delete(source_to_delete)
        await db.commit()

        return {"success": True, "message": f"Successfully deleted document {document_id}"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {e}")


@router.post("/session/cleanup", summary="Clean up all data for a given session")
async def cleanup_session(
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required.")

    try:
        # 1. Find all source IDs for the session
        stmt = select(Source.id).where(Source.session_id == session_id)
        result = await db.execute(stmt)
        source_ids = result.scalars().all()

        if not source_ids:
            return {"success": True, "message": "No data found for the session."}

        # 2. Delete from vector DB
        await delete_vector_db_data(source_ids)

        # 3. Delete from SQL database，先删 chunks 再删 sources，避免孤儿数据
        await db.execute(Chunk.__table__.delete().where(Chunk.session_id == session_id))
        await db.execute(Source.__table__.delete().where(Source.session_id == session_id))
        await db.commit()

        return {"success": True, "message": f"Successfully cleaned up data for session {session_id}"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {e}")


