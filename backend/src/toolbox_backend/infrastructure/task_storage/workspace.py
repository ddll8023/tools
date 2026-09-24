"""提供本地任务工作区、任务标识和路径边界能力。"""

from __future__ import annotations

import os
import re
from pathlib import Path

from toolbox_backend.core.config import settings
from toolbox_backend.core.errors import ServiceException
from toolbox_backend.schemas.response import ErrorCode

_TASK_ID_RE = re.compile(r"^[a-f0-9]{12}$")

# 临时任务必须写入用户数据目录，不能写入打包后的只读应用资源目录。
TEMP_DIR = os.path.join(settings.data_root, "temp")
UPLOADS_DIR = os.path.join(TEMP_DIR, "uploads")


def validate_task_id(task_id: str) -> bool:
    """校验任务 ID 仅包含当前任务目录允许的字符。"""
    return bool(_TASK_ID_RE.fullmatch(task_id))


def get_task_dir(task_id: str) -> str:
    """根据任务 ID 返回任务目录，不执行目录创建。"""
    return os.path.join(TEMP_DIR, "tasks", task_id)


def ensure_task_path(path: str | Path) -> Path:
    """确认路径解析后仍位于临时任务根目录内。"""
    root = Path(TEMP_DIR).resolve()
    candidate = Path(path).resolve()
    if not candidate.is_relative_to(root):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")
    return candidate
