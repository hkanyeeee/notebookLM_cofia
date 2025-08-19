from typing import Annotated
from fastapi import Header, HTTPException
from . import workflow_response


async def get_session_id(x_session_id: Annotated[str, Header()]) -> str:
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header is required.")
    return x_session_id


