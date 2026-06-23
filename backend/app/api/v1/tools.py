from fastapi import APIRouter
from app.schemas.response import success, ApiResponse

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


@router.post("/list", response_model=ApiResponse)
def list_tools():
    return success(data={"tools": []})
