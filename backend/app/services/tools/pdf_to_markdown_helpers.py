"""PDF 转 Markdown 共享辅助函数"""

import os
import re
import json
import time
import shutil

from app.core.config import settings
from app.utils.exception import ServiceException
from app.schemas.response import ErrorCode
from app.utils.logger_config import setup_logger
from app.schemas.tools.pdf_to_markdown import GetPreviewResponse

logger = setup_logger(__name__)

TEMP_DIR = os.path.join(settings.ROOT_PATH, "temp")


def validate_task_id(task_id: str):
    """校验 task_id 仅含合法字符"""
    return bool(re.match(r"^[a-f0-9]{12}$", task_id))


def get_task_dir(task_id: str):
    """获取任务目录"""
    return os.path.join(TEMP_DIR, task_id)


def get_preview_detail(task_id: str):
    """获取 Markdown 预览"""
    logger.info(f"获取预览: task_id={task_id}")
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = get_task_dir(task_id)
    resolved = os.path.abspath(task_dir)
    if not resolved.startswith(os.path.abspath(TEMP_DIR)):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    if not os.path.exists(task_dir):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "任务不存在")

    md_path = os.path.join(task_dir, "output.md")
    if not os.path.exists(md_path):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "转换结果不存在")

    images_dir = os.path.join(task_dir, "images")
    image_count = len(os.listdir(images_dir)) if os.path.exists(images_dir) else 0

    with open(md_path, encoding="utf-8") as f:
        md_content = f.read()

    table_count = md_content.count("\n|---")
    page_count = md_content.count("\n---\n\n## 第")

    # 标准模式使用 ## 第 N 页 标记分页，MinerU 输出无此标记时从原始 PDF 获取页数
    if page_count == 0:
        pdf_path = os.path.join(task_dir, "input.pdf")
        if os.path.exists(pdf_path):
            try:
                import fitz
                doc = fitz.open(pdf_path)
                page_count = len(doc)
                doc.close()
            except Exception:
                pass

    logger.info(f"预览返回: task_id={task_id} pages={page_count} tables={table_count} images={image_count}")
    return GetPreviewResponse(
        markdown_content=md_content,
        page_count=page_count,
        table_count=table_count,
        image_count=image_count,
    )


def download_md(task_id: str):
    """获取 Markdown 文件下载路径"""
    logger.info(f"下载文件: task_id={task_id}")
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = get_task_dir(task_id)
    resolved = os.path.abspath(task_dir)
    if not resolved.startswith(os.path.abspath(TEMP_DIR)):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    md_path = os.path.join(task_dir, "output.md")
    if not os.path.exists(md_path):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "文件不存在")

    logger.info(f"文件下载返回: task_id={task_id}")
    return md_path


def normalize_output(task_dir: str, mineru_result):
    """将 MinerU 输出归一化为标准目录结构"""
    md_path = os.path.join(task_dir, "output.md")
    md_content = mineru_result.markdown if hasattr(mineru_result, "markdown") else str(mineru_result)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)


def write_status_atomic(task_dir: str, progress: int, stage: str):
    """原子写入进度状态文件（先写 .tmp 再 rename）"""
    os.makedirs(task_dir, exist_ok=True)
    tmp_path = os.path.join(task_dir, "deep_status.json.tmp")
    final_path = os.path.join(task_dir, "deep_status.json")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"progress": progress, "stage": stage}, f, ensure_ascii=False)
    os.replace(tmp_path, final_path)


def cleanup_expired_temp(max_hours: int = 24):
    """删除超过指定时间的临时目录"""
    if not os.path.exists(TEMP_DIR):
        return
    now = time.time()
    cutoff = max_hours * 3600
    for name in os.listdir(TEMP_DIR):
        path = os.path.join(TEMP_DIR, name)
        if not os.path.isdir(path):
            continue
        try:
            if now - os.path.getmtime(path) > cutoff:
                shutil.rmtree(path, ignore_errors=True)
                logger.info(f"清理过期临时目录: {name}")
        except OSError:
            pass
