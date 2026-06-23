"""工具列表接口"""
from fastapi import APIRouter
from app.schemas.response import success, ApiResponse

router = APIRouter(tags=["tools"])


@router.post("/api/v1/tools/list", response_model=ApiResponse)
def list_tools():
    return success(data={"tools": []})
