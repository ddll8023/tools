"""局域网投送的待确认接收队列。

队列只保存已完整写入隔离区的内容。状态迁移在同一把锁内完成，并接受一个
会话开关判定，使「开始确认」与「关闭会话」不会同时操作同一个文件。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from toolbox_backend.core.errors import ServiceException
from toolbox_backend.schemas.response import ErrorCode


class PendingState(StrEnum):
    """待确认内容的状态；移出队列即代表已接收或已拒绝。"""

    PENDING = "pending"
    COMMITTING = "committing"


@dataclass
class PendingFile:
    """一个已完整上传、等待用户确认的接收内容。"""

    upload_id: str
    original_name: str
    stored_name: str
    size_bytes: int
    stored_path: Path
    uploaded_at: float
    state: PendingState = PendingState.PENDING


class PendingQueue:
    """串行管理待确认内容的状态迁移。"""

    def __init__(self) -> None:
        """初始化空队列。"""
        self._lock = threading.RLock()
        self._items: dict[str, PendingFile] = {}

    def add(self, item: PendingFile) -> None:
        """登记一个刚完成写入的接收内容。"""
        with self._lock:
            self._items[item.upload_id] = item

    def list_pending(self) -> list[PendingFile]:
        """按上传时间返回仍在等待确认的内容。"""
        with self._lock:
            items = [
                item for item in self._items.values() if item.state is PendingState.PENDING
            ]
        return sorted(items, key=lambda item: item.uploaded_at)

    def count(self) -> int:
        """返回等待确认的内容数量。"""
        with self._lock:
            return sum(
                1 for item in self._items.values() if item.state is PendingState.PENDING
            )

    def claim(self, upload_id: str, accepting_gate: Callable[[], bool]) -> PendingFile:
        """把待确认内容标记为提交中；会话已进入关闭时拒绝。"""
        with self._lock:
            if not accepting_gate():
                raise ServiceException(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "投送会话已停止，无法继续操作",
                )
            item = self._items.get(upload_id)
            if item is None or item.state is not PendingState.PENDING:
                raise ServiceException(ErrorCode.DATA_NOT_FOUND, "该文件已不在待接收列表中")
            item.state = PendingState.COMMITTING
            return item

    def release(self, upload_id: str) -> None:
        """提交失败时退回待确认状态，保留内容供用户重试。"""
        with self._lock:
            item = self._items.get(upload_id)
            if item is not None and item.state is PendingState.COMMITTING:
                item.state = PendingState.PENDING

    def discard(self, upload_id: str) -> None:
        """把提交中的内容移出队列，表示已接收或已拒绝。"""
        with self._lock:
            self._items.pop(upload_id, None)

    def take_pending(self) -> list[PendingFile]:
        """取出并移除全部待确认内容，供关闭时清理。"""
        with self._lock:
            items = [
                item for item in self._items.values() if item.state is PendingState.PENDING
            ]
            for item in items:
                self._items.pop(item.upload_id, None)
        return sorted(items, key=lambda item: item.uploaded_at)
