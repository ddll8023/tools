"""局域网投送隔离区的路径、文件名与遗留回收。

隔离区位于用户数据目录下的独立子树，不与其他工具的临时任务共享目录与保留
时长。所有对外暴露的路径都必须先经过边界校验，文件名一律由服务端净化。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from toolbox_backend.core.config import settings
from toolbox_backend.core.errors import ServiceException
from toolbox_backend.core.logging import setup_logger
from toolbox_backend.infrastructure.files import safe_filename
from toolbox_backend.schemas.response import ErrorCode

logger = setup_logger(__name__)

_INCOMING_DIRNAME = "incoming"
_MAX_NAME_LENGTH = 120
_MAX_DEDUPE_ATTEMPTS = 1000


@dataclass(frozen=True)
class RecoveryResult:
    """描述一次遗留内容回收的结果。"""

    removed_files: int
    removed_bytes: int
    failures: list[str] = field(default_factory=list)


def incoming_root() -> Path:
    """返回隔离区根目录，不执行创建。"""
    return Path(settings.lan_transfer_root) / _INCOMING_DIRNAME


def session_dir(session_id: str) -> Path:
    """返回某次会话的隔离目录。"""
    return incoming_root() / session_id


def upload_path(session_id: str, upload_id: str) -> Path:
    """返回单个上传内容在隔离区内的路径，并确认仍在隔离区内。"""
    return ensure_within_isolation(session_dir(session_id) / upload_id)


def ensure_within_isolation(path: str | Path) -> Path:
    """确认路径解析后仍位于隔离区根目录内。"""
    root = incoming_root().resolve()
    candidate = Path(path).resolve()
    if not candidate.is_relative_to(root):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")
    return candidate


def sanitize_name(name: str | None) -> str:
    """净化客户端声明的文件名：去目录、去控制字符、限制长度。"""
    cleaned = safe_filename(name, "file")[:_MAX_NAME_LENGTH].strip()
    if cleaned in {"", ".", ".."}:
        return "file"
    return cleaned


def unique_destination(directory: Path, name: str) -> Path:
    """在接收目录内避让重名，返回不会覆盖既有文件的落盘路径。"""
    candidate = directory / name
    if not candidate.exists():
        return candidate

    stem, suffix = os.path.splitext(name)
    for index in range(1, _MAX_DEDUPE_ATTEMPTS + 1):
        candidate = directory / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "接收目录中同名文件过多，请先整理")


def recover_leftovers() -> RecoveryResult:
    """删除上次异常终止留下的投送隔离内容，不触碰接收目录与其他工具任务。"""
    root = incoming_root()
    if not root.exists():
        return RecoveryResult(removed_files=0, removed_bytes=0)

    removed_files = 0
    removed_bytes = 0
    failures: list[str] = []
    # 由深到浅删除，便于逐项记录失败原因。
    entries = sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True)
    for path in entries:
        try:
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
                continue
            size = path.stat().st_size
            path.unlink()
            removed_files += 1
            removed_bytes += size
        except OSError:
            failures.append(str(path))

    try:
        root.rmdir()
    except OSError:
        failures.append(str(root))

    if removed_files or failures:
        logger.info(
            "投送遗留回收完成: 文件=%s 字节=%s 失败=%s",
            removed_files,
            removed_bytes,
            len(failures),
        )
    for path in failures:
        logger.warning("投送遗留内容回收失败: %s", path)
    return RecoveryResult(removed_files, removed_bytes, failures)
