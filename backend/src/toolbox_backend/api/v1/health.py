"""健康检查接口：附带本次启动身份，使启动器能排除旧实例或其他服务。"""

from fastapi import APIRouter

from toolbox_backend.core import runtime
from toolbox_backend.schemas.response import ApiResponse, success

router = APIRouter(tags=["health"])

@router.post("/health", response_model=ApiResponse)
def health_check() -> dict[str, object]:
    """返回本次启动的身份与阶段；不返回凭据，也不代表设备可用。"""
    owner = runtime.identity()
    return success(data={
        "status": "ok",
        "instance_id": owner.instance_id,
        "launch_id": owner.launch_id,
        "pid": owner.pid,
        "phase": runtime.phase(),
    })
