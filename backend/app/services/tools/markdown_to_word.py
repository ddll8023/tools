"""Markdown 转 Word 服务。"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import UploadFile

from app.core.config import settings
from app.schemas.response import ErrorCode
from app.schemas.tools.markdown_to_word import ConvertResponse
from app.utils.exception import ServiceException
from app.utils.file import safe_filename, save_file
from app.utils.logger_config import setup_logger
from app.utils.markdown_docx import render_markdown_to_docx
from app.utils.temp_cleanup import TEMP_DIR, get_task_dir, validate_task_id

logger = setup_logger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 512
MAX_ARCHIVE_UNPACKED_SIZE = 200 * 1024 * 1024
SUPPORTED_MARKDOWN_EXTENSIONS = (".md", ".markdown")
SUPPORTED_INPUT_EXTENSIONS = SUPPORTED_MARKDOWN_EXTENSIONS + (".zip",)
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOC_MEDIA_TYPE = "application/msword"
OutputFormat = Literal["docx", "doc"]

CONVERT_TIMEOUT = 120


_POPEN_KWARGS: dict[str, int] = {}
if os.name == "nt":
    _POPEN_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW


@dataclass(frozen=True)
class _SourceBundle:
    """解包后的 Markdown 来源。"""

    markdown_path: Path
    base_dir: Path


class _InputError(Exception):
    """内部输入文件错误。"""


class _ArchiveLimitError(_InputError):
    """压缩包超过安全限制。"""


def convert_markdown_to_word(
    file: UploadFile,
    output_format: str = "docx",
) -> ConvertResponse:
    """接收 Markdown 或资源 ZIP，并生成 DOCX/DOC。"""
    normalized_format = output_format.lower().strip()
    if normalized_format not in {"docx", "doc"}:
        raise ServiceException(ErrorCode.PARAM_ERROR, "输出格式必须是 docx 或 doc")
    selected_format: OutputFormat = "doc" if normalized_format == "doc" else "docx"

    filename = safe_filename(file.filename, "document.md")
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_INPUT_EXTENSIONS:
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "仅支持 .md、.markdown 或 .zip 文件")

    content = _read_upload(file)
    task_id = uuid.uuid4().hex[:12]
    task_dir = Path(get_task_dir(task_id))
    task_dir.mkdir(parents=True, exist_ok=True)

    try:
        source = _prepare_source(task_dir, filename, content, extension)
        markdown_content = _read_markdown(source.markdown_path)
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
    except _InputError as exc:
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


def _read_upload(file: UploadFile) -> bytes:
    try:
        content = file.file.read(MAX_FILE_SIZE + 1)
    except OSError as exc:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "读取 Markdown 文件失败") from exc

    if len(content) > MAX_FILE_SIZE:
        raise ServiceException(ErrorCode.FILE_TOO_LARGE, "文件大小不能超过 50MB")
    if not content:
        raise ServiceException(ErrorCode.PARAM_ERROR, "文件不能为空")
    return content


def _prepare_source(
    task_dir: Path,
    filename: str,
    content: bytes,
    extension: str,
) -> _SourceBundle:
    source_dir = task_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    if extension in SUPPORTED_MARKDOWN_EXTENSIONS:
        markdown_path = source_dir / safe_filename(filename, "document.md")
        save_file(content, str(markdown_path))
        return _SourceBundle(markdown_path=markdown_path, base_dir=source_dir)

    archive_path = task_dir / "input.zip"
    save_file(content, str(archive_path))
    _extract_archive(archive_path, source_dir)

    markdown_files = [
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_MARKDOWN_EXTENSIONS
    ]
    if not markdown_files:
        raise _InputError("ZIP 中未找到 .md 或 .markdown 文件")
    if len(markdown_files) > 1:
        raise _InputError("ZIP 中只能包含一个 .md 或 .markdown 文件")

    markdown_path = markdown_files[0]
    return _SourceBundle(markdown_path=markdown_path, base_dir=markdown_path.parent)


def _extract_archive(archive_path: Path, target_dir: Path) -> None:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise _ArchiveLimitError("ZIP 文件包含的条目不能超过 512 个")

            unpacked_size = 0
            for member in members:
                _validate_archive_member(member, target_dir)
                unpacked_size += member.file_size
                if unpacked_size > MAX_ARCHIVE_UNPACKED_SIZE:
                    raise _ArchiveLimitError("ZIP 解压后的内容不能超过 200MB")

            for member in members:
                if member.is_dir():
                    continue
                destination = _archive_destination(member, target_dir)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
    except _InputError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise _InputError("ZIP 文件损坏或无法读取") from exc


def _validate_archive_member(member: zipfile.ZipInfo, target_dir: Path) -> None:
    name = member.filename.replace("\\", "/")
    if not name or name.startswith("/"):
        raise _InputError("ZIP 包含非法路径")

    mode = (member.external_attr >> 16) & 0xFFFF
    if stat.S_ISLNK(mode):
        raise _InputError("ZIP 不支持符号链接")

    destination = _archive_destination(member, target_dir)
    target_root = target_dir.resolve()
    if not destination.parent.resolve().is_relative_to(target_root):
        raise _InputError("ZIP 包含路径穿越内容")


def _archive_destination(member: zipfile.ZipInfo, target_dir: Path) -> Path:
    parts = [part for part in member.filename.replace("\\", "/").split("/") if part not in {"", "."}]
    if not parts or ".." in parts:
        raise _InputError("ZIP 包含非法路径")
    return target_dir.joinpath(*parts)


def _read_markdown(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise
    except OSError as exc:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "读取 Markdown 内容失败") from exc


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
