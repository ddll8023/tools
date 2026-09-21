"""复用 Markdown 转 Word 排版，再由 LibreOffice 生成 PDF。"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.schemas.response import ErrorCode
from app.modules.markdown_to_pdf.schemas import ConvertResponse
from app.core.errors import ServiceException
from app.utils.file import safe_filename
from app.integrations.libreoffice import convert_to_pdf
from app.utils.logger_config import setup_logger
from app.modules.markdown_document.docx import DocumentRenderOptions, render_markdown_to_docx
from app.modules.markdown_document.source import (
    MarkdownInputError,
    MarkdownSource,
    prepare_markdown_source,
    read_markdown,
)
from app.infrastructure.task_storage.workspace import (
    ensure_task_path,
    get_task_dir,
    validate_task_id,
)

logger = setup_logger(__name__)

PDF_MEDIA_TYPE = "application/pdf"
CONVERT_TIMEOUT = 600
_UPLOAD_IMAGE_HINT = (
    "图片文件未随 Markdown 一起提供：桌面端可用「选择本地 Markdown」直接读取同目录图片，"
    "或把 .md 与 images/ 目录一起打包成 ZIP 上传"
)


def convert_markdown_to_pdf(
    file: UploadFile | None,
    source_path: str | None = None,
    *,
    landscape: bool = False,
    margin_mm: int = 18,
    font_size: int = 11,
    page_numbers: bool = True,
) -> ConvertResponse:
    """将 Markdown 先渲染为 DOCX，再调用 LibreOffice 生成 PDF。"""
    _validate_options(margin_mm, font_size)
    task_id = uuid.uuid4().hex[:12]
    task_dir = Path(get_task_dir(task_id))
    task_dir.mkdir(parents=True, exist_ok=True)

    try:
        source, filename = prepare_markdown_source(file, source_path, task_dir)
        markdown_content = read_markdown(source.markdown_path)
        output_stem = safe_filename(source.markdown_path.stem, "document")
        docx_path = task_dir / "output.docx"
        pdf_path = task_dir / "output.pdf"

        logger.info("开始 Markdown 转 PDF: task_id=%s filename=%s", task_id, filename)
        warnings = render_markdown_to_docx(
            markdown_content,
            source.base_dir,
            docx_path,
            DocumentRenderOptions(
                landscape=landscape,
                margin_mm=margin_mm,
                font_size=font_size,
                page_numbers=page_numbers,
            ),
        )
        warnings.extend(_missing_image_hints(source, warnings))
        _validate_docx(docx_path)
        convert_to_pdf(docx_path, pdf_path, task_dir, timeout=CONVERT_TIMEOUT)

        output_filename = f"{output_stem}.pdf"
        _write_meta(task_dir, {
            "filename": filename,
            "output_filename": output_filename,
            "warnings": warnings,
        })
        logger.info("Markdown 转 PDF 完成: task_id=%s warnings=%s", task_id, len(warnings))
        return ConvertResponse(
            task_id=task_id,
            filename=filename,
            output_filename=output_filename,
            warnings=warnings,
        )
    except ServiceException:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise
    except MarkdownInputError as exc:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, str(exc)) from exc
    except UnicodeDecodeError as exc:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise ServiceException(ErrorCode.UNSUPPORTED_CONTENT, "Markdown 文件必须使用 UTF-8 编码") from exc
    except Exception as exc:
        shutil.rmtree(task_dir, ignore_errors=True)
        logger.error("Markdown 转 PDF 异常: task_id=%s error=%s", task_id, exc, exc_info=True)
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "Markdown 转 PDF 失败") from exc


def download_pdf(task_id: str) -> tuple[str, str, str]:
    """获取 Markdown 转 PDF 的结果文件。"""
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")
    task_dir = Path(get_task_dir(task_id))
    ensure_task_path(task_dir)
    metadata = _read_meta(task_dir)
    output_filename = metadata.get("output_filename")
    if not isinstance(output_filename, str) or not output_filename.lower().endswith(".pdf"):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "转换结果不存在")
    pdf_path = task_dir / "output.pdf"
    ensure_task_path(pdf_path)
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "文件不存在")
    return str(pdf_path), safe_filename(output_filename, f"{task_id}.pdf"), PDF_MEDIA_TYPE


def _validate_options(margin_mm: int, font_size: int) -> None:
    if not 10 <= margin_mm <= 30:
        raise ServiceException(ErrorCode.PARAM_ERROR, "页边距必须在 10 到 30 mm 之间")
    if not 8 <= font_size <= 20:
        raise ServiceException(ErrorCode.PARAM_ERROR, "字号必须在 8 到 20 pt 之间")


def _missing_image_hints(source: MarkdownSource, warnings: list[str]) -> list[str]:
    if source.from_local or not any("图片文件不存在" in warning for warning in warnings):
        return []
    return [_UPLOAD_IMAGE_HINT]


def _validate_docx(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "未生成有效的 DOCX 中间文件")


def _write_meta(task_dir: Path, metadata: dict[str, object]) -> None:
    with (task_dir / "meta.json").open("w", encoding="utf-8") as stream:
        json.dump(metadata, stream, ensure_ascii=False)


def _read_meta(task_dir: Path) -> dict[str, object]:
    meta_path = task_dir / "meta.json"
    ensure_task_path(meta_path)
    try:
        with meta_path.open(encoding="utf-8") as stream:
            metadata = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "转换结果不存在") from exc
    if not isinstance(metadata, dict):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "转换结果不存在")
    return metadata
