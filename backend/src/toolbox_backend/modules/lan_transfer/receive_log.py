"""局域网投送的接收记录。

只记录已成功移入接收目录的条目，用于回答"收到的文件去了哪里"。记录持久化在
用户数据目录的投送目录下，超出保留条数时裁掉最旧的记录；记录文件损坏时按空
记录处理，写入失败也不影响已经完成的接收。
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from toolbox_backend.core.config import settings
from toolbox_backend.core.logging import setup_logger

logger = setup_logger(__name__)

_LOG_FILENAME = "receive-log.json"
_lock = threading.RLock()


@dataclass(frozen=True)
class ReceiveRecord:
    """一条接收成功记录。"""

    name: str
    size_bytes: int
    received_at: float
    destination: str


def log_path() -> Path:
    """返回接收记录文件路径。"""
    return Path(settings.lan_transfer_root) / _LOG_FILENAME


def _read() -> list[ReceiveRecord]:
    """读取全部记录（新的在前）；文件缺失或损坏时返回空列表。"""
    path = log_path()
    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8") as source:
            raw = json.load(source)
    except (OSError, ValueError, UnicodeDecodeError):
        logger.warning("接收记录不可读，按空记录处理: %s", path)
        return []
    if not isinstance(raw, list):
        return []

    records: list[ReceiveRecord] = []
    for item in raw:
        record = _parse(item)
        if record is not None:
            records.append(record)
    return records


def _parse(item: object) -> ReceiveRecord | None:
    """把一条原始记录转换为模型；字段缺失或类型不符时返回 None。"""
    if not isinstance(item, dict):
        return None
    name = item.get("name")
    destination = item.get("destination")
    size_bytes = item.get("size_bytes")
    received_at = item.get("received_at")
    if not isinstance(name, str) or not isinstance(destination, str):
        return None
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool):
        return None
    if not isinstance(received_at, (int, float)) or isinstance(received_at, bool):
        return None
    return ReceiveRecord(
        name=name,
        size_bytes=size_bytes,
        received_at=float(received_at),
        destination=destination,
    )


def _write(records: list[ReceiveRecord]) -> None:
    """以原子替换方式写入记录文件。"""
    path = log_path()
    os.makedirs(path.parent, exist_ok=True)
    payload = [
        {
            "name": record.name,
            "size_bytes": record.size_bytes,
            "received_at": record.received_at,
            "destination": record.destination,
        }
        for record in records
    ]
    temp_path = path.with_name(f"{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as target:
        json.dump(payload, target, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def append(name: str, size_bytes: int, destination: str) -> None:
    """追加一条接收成功记录，并按保留条数裁掉最旧的记录。"""
    record = ReceiveRecord(
        name=name,
        size_bytes=size_bytes,
        received_at=time.time(),
        destination=destination,
    )
    with _lock:
        records = [record, *_read()]
        del records[settings.LAN_TRANSFER_MAX_RECEIVE_RECORDS :]
        try:
            _write(records)
        except OSError as exc:
            # 接收已经完成，记录失败只影响历史查询。
            logger.warning("写入接收记录失败: %s", type(exc).__name__)


def list_recent() -> list[ReceiveRecord]:
    """按接收时间倒序返回记录。"""
    with _lock:
        return _read()
