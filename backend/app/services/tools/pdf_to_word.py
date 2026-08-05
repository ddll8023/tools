"""PDF 转 Word 服务。"""

from __future__ import annotations

import json
import os
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from typing import Any

import fitz
from fastapi import UploadFile

from app.schemas.response import ErrorCode
from app.schemas.tools.pdf_to_word import ConvertResponse
from app.utils.exception import ServiceException
from app.utils.file import safe_filename, save_file
from app.utils.logger_config import setup_logger
from app.utils.temp_cleanup import TEMP_DIR, get_task_dir, validate_task_id

logger = setup_logger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024
SUPPORTED_EXTENSIONS = (".pdf",)
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass(frozen=True)
class PdfInspection:
    """PDF 基础检查结果。"""

    page_count: int
    text_page_count: int

    @property
    def warnings(self) -> list[str]:
        if self.text_page_count < self.page_count:
            return ["部分页面未检测到文字层，转换结果可能需要人工校对"]
        return []


def _check_task_path(task_dir: str) -> None:
    """确保任务目录仍位于临时目录内。"""
    root = os.path.realpath(TEMP_DIR)
    candidate = os.path.realpath(task_dir)
    try:
        is_inside = os.path.commonpath([root, candidate]) == root
    except ValueError:
        is_inside = False
    if not is_inside:
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")


def _inspect_pdf(pdf_path: str) -> PdfInspection:
    """检查 PDF 是否可解析，并判断是否存在文字层。"""
    try:
        document = fitz.open(pdf_path)
    except Exception as exc:
        logger.warning("PDF 打开失败: error=%s", exc)
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "无法解析 PDF 文件") from exc

    try:
        if document.needs_pass:
            raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "PDF 已加密，暂不支持转换")

        page_count = len(document)
        if page_count <= 0:
            raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "PDF 不包含可转换页面")

        text_page_count = 0
        for page in document:
            if page.get_text("text").strip():
                text_page_count += 1

        if text_page_count == 0:
            raise ServiceException(
                ErrorCode.UNSUPPORTED_CONTENT,
                "当前仅支持包含文字层的 PDF，纯扫描 PDF 暂不支持转换为 Word",
            )

        return PdfInspection(page_count=page_count, text_page_count=text_page_count)
    except ServiceException:
        raise
    except Exception as exc:
        logger.warning("PDF 检查失败: error=%s", exc)
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "PDF 检查失败，请确认文件未损坏") from exc
    finally:
        document.close()


def _convert_with_pdf2docx(pdf_path: str, output_path: str) -> None:
    """调用 pdf2docx 生成 DOCX。"""
    try:
        from pdf2docx import Converter
    except ImportError as exc:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "PDF 转 Word 依赖未安装") from exc

    converter: Any | None = None
    try:
        converter = Converter(pdf_path)
        converter.convert(output_path, start=0, end=None)
    except ServiceException:
        raise
    except Exception as exc:
        logger.error("pdf2docx 转换失败: error=%s", exc, exc_info=True)
        raise ServiceException(
            ErrorCode.CONVERSION_FAILED,
            "PDF 转 Word 失败，请确认文件未损坏或版式未超出支持范围",
        ) from exc
    finally:
        if converter is not None:
            try:
                converter.close()
            except Exception as exc:
                logger.warning("pdf2docx 资源释放失败: error=%s", exc)


def _validate_docx(output_path: str) -> None:
    """验证转换结果是可读取的 DOCX 压缩包。"""
    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "转换未生成有效的 Word 文件")

    try:
        with zipfile.ZipFile(output_path) as archive:
            if archive.testzip() is not None:
                raise ServiceException(ErrorCode.CONVERSION_FAILED, "生成的 Word 文件已损坏")
            required = {"[Content_Types].xml", "word/document.xml"}
            if not required.issubset(archive.namelist()):
                raise ServiceException(ErrorCode.CONVERSION_FAILED, "生成的 Word 文件格式无效")
    except ServiceException:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        logger.error("DOCX 结果校验失败: error=%s", exc, exc_info=True)
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "生成的 Word 文件格式无效") from exc


def _write_meta(task_dir: str, metadata: dict[str, object]) -> None:
    meta_path = os.path.join(task_dir, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as stream:
        json.dump(metadata, stream, ensure_ascii=False)


def convert_pdf_to_word(file: UploadFile) -> ConvertResponse:
    """将包含文字层的 PDF 转换为 DOCX。"""
    filename = safe_filename(file.filename, "input.pdf")
    if not filename.lower().endswith(SUPPORTED_EXTENSIONS):
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "仅支持 .pdf 格式")

    try:
        content = file.file.read(MAX_FILE_SIZE + 1)
    except OSError as exc:
        logger.error("读取 PDF 失败: filename=%s error=%s", filename, exc, exc_info=True)
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "读取 PDF 文件失败") from exc

    if len(content) > MAX_FILE_SIZE:
        raise ServiceException(ErrorCode.FILE_TOO_LARGE, "文件大小不能超过 50MB")
    if not content:
        raise ServiceException(ErrorCode.PARAM_ERROR, "文件不能为空")

    task_id = uuid.uuid4().hex[:12]
    task_dir = get_task_dir(task_id)
    input_path = os.path.join(task_dir, "input.pdf")
    output_path = os.path.join(task_dir, "output.docx")
    output_filename = f"{os.path.splitext(filename)[0]}.docx"

    try:
        save_file(content, input_path)
        inspection = _inspect_pdf(input_path)

        logger.info(
            "开始 PDF 转 Word: task_id=%s filename=%s pages=%s",
            task_id,
            filename,
            inspection.page_count,
        )
        _convert_with_pdf2docx(input_path, output_path)
        _validate_docx(output_path)

        metadata = {
            "original_filename": filename,
            "output_filename": output_filename,
            "page_count": inspection.page_count,
            "engine": "pdf2docx",
            "warnings": inspection.warnings,
        }
        _write_meta(task_dir, metadata)

        logger.info("PDF 转 Word 完成: task_id=%s filename=%s", task_id, filename)
        return ConvertResponse(
            task_id=task_id,
            filename=filename,
            output_filename=output_filename,
            page_count=inspection.page_count,
            warnings=inspection.warnings,
        )
    except ServiceException:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(task_dir, ignore_errors=True)
        logger.error("PDF 转 Word 异常: task_id=%s error=%s", task_id, exc, exc_info=True)
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "PDF 转 Word 失败") from exc


def download_docx(task_id: str) -> tuple[str, str]:
    """获取 DOCX 下载路径和文件名。"""
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = get_task_dir(task_id)
    _check_task_path(task_dir)
    output_path = os.path.join(task_dir, "output.docx")
    _check_task_path(output_path)
    if not os.path.isfile(output_path):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "文件不存在")

    output_filename = f"{task_id}.docx"
    meta_path = os.path.join(task_dir, "meta.json")
    _check_task_path(meta_path)
    try:
        with open(meta_path, encoding="utf-8") as stream:
            metadata = json.load(stream)
        raw_filename = metadata.get("output_filename")
        if isinstance(raw_filename, str) and raw_filename.lower().endswith(".docx"):
            output_filename = safe_filename(raw_filename, output_filename)
    except (OSError, json.JSONDecodeError):
        logger.warning("读取 PDF 转 Word 元数据失败: task_id=%s", task_id)

    return output_path, output_filename
