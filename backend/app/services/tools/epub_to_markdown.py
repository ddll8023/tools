"""EPUB 转 Markdown 服务。"""

import os
import shutil
import uuid

from fastapi import UploadFile

from app.schemas.response import ErrorCode
from app.schemas.tools.epub_to_markdown import ConvertResponse
from app.services.tools.epub_to_markdown_helpers import (
    TEMP_UPLOADS_DIR,
    convert_epub,
    create_download_zip,
    get_preview_detail,
    validate_and_extract_epub,
)
from app.utils.exception import ServiceException
from app.utils.file import save_file, safe_filename
from app.utils.logger_config import setup_logger
from app.utils.temp_cleanup import get_task_dir

logger = setup_logger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024


def convert_epub_file(file: UploadFile) -> ConvertResponse:
    """上传并同步转换 EPUB。"""
    filename = safe_filename(file.filename, "book.epub")
    if not filename.lower().endswith(".epub"):
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "不支持的文件格式")

    content = file.file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise ServiceException(ErrorCode.FILE_TOO_LARGE, "文件大小不能超过 50MB")
    if not content:
        raise ServiceException(ErrorCode.PARAM_ERROR, "文件不能为空")

    task_id = uuid.uuid4().hex[:12]
    task_dir = get_task_dir(task_id)
    extract_dir = os.path.join(task_dir, "epub")
    os.makedirs(extract_dir, exist_ok=True)
    os.makedirs(TEMP_UPLOADS_DIR, exist_ok=True)
    upload_path = os.path.join(TEMP_UPLOADS_DIR, f"{task_id}-{filename}")
    save_file(content, upload_path)
    try:
        validate_and_extract_epub(upload_path, extract_dir)
        _, chapter_count, _, image_count, _ = convert_epub(extract_dir)
        with open(os.path.join(task_dir, "meta.txt"), "w", encoding="utf-8") as stream:
            stream.write(filename)
    except ServiceException:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise
    except Exception as exc:
        logger.error(f"EPUB 转换失败: task_id={task_id} error={exc}", exc_info=True)
        shutil.rmtree(task_dir, ignore_errors=True)
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "EPUB 转换失败")
    finally:
        try:
            os.remove(upload_path)
        except OSError:
            pass

    logger.info(f"EPUB 转换完成: task_id={task_id} chapters={chapter_count} images={image_count}")
    return ConvertResponse(
        task_id=task_id,
        filename=filename,
        chapter_count=chapter_count,
        image_count=image_count,
    )


def download_epub_markdown(task_id: str) -> tuple[str, str]:
    """返回 Markdown 与图片 ZIP 下载路径及原始文件名。"""
    return create_download_zip(task_id)
