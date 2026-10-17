"""桌面运行时控制接口：报告所属实例状态并请求有序停止，不暴露凭据或设备操作。"""

from __future__ import annotations

from fastapi import APIRouter

from toolbox_backend import lifecycle
from toolbox_backend.core import runtime
from toolbox_backend.core.errors import ServiceException
from toolbox_backend.modules.usb_transfer import service as usb_transfer_service
from toolbox_backend.schemas.response import ApiResponse, ErrorCode, success
from toolbox_backend.schemas.runtime import RuntimeRequest, RuntimeStatus

router = APIRouter(prefix="/runtime", tags=["runtime"])

def _snapshot(expected_instance_id: str) -> RuntimeStatus:
    """按预期实例生成快照；实例不符时拒绝，避免操作或停止其他后端。"""
    owner = runtime.identity()
    if owner.instance_id != expected_instance_id:
        raise ServiceException(ErrorCode.PARAM_ERROR, "后端实例已变化，请刷新后重试")
    stop_state = usb_transfer_service.stop_state()
    return RuntimeStatus(
        **owner.model_dump(),
        phase=runtime.phase(),
        usb_active_tasks=stop_state.active_tasks,
        usb_busy=stop_state.busy,
        usb_stopped=stop_state.stopped,
        usb_forced=stop_state.forced,
        record_errors=list(stop_state.record_errors),
    )

@router.post("/status", response_model=ApiResponse[RuntimeStatus])
def runtime_status(body: RuntimeRequest) -> dict[str, object]:
    """只读报告当前阶段和 USB 停止确认情况，不触发停止。"""
    return success(data=_snapshot(body.expected_instance_id))

@router.post("/stop", response_model=ApiResponse[RuntimeStatus])
def runtime_stop(body: RuntimeRequest) -> dict[str, object]:
    """阻塞到停止确认或超时后返回真实状态；超时结果不冒充正常停止。"""
    owner = runtime.identity()
    if owner.instance_id != body.expected_instance_id:
        raise ServiceException(ErrorCode.PARAM_ERROR, "后端实例已变化，请刷新后重试")
    lifecycle.request_shutdown("desktop_stop")
    return success(data=_snapshot(body.expected_instance_id))
