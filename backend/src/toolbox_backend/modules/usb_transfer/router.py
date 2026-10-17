"""USB 已认证控制面：设备会话、目录及双向复制任务统一使用 POST。"""

from fastapi import APIRouter

from toolbox_backend.modules.usb_transfer import service
from toolbox_backend.modules.usb_transfer.schemas import (
    UsbCopyRequest, UsbDeviceListResponse, UsbDirectoryListRequest, UsbDirectoryListResponse,
    UsbOpenSessionRequest, UsbPreparedCopy, UsbSessionRequest, UsbStatusResponse, UsbSubmitCopy,
    UsbTaskEntriesRequest, UsbTaskEntriesResponse, UsbTaskListResponse, UsbTaskRequest, UsbTaskSummary,
)
from toolbox_backend.schemas.response import ApiResponse, success

router = APIRouter(prefix="/tools/usb-transfer", tags=["usb-transfer"])


@router.post("/status", response_model=ApiResponse[UsbStatusResponse])
def get_status() -> dict[str, object]:
    return success(data=service.get_status())


@router.post("/devices/scan", response_model=ApiResponse[UsbDeviceListResponse])
def scan_devices() -> dict[str, object]:
    return success(data=service.scan_devices())


@router.post("/session/open", response_model=ApiResponse[UsbStatusResponse])
def open_session(body: UsbOpenSessionRequest) -> dict[str, object]:
    return success(data=service.open_session(body))


@router.post("/session/close", response_model=ApiResponse[UsbStatusResponse])
def close_session(body: UsbSessionRequest) -> dict[str, object]:
    return success(data=service.close_session(body))


@router.post("/directory/list", response_model=ApiResponse[UsbDirectoryListResponse])
def list_directory(body: UsbDirectoryListRequest) -> dict[str, object]:
    return success(data=service.list_directory(body))


@router.post("/tasks/prepare", response_model=ApiResponse[UsbPreparedCopy])
def prepare_copy(body: UsbCopyRequest) -> dict[str, object]:
    return success(data=service.prepare_copy(body))


@router.post("/tasks/submit", response_model=ApiResponse[UsbTaskSummary])
def submit_copy(body: UsbSubmitCopy) -> dict[str, object]:
    return success(data=service.submit_copy(body))


@router.post("/tasks/list", response_model=ApiResponse[UsbTaskListResponse])
def list_tasks() -> dict[str, object]:
    return success(data=service.list_tasks())


@router.post("/tasks/entries", response_model=ApiResponse[UsbTaskEntriesResponse])
def task_entries(body: UsbTaskEntriesRequest) -> dict[str, object]:
    return success(data=service.task_entries(body))


@router.post("/tasks/cancel", response_model=ApiResponse[UsbTaskSummary])
def cancel_task(body: UsbTaskRequest) -> dict[str, object]:
    return success(data=service.cancel_task(body.task_id))


@router.post("/tasks/remove", response_model=ApiResponse[UsbTaskListResponse])
def remove_record(body: UsbTaskRequest) -> dict[str, object]:
    return success(data=service.remove_record(body.task_id))
