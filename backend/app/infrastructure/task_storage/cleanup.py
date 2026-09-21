"""清理本地任务工作区中的过期文件和目录。"""

from __future__ import annotations

import os
import shutil
import time

from app.infrastructure.task_storage.workspace import TEMP_DIR, UPLOADS_DIR
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)


def cleanup_expired_temp(max_hours: int = 24) -> None:
    """删除超过指定保留时间的临时目录和文件。"""
    if not os.path.exists(TEMP_DIR):
        return

    now = time.time()
    cutoff = max_hours * 3600

    # 清理旧版遗留文件（TEMP_DIR 根目录，跳过 uploads/ 和 tasks/）。
    for name in os.listdir(TEMP_DIR):
        if name in {"uploads", "tasks"}:
            continue
        path = os.path.join(TEMP_DIR, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
                logger.info("清理旧版残留目录: %s", name)
            else:
                os.remove(path)
                logger.info("清理旧版残留文件: %s", name)
        except OSError:
            pass

    if os.path.exists(UPLOADS_DIR):
        for name in os.listdir(UPLOADS_DIR):
            path = os.path.join(UPLOADS_DIR, name)
            try:
                if now - os.path.getmtime(path) > cutoff:
                    os.remove(path)
                    logger.info("清理过期上传文件: %s", name)
            except OSError:
                pass

    tasks_dir = os.path.join(TEMP_DIR, "tasks")
    if os.path.exists(tasks_dir):
        for name in os.listdir(tasks_dir):
            path = os.path.join(tasks_dir, name)
            if not os.path.isdir(path):
                continue
            try:
                if now - os.path.getmtime(path) > cutoff:
                    shutil.rmtree(path, ignore_errors=True)
                    logger.info("清理过期任务目录: %s", name)
            except OSError:
                pass
