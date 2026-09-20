"""准备 Markdown 本地文件或上传资源包，供文档转换服务复用。"""

from __future__ import annotations

import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.schemas.response import ErrorCode
from app.utils.exception import ServiceException
from app.utils.file import safe_filename, save_file

MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 4096
MAX_ARCHIVE_UNPACKED_SIZE = 1024 * 1024 * 1024
SUPPORTED_MARKDOWN_EXTENSIONS = (".md", ".markdown")
SUPPORTED_INPUT_EXTENSIONS = SUPPORTED_MARKDOWN_EXTENSIONS + (".zip",)


@dataclass(frozen=True)
class MarkdownSource:
    """Markdown 文件及允许解析相对图片的基准目录。"""

    markdown_path: Path
    base_dir: Path
    from_local: bool = False


class MarkdownInputError(Exception):
    """来源文件或压缩包不符合输入要求。"""


def prepare_markdown_source(
    file: UploadFile | None,
    source_path: str | None,
    task_dir: Path,
) -> tuple[MarkdownSource, str]:
    """按本地路径或上传文件准备来源；调用方管理临时目录生命周期。"""
    local_path = (source_path or "").strip()
    if local_path:
        return _prepare_local_source(local_path)
    if file is None:
        raise ServiceException(ErrorCode.PARAM_ERROR, "请上传 Markdown 文件或提供本地 Markdown 路径")

    filename = safe_filename(file.filename, "document.md")
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_INPUT_EXTENSIONS:
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "仅支持 .md、.markdown 或 .zip 文件")
    try:
        content = file.file.read(MAX_FILE_SIZE + 1)
    except OSError as exc:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "读取 Markdown 文件失败") from exc
    if len(content) > MAX_FILE_SIZE:
        raise ServiceException(ErrorCode.FILE_TOO_LARGE, "文件大小不能超过 50MB")
    if not content:
        raise ServiceException(ErrorCode.PARAM_ERROR, "文件不能为空")

    source_dir = task_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    if extension in SUPPORTED_MARKDOWN_EXTENSIONS:
        markdown_path = source_dir / filename
        save_file(content, str(markdown_path))
        return MarkdownSource(markdown_path, source_dir), filename

    archive_path = task_dir / "input.zip"
    save_file(content, str(archive_path))
    _extract_archive(archive_path, source_dir)
    markdown_files = [
        path for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_MARKDOWN_EXTENSIONS
    ]
    if not markdown_files:
        raise MarkdownInputError("ZIP 中未找到 .md 或 .markdown 文件")
    if len(markdown_files) > 1:
        raise MarkdownInputError("ZIP 中只能包含一个 .md 或 .markdown 文件")
    markdown_path = markdown_files[0]
    return MarkdownSource(markdown_path, markdown_path.parent), filename


def _prepare_local_source(raw_path: str) -> tuple[MarkdownSource, str]:
    path = Path(raw_path).expanduser()
    if path.suffix.lower() not in SUPPORTED_MARKDOWN_EXTENSIONS:
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "本地文件必须是 .md 或 .markdown")
    try:
        is_file = path.is_file()
        size = path.stat().st_size if is_file else 0
    except OSError as exc:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "本地 Markdown 文件不存在或无法读取") from exc
    if not is_file:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "本地 Markdown 文件不存在或无法读取")
    if size == 0:
        raise ServiceException(ErrorCode.PARAM_ERROR, "文件不能为空")
    if size > MAX_FILE_SIZE:
        raise ServiceException(ErrorCode.FILE_TOO_LARGE, "文件大小不能超过 50MB")
    markdown_path = path.resolve()
    return (
        MarkdownSource(markdown_path, markdown_path.parent, from_local=True),
        safe_filename(markdown_path.name, "document.md"),
    )


def _extract_archive(archive_path: Path, target_dir: Path) -> None:
    """先检查全部成员，再限量解包；不接受符号链接、跨平台绝对路径或穿越。"""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise MarkdownInputError(f"ZIP 文件包含的条目不能超过 {MAX_ARCHIVE_MEMBERS} 个")
            if sum(member.file_size for member in members) > MAX_ARCHIVE_UNPACKED_SIZE:
                raise MarkdownInputError(f"ZIP 解压后的内容不能超过 {MAX_ARCHIVE_UNPACKED_SIZE // 1024 // 1024}MB")
            for member in members:
                _archive_destination(member, target_dir)

            remaining = MAX_ARCHIVE_UNPACKED_SIZE
            for member in members:
                if member.is_dir():
                    continue
                destination = _archive_destination(member, target_dir)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as target:
                    while chunk := source.read(min(1024 * 1024, remaining + 1)):
                        remaining -= len(chunk)
                        if remaining < 0:
                            raise MarkdownInputError(f"ZIP 解压后的内容不能超过 {MAX_ARCHIVE_UNPACKED_SIZE // 1024 // 1024}MB")
                        target.write(chunk)
    except MarkdownInputError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise MarkdownInputError("ZIP 文件损坏、加密或无法读取") from exc


def _archive_destination(member: zipfile.ZipInfo, target_dir: Path) -> Path:
    name = member.filename.replace("\\", "/")
    parts = [part for part in name.split("/") if part not in {"", "."}]
    if not parts or name.startswith("/") or ".." in parts or any(":" in part for part in parts):
        raise MarkdownInputError("ZIP 包含非法路径")
    if stat.S_ISLNK((member.external_attr >> 16) & 0xFFFF):
        raise MarkdownInputError("ZIP 不支持符号链接")
    destination = target_dir.joinpath(*parts)
    if not destination.resolve().is_relative_to(target_dir.resolve()):
        raise MarkdownInputError("ZIP 包含路径穿越内容")
    return destination


def read_markdown(path: Path, max_bytes: int = MAX_FILE_SIZE) -> str:
    """限制实际读取字节，避免校验后文件变化导致无限制读取。"""
    try:
        with path.open("rb") as stream:
            content = stream.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ServiceException(ErrorCode.FILE_TOO_LARGE, "Markdown 内容超过当前转换工具的大小限制")
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise
    except OSError as exc:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "读取 Markdown 内容失败") from exc
