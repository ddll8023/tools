"""USB 内存任务权威状态、单会话 FIFO 和实例绑定的有限期幂等提交。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from toolbox_backend.core.config import settings
from toolbox_backend.modules.usb_transfer.records import RecordError, RecordStore, count_result
from toolbox_backend.modules.usb_transfer.schemas import (
    PlanEntry, TERMINAL_STATES, UsbCopyRequest, UsbEntryResult, UsbPreparedCopy,
    UsbProgress, UsbRecordError, UsbTaskEntriesResponse, UsbTaskSummary, TransferStart,
)


class TaskError(Exception):
    pass


@dataclass
class TaskRuntime:
    summary: UsbTaskSummary
    generation: str
    start: TransferStart | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    io_lock: threading.RLock = field(default_factory=threading.RLock)
    interrupted_reason: str = ""
    stop_connection: bool = False


@dataclass(frozen=True)
class _Receipt:
    digest: str
    task_id: str
    expires_at: float


class TaskManager:
    def __init__(self, store: RecordStore) -> None:
        self.instance_id = uuid.uuid4().hex
        self.store = store
        self.lock = threading.RLock()
        self._condition = threading.Condition(self.lock)
        self._admission = threading.Lock()
        self._secret = secrets.token_bytes(32)
        self._tasks: dict[str, TaskRuntime] = {}
        self._receipts: dict[str, _Receipt] = {}
        self._queue: deque[str] = deque()
        self._invalid_sessions: dict[str, str] = {}
        self._active: str | None = None
        self._thread: threading.Thread | None = None
        self._runner: Callable[[TaskRuntime], None] | None = None
        self._cancel_worker: Callable[[str], None] | None = None
        self._stopping = False
        self._initialized = False
        self._revision = 0
        self._record_errors: list[UsbRecordError] = []

    @property
    def revision(self) -> int:
        with self.lock:
            return self._revision

    @property
    def record_errors(self) -> list[UsbRecordError]:
        with self.lock:
            return [item.model_copy() for item in self._record_errors]

    def initialize(self) -> None:
        with self._admission:
            if self._initialized:
                return
            tasks = self.store.load()
            with self.lock:
                self._record_errors = [item.model_copy() for item in self.store.errors]
                for task in tasks:
                    self._tasks[task.task_id] = TaskRuntime(task, "")
                self._initialized = True
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, daemon=True, name="usb-task-executor")
                    self._thread.start()

    def configure(self, runner: Callable[[TaskRuntime], None], cancel_worker: Callable[[str], None]) -> None:
        self._runner, self._cancel_worker = runner, cancel_worker

    @staticmethod
    def _digest(request: UsbCopyRequest) -> str:
        value = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(value.encode("ascii")).hexdigest()

    def prepare(self, request: UsbCopyRequest) -> UsbPreparedCopy:
        if request.instance_id != self.instance_id:
            raise TaskError("服务实例已变化，请重新准备任务")
        if len(request.model_dump_json().encode("utf-8")) > min(131072, settings.USB_TRANSFER_MAX_MESSAGE_BYTES // 2):
            raise TaskError("所选来源路径集合超过通信与记录预算，请缩小选择")
        expires = time.time() + settings.USB_TRANSFER_SUBMISSION_TTL
        raw = json.dumps({"instance": self.instance_id, "submission": uuid.uuid4().hex,
                          "digest": self._digest(request), "expires": expires}, separators=(",", ":")).encode("ascii")
        token = base64.urlsafe_b64encode(raw).decode("ascii") + "." + hmac.new(self._secret, raw, hashlib.sha256).hexdigest()
        return UsbPreparedCopy(request=request, submission_token=token, expires_at=expires)

    def _ticket(self, token: str, request: UsbCopyRequest) -> tuple[str, str, float]:
        try:
            encoded, signature = token.split(".", 1)
            raw = base64.b64decode(encoded.encode("ascii"), altchars=b"-_", validate=True)
            expected = hmac.new(self._secret, raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get("instance") != self.instance_id:
                raise ValueError
            submission, digest, expires = value["submission"], value["digest"], value["expires"]
            if not isinstance(submission, str) or len(submission) != 32 or digest != self._digest(request):
                raise ValueError
            if type(expires) not in {float, int} or expires <= time.time():
                raise ValueError
            return submission, digest, float(expires)
        except (ValueError, KeyError, UnicodeError, TypeError) as exc:
            raise TaskError("提交凭据失效、过期或请求已改变；请重新确认并准备任务") from exc

    def _touch(self, task: UsbTaskSummary) -> None:
        self._revision += 1
        task.revision += 1
        task.updated_at = time.time()

    def snapshot(self, runtime: TaskRuntime) -> UsbTaskSummary:
        with self.lock:
            return runtime.summary.model_copy(deep=True)

    def list(self) -> list[UsbTaskSummary]:
        with self.lock:
            return [item.summary.model_copy(deep=True) for item in reversed(list(self._tasks.values()))]

    def get(self, task_id: str) -> TaskRuntime:
        with self.lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise TaskError("任务不存在或记录已移除，不会重新执行旧提交")
            return task

    def persist(self, runtime: TaskRuntime) -> None:
        with runtime.io_lock:
            try:
                self.store.save(self.snapshot(runtime))
            except RecordError as exc:
                self.record_failure(runtime, str(exc))
                raise

    def record_failure(self, runtime: TaskRuntime, message: str) -> None:
        with self.lock:
            runtime.summary.record_error = message
            runtime.cancel.set()
            runtime.stop_connection = True
            self._touch(runtime.summary)

    def _prune(self) -> None:
        """释放过期凭据映射，回收无有效凭据关联且无记录错误的完成记录。

        当前实例的完成记录还需超过配置保留期，历史完成记录不受该期限限制；
        完成包括全部跳过或仅复用，其他终态记录及传输文件不在回收范围。
        """
        now = time.time()
        with self.lock:
            self._receipts = {key: value for key, value in self._receipts.items() if value.expires_at > now}
            referenced = {value.task_id for value in self._receipts.values()}
            expired = [item for item in self._tasks.values() if item.summary.state == "completed"
                       and not item.summary.record_error and item.summary.task_id not in referenced
                       and (item.summary.historical or now - item.summary.updated_at > settings.USB_TRANSFER_SUBMISSION_TTL)]
        for runtime in expired:
            try:
                self.store.remove(runtime.summary.task_id)
            except RecordError as exc:
                with self.lock:
                    if not any(item.record_id == runtime.summary.task_id for item in self._record_errors):
                        self._record_errors.append(UsbRecordError(record_id=runtime.summary.task_id, message=str(exc)))
                continue
            with self.lock:
                self._tasks.pop(runtime.summary.task_id, None)
                self._revision += 1

    def lookup_submission(self, request: UsbCopyRequest, token: str) -> UsbTaskSummary | None:
        submission, digest, _ = self._ticket(token, request)
        with self.lock:
            receipt = self._receipts.get(submission)
            if receipt is None:
                return None
            if receipt.digest != digest:
                raise TaskError("同一提交凭据不能用于不同请求")
            return self.snapshot(self.get(receipt.task_id))

    def submit(self, request: UsbCopyRequest, token: str, generation: str, start: TransferStart) -> UsbTaskSummary:
        submission, digest, expires = self._ticket(token, request)
        with self._admission:
            with self.lock:
                receipt = self._receipts.get(submission)
                if receipt is not None:
                    if receipt.digest != digest:
                        raise TaskError("同一提交凭据不能用于不同请求")
                    return self.snapshot(self.get(receipt.task_id))
            try:
                self._prune()
            except RecordError as exc:
                raise TaskError(str(exc)) from exc
            with self.lock:
                if self._stopping or request.session_id in self._invalid_sessions:
                    raise TaskError("设备会话已停止接收任务")
                if self._record_errors or any(item.summary.record_error for item in self._tasks.values()):
                    raise TaskError("存在不可读或写入失败的 USB 记录，请处理记录后再提交")
                if len(self._receipts) >= settings.USB_TRANSFER_MAX_RECORDS * 4:
                    raise TaskError("本次实例的幂等记录已达预算，请等待提交凭据到期")
                duplicate = next((item for item in self._tasks.values() if item.summary.state not in TERMINAL_STATES
                                  and self._digest(item.summary.request) == digest), None)
                if duplicate is not None:
                    self._receipts[submission] = _Receipt(digest, duplicate.summary.task_id, expires)
                    return self.snapshot(duplicate)
                active_count = sum(item.summary.state not in TERMINAL_STATES for item in self._tasks.values())
                if active_count >= settings.USB_TRANSFER_MAX_QUEUE or len(self._tasks) >= settings.USB_TRANSFER_MAX_RECORDS:
                    raise TaskError("队列或记录预算已满，请等待任务完成或移除终态记录")
                now = time.time()
                target_label = request.local_target or (
                    f"设备存储 {request.target_storage_id}/" + "/".join(item.name for item in start.target_chain)
                )
                task = UsbTaskSummary(task_id=uuid.uuid4().hex, request=request, target_label=target_label[:16384],
                                      created_at=now, updated_at=now)
                context = start.model_copy(deep=True)
                context.task_id = task.task_id
                runtime = TaskRuntime(task, generation, start=context)
            try:
                self.store.create(task)
            except RecordError as exc:
                with self.lock:
                    self._record_errors.append(UsbRecordError(record_id=task.task_id, message=str(exc)))
                raise TaskError(str(exc)) from exc
            with self._condition:
                self._tasks[task.task_id] = runtime
                self._receipts[submission] = _Receipt(digest, task.task_id, expires)
                if request.session_id in self._invalid_sessions or self._stopping:
                    task.state, task.stop_reason = "interrupted", "session_invalidated"
                    task.message = "提交期间会话失效，任务不会执行"
                self._touch(task)
                self._queue.append(task.task_id)
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, daemon=True, name="usb-task-executor")
                    self._thread.start()
                self._condition.notify_all()
            return self.snapshot(runtime)

    def update_progress(self, runtime: TaskRuntime, progress: UsbProgress) -> None:
        with self.lock:
            if runtime.summary.state in TERMINAL_STATES:
                return
            runtime.summary.progress = progress.model_copy(deep=True)
            self._touch(runtime.summary)

    def set_plan(self, runtime: TaskRuntime, count: int, complete: bool, known_bytes: int) -> None:
        with self.lock:
            task = runtime.summary
            task.planned_count, task.enumeration_complete = count, complete
            task.progress = UsbProgress(stage="copying" if not runtime.cancel.is_set() else "stopping",
                                       discovered=count, known_bytes=known_bytes, total_known=complete)
            self._touch(task)

    def begin_item(self, runtime: TaskRuntime, entry: PlanEntry) -> None:
        with self.lock:
            runtime.summary.active_intent = {
                "entry_id": entry.entry_id, "source": entry.source, "raw_name": entry.raw_name,
                "target": runtime.summary.request.local_target or f"设备存储 {runtime.summary.request.target_storage_id}",
                "temporary_name": f".toolbox-usb-{runtime.summary.task_id}-{entry.entry_id}.part",
            }
            self._touch(runtime.summary)
        self.persist(runtime)

    def append(self, runtime: TaskRuntime, entry: UsbEntryResult) -> None:
        with runtime.io_lock:
            with self.lock:
                sequence = runtime.summary.entry_count
            try:
                self.store.append(runtime.summary.task_id, sequence, entry)
                with self.lock:
                    count_result(runtime.summary.counts, entry)
                    runtime.summary.entry_count += 1
                    if runtime.summary.active_intent and runtime.summary.active_intent.get("entry_id") == entry.entry_id:
                        runtime.summary.active_intent = None
                    self._touch(runtime.summary)
                self.store.save(self.snapshot(runtime))
            except RecordError as exc:
                self.record_failure(runtime, str(exc))
                raise

    def cancel(self, task_id: str) -> UsbTaskSummary:
        runtime = self.get(task_id)
        with self.lock:
            task = runtime.summary
            if task.state in TERMINAL_STATES:
                return self.snapshot(runtime)
            task.cancel_requested = True
            runtime.cancel.set()
            if task.state == "queued":
                task.state, task.stop_reason, task.message = "cancelled", "user_cancel", "排队任务已取消，未操作设备"
            else:
                task.state, task.message = "cancelling", "正在取消，尚未确认停止"
                runtime.stop_connection = True
            self._touch(task)
        if self._active == task_id and self._cancel_worker:
            self._cancel_worker(task_id)
        try:
            self.persist(runtime)
        except RecordError:
            pass
        return self.snapshot(runtime)

    def invalidate_session(self, session_id: str, reason: str, exclude_task_id: str | None = None) -> None:
        with self._condition:
            self._invalid_sessions[session_id] = reason
            for runtime in self._tasks.values():
                task = runtime.summary
                if task.task_id == exclude_task_id or task.request.session_id != session_id or task.state in TERMINAL_STATES:
                    continue
                runtime.interrupted_reason = reason
                runtime.cancel.set()
                runtime.stop_connection = True
                if task.state == "queued":
                    task.state, task.stop_reason, task.message = "interrupted", reason, "原设备会话已失效，排队任务不会继续"
                else:
                    task.state, task.message = "cancelling", "连接停止中，正在收集已完成结果"
                self._touch(task)
            self._condition.notify_all()

    def finish(self, runtime: TaskRuntime, reason: str = "") -> None:
        with self.lock:
            task, counts = runtime.summary, runtime.summary.counts
            if runtime.interrupted_reason or reason in {"worker_lost", "cancel_timeout", "record_error", "session_invalidated"}:
                task.state = "interrupted"
                task.stop_reason = runtime.interrupted_reason or reason
                task.message = "任务已中断；已完成内容保留，未确认结果不会当作成功"
            elif task.cancel_requested:
                task.state, task.stop_reason = "cancelled", "user_cancel"
                task.message = "任务已协作取消；已完成内容保留"
            elif reason:
                task.state, task.stop_reason = ("partial_success" if counts.succeeded else "failed"), reason
                if task.message in {"等待执行", "正在枚举所选范围"}:
                    task.message = "任务未全部完成"
            elif counts.failed or counts.unconfirmed or counts.unexecuted or (counts.succeeded and counts.skipped):
                task.state = "partial_success" if counts.succeeded else "failed"
                task.message = "部分完成" if counts.succeeded else "没有确认的复制成果"
            else:
                task.state = "completed"
                task.message = "已完成" if counts.succeeded else "未复制：全部跳过或仅复用已有目录"
            task.progress.stage = "finished"
            self._touch(task)
        try:
            self.persist(runtime)
        except RecordError:
            with self.lock:
                task.state, task.stop_reason = "interrupted", "record_error"
                task.message = "结果未能持久化，已停止；重启后可能显示为未确认"
                self._touch(task)

    def entries(self, task_id: str, offset: int, limit: int) -> UsbTaskEntriesResponse:
        runtime = self.get(task_id)
        with runtime.io_lock:
            task = self.snapshot(runtime)
            entries, total = self.store.entries(task, offset, limit)
        return UsbTaskEntriesResponse(instance_id=self.instance_id, task=task, entries=entries, offset=offset, total=total,
                                      next_offset=offset + len(entries) if offset + len(entries) < total else None)

    def remove(self, task_id: str) -> None:
        with self._admission:
            with self.lock:
                runtime = self._tasks.get(task_id)
                corrupt = any(item.record_id == task_id for item in self._record_errors)
                if runtime is None and not corrupt:
                    raise TaskError("记录不存在")
                if runtime is not None and (runtime.summary.state not in TERMINAL_STATES or self._active == task_id):
                    raise TaskError("任务尚未停止，不能移除记录")
            self.store.remove(task_id)
            with self.lock:
                self._tasks.pop(task_id, None)
                self._record_errors = [item for item in self._record_errors if item.record_id != task_id]
                if len(self._tasks) + sum(item.record_id is not None for item in self._record_errors) <= settings.USB_TRANSFER_MAX_RECORDS:
                    self._record_errors = [item for item in self._record_errors if item.message != "USB 记录数量超过预算；已暂停接收新任务"]
                # 凭据映射仍保留至到期；旧提交只能得到记录已移除，不会重新执行。
                self._revision += 1

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._queue or self._stopping, timeout=30.0)
                if self._stopping and not self._queue:
                    return
                task_id = self._queue.popleft() if self._queue else None
                runtime = self._tasks.get(task_id) if task_id is not None else None
                if runtime is not None:
                    if runtime.summary.state not in TERMINAL_STATES and (
                        self._stopping or runtime.summary.request.session_id in self._invalid_sessions
                        or self._record_errors or any(item.summary.record_error for item in self._tasks.values())
                    ):
                        runtime.summary.state, runtime.summary.stop_reason = "interrupted", "admission_stopped"
                        runtime.summary.message = "会话或记录状态不允许继续，未执行排队任务"
                        self._touch(runtime.summary)
                    terminal = runtime.summary.state in TERMINAL_STATES
                    if not terminal:
                        self._active = task_id
                        runtime.summary.state, runtime.summary.message = "running", "正在枚举所选范围"
                        self._touch(runtime.summary)
            if runtime is None:
                # 按 _prune 的保留规则回收完成记录，不访问 USB 或扫描用户目录。
                with self._admission:
                    self._prune()
                continue
            try:
                self.persist(runtime)
                if not terminal:
                    if self._runner is None:
                        raise TaskError("USB 执行器未配置")
                    self._runner(runtime)
            except Exception as exc:
                self.record_failure(runtime, f"任务执行异常：{type(exc).__name__}")
                self.finish(runtime, "record_error")
            finally:
                with self._condition:
                    if self._active == task_id:
                        self._active = None
                    self._condition.notify_all()

    def shutdown(self, deadline: float | None = None) -> bool:
        """请求停止并等待执行线程真正退出；join 超时不等于停止完成。"""
        with self._condition:
            self._stopping = True
            sessions = {item.summary.request.session_id for item in self._tasks.values() if item.summary.state not in TERMINAL_STATES}
            active = self._active
            self._condition.notify_all()
        for session in sessions:
            self.invalidate_session(session, "backend_shutdown")
        with self._condition:
            self._condition.notify_all()
        if active and self._cancel_worker:
            self._cancel_worker(active)
        thread = self._thread
        if thread is None:
            return True
        limit = deadline if deadline is not None else time.monotonic() + settings.USB_TRANSFER_CANCEL_GRACE + 3
        while True:
            remaining = limit - time.monotonic()
            if remaining <= 0:
                return not thread.is_alive()
            thread.join(timeout=min(0.2, remaining))
            if not thread.is_alive():
                return True
