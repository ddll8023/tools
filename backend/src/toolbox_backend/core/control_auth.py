"""控制面凭据的生成、受限落盘与校验，仅供本机桌面端调用链使用。

凭据在每次后端启动时重新生成，不沿用上次的值，也不进入局域网链接、
二维码或浏览器页面。凭据文件权限受限，是桌面外壳取得凭据的唯一通道。
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
from pathlib import Path

from toolbox_backend.core.config import settings
from toolbox_backend.core import runtime
from toolbox_backend.core.logging import setup_logger

logger = setup_logger(__name__)

CONTROL_TOKEN_FILENAME = "control-token"
_TOKEN_BYTES = 32
_DIR_MODE = 0o700
_FILE_MODE = 0o600

_token: str | None = None


def token_path() -> Path:
    """返回控制面凭据文件路径。"""
    return Path(settings.runtime_dir) / CONTROL_TOKEN_FILENAME


def _write_token_file(path: Path, token: str) -> None:
    """以受限权限原子写入凭据身份包，避免读取方看到拼接或半写入内容。"""
    os.makedirs(path.parent, exist_ok=True)
    # Windows 的 chmod 语义有限，此处仅保证 POSIX 下不被其他用户读取。
    os.chmod(path.parent, _DIR_MODE)
    temp_path = path.with_name(f"{path.name}.tmp")
    descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FILE_MODE)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(token)
    os.replace(temp_path, path)


def initialize_control_token() -> str:
    """生成本次启动的控制面凭据并落盘，返回凭据值。"""
    global _token
    owner = runtime.identity()
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    # 单个原子文件绑定身份与凭据，桌面端不能把旧凭据与新身份拼接使用。
    bundle = {**owner.model_dump(), "token": token}
    _write_token_file(token_path(), json.dumps(bundle, separators=(",", ":")))
    _token = token
    logger.info("控制面凭据已生成: %s", token_path())
    return token


def verify_control_token(candidate: str | None) -> bool:
    """以常量时间比对候选凭据；未初始化或候选缺失时一律拒绝。"""
    current = _token
    if not current or not candidate:
        return False
    return hmac.compare_digest(current, candidate)
