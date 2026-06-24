"""工具列表接口"""
from fastapi import APIRouter
from app.schemas.response import success, error, ApiResponse
from app.schemas.tools.list import GetToolListResponse
from app.services.tools.list import get_tool_list
from app.utils.exception import ServiceException

router = APIRouter(tags=["tools"])


@router.post("/api/v1/tools/list", response_model=ApiResponse[GetToolListResponse])
def list_tools():
    try:
        tools = get_tool_list()
        return success(data={"tools": tools})
    except ServiceException as e:
        return error(code=e.code, message=e.message)
