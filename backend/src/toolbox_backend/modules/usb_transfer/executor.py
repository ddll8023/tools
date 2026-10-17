"""USB 后台执行器：写前记录后逐项驱动 worker，终态保留真实停止原因。"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import JsonValue

from toolbox_backend.core.config import settings
from toolbox_backend.modules.usb_transfer.records import RecordError
from toolbox_backend.modules.usb_transfer.schemas import (
    PlanEntry, TransferStart, UsbEntryResult, UsbModel, UsbProgress,
)
from toolbox_backend.modules.usb_transfer.supervisor import (
    UsbWorkerSupervisor, WorkerError, WorkerTimeoutError, WorkerUnavailableError,
)
from toolbox_backend.modules.usb_transfer.tasks import TaskManager, TaskRuntime


class _PlanResult(UsbModel):
    planned_count: int
    complete: bool
    known_bytes: int


class _StepResult(UsbModel):
    entry: UsbEntryResult
    connection_lost: bool


class Executor:
    def __init__(
        self, manager: TaskManager, supervisor: UsbWorkerSupervisor,
        acquire: Callable[[TaskRuntime], TransferStart], release: Callable[[], None],
        disconnect: Callable[[TaskRuntime], None],
    ) -> None:
        self.manager, self.supervisor = manager, supervisor
        self.acquire, self.release, self.disconnect = acquire, release, disconnect

    def execute(self, runtime: TaskRuntime) -> None:
        plans: dict[str, PlanEntry] = {}
        recorded: set[str] = set()
        acquired = False
        reason = ""
        plan_result: _PlanResult | None = None

        def event(payload: dict[str, JsonValue]) -> None:
            if set(payload) != {"entry"}:
                raise ValueError("无效枚举事件")
            entry = PlanEntry.model_validate(payload["entry"])
            old = plans.get(entry.entry_id)
            if old is not None and old.model_dump(exclude={"issue", "message"}) != entry.model_dump(exclude={"issue", "message"}):
                raise ValueError("枚举条目身份被改写")
            if old is None and (len(plans) >= settings.USB_TRANSFER_MAX_ENTRIES or (
                entry.parent_entry_id is not None and entry.parent_entry_id not in plans
            )):
                raise ValueError("枚举预算或父项关联无效")
            plans[entry.entry_id] = entry

        def progress(value: UsbProgress) -> None:
            snapshot = self.manager.snapshot(runtime)
            if plan_result is not None:
                value.discovered = plan_result.planned_count
                value.processed = snapshot.entry_count
                value.known_bytes = plan_result.known_bytes
                value.total_known = plan_result.complete
            self.manager.update_progress(runtime, value)

        try:
            start = self.acquire(runtime)
            acquired = True
            if runtime.cancel.is_set():
                return
            payload = self.supervisor.call(
                "plan", start.model_dump(mode="json"), task_id=runtime.summary.task_id,
                expected_generation=runtime.generation, long_operation=True,
                on_event=event, on_progress=progress, cancel=runtime.cancel,
            )
            plan_result = _PlanResult.model_validate(payload)
            if plan_result.planned_count != len(plans):
                raise WorkerError("protocol", "枚举结果数量不一致")
            self.manager.store.save_plan(runtime.summary.task_id, list(plans.values()))
            self.manager.set_plan(runtime, len(plans), plan_result.complete, plan_result.known_bytes)
            self.manager.persist(runtime)
            for entry in plans.values():
                if runtime.cancel.is_set():
                    break
                if entry.issue is not None:
                    result = UsbEntryResult(entry_id=entry.entry_id, source=entry.source, raw_name=entry.raw_name,
                                            status=entry.issue, message=entry.message, is_folder=entry.is_folder,
                                            size_bytes=entry.size_bytes)
                else:
                    self.manager.begin_item(runtime, entry)
                    if runtime.cancel.is_set():
                        break
                    payload = self.supervisor.call(
                        "step", {"session_id": start.request.session_id, "entry_id": entry.entry_id},
                        task_id=runtime.summary.task_id, expected_generation=runtime.generation,
                        long_operation=True, on_progress=progress, cancel=runtime.cancel,
                    )
                    response = _StepResult.model_validate(payload)
                    result = response.entry
                    if result.entry_id != entry.entry_id or result.source != entry.source or result.raw_name != entry.raw_name:
                        raise WorkerError("protocol", "复制结果与来源条目不一致")
                    self.manager.append(runtime, result)
                    recorded.add(entry.entry_id)
                    if response.connection_lost:
                        self.supervisor.fail_generation(runtime.generation, "设备通信已经失效")
                        raise WorkerUnavailableError("unavailable", "设备通信已经失效")
                    continue
                self.manager.append(runtime, result)
                recorded.add(entry.entry_id)
        except RecordError as exc:
            self.manager.record_failure(runtime, str(exc))
            reason = "record_error"
        except WorkerError as exc:
            if isinstance(exc, WorkerTimeoutError) or isinstance(exc, WorkerUnavailableError) or exc.kind in {"disconnected", "not_open", "protocol"}:
                reason = "cancel_timeout" if exc.kind == "cancel_timeout" else "worker_lost"
                runtime.interrupted_reason = reason
                runtime.stop_connection = True
                self.supervisor.fail_generation(runtime.generation, exc.message)
            elif exc.kind != "cancelled":
                reason = exc.kind
                with self.manager.lock:
                    runtime.summary.message = exc.message
        except Exception as exc:
            reason = "execution_error"
            runtime.stop_connection = True
            with self.manager.lock:
                runtime.summary.message = f"复制未能继续：{type(exc).__name__}"
        finally:
            # 枚举被取消时也保存已发现部分；未知后代不虚构条目或数量。
            if not runtime.summary.record_error:
                try:
                    if plan_result is None:
                        self.manager.store.save_plan(runtime.summary.task_id, list(plans.values()))
                        self.manager.set_plan(runtime, len(plans), False,
                                              sum(entry.size_bytes or 0 for entry in plans.values()))
                    active = self.manager.snapshot(runtime).active_intent
                    for entry in plans.values():
                        if entry.entry_id in recorded:
                            continue
                        uncertain = active is not None and active.get("entry_id") == entry.entry_id and reason in {"worker_lost", "cancel_timeout", "execution_error"}
                        result = UsbEntryResult(
                            entry_id=entry.entry_id, source=entry.source, raw_name=entry.raw_name,
                            is_folder=entry.is_folder, size_bytes=entry.size_bytes,
                            status="unconfirmed" if uncertain else "unexecuted",
                            message="原生操作的最终结果未收到" if uncertain else "任务已停止，未执行本项",
                            residual=(f"目标 {active.get('target', '')}；可能有写入结果或 {active.get('temporary_name', '')}" if uncertain and active else None),
                        )
                        self.manager.append(runtime, result)
                except RecordError as exc:
                    self.manager.record_failure(runtime, str(exc))
                    reason = "record_error"
            try:
                if acquired and self.supervisor.generation == runtime.generation:
                    try:
                        self.supervisor.call("finish", {"session_id": runtime.summary.request.session_id},
                                             task_id=runtime.summary.task_id, expected_generation=runtime.generation,
                                             timeout=settings.USB_TRANSFER_CANCEL_GRACE)
                    except WorkerError:
                        reason = "worker_lost"
                        runtime.stop_connection = True
                if acquired and (runtime.stop_connection or runtime.cancel.is_set()):
                    try:
                        self.disconnect(runtime)
                    except WorkerError:
                        reason = "worker_lost"
                self.manager.finish(runtime, reason)
            finally:
                if acquired:
                    self.release()
