"""USB 控制面编排：会话、引用、后台队列与监管；API 进程不加载原生 USB 库。"""

from __future__ import annotations

import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from collections.abc import Iterator

from pydantic import Field, JsonValue, ValidationError

from toolbox_backend.core.config import settings
from toolbox_backend.core.errors import ServiceException
from toolbox_backend.modules.usb_transfer.executor import Executor
from toolbox_backend.modules.usb_transfer.records import RecordError, RecordStore
from toolbox_backend.modules.usb_transfer.protocol import Operation
from toolbox_backend.modules.usb_transfer.schemas import (
    TERMINAL_STATES, TransferStart, UsbCopyRequest, UsbDeviceItem, UsbDeviceListResponse, UsbDirectoryEntry,
    UsbDirectoryListRequest, UsbDirectoryListResponse, UsbModel, UsbOpenSessionRequest,
    UsbPreparedCopy, UsbSessionRequest, UsbSessionSummary, UsbStatusResponse, UsbStorageItem,
    UsbSubmitCopy, UsbTaskEntriesRequest, UsbTaskEntriesResponse, UsbTaskListResponse,
    UsbTaskSummary,
)
from toolbox_backend.modules.usb_transfer.session import ReferenceBudgetError, UsbSession
from toolbox_backend.modules.usb_transfer.supervisor import (
    CLOSE_TIMEOUT_SECONDS, OPEN_TIMEOUT_SECONDS, SCAN_TIMEOUT_SECONDS,
    UsbWorkerSupervisor, WorkerError, WorkerUnavailableError,
)
from toolbox_backend.modules.usb_transfer.tasks import TaskError, TaskManager, TaskRuntime
from toolbox_backend.schemas.response import ErrorCode

_state_lock = threading.RLock()
_operation_lock = threading.Lock()
_initialization_lock = threading.Lock()
_supervisor = UsbWorkerSupervisor()
_manager = TaskManager(RecordStore())
_session: UsbSession | None = None
_scan_id = ""
_scanned: dict[str, tuple[int, int, int, int]] = {}
_revision = 0
_initialized = False
_stopping = False
_library_path: str | None = None
_dependency_error: str | None = None
_library_loaded = False
# 停止结果只在确认后置位；forced 表示超时或强制中断，不等同于正常停止。
_stop_confirmed = False
_stop_forced = False
# 无效响应时丢弃 worker 的等待上限，不占用完整的应用停止期限。
WORKER_DROP_SECONDS = 3.0


class _RawDevice(UsbModel):
    bus_location: int = Field(ge=0, le=0xFFFFFFFF)
    devnum: int = Field(ge=0, le=255)
    vendor_id: int = Field(ge=0, le=65535)
    product_id: int = Field(ge=0, le=65535)
    vendor: str = Field(max_length=4096)
    product: str = Field(max_length=4096)
    device_flags: int = Field(ge=0, le=0xFFFFFFFF)


class _ScanResult(UsbModel):
    devices: list[_RawDevice] = Field(max_length=1024)


class _OpenInfo(UsbModel):
    name: str
    model: str
    manufacturer: str
    serial: str | None


class _OpenResult(UsbModel):
    device: _OpenInfo
    storages: list[UsbStorageItem] = Field(max_length=128)


class _DirectoryResult(UsbModel):
    entries: list[UsbDirectoryEntry]
    missing_ids: list[int]
    complete: bool

class _StopState(UsbModel):
    active_tasks: int = Field(ge=0)
    busy: bool
    stopped: bool
    forced: bool
    record_errors: list[str] = Field(default_factory=list)


def probe_platform() -> tuple[bool, str | None]:
    return (True, None) if sys.platform == "darwin" else (False, "有线传输当前仅支持 macOS")


def initialize() -> None:
    """在 macOS 加载保留记录、启动后台管理并解析库路径，不创建 USB 子进程。

    后台管理只回收满足条件的完成记录，不恢复设备写入；其他平台不访问 USB 状态目录。
    """
    global _initialized, _library_path
    with _initialization_lock:
        if _initialized:
            return
        # 记录层使用 macOS 的目录 FD 操作；不支持的平台连状态目录也不访问。
        if sys.platform == "darwin":
            _manager.initialize()
            _library_path = settings.usb_transfer_library_path
        _initialized = True


def _stamp(value: float) -> str:
    return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")


def _require_instance(instance_id: str) -> None:
    if instance_id != _manager.instance_id:
        raise ServiceException(ErrorCode.PARAM_ERROR, "服务实例已变化，请刷新并重新确认目标")


def _refresh_library_path() -> None:
    """重新解析运行库路径，只比较文件存在性。

    状态查询与设备操作共用该逻辑：不加载库、不创建子进程、不访问设备，
    因此安装或移除运行库后无需先发起扫描就能看到新的依赖状态。
    """
    global _library_path, _dependency_error
    path = settings.usb_transfer_library_path
    with _state_lock:
        if path != _library_path:
            _library_path, _dependency_error = path, None

def _require_ready() -> None:
    global _dependency_error
    initialize()
    supported, reason = probe_platform()
    if not supported:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, reason or "平台不支持")
    if _stopping:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "有线传输正在停止")
    # 与状态查询共用路径重解析；它不加载库也不访问设备。
    _refresh_library_path()
    if _library_path is None:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "未找到 MTP 运行库（libmtp）")


def _current(session_id: str, *, allow_closing: bool = False) -> UsbSession:
    if _session is None or _session.session_id != session_id:
        raise ServiceException(ErrorCode.PARAM_ERROR, "连接已失效，请重新连接设备")
    if _session.closing and not allow_closing:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "设备连接正在关闭")
    if _session.generation != _supervisor.generation:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "设备工作进程已失效")
    return _session


@contextmanager
def _operation() -> Iterator[None]:
    global _revision
    if not _operation_lock.acquire(blocking=False):
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "设备正忙，请等待当前操作结束")
    try:
        with _state_lock:
            # 停止屏障：已通过 _require_ready 的请求到达这里时也要拒绝。
            if _stopping:
                raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "有线传输正在停止")
            _revision += 1
        yield
    finally:
        _operation_lock.release()
        with _state_lock:
            _revision += 1


def _drop_session(reason: str, generation: str | None = None, exclude_task_id: str | None = None) -> None:
    global _session, _revision
    with _state_lock:
        current = _session
        if current is None or (generation is not None and current.generation != generation):
            return
        _session = None
        _revision += 1
    _manager.invalidate_session(current.session_id, reason, exclude_task_id)


def _worker_failed(generation: str, _reason: str) -> None:
    _drop_session("worker_lost", generation)


_supervisor.set_failure_handler(_worker_failed)


def _call(op: Operation, payload: dict[str, JsonValue], *, generation: str | None = None, timeout: float = 30, long_operation: bool = False) -> dict[str, JsonValue]:
    global _dependency_error, _library_loaded, _revision
    try:
        result = _supervisor.call(op, payload, expected_generation=generation, timeout=timeout, long_operation=long_operation)
        with _state_lock:
            _library_loaded, _dependency_error = True, None
            if _session is not None and _session.generation == generation:
                _session.last_response_at = time.time()
            _revision += 1
        return result
    except WorkerError as exc:
        if exc.kind == "unavailable" and not isinstance(exc, WorkerUnavailableError):
            with _state_lock:
                _dependency_error = exc.message
        if exc.kind in {"disconnected", "not_open", "no_device", "timeout", "unavailable"}:
            if generation is not None:
                _supervisor.fail_generation(generation, exc.message)
            _drop_session("worker_lost", generation)
        code = ErrorCode.PARAM_ERROR if exc.kind in {"bad_request", "stale_reference"} else ErrorCode.SERVICE_UNAVAILABLE
        raise ServiceException(code, exc.message) from exc


def get_status() -> UsbStatusResponse:
    initialize()
    supported, platform_reason = probe_platform()
    # 只做路径存在性重解析，使安装运行库后刷新状态即可反映，不必先扫描。
    if supported:
        _refresh_library_path()
    with _state_lock:
        current = _session
        summary = None if current is None else UsbSessionSummary(
            session_id=current.session_id, device=current.device, storages=current.storages,
            connected_at=_stamp(current.created_at), last_device_response_at=_stamp(current.last_response_at),
            closing=current.closing,
        )
        state = "unsupported" if not supported else "failed" if _dependency_error else "missing" if _library_path is None else "loaded" if _library_loaded else "located"
        reason = platform_reason if not supported else _dependency_error or ("未找到 MTP 运行库（libmtp）" if _library_path is None else None)
        revision = _revision
    return UsbStatusResponse(
        instance_id=_manager.instance_id, revision=revision + _manager.revision,
        platform_supported=supported, platform_reason=platform_reason,
        dependency_available=supported and state in {"located", "loaded"}, dependency_state=state,
        dependency_reason=reason, worker_running=_supervisor.is_running(), busy=_operation_lock.locked(),
        session=summary, record_errors=_manager.record_errors,
    )


def scan_devices() -> UsbDeviceListResponse:
    global _scan_id, _scanned
    _require_ready()
    with _operation():
        with _state_lock:
            if _session is not None:
                raise ServiceException(ErrorCode.PARAM_ERROR, "请先断开当前设备再扫描")
        try:
            result = _ScanResult.model_validate(_call("scan", {}, timeout=SCAN_TIMEOUT_SECONDS))
        except ValidationError as exc:
            # 返回结构无效时丢弃当前 worker；用短期限基线避免请求长时间阻塞。
            _supervisor.shutdown(time.monotonic() + WORKER_DROP_SECONDS, seal=False)
            raise ServiceException(ErrorCode.INTERNAL_ERROR, "设备扫描返回结构无效") from exc
        devices = []
        scanned: dict[str, tuple[int, int, int, int]] = {}
        for item in result.devices:
            device_id = f"{item.bus_location}-{item.devnum}-{item.vendor_id:04x}-{item.product_id:04x}"
            scanned[device_id] = item.bus_location, item.devnum, item.vendor_id, item.product_id
            devices.append(UsbDeviceItem(device_id=device_id, vendor_id=item.vendor_id, product_id=item.product_id,
                                         name=item.product or "MTP 设备", model=item.product))
        with _state_lock:
            _scan_id, _scanned = uuid.uuid4().hex, scanned
            scan_id = _scan_id
    return UsbDeviceListResponse(instance_id=_manager.instance_id, scan_id=scan_id, devices=devices)


def open_session(body: UsbOpenSessionRequest) -> UsbStatusResponse:
    global _session, _revision
    _require_ready()
    _require_instance(body.instance_id)
    with _operation():
        with _state_lock:
            if _session is not None:
                raise ServiceException(ErrorCode.PARAM_ERROR, "请先断开当前设备")
            raw = _scanned.get(body.device_id) if body.scan_id == _scan_id else None
        if raw is None:
            raise ServiceException(ErrorCode.PARAM_ERROR, "扫描结果已失效，请重新扫描")
        session_id = uuid.uuid4().hex
        bus, devnum, vendor, product = raw
        try:
            result = _OpenResult.model_validate(_call("open", {
                "session_id": session_id, "bus_location": bus, "devnum": devnum,
                "vendor_id": vendor, "product_id": product,
            }, timeout=OPEN_TIMEOUT_SECONDS))
            generation = _supervisor.generation
            if generation is None or not result.storages:
                raise ValueError("设备打开结果失效")
        except (ValidationError, ValueError) as exc:
            # 打开结果无效时同样丢弃 worker，不把未确认的进程当成已结束。
            _supervisor.shutdown(time.monotonic() + WORKER_DROP_SECONDS, seal=False)
            raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "设备未返回有效存储或工作进程已退出") from exc
        now = time.time()
        with _state_lock:
            if _supervisor.generation != generation or not _supervisor.is_running():
                raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "设备工作进程在建立会话前已退出")
            _session = UsbSession(
                session_id=session_id, generation=generation,
                device=UsbDeviceItem(device_id=body.device_id, vendor_id=vendor, product_id=product,
                                     name=result.device.name, model=result.device.model, serial=result.device.serial),
                storages=result.storages, created_at=now, last_response_at=now,
            )
            _revision += 1
    return get_status()


def close_session(body: UsbSessionRequest) -> UsbStatusResponse:
    global _revision
    _require_instance(body.instance_id)
    with _state_lock:
        current = _current(body.session_id, allow_closing=True)
        if current.closing:
            return get_status()
        current.closing = True
        generation = current.generation
        _revision += 1
    _manager.invalidate_session(body.session_id, "session_closed")
    _supervisor.request_cancel(None)
    if not _operation_lock.acquire(blocking=False):
        # 正在执行的任务负责释放；浏览结束后由独立收尾线程串行关闭。
        threading.Thread(target=_finish_close, args=(body.session_id, generation), daemon=True, name="usb-close-session").start()
        return get_status()
    try:
        _close_idle(body.session_id, generation)
    finally:
        _operation_lock.release()
    return get_status()


def _finish_close(session_id: str, generation: str) -> None:
    with _operation_lock:
        with _state_lock:
            if _session is None or _session.session_id != session_id:
                return
            # 停止期间由 shutdown 统一释放设备，收尾线程不再发起新的原生调用。
            if _stopping:
                _drop_session("backend_shutdown", generation)
                return
        _close_idle(session_id, generation)


def _close_idle(session_id: str, generation: str, exclude_task_id: str | None = None) -> None:
    try:
        if _supervisor.generation == generation:
            _supervisor.call("close", {"session_id": session_id}, expected_generation=generation, timeout=CLOSE_TIMEOUT_SECONDS)
    except WorkerError:
        _supervisor.fail_generation(generation, "设备释放未正常完成")
    finally:
        _drop_session("session_closed", generation, exclude_task_id)


def list_directory(body: UsbDirectoryListRequest) -> UsbDirectoryListResponse:
    _require_ready()
    _require_instance(body.instance_id)
    with _operation():
        with _state_lock:
            current = _current(body.session_id)
            if not current.allows_folder(body.storage_id, body.folder_id):
                raise ServiceException(ErrorCode.PARAM_ERROR, "目录引用无效，请重新浏览")
            generation = current.generation
        try:
            result = _DirectoryResult.model_validate(_call("list", {
                "session_id": body.session_id, "storage_id": body.storage_id, "folder_id": body.folder_id,
            }, generation=generation, long_operation=True))
            if len(result.entries) > settings.USB_TRANSFER_MAX_ENTRIES or result.complete != (not result.missing_ids):
                raise ValueError("目录完整性标记无效")
            with _state_lock:
                _current(body.session_id).remember_listing(body.storage_id, body.folder_id, result.entries, result.complete)
        except ReferenceBudgetError as exc:
            raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, str(exc)) from exc
        except (ValidationError, ValueError) as exc:
            _supervisor.fail_generation(generation, "目录返回结构或归属无效")
            raise ServiceException(ErrorCode.INTERNAL_ERROR, "设备目录返回了无效结果") from exc
    return UsbDirectoryListResponse(
        instance_id=_manager.instance_id, session_id=body.session_id, storage_id=body.storage_id,
        folder_id=body.folder_id, entries=result.entries, complete=result.complete, missing_ids=result.missing_ids,
        message="" if result.complete else "目录有对象信息不可读，当前列表不完整",
    )


def _start_context(request: UsbCopyRequest) -> tuple[str, TransferStart]:
    _require_instance(request.instance_id)
    with _state_lock:
        current = _current(request.session_id)
        try:
            source_chains = {f"{ref.storage_id}:{ref.object_id}": current.chain(ref.storage_id, ref.object_id)
                             for ref in request.source_objects}
            target_chain = []
            if request.direction == "upload":
                if request.target_storage_id is None or request.target_folder_id is None or not current.allows_folder(request.target_storage_id, request.target_folder_id):
                    raise ValueError("上传目标引用无效")
                target_chain = current.chain(request.target_storage_id, request.target_folder_id)
            return current.generation, TransferStart(task_id="0" * 32, request=request,
                                                     source_chains=source_chains, target_chain=target_chain)
        except ValueError as exc:
            raise ServiceException(ErrorCode.PARAM_ERROR, str(exc)) from exc


def prepare_copy(request: UsbCopyRequest) -> UsbPreparedCopy:
    _require_ready()
    # 固定来源集合的顺序与去重，使相同未结束请求可以防重。
    normalized = request.model_copy(deep=True)
    normalized.source_paths = sorted(set(request.source_paths))
    normalized.source_objects = sorted({(item.storage_id, item.object_id): item for item in request.source_objects}.values(), key=lambda item: (item.storage_id, item.object_id))
    _, context = _start_context(normalized)
    if len(context.model_dump_json().encode("utf-8")) + 1024 > settings.USB_TRANSFER_MAX_MESSAGE_BYTES:
        raise ServiceException(ErrorCode.PARAM_ERROR, "设备归属信息超过通信预算，请缩小所选范围")
    try:
        return _manager.prepare(normalized)
    except TaskError as exc:
        raise ServiceException(ErrorCode.PARAM_ERROR, str(exc)) from exc


def submit_copy(body: UsbSubmitCopy) -> UsbTaskSummary:
    initialize()
    _require_instance(body.request.instance_id)
    try:
        previous = _manager.lookup_submission(body.request, body.submission_token)
        if previous is not None:
            return previous
        _require_ready()
        generation, start = _start_context(body.request)
        return _manager.submit(body.request, body.submission_token, generation, start)
    except (TaskError, RecordError) as exc:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, str(exc)) from exc


def list_tasks() -> UsbTaskListResponse:
    initialize()
    return UsbTaskListResponse(instance_id=_manager.instance_id, tasks=_manager.list(), record_errors=_manager.record_errors)


def task_entries(body: UsbTaskEntriesRequest) -> UsbTaskEntriesResponse:
    try:
        return _manager.entries(body.task_id, body.offset, body.limit)
    except (TaskError, RecordError) as exc:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, str(exc)) from exc


def cancel_task(task_id: str) -> UsbTaskSummary:
    try:
        return _manager.cancel(task_id)
    except TaskError as exc:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, str(exc)) from exc


def remove_record(task_id: str) -> UsbTaskListResponse:
    try:
        _manager.remove(task_id)
    except (TaskError, RecordError) as exc:
        raise ServiceException(ErrorCode.PARAM_ERROR, str(exc)) from exc
    return list_tasks()


def _acquire_task(runtime: TaskRuntime) -> TransferStart:
    while not _operation_lock.acquire(timeout=0.1):
        if runtime.cancel.is_set():
            raise WorkerError("cancelled", "任务已停止")
    try:
        with _state_lock:
            current = _current(runtime.summary.request.session_id)
            if current.generation != runtime.generation or runtime.start is None:
                raise WorkerError("not_open", "任务所属设备会话已失效")
            return runtime.start
    except ServiceException as exc:
        _operation_lock.release()
        raise WorkerError("not_open", exc.message) from exc
    except BaseException:
        _operation_lock.release()
        raise


def _disconnect_task(runtime: TaskRuntime) -> None:
    _close_idle(runtime.summary.request.session_id, runtime.generation, runtime.summary.task_id)


_executor = Executor(_manager, _supervisor, _acquire_task, _operation_lock.release, _disconnect_task)
_manager.configure(_executor.execute, _supervisor.request_cancel)


def shutdown() -> _StopState:
    """停止接收任务、中断旧队列、确认线程与工作进程退出，并返回真实结果。

    超时或强制中断不冒充正常停止；写前记录仍是结果不确定时的唯一兜底。
    """
    global _stopping, _stop_confirmed, _stop_forced
    with _state_lock:
        _stopping = True
        current = _session
    deadline = time.monotonic() + settings.APP_SHUTDOWN_TIMEOUT_SECONDS
    # 先中断旧会话队列，避免取消后又被重新调度。
    if current is not None:
        _manager.invalidate_session(current.session_id, "backend_shutdown")
    tasks_confirmed = _manager.shutdown(deadline)
    # 执行中的任务取消后仍可能持有操作锁，等它真正释放再关工作进程。
    barrier = _acquire_exit_barrier(deadline)
    worker_confirmed = _supervisor.shutdown(deadline)
    _drop_session("backend_shutdown")
    confirmed = tasks_confirmed and barrier and worker_confirmed
    with _state_lock:
        _stop_confirmed = confirmed
        _stop_forced = not confirmed
    return stop_state()

def _acquire_exit_barrier(deadline: float) -> bool:
    """确认没有设备操作在途；超时返回 False，不假装已经静止。"""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if _operation_lock.acquire(timeout=min(0.1, remaining)):
            _operation_lock.release()
            return True

def stop_state() -> _StopState:
    """报告停止进度；非 macOS 或未初始化时不访问 USB 状态目录。"""
    active = 0
    errors: list[str] = []
    if _initialized:
        active = sum(1 for task in _manager.list() if task.state not in TERMINAL_STATES)
        errors = [item.message for item in _manager.record_errors]
    with _state_lock:
        busy = _operation_lock.locked() or _supervisor.is_running()
        return _StopState(
            active_tasks=active, busy=busy, stopped=_stop_confirmed,
            forced=_stop_forced, record_errors=errors,
        )
