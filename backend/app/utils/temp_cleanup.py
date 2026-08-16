"""临时文件清理工具函数

从 pdf_to_markdown_helpers.py 抽取的通用函数，
供所有工具的服务层共享。
"""

import os
import re
import time
import shutil

from app.core.config import settings
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

# 临时任务必须写入用户数据目录，不能写入打包后的只读应用资源目录。
TEMP_DIR = os.path.join(settings.data_root, "temp")
UPLOADS_DIR = os.path.join(TEMP_DIR, "uploads")


def validate_task_id(task_id: str) -> bool:
    """校验 task_id 仅含合法字符"""
    return bool(re.match(r"^[a-f0-9]{12}$", task_id))


def get_task_dir(task_id: str) -> str:
    """获取任务目录"""
    return os.path.join(TEMP_DIR, "tasks", task_id)


def cleanup_expired_temp(max_hours: int = 24):
    """删除超过指定时间的临时目录和文件"""
    if not os.path.exists(TEMP_DIR):
        return
    now = time.time()
    cutoff = max_hours * 3600

    # 清理旧版遗留文件（TEMP_DIR 根目录，跳过 uploads/ 和 tasks/）
    for name in os.listdir(TEMP_DIR):
        if name in ("uploads", "tasks"):
            continue
        path = os.path.join(TEMP_DIR, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
                logger.info(f"清理旧版残留目录: {name}")
            else:
                os.remove(path)
                logger.info(f"清理旧版残留文件: {name}")
        except OSError:
            pass

    # 清理 uploads/ 目录下的过期文件
    if os.path.exists(UPLOADS_DIR):
        for name in os.listdir(UPLOADS_DIR):
            path = os.path.join(UPLOADS_DIR, name)
            try:
                if now - os.path.getmtime(path) > cutoff:
                    os.remove(path)
                    logger.info(f"清理过期上传文件: {name}")
            except OSError:
                pass

    # 清理 tasks/ 目录下的过期任务目录
    tasks_dir = os.path.join(TEMP_DIR, "tasks")
    if os.path.exists(tasks_dir):
        for name in os.listdir(tasks_dir):
            path = os.path.join(tasks_dir, name)
            if not os.path.isdir(path):
                continue
            try:
                if now - os.path.getmtime(path) > cutoff:
                    shutil.rmtree(path, ignore_errors=True)
                    logger.info(f"清理过期任务目录: {name}")
            except OSError:
                pass
