from fastapi import APIRouter, Body

router = APIRouter()


@router.post("/workflow_response", summary="Demo endpoint to print incoming request data")
async def workflow_response(
    data: dict = Body(...),
):
    """
    Demo endpoint that prints the incoming request data.
    """
    print("Received workflow response data:")
    print(data)
    
    return {
        "message": "Data received and printed to console",
        "received_data": data
    }