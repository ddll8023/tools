"""PDF 转 Markdown 服务"""
import uuid
import os
import shutil
import re
from pathlib import Path

import fitz

from app.utils.logger_config import setup_logger
from app.utils.exception import ServiceException
from app.schemas.response import ErrorCode
from app.schemas.tools.pdf_to_markdown import ConvertResponse, GetPreviewResponse

logger = setup_logger(__name__)

TEMP_DIR = Path(__file__).resolve().parents[3] / "temp"


# ========== 公共入口函数 ==========


def convert_pdf(file_path: str, filename: str) -> ConvertResponse:
    """转换 PDF 为 Markdown"""
    with open(file_path, "rb") as f:
        header = f.read(4)
    if header != b"%PDF":
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "不支持的文件格式")

    task_id = uuid.uuid4().hex[:12]
    task_dir = _ensure_temp_dir(task_id)

    pdf_path = task_dir / "input.pdf"
    shutil.copy2(file_path, str(pdf_path))

    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "无法解析 PDF 文件")

    page_count = len(doc)
    md_content = []
    images_dir = task_dir / "images"
    images_dir.mkdir(exist_ok=True)
    image_count = 0
    table_count = 0

    for page_num in range(page_count):
        page = doc[page_num]
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
            img_path = images_dir / img_filename
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

    md_path = task_dir / "output.md"
    full_md = "\n".join(md_content)
    md_path.write_text(full_md, encoding="utf-8")

    logger.info(f"PDF 转换完成: task_id={task_id} pages={page_count} tables={table_count} images={image_count}")
    return ConvertResponse(task_id=task_id, filename=filename, page_count=page_count)


def get_preview_detail(task_id: str) -> GetPreviewResponse:
    """获取 Markdown 预览"""
    if not _validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = _get_task_dir(task_id)
    resolved = task_dir.resolve()
    if not str(resolved).startswith(str(TEMP_DIR.resolve())):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    if not task_dir.exists():
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "任务不存在")

    md_path = task_dir / "output.md"
    if not md_path.exists():
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "转换结果不存在")

    images_dir = task_dir / "images"
    image_count = len(list(images_dir.glob("*"))) if images_dir.exists() else 0

    md_content = md_path.read_text(encoding="utf-8")
    table_count = md_content.count("\n|---")
    page_count = md_content.count("\n---\n\n## 第")

    return GetPreviewResponse(
        markdown_content=md_content,
        page_count=page_count,
        table_count=table_count,
        image_count=image_count,
    )


"""辅助函数"""


def _ensure_temp_dir(task_id: str) -> Path:
    """确保临时目录存在"""
    task_dir = TEMP_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir


def _get_task_dir(task_id: str) -> Path:
    """获取任务目录"""
    return TEMP_DIR / task_id


def _validate_task_id(task_id: str) -> bool:
    """校验 task_id 仅含合法字符，防止路径遍历"""
    return bool(re.match(r'^[a-f0-9]{12}$', task_id))
