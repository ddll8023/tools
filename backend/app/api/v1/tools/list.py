"""工具列表接口。"""

from fastapi import APIRouter

from app.schemas.response import ApiResponse, success
from app.schemas.tools.list import GetToolListResponse
from app.services.tools.list import get_tool_list

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/list", response_model=ApiResponse[GetToolListResponse])
def list_tools() -> dict[str, object]:
    """返回工具目录和启动期探测到的可用状态。"""
    return success(data={"tools": get_tool_list()})
