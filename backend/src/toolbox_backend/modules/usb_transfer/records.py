"""USB 独立状态记录：写前意图、原子摘要和同步条目日志，不存文件内容。"""

from __future__ import annotations

import json
import os
import re
import stat
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from pydantic import ValidationError

from toolbox_backend.core.config import settings
from toolbox_backend.modules.usb_transfer.schemas import (
    PlanEntry, TERMINAL_STATES, UsbCounts, UsbEntryResult, UsbRecordError, UsbTaskSummary,
)

_ID = re.compile(r"^[a-f0-9]{32}$")


class RecordError(Exception):
    """记录失败不能被当作空历史或继续写入设备。"""


def count_result(counts: UsbCounts, result: UsbEntryResult) -> None:
    if result.status == "succeeded":
        if result.reused:
            counts.reused += 1
        else:
            counts.succeeded += 1
            if not result.is_folder:
                counts.copied_bytes += result.size_bytes or 0
    else:
        setattr(counts, result.status, getattr(counts, result.status) + 1)
    if result.effect:
        counts.effects += 1


class RecordStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.errors: list[UsbRecordError] = []

    @contextmanager
    def _root(self, create: bool = False) -> Iterator[int | None]:
        path = settings.usb_transfer_root
        if create:
            try:
                os.mkdir(path, 0o700)
            except FileExistsError:
                pass
            else:
                parent = os.open(settings.data_root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
                try:
                    os.fsync(parent)
                finally:
                    os.close(parent)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except FileNotFoundError:
            if create:
                raise
            yield None
            return
        try:
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def _directory(self, task_id: str, create: bool = False) -> Iterator[int]:
        if not _ID.fullmatch(task_id):
            raise RecordError("任务记录标识无效")
        with self._root(create) as root:
            if root is None:
                raise RecordError("任务记录不存在")
            if create:
                os.mkdir(task_id, 0o700, dir_fd=root)
                os.fsync(root)
            fd = os.open(task_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root)
            try:
                yield fd
            finally:
                os.close(fd)

    @staticmethod
    def _read(fd: int, name: str, maximum: int) -> bytes:
        source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        try:
            info = os.fstat(source)
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                raise RecordError("记录类型或大小超出预算")
            with os.fdopen(source, "rb", closefd=False) as stream:
                value = stream.read(maximum + 1)
            if len(value) > maximum:
                raise RecordError("记录超过预算")
            return value
        finally:
            os.close(source)

    @staticmethod
    def _atomic(fd: int, name: str, value: bytes) -> None:
        temporary = f".{name}-{uuid.uuid4().hex}.tmp"
        output = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd)
        try:
            with os.fdopen(output, "wb", closefd=False) as stream:
                stream.write(value)
                stream.flush()
                os.fsync(output)
            os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(output)
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass

    def create(self, task: UsbTaskSummary) -> None:
        with self._lock:
            try:
                with self._directory(task.task_id, create=True) as fd:
                    self._atomic(fd, "summary.json", task.model_dump_json().encode("utf-8"))
            except (OSError, ValueError) as exc:
                raise RecordError("无法持久化任务意图，任务未接受") from exc

    def save(self, task: UsbTaskSummary) -> None:
        with self._lock:
            try:
                with self._directory(task.task_id) as fd:
                    self._atomic(fd, "summary.json", task.model_dump_json().encode("utf-8"))
            except (OSError, ValueError) as exc:
                raise RecordError("任务摘要写入失败，停止后续设备写入") from exc

    def save_plan(self, task_id: str, entries: list[PlanEntry]) -> None:
        value = b"".join(entry.model_dump_json().encode("utf-8") + b"\n" for entry in entries)
        if len(value) > settings.USB_TRANSFER_MAX_RECORD_BYTES // 2:
            raise RecordError("任务枚举记录超过预算，未开始复制")
        with self._lock:
            try:
                with self._directory(task_id) as fd:
                    self._atomic(fd, "plan.jsonl", value)
            except (OSError, ValueError) as exc:
                raise RecordError("枚举记录写入失败，未开始复制") from exc

    def append(self, task_id: str, sequence: int, entry: UsbEntryResult) -> None:
        line = json.dumps({"sequence": sequence, "entry": entry.model_dump(mode="json")}, ensure_ascii=True).encode("utf-8") + b"\n"
        with self._lock:
            try:
                with self._directory(task_id) as fd:
                    output = os.open("entries.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd)
                    try:
                        info = os.fstat(output)
                        if not stat.S_ISREG(info.st_mode) or info.st_size + len(line) > settings.USB_TRANSFER_MAX_RECORD_BYTES // 2:
                            raise RecordError("条目记录超过预算")
                        with os.fdopen(output, "ab", closefd=False) as stream:
                            stream.write(line)
                            stream.flush()
                            os.fsync(output)
                        if info.st_size == 0:
                            os.fsync(fd)
                    finally:
                        os.close(output)
            except (OSError, ValueError) as exc:
                raise RecordError("条目结果记录失败，停止后续设备写入") from exc

    def _plan(self, fd: int) -> list[PlanEntry]:
        try:
            value = self._read(fd, "plan.jsonl", settings.USB_TRANSFER_MAX_RECORD_BYTES // 2)
        except FileNotFoundError:
            return []
        entries: list[PlanEntry] = []
        ids: set[str] = set()
        if value and not value.endswith(b"\n"):
            raise RecordError("枚举记录末尾不完整")
        for line in value.splitlines():
            if len(entries) >= settings.USB_TRANSFER_MAX_ENTRIES:
                raise RecordError("枚举记录条数超过预算")
            entry = PlanEntry.model_validate_json(line)
            if entry.entry_id in ids or (entry.parent_entry_id is not None and entry.parent_entry_id not in ids):
                raise RecordError("枚举记录存在重复或失效父项")
            ids.add(entry.entry_id)
            entries.append(entry)
        return entries

    def _results(self, fd: int) -> list[UsbEntryResult]:
        try:
            value = self._read(fd, "entries.jsonl", settings.USB_TRANSFER_MAX_RECORD_BYTES // 2)
        except FileNotFoundError:
            return []
        entries: list[UsbEntryResult] = []
        ids: set[str] = set()
        if value and not value.endswith(b"\n"):
            raise RecordError("条目日志末尾不完整")
        for line in value.splitlines():
            if len(entries) >= settings.USB_TRANSFER_MAX_ENTRIES:
                raise RecordError("条目记录条数超过预算")
            raw = json.loads(line)
            if not isinstance(raw, dict) or type(raw.get("sequence")) is not int or raw["sequence"] != len(entries):
                raise RecordError("条目日志序号损坏")
            entry = UsbEntryResult.model_validate(raw.get("entry"))
            if entry.entry_id in ids:
                raise RecordError("条目日志重复")
            ids.add(entry.entry_id)
            entries.append(entry)
        return entries

    def _entries(self, fd: int, task: UsbTaskSummary, *, recover: bool) -> list[UsbEntryResult]:
        results = self._results(fd)
        if not recover:
            return results
        plans = self._plan(fd)
        if task.planned_count and len(plans) != task.planned_count:
            raise RecordError("枚举记录数量与摘要不符")
        if not task.historical and task.entry_count > len(results):
            raise RecordError("已提交的条目记录缺失")
        task.planned_count = len(plans)
        plan_ids = {entry.entry_id for entry in plans}
        if any(entry.entry_id not in plan_ids for entry in results):
            raise RecordError("条目结果没有对应枚举记录")
        done = {entry.entry_id for entry in results}
        for plan in plans:
            if plan.entry_id in done:
                continue
            uncertain = task.active_intent is not None and task.active_intent.get("entry_id") == plan.entry_id
            results.append(UsbEntryResult(
                entry_id=plan.entry_id, source=plan.source, raw_name=plan.raw_name,
                is_folder=plan.is_folder, size_bytes=plan.size_bytes,
                status="unconfirmed" if uncertain else "unexecuted",
                message="应用中断时本项结果尚未记录" if uncertain else "应用中断，未执行本项",
                residual="可能有写入结果或临时文件；未自动扫描或删除" if uncertain else None,
            ))
        return results

    def load(self) -> list[UsbTaskSummary]:
        """仅恢复展示，不启动 worker，不改写用户文件或自动恢复队列。"""
        tasks: list[UsbTaskSummary] = []
        self.errors = []
        with self._lock:
            try:
                with self._root() as root:
                    if root is None:
                        return []
                    names = os.listdir(root)
                    if len(names) > settings.USB_TRANSFER_MAX_RECORDS:
                        self.errors.append(UsbRecordError(message="USB 记录数量超过预算；已暂停接收新任务"))
                    for name in sorted(names):
                        if not _ID.fullmatch(name):
                            self.errors.append(UsbRecordError(message=f"USB 状态目录中存在无法识别的记录：{name[:80]}"))
                            continue
                        if len(tasks) >= settings.USB_TRANSFER_MAX_RECORDS:
                            self.errors.append(UsbRecordError(record_id=name, message="记录超出加载预算，未隐藏或清理原文件"))
                            continue
                        try:
                            with self._directory(name) as fd:
                                task = UsbTaskSummary.model_validate_json(self._read(fd, "summary.json", 262144))
                                if task.task_id != name:
                                    raise RecordError("摘要与目录标识不符")
                                active = task.state not in TERMINAL_STATES
                                entries = self._entries(fd, task, recover=True)
                                task.counts = UsbCounts()
                                for entry in entries:
                                    count_result(task.counts, entry)
                                task.entry_count = len(entries)
                                if active:
                                    task.state, task.stop_reason = "interrupted", "application_exit"
                                    task.message = "上次任务已中断；只恢复结果展示，不恢复设备写入"
                                task.historical = True
                                tasks.append(task)
                        except (OSError, ValueError, RecordError, ValidationError):
                            self.errors.append(UsbRecordError(record_id=name, message="任务记录损坏或不可读，未按空记录处理"))
            except OSError:
                self.errors.append(UsbRecordError(message="USB 状态目录不可读，已暂停接收新任务"))
        return tasks

    def entries(self, task: UsbTaskSummary, offset: int, limit: int) -> tuple[list[UsbEntryResult], int]:
        with self._lock:
            try:
                with self._directory(task.task_id) as fd:
                    entries = self._entries(fd, task, recover=task.historical)
                return entries[offset:offset + limit], len(entries)
            except (OSError, ValueError, RecordError) as exc:
                raise RecordError("条目记录不可读，未返回空列表") from exc

    def remove(self, task_id: str) -> None:
        """只移除本模块指定任务目录中的普通记录文件，不解释其中的用户路径。"""
        with self._lock:
            try:
                with self._directory(task_id) as fd:
                    names = os.listdir(fd)
                    for name in names:
                        owned = name in {"summary.json", "plan.jsonl", "entries.jsonl"} or re.fullmatch(
                            r"\.(?:summary\.json|plan\.jsonl)-[a-f0-9]{32}\.tmp", name,
                        ) is not None
                        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        if not owned or not stat.S_ISREG(info.st_mode):
                            raise RecordError("记录目录含非本模块文件或非普通文件，拒绝清理")
                    for name in names:
                        os.unlink(name, dir_fd=fd)
                with self._root() as root:
                    if root is None:
                        raise RecordError("记录目录已消失")
                    os.rmdir(task_id, dir_fd=root)
                    os.fsync(root)
                self.errors = [item for item in self.errors if item.record_id != task_id]
            except FileNotFoundError:
                self.errors = [item for item in self.errors if item.record_id != task_id]
            except (OSError, ValueError) as exc:
                raise RecordError("移除任务记录失败；未触碰传输文件") from exc
