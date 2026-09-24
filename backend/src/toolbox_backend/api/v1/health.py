"""健康检查接口。"""

from fastapi import APIRouter

from toolbox_backend.schemas.response import ApiResponse, success

router = APIRouter(tags=["health"])


@router.post("/health", response_model=ApiResponse)
def health_check() -> dict[str, object]:
    """返回本地后端已完成启动的状态。"""
    return success(data={"status": "ok"})
