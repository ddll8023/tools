"""PDF 转 Markdown 共享辅助函数"""

import os
import json

from app.utils.temp_cleanup import TEMP_DIR, UPLOADS_DIR, get_task_dir, validate_task_id
from app.utils.exception import ServiceException
from app.utils.markdown import count_tables
from app.schemas.response import ErrorCode
from app.utils.logger_config import setup_logger
from app.schemas.tools.pdf_to_markdown import GetPreviewResponse

logger = setup_logger(__name__)


def _check_task_path(task_dir: str):
    """校验任务目录仍位于临时目录内，防止路径逃逸。"""
    root = os.path.abspath(TEMP_DIR)
    if os.path.commonpath([root, os.path.abspath(task_dir)]) != root:
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")


def get_preview_detail(task_id: str):
    """获取 Markdown 预览"""
    logger.info(f"获取预览: task_id={task_id}")
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = get_task_dir(task_id)
    _check_task_path(task_dir)

    if not os.path.exists(task_dir):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "任务不存在")

    md_path = os.path.join(task_dir, "output.md")
    if not os.path.exists(md_path):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "转换结果不存在")

    images_dir = os.path.join(task_dir, "images")
    image_count = len(os.listdir(images_dir)) if os.path.exists(images_dir) else 0

    with open(md_path, encoding="utf-8") as f:
        md_content = f.read()

    table_count = count_tables(md_content)
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
    _check_task_path(task_dir)

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
