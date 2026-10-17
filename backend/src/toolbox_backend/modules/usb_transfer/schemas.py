"""定义 USB 控制面、任务记录及进程边界的数据契约。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

UINT32_MAX = 0xFFFFFFFF
StorageId = Annotated[int, Field(strict=True, ge=1, le=UINT32_MAX - 1)]
ObjectId = Annotated[int, Field(strict=True, ge=1, le=UINT32_MAX - 1)]
FolderId = Annotated[int, Field(strict=True, ge=1, le=UINT32_MAX)]
Identifier = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
LocalPath = Annotated[str, Field(min_length=1, max_length=4096)]
TaskState = Literal[
    "queued", "running", "cancelling", "completed", "partial_success",
    "failed", "cancelled", "interrupted",
]
EntryState = Literal["succeeded", "skipped", "failed", "unexecuted", "unconfirmed"]
TERMINAL_STATES = frozenset({"completed", "partial_success", "failed", "cancelled", "interrupted"})


class UsbModel(BaseModel):
    """边界禁止静默丢字段和隐式类型转换。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class UsbStorageItem(UsbModel):
    id: StorageId
    description: str = Field(max_length=4096)
    capacity_bytes: int | None = Field(None, ge=0)
    free_bytes: int | None = Field(None, ge=0)
    access_capability: int | None = Field(None, ge=0, le=65535)
    information_complete: bool = False


class UsbDeviceItem(UsbModel):
    device_id: str = Field(min_length=1, max_length=64)
    vendor_id: int = Field(ge=0, le=65535)
    product_id: int = Field(ge=0, le=65535)
    name: str = Field(max_length=4096)
    model: str = Field(default="", max_length=4096)
    serial: str | None = Field(None, max_length=4096)


class UsbSessionSummary(UsbModel):
    session_id: Identifier
    device: UsbDeviceItem
    storages: list[UsbStorageItem]
    connected_at: str
    last_device_response_at: str
    closing: bool = False


class UsbRecordError(UsbModel):
    record_id: Identifier | None = None
    message: str


class UsbStatusResponse(UsbModel):
    instance_id: Identifier
    revision: int = Field(ge=0)
    platform_supported: bool
    platform_reason: str | None = None
    dependency_available: bool
    dependency_state: Literal["unsupported", "missing", "located", "loaded", "failed"]
    dependency_reason: str | None = None
    worker_running: bool
    busy: bool
    session: UsbSessionSummary | None = None
    record_errors: list[UsbRecordError] = Field(default_factory=list)


class UsbDeviceListResponse(UsbModel):
    instance_id: Identifier
    scan_id: Identifier
    devices: list[UsbDeviceItem]


class UsbOpenSessionRequest(UsbModel):
    instance_id: Identifier
    scan_id: Identifier
    device_id: str = Field(min_length=1, max_length=64)


class UsbSessionRequest(UsbModel):
    instance_id: Identifier
    session_id: Identifier


class UsbDirectoryListRequest(UsbSessionRequest):
    storage_id: StorageId
    folder_id: FolderId


class UsbDirectoryEntry(UsbModel):
    object_id: ObjectId
    parent_id: FolderId
    storage_id: StorageId
    raw_name: str = Field(max_length=4096)
    name: str = Field(max_length=4096)
    is_folder: bool
    size_bytes: int | None = Field(None, ge=0)
    modified_at: str | None = None


class UsbDirectoryListResponse(UsbModel):
    instance_id: Identifier
    session_id: Identifier
    storage_id: StorageId
    folder_id: FolderId
    entries: list[UsbDirectoryEntry]
    complete: bool
    missing_ids: list[int] = Field(default_factory=list)
    message: str = ""


class UsbObjectRef(UsbModel):
    storage_id: StorageId
    object_id: ObjectId


class UsbCopyRequest(UsbSessionRequest):
    direction: Literal["download", "upload"]
    source_objects: list[UsbObjectRef] = Field(default_factory=list, max_length=100)
    source_paths: list[LocalPath] = Field(default_factory=list, max_length=100)
    local_target: LocalPath | None = None
    target_storage_id: StorageId | None = None
    target_folder_id: FolderId | None = None

    @model_validator(mode="after")
    def check_direction(self) -> UsbCopyRequest:
        if self.direction == "download":
            if not self.source_objects or self.source_paths or not self.local_target:
                raise ValueError("下载需要设备来源和本机目标目录")
            if self.target_storage_id is not None or self.target_folder_id is not None:
                raise ValueError("下载不能携带设备目标")
        else:
            if not self.source_paths or self.source_objects or self.local_target is not None:
                raise ValueError("上传需要本机来源和设备目标")
            if self.target_storage_id is None or self.target_folder_id is None:
                raise ValueError("缺少设备目标目录")
        for path in [*self.source_paths, *([self.local_target] if self.local_target else [])]:
            if not path.startswith("/") or "\x00" in path or any(part in {".", ".."} for part in path.split("/")):
                raise ValueError("本机路径必须是无相对跳转的绝对路径")
        return self


class UsbPreparedCopy(UsbModel):
    request: UsbCopyRequest
    submission_token: str
    expires_at: float = Field(ge=0, allow_inf_nan=False)


class UsbSubmitCopy(UsbModel):
    request: UsbCopyRequest
    submission_token: str = Field(min_length=1, max_length=4096)


class UsbTaskRequest(UsbModel):
    task_id: Identifier


class UsbTaskEntriesRequest(UsbTaskRequest):
    offset: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=100)


class UsbProgress(UsbModel):
    stage: str = Field(default="queued", max_length=64)
    current_name: str = Field(default="", max_length=4096)
    discovered: int = Field(default=0, ge=0)
    processed: int = Field(default=0, ge=0)
    known_bytes: int = Field(default=0, ge=0)
    total_known: bool = False
    current_sent: int = Field(default=0, ge=0)
    current_total: int | None = Field(None, ge=0)


class UsbCounts(UsbModel):
    succeeded: int = Field(0, ge=0)
    reused: int = Field(0, ge=0)
    skipped: int = Field(0, ge=0)
    failed: int = Field(0, ge=0)
    unexecuted: int = Field(0, ge=0)
    unconfirmed: int = Field(0, ge=0)
    copied_bytes: int = Field(0, ge=0)
    effects: int = Field(0, ge=0)


class UsbEntryResult(UsbModel):
    entry_id: str = Field(min_length=1, max_length=64)
    source: str = Field(max_length=16384)
    raw_name: str = Field(max_length=4096)
    destination: str = Field(default="", max_length=16384)
    status: EntryState
    is_folder: bool = False
    message: str = Field(default="", max_length=4096)
    size_bytes: int | None = Field(None, ge=0)
    effect: bool = False
    reused: bool = False
    object_id: int | None = Field(None, ge=1, le=UINT32_MAX - 1)
    residual: str | None = Field(None, max_length=16384)
    size_checked: bool = False


class UsbTaskSummary(UsbModel):
    task_id: Identifier
    request: UsbCopyRequest
    target_label: str = Field(default="", max_length=16384)
    state: TaskState = "queued"
    created_at: float = Field(ge=0, allow_inf_nan=False)
    updated_at: float = Field(ge=0, allow_inf_nan=False)
    revision: int = Field(0, ge=0)
    progress: UsbProgress = Field(default_factory=UsbProgress)
    counts: UsbCounts = Field(default_factory=UsbCounts)
    entry_count: int = Field(0, ge=0)
    planned_count: int = Field(0, ge=0)
    enumeration_complete: bool = False
    stop_reason: str = ""
    message: str = "等待执行"
    cancel_requested: bool = False
    active_intent: dict[str, str] | None = None
    record_error: str | None = None
    historical: bool = False


class UsbTaskListResponse(UsbModel):
    instance_id: Identifier
    tasks: list[UsbTaskSummary]
    record_errors: list[UsbRecordError]


class UsbTaskEntriesResponse(UsbModel):
    instance_id: Identifier
    task: UsbTaskSummary
    entries: list[UsbEntryResult]
    offset: int
    total: int
    next_offset: int | None


class PlanEntry(UsbModel):
    """工作进程保留真实句柄，父进程只接收受预算约束的计划条目。"""

    entry_id: str = Field(min_length=1, max_length=64)
    parent_entry_id: str | None = Field(None, max_length=64)
    raw_name: str = Field(max_length=4096)
    source: str = Field(max_length=16384)
    is_folder: bool
    size_bytes: int | None = Field(None, ge=0)
    issue: Literal["failed", "skipped"] | None = None
    message: str = Field(default="", max_length=4096)


class TransferStart(UsbModel):
    task_id: Identifier
    request: UsbCopyRequest
    target_chain: list[UsbDirectoryEntry] = Field(default_factory=list, max_length=128)
    source_chains: dict[str, list[UsbDirectoryEntry]] = Field(default_factory=dict)
