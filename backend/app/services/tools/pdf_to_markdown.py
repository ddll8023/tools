"""PDF 转 Markdown 服务"""

import os
import uuid

import fitz
from fastapi import UploadFile

from app.core.config import settings
from app.utils.file import save_file
from app.utils.logger_config import setup_logger
from app.utils.exception import ServiceException
from app.schemas.response import ErrorCode
from app.schemas.tools.pdf_to_markdown import ConvertResponse
from app.services.tools.pdf_to_markdown_helpers import (
    TEMP_DIR,
    get_preview_detail,
    download_md,
)

logger = setup_logger(__name__)


# ========== 公共入口函数 ==========


def convert_pdf(file: UploadFile):
    """转换 PDF 为 Markdown（标准模式）"""
    if not file.filename.lower().endswith(".pdf"):
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "不支持的文件格式")
    if file.size > 50 * 1024 * 1024:
        raise ServiceException(ErrorCode.FILE_TOO_LARGE, "文件大小不能超过 50MB")

    task_id = uuid.uuid4().hex[:12]
    task_dir = os.path.join(TEMP_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)
    pdf_path = os.path.join(TEMP_DIR, file.filename)

    save_file(file.file.read(), pdf_path)

    logger.info(f"开始转换 PDF: task_id={task_id} filename={file.filename}")

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "无法解析 PDF 文件")

    page_count = len(doc)
    md_content = []
    images_dir = os.path.join(task_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    image_count = 0
    table_count = 0

    for page_num in range(page_count):
        page = doc[page_num]
        logger.info(f"正在处理第 {page_num + 1} 页: task_id={task_id}")
        md_content.append(f"\n\n---\n\n## 第 {page_num + 1} 页\n")

        text = page.get_text().strip()
        if text:
            md_content.append(text)

        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            base_image = doc.extract_image(xref)
            img_bytes = base_image["image"]
            img_ext = base_image["ext"]
            img_filename = f"page{page_num + 1}_{img_index + 1}.{img_ext}"
            img_path = os.path.join(images_dir, img_filename)
            with open(img_path, "wb") as f:
                f.write(img_bytes)
            md_content.append(f"\n![图片](images/{img_filename})\n")
            image_count += 1

        tables = page.find_tables()
        for table in tables:
            md_content.append("\n")
            headers = table.header.names if table.header else []
            if headers:
                md_content.append("| " + " | ".join(headers) + " |")
                md_content.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for row in table.extract():
                cleaned = [str(cell).replace("\n", " ") if cell else "" for cell in row]
                md_content.append("| " + " | ".join(cleaned) + " |")
            md_content.append("")
            table_count += 1

    doc.close()

    md_path = os.path.join(task_dir, "output.md")
    full_md = "\n".join(md_content)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(full_md)

    logger.info(
        f"PDF 转换完成: task_id={task_id} pages={page_count} tables={table_count} images={image_count}"
    )
    return ConvertResponse(
        task_id=task_id, filename=file.filename, page_count=page_count
    )
