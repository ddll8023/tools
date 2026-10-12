"""应用偏好的持久化读写。

偏好保存在用户数据目录下的 JSON 文件，写入采用临时文件加原子替换；文件缺失、
损坏或字段类型不符时回退默认值并保持可用。只保存用户显式设置过的字段，不写入
默认值，便于后续调整默认行为。本模块只依赖数据目录，不反向依赖调用方。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from toolbox_backend.core.config import settings
from toolbox_backend.core.logging import setup_logger

logger = setup_logger(__name__)

_SETTINGS_FILENAME = "settings.json"
_DEVICE_NAME_KEY = "lan_transfer_device_name"
_RECEIVE_DIR_KEY = "lan_transfer_receive_dir"

_lock = threading.RLock()
_cache: dict[str, str] | None = None


def settings_path() -> Path:
    """返回偏好文件路径。"""
    return Path(settings.data_root) / _SETTINGS_FILENAME


def _load() -> dict[str, str]:
    """读取偏好；文件缺失、损坏或内容非对象时返回空表。"""
    global _cache
    with _lock:
        if _cache is not None:
            return _cache

        values: dict[str, str] = {}
        path = settings_path()
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as source:
                    raw = json.load(source)
                if isinstance(raw, dict):
                    values = {
                        key: value
                        for key, value in raw.items()
                        if isinstance(key, str) and isinstance(value, str)
                    }
            except (OSError, ValueError, UnicodeDecodeError):
                logger.warning("偏好文件不可读，按默认值处理: %s", path)
        _cache = values
        return values


def _save(values: dict[str, str]) -> None:
    """以原子替换方式写入偏好文件，并同步内存缓存。"""
    global _cache
    path = settings_path()
    os.makedirs(path.parent, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as target:
        json.dump(values, target, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)
    _cache = values


def device_name() -> str:
    """返回用户设置的设备名；未设置时返回空串。"""
    return _load().get(_DEVICE_NAME_KEY, "")


def receive_dir() -> str:
    """返回用户设置的接收目录；未设置时返回空串。"""
    return _load().get(_RECEIVE_DIR_KEY, "")


def customized_fields() -> set[str]:
    """返回已由用户自定义的偏好字段集合。"""
    values = _load()
    fields = set()
    if values.get(_DEVICE_NAME_KEY):
        fields.add("device_name")
    if values.get(_RECEIVE_DIR_KEY):
        fields.add("receive_dir")
    return fields


def update(*, device_name: str | None = None, receive_dir: str | None = None) -> None:
    """更新指定偏好；传入空串表示清除该项并回退默认值，传入 None 表示不修改。"""
    with _lock:
        values = dict(_load())
        if device_name is not None:
            _assign(values, _DEVICE_NAME_KEY, device_name)
        if receive_dir is not None:
            _assign(values, _RECEIVE_DIR_KEY, receive_dir)
        _save(values)


def _assign(values: dict[str, str], key: str, value: str) -> None:
    """写入或清除单个偏好字段，避免把空值当作设置保存。"""
    cleaned = value.strip()
    if cleaned:
        values[key] = cleaned
    else:
        values.pop(key, None)
