from fastapi import APIRouter
from app.services.orchestrator_service import run_pipeline


router = APIRouter()

@router.post("/test-pipeline")
async def test_pipeline():
    session_id = "test_session_1"

    result = await run_pipeline(session_id)

    return {
        "status": "success",
        "data": result
    }
