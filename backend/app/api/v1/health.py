from fastapi import APIRouter
from app.schemas.response import success, ApiResponse

router = APIRouter(tags=["health"])


@router.post("/api/v1/health", response_model=ApiResponse)
def health_check():
    return success(data={"status": "ok"})
