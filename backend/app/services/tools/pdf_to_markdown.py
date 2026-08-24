"""PDF 转 Markdown 服务"""

import os
import uuid
import shutil

import fitz
from fastapi import UploadFile

from app.utils.file import save_file, safe_filename
from app.utils.logger_config import setup_logger
from app.utils.exception import ServiceException
from app.schemas.response import ErrorCode
from app.schemas.tools.pdf_to_markdown import ConvertResponse
from app.services.tools.pdf_to_markdown_helpers import (
    TEMP_DIR,
    UPLOADS_DIR,
    get_preview_detail,
    download_md,
)

logger = setup_logger(__name__)


# ========== 公共入口函数 ==========


def convert_pdf(file: UploadFile):
    """转换 PDF 为 Markdown（标准模式）"""
    safe_name = safe_filename(file.filename, "input.pdf")
    if not safe_name.lower().endswith(".pdf"):
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "不支持的文件格式")
    if file.size > 50 * 1024 * 1024:
        raise ServiceException(ErrorCode.FILE_TOO_LARGE, "文件大小不能超过 50MB")

    task_id = uuid.uuid4().hex[:12]
    task_dir = os.path.join(TEMP_DIR, "tasks", task_id)
    os.makedirs(task_dir, exist_ok=True)

    # 记录原始文件名，供下载命名使用
    with open(os.path.join(task_dir, "meta.txt"), "w", encoding="utf-8") as f:
        f.write(safe_name)

    # 保存原始 PDF 到 uploads/（带 task_id 前缀）
    upload_filename = f"{task_id}-{safe_name}"
    upload_path = os.path.join(UPLOADS_DIR, upload_filename)
    save_file(file.file.read(), upload_path)

    # 复制到任务目录
    pdf_path = os.path.join(task_dir, "input.pdf")
    shutil.copy2(upload_path, pdf_path)

    logger.info(f"开始转换 PDF: task_id={task_id} filename={safe_name}")

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "无法解析 PDF 文件")

    try:
        if doc.needs_pass:
            raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "PDF 已加密，暂不支持解析")
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
                    cleaned_headers = [str(h).replace("\n", " ") if h else "" for h in headers]
                    md_content.append("| " + " | ".join(cleaned_headers) + " |")
                    md_content.append("| " + " | ".join(["---"] * len(cleaned_headers)) + " |")
                for row in table.extract():
                    cleaned = [str(cell).replace("\n", " ") if cell else "" for cell in row]
                    md_content.append("| " + " | ".join(cleaned) + " |")
                md_content.append("")
                table_count += 1
    except ServiceException:
        raise
    except Exception:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "PDF 解析失败，请确认文件未损坏")
    finally:
        doc.close()

    md_path = os.path.join(task_dir, "output.md")
    full_md = "\n".join(md_content)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(full_md)

    logger.info(
        f"PDF 转换完成: task_id={task_id} pages={page_count} tables={table_count} images={image_count}"
    )
    return ConvertResponse(
        task_id=task_id, filename=safe_name, page_count=page_count
    )
