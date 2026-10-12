"""局域网投送控制面接口。"""

from fastapi import APIRouter

from toolbox_backend.modules.lan_transfer import service
from toolbox_backend.modules.lan_transfer.schemas import (
    AddOutgoingRequest,
    LanOutgoingListResponse,
    LanPendingListResponse,
    LanPreferencesResponse,
    LanPreferencesUpdateRequest,
    LanReceiveRecordListResponse,
    LanRecoveryResponse,
    LanSessionResponse,
    PassphraseRequest,
    PendingFileRequest,
    RemoveOutgoingRequest,
)
from toolbox_backend.schemas.response import ApiResponse, success

router = APIRouter(prefix="/tools/lan-transfer", tags=["lan-transfer"])


@router.post("/session/start", response_model=ApiResponse[LanSessionResponse])
def start_session() -> dict[str, object]:
    """开启局域网投送会话。"""
    return success(data=service.start_session())


@router.post("/session/status", response_model=ApiResponse[LanSessionResponse])
def get_session_status() -> dict[str, object]:
    """查询当前投送会话状态。"""
    return success(data=service.get_status())


@router.post("/session/stop", response_model=ApiResponse[LanSessionResponse])
def stop_session() -> dict[str, object]:
    """停止投送会话并完成关闭协调。"""
    return success(data=service.stop_session())


@router.post("/session/passphrase", response_model=ApiResponse[LanSessionResponse])
def set_passphrase(body: PassphraseRequest) -> dict[str, object]:
    """设置或清除当前会话的访问口令。"""
    return success(data=service.set_passphrase(body.passphrase))


@router.post("/pending/list", response_model=ApiResponse[LanPendingListResponse])
def list_pending() -> dict[str, object]:
    """返回等待确认的接收内容。"""
    return success(data=service.list_pending())


@router.post("/pending/accept", response_model=ApiResponse[LanPendingListResponse])
def accept_pending(body: PendingFileRequest) -> dict[str, object]:
    """接收指定文件并移入接收目录。"""
    return success(data=service.accept_pending(body.upload_id))


@router.post("/pending/reject", response_model=ApiResponse[LanPendingListResponse])
def reject_pending(body: PendingFileRequest) -> dict[str, object]:
    """拒绝指定文件并删除其隔离内容。"""
    return success(data=service.reject_pending(body.upload_id))


@router.post("/send/list", response_model=ApiResponse[LanOutgoingListResponse])
def list_outgoing() -> dict[str, object]:
    """返回等待对方取件的文件清单。"""
    return success(data=service.list_outgoing())


@router.post("/send/add", response_model=ApiResponse[LanOutgoingListResponse])
def add_outgoing(body: AddOutgoingRequest) -> dict[str, object]:
    """把本机文件加入待取件清单。"""
    return success(data=service.add_outgoing(body.paths))


@router.post("/send/remove", response_model=ApiResponse[LanOutgoingListResponse])
def remove_outgoing(body: RemoveOutgoingRequest) -> dict[str, object]:
    """从待取件清单移除文件。"""
    return success(data=service.remove_outgoing(body.file_id))


@router.post("/settings/get", response_model=ApiResponse[LanPreferencesResponse])
def get_preferences() -> dict[str, object]:
    """返回设备名与接收目录的生效值。"""
    return success(data=service.get_preferences())


@router.post("/settings/update", response_model=ApiResponse[LanPreferencesResponse])
def update_preferences(body: LanPreferencesUpdateRequest) -> dict[str, object]:
    """更新设备名与接收目录；字段传空字符串表示回退默认值。"""
    return success(
        data=service.update_preferences(
            device_name=body.device_name,
            receive_dir=body.receive_dir,
        )
    )


@router.post("/records/list", response_model=ApiResponse[LanReceiveRecordListResponse])
def list_receive_records() -> dict[str, object]:
    """返回接收成功的文件记录。"""
    return success(data=service.list_receive_records())


@router.post("/recovery/last", response_model=ApiResponse[LanRecoveryResponse])
def get_last_recovery() -> dict[str, object]:
    """返回本次启动回收上次遗留内容的结果。"""
    return success(data=service.get_last_recovery())
