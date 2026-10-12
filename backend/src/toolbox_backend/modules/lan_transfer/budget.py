"""局域网投送会话的资源预算：并发额度、字节预留与磁盘余量。

上传中与待确认内容共同占用同一份会话预算：并发上传在开始前统一预留额度，
写入过程中按实际字节数结算，失败时全额释放。全部记账在同一把锁内完成，
避免并发上传各自判断后集体超支。
"""

from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from toolbox_backend.core.config import settings
from toolbox_backend.core.errors import ServiceException
from toolbox_backend.schemas.response import ErrorCode


@dataclass(frozen=True)
class BudgetSnapshot:
    """预算占用快照，用于会话状态展示。"""

    used_bytes: int
    max_bytes: int
    active_uploads: int
    max_uploads: int


class SessionBudget:
    """串行记账单次会话的隔离区占用、并发上传与待确认文件额度。"""

    def __init__(self) -> None:
        """按当前配置初始化空额度。"""
        self._lock = threading.RLock()
        self._used_bytes = 0
        self._active_uploads = 0
        self._pending_slots = 0

    def acquire_upload_slot(self) -> None:
        """预留一个上传槽与一个待确认文件槽，任一额度不足即拒绝。"""
        with self._lock:
            if self._active_uploads >= settings.LAN_TRANSFER_MAX_CONCURRENT_UPLOADS:
                raise ServiceException(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "同时上传的文件过多，请稍后重试",
                )
            if self._pending_slots >= settings.LAN_TRANSFER_MAX_PENDING_FILES:
                raise ServiceException(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "待接收文件过多，请先在电脑端处理",
                )
            self._active_uploads += 1
            self._pending_slots += 1

    def release_upload_slot(self, keep_pending_slot: bool) -> None:
        """释放上传槽；上传失败时同时释放已预留的待确认槽。"""
        with self._lock:
            self._active_uploads = max(0, self._active_uploads - 1)
            if not keep_pending_slot:
                self._pending_slots = max(0, self._pending_slots - 1)

    def release_pending_slot(self) -> None:
        """释放一个待确认文件槽，用于内容被接收、拒绝或清理之后。"""
        with self._lock:
            self._pending_slots = max(0, self._pending_slots - 1)

    def reserve(self, amount: int) -> None:
        """预留字节额度，同时校验会话累计占用与磁盘最低余量。"""
        if amount <= 0:
            return
        with self._lock:
            projected = self._used_bytes + amount
            if projected > settings.LAN_TRANSFER_MAX_SESSION_BYTES:
                raise ServiceException(
                    ErrorCode.FILE_TOO_LARGE,
                    "超出本次投送可接收的总大小",
                )
            if not self._has_disk_space(projected):
                raise ServiceException(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "磁盘可用空间不足，已停止接收",
                )
            self._used_bytes = projected

    def release(self, amount: int) -> None:
        """释放已占用或已预留的字节额度。"""
        if amount <= 0:
            return
        with self._lock:
            self._used_bytes = max(0, self._used_bytes - amount)

    def settle(self, reserved: int, actual: int) -> None:
        """把预留额度按实际写入字节数结算，差额归还预算。"""
        with self._lock:
            self._used_bytes = max(0, self._used_bytes - reserved) + actual

    def snapshot(self) -> BudgetSnapshot:
        """返回当前占用快照。"""
        with self._lock:
            return BudgetSnapshot(
                used_bytes=self._used_bytes,
                max_bytes=settings.LAN_TRANSFER_MAX_SESSION_BYTES,
                active_uploads=self._active_uploads,
                max_uploads=settings.LAN_TRANSFER_MAX_CONCURRENT_UPLOADS,
            )

    @staticmethod
    def free_disk_bytes() -> int | None:
        """返回隔离区所在磁盘的剩余空间；读不到磁盘信息时返回 None。"""
        try:
            return shutil.disk_usage(Path(settings.data_root)).free
        except OSError:
            return None

    @classmethod
    def _has_disk_space(cls, projected: int) -> bool:
        """判断磁盘剩余空间是否满足最低余量；读不到磁盘信息时不拦截。"""
        free_bytes = cls.free_disk_bytes()
        if free_bytes is None:
            return True
        return free_bytes >= projected + settings.LAN_TRANSFER_MIN_FREE_DISK_BYTES
