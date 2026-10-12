"""局域网投送的待取件清单。

清单只登记用户在工具页显式选中的文件路径，不复制内容，也不占用会话的隔离区
预算。对端只能按标识取用清单内的条目，无法请求任意路径。
"""

from __future__ import annotations

import os
import secrets
import threading
from dataclasses import dataclass

from toolbox_backend.core.config import settings
from toolbox_backend.core.errors import ServiceException
from toolbox_backend.schemas.response import ErrorCode

_ID_BYTES = 8


@dataclass(frozen=True)
class OutgoingFile:
    """一个用户显式选中、等待对方取件的文件。"""

    file_id: str
    path: str
    name: str
    size_bytes: int

    @property
    def is_available(self) -> bool:
        """判断源文件当前是否仍可读取。"""
        try:
            return os.path.isfile(self.path) and os.access(self.path, os.R_OK)
        except OSError:
            return False


class OutgoingList:
    """串行管理待取件清单的登记、查询与移除。"""

    def __init__(self) -> None:
        """初始化空清单。"""
        self._lock = threading.RLock()
        self._items: dict[str, OutgoingFile] = {}

    def register(self, paths: list[str]) -> list[OutgoingFile]:
        """登记用户选中的文件；任一路径无效则整体拒绝，并按绝对路径去重。"""
        resolved = [self._resolve(raw) for raw in paths]

        added: list[OutgoingFile] = []
        with self._lock:
            for path, size_bytes in resolved:
                if any(item.path == path for item in self._items.values()) or any(
                    item.path == path for item in added
                ):
                    continue
                if len(self._items) + len(added) >= settings.LAN_TRANSFER_MAX_SEND_FILES:
                    raise ServiceException(
                        ErrorCode.PARAM_ERROR,
                        f"待取件文件数量已达上限（{settings.LAN_TRANSFER_MAX_SEND_FILES} 个）",
                    )
                added.append(
                    OutgoingFile(
                        file_id=secrets.token_hex(_ID_BYTES),
                        path=path,
                        name=os.path.basename(path),
                        size_bytes=size_bytes,
                    )
                )
            for item in added:
                self._items[item.file_id] = item
        return added

    def list_items(self) -> list[OutgoingFile]:
        """按登记顺序返回全部待取件条目。"""
        with self._lock:
            return list(self._items.values())

    def get(self, file_id: str) -> OutgoingFile | None:
        """按标识返回条目，不存在时为 None。"""
        with self._lock:
            return self._items.get(file_id)

    def remove(self, file_id: str) -> bool:
        """移除条目；标识不存在时返回 False。"""
        with self._lock:
            return self._items.pop(file_id, None) is not None

    def clear(self) -> None:
        """清空清单，用于会话关闭。"""
        with self._lock:
            self._items.clear()

    @staticmethod
    def _resolve(raw: str) -> tuple[str, int]:
        """校验路径为存在且可读的普通文件，返回绝对路径与字节数。"""
        if not raw or not os.path.isabs(raw):
            raise ServiceException(ErrorCode.PARAM_ERROR, "只能投送本机绝对路径的文件")

        path = os.path.abspath(raw)
        if not os.path.isfile(path):
            raise ServiceException(
                ErrorCode.DATA_NOT_FOUND,
                f"文件不存在：{os.path.basename(path)}",
            )
        if not os.access(path, os.R_OK):
            raise ServiceException(
                ErrorCode.PARAM_ERROR,
                f"文件不可读：{os.path.basename(path)}",
            )
        try:
            size_bytes = os.path.getsize(path)
        except OSError as exc:
            raise ServiceException(
                ErrorCode.PARAM_ERROR,
                f"无法读取文件信息：{os.path.basename(path)}",
            ) from exc
        return path, size_bytes
