"""Markdown 转 Word 服务。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path
from typing import Literal

from fastapi import UploadFile

from app.core.config import settings
from app.schemas.response import ErrorCode
from app.schemas.tools.markdown_to_word import ConvertResponse
from app.utils.exception import ServiceException
from app.utils.file import safe_filename
from app.utils.logger_config import setup_logger
from app.utils.markdown_docx import render_markdown_to_docx
from app.utils.markdown_source import (
    MarkdownInputError,
    MarkdownSource,
    prepare_markdown_source,
    read_markdown,
)
from app.utils.temp_cleanup import TEMP_DIR, get_task_dir, validate_task_id

logger = setup_logger(__name__)

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOC_MEDIA_TYPE = "application/msword"
OutputFormat = Literal["docx", "doc"]

CONVERT_TIMEOUT = 120

_UPLOAD_IMAGE_HINT = (
    "图片文件未随 Markdown 一起提供：桌面端可用「选择本地 Markdown」直接读取同目录图片，"
    "或把 .md 与 images/ 目录一起打包成 ZIP 上传"
)


_POPEN_KWARGS: dict[str, int] = {}
if os.name == "nt":
    _POPEN_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW


def convert_markdown_to_word(
    file: UploadFile | None,
    output_format: str = "docx",
    source_path: str | None = None,
) -> ConvertResponse:
    """接收本地 Markdown 路径、上传的 Markdown 或资源 ZIP，并生成 DOCX/DOC。"""
    normalized_format = output_format.lower().strip()
    if normalized_format not in {"docx", "doc"}:
        raise ServiceException(ErrorCode.PARAM_ERROR, "输出格式必须是 docx 或 doc")
    selected_format: OutputFormat = "doc" if normalized_format == "doc" else "docx"

    task_id = uuid.uuid4().hex[:12]
    task_dir = Path(get_task_dir(task_id))
    task_dir.mkdir(parents=True, exist_ok=True)

    try:
        source, filename = prepare_markdown_source(file, source_path, task_dir)
        markdown_content = read_markdown(source.markdown_path)
        output_stem = safe_filename(source.markdown_path.stem, "document")
        output_filename = f"{output_stem}.{selected_format}"
        docx_path = task_dir / "output.docx"

        logger.info(
            "开始 Markdown 转 Word: task_id=%s filename=%s format=%s",
            task_id,
            filename,
            selected_format,
        )
        warnings = render_markdown_to_docx(
            markdown_content,
            source.base_dir,
            docx_path,
        )
        warnings.extend(_missing_image_hints(source, warnings))
        _validate_docx(docx_path)

        output_path = docx_path
        if selected_format == "doc":
            output_path = task_dir / "output.doc"
            _convert_docx_to_doc(docx_path, output_path, task_dir)
            _validate_doc(output_path)

        metadata = {
            "filename": filename,
            "output_filename": output_filename,
            "output_format": selected_format,
            "warnings": warnings,
        }
        _write_meta(task_dir, metadata)

        logger.info(
            "Markdown 转 Word 完成: task_id=%s format=%s warnings=%s",
            task_id,
            selected_format,
            len(warnings),
        )
        return ConvertResponse(
            task_id=task_id,
            filename=filename,
            output_filename=output_filename,
            output_format=selected_format,
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
        logger.error(
            "Markdown 转 Word 异常: task_id=%s error=%s",
            task_id,
            exc,
            exc_info=True,
        )
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "Markdown 转 Word 失败") from exc


def download_word(task_id: str) -> tuple[str, str, str]:
    """获取 Word 文件下载路径、文件名和媒体类型。"""
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = Path(get_task_dir(task_id))
    _check_task_path(task_dir)
    meta = _read_meta(task_dir)
    output_format = meta.get("output_format")
    if output_format not in {"docx", "doc"}:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "转换结果不存在")

    output_path = task_dir / f"output.{output_format}"
    _check_task_path(output_path)
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "文件不存在")

    fallback = f"{task_id}.{output_format}"
    raw_filename = meta.get("output_filename")
    output_filename = (
        safe_filename(raw_filename, fallback)
        if isinstance(raw_filename, str) and raw_filename.lower().endswith(f".{output_format}")
        else fallback
    )
    media_type = DOCX_MEDIA_TYPE if output_format == "docx" else DOC_MEDIA_TYPE
    return str(output_path), output_filename, media_type


def _missing_image_hints(source: MarkdownSource, warnings: list[str]) -> list[str]:
    """Markdown 引用的图片全部缺失时，补充可恢复操作的提示。"""
    if source.from_local:
        return []
    if not any("图片文件不存在" in warning for warning in warnings):
        return []
    return [_UPLOAD_IMAGE_HINT]


def _convert_docx_to_doc(docx_path: Path, output_path: Path, task_dir: Path) -> None:
    libreoffice_path = settings.libreoffice_path
    if not libreoffice_path:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "DOC 格式需要 LibreOffice")

    profile_dir = task_dir / "libreoffice-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        libreoffice_path,
        "--headless",
        "--nologo",
        "--nodefault",
        "--norestore",
        "--nofirststartwizard",
        f"-env:UserInstallation={profile_dir.as_uri()}",
        "--convert-to",
        "doc:MS Word 97",
        "--outdir",
        str(task_dir),
        str(docx_path),
    ]

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_POPEN_KWARGS,
        )
        try:
            _stdout, stderr = process.communicate(timeout=CONVERT_TIMEOUT)
        except subprocess.TimeoutExpired:
            _kill_process_tree(process)
            raise ServiceException(ErrorCode.TIMEOUT, "DOC 转换超时，文档可能过大或格式复杂")

        if process.returncode != 0:
            error_detail = stderr.decode(errors="replace").strip() if stderr else "未知错误"
            logger.error("DOC 转换失败: error=%s", error_detail)
            raise ServiceException(ErrorCode.CONVERSION_FAILED, "DOC 转换失败，请确认 LibreOffice 可用")
    except FileNotFoundError as exc:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "未检测到 LibreOffice，无法生成 DOC") from exc

    if not output_path.is_file():
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "DOC 转换未生成输出文件")


def _kill_process_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
        else:
            process.kill()
    except Exception:
        pass
    try:
        process.wait(timeout=5)
    except Exception:
        pass


def _validate_docx(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "转换未生成有效的 DOCX 文件")

    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ServiceException(ErrorCode.CONVERSION_FAILED, "生成的 DOCX 文件已损坏")
            required = {"[Content_Types].xml", "word/document.xml"}
            if not required.issubset(archive.namelist()):
                raise ServiceException(ErrorCode.CONVERSION_FAILED, "生成的 DOCX 文件格式无效")
    except ServiceException:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "生成的 DOCX 文件格式无效") from exc


def _validate_doc(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "转换未生成有效的 DOC 文件")


def _check_task_path(path: Path) -> None:
    root = Path(TEMP_DIR).resolve()
    candidate = path.resolve()
    if not candidate.is_relative_to(root):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")


def _write_meta(task_dir: Path, metadata: dict[str, object]) -> None:
    with (task_dir / "meta.json").open("w", encoding="utf-8") as stream:
        json.dump(metadata, stream, ensure_ascii=False)


def _read_meta(task_dir: Path) -> dict[str, object]:
    meta_path = task_dir / "meta.json"
    _check_task_path(meta_path)
    try:
        with meta_path.open(encoding="utf-8") as stream:
            metadata = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "转换结果不存在") from exc
    if not isinstance(metadata, dict):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "转换结果不存在")
    return metadata
