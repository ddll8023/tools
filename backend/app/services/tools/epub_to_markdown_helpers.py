"""EPUB 解析与 Markdown 转换辅助函数。"""

import html
import os
import posixpath
import re
import shutil
import uuid
import zipfile
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from markdownify import markdownify

from app.schemas.response import ErrorCode
from app.schemas.tools.epub_to_markdown import GetPreviewResponse
from app.utils.exception import ServiceException
from app.utils.logger_config import setup_logger
from app.utils.markdown import count_tables
from app.utils.temp_cleanup import TEMP_DIR, get_task_dir, validate_task_id

logger = setup_logger(__name__)

# EPUB 模块内部仍使用 _count_tables 名称，实现统一来自 utils.markdown
_count_tables = count_tables

MAX_ENTRY_COUNT = 10_000
MAX_UNCOMPRESSED_SIZE = 200 * 1024 * 1024
MAX_ENTRY_SIZE = 50 * 1024 * 1024
TEMP_UPLOADS_DIR = os.path.join(TEMP_DIR, "uploads")
CHAPTER_COUNT_FILE = "chapter_count.txt"

_XML_NS = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
}


def _local_name(tag: str) -> str:
    """返回 XML 标签的本地名，兼容带命名空间和无命名空间文档。"""
    return tag.rsplit("}", 1)[-1]


def _elements(root: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [element for element in root.iter() if _local_name(element.tag) == name]


def _reject(message: str, code: int = ErrorCode.UNSUPPORTED_FILE_FORMAT) -> None:
    raise ServiceException(code, message)


def _safe_member_name(name: str) -> str:
    """校验 ZIP 成员名，拒绝绝对路径和目录穿越。"""
    name = name.replace("\\", "/")
    if not name or "\x00" in name or name.startswith("/"):
        _reject("EPUB 包含非法路径")
    # Directory entries are valid EPUB ZIP members; normalize their suffix.
    is_directory = name.endswith("/")
    normalized = name.rstrip("/") if is_directory else name
    parts = normalized.split("/")
    if not normalized or any(part in ("", ".", "..") for part in parts):
        _reject("EPUB 包含非法路径")
    return "/".join(parts) + ("/" if is_directory else "")


def validate_and_extract_epub(epub_path: str, extract_dir: str) -> None:
    """校验 EPUB ZIP 并安全解压到任务目录。"""
    try:
        with zipfile.ZipFile(epub_path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRY_COUNT:
                _reject("EPUB 文件条目数量超限")
            total_size = 0
            names: set[str] = set()
            for info in infos:
                name = _safe_member_name(info.filename)
                if info.is_dir() or info.filename.endswith(("/", "\\")):
                    continue
                if name in names:
                    _reject("EPUB 包含重复文件路径")
                names.add(name)
                if info.file_size > MAX_ENTRY_SIZE or info.file_size < 0:
                    _reject("EPUB 包含过大的文件")
                total_size += info.file_size
                if total_size > MAX_UNCOMPRESSED_SIZE:
                    _reject("EPUB 解压后大小超限")

            # 逐个读取并写入，目录项不需要创建文件。
            for info in infos:
                if info.is_dir() or info.filename.endswith(("/", "\\")):
                    continue
                name = _safe_member_name(info.filename)
                target = os.path.join(extract_dir, *name.rstrip("/").split("/"))
                target_parent = os.path.dirname(target)
                os.makedirs(target_parent, exist_ok=True)
                with archive.open(info) as source, open(target, "wb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
    except ServiceException:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError):
        _reject("无法解析 EPUB 文件")


def _xml(path: str) -> ElementTree.Element:
    try:
        with open(path, "rb") as stream:
            return _xml_bytes(stream.read())
    except OSError:
        _reject("EPUB XML 文件无效")


def _xml_bytes(content: bytes) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(content)
    except (ElementTree.ParseError, ValueError):
        _reject("EPUB XML 文件无效")


def _href_path(base_dir: str, href: str) -> str:
    """解析包内 href，并限制结果仍位于 EPUB 根目录。"""
    href = unquote(urlsplit(href).path).replace("\\", "/")
    if not href:
        return ""
    combined = posixpath.normpath(posixpath.join(base_dir.replace("\\", "/"), href))
    if combined.startswith("/") or combined == ".." or combined.startswith("../"):
        _reject("EPUB 包含非法资源路径")
    return combined


def _read_member(root_dir: str, member: str, binary: bool = False) -> str | bytes:
    path = os.path.join(root_dir, *member.split("/"))
    if not os.path.isfile(path):
        _reject("EPUB 引用的资源不存在")
    try:
        with open(path, "rb") as stream:
            data = stream.read()
        if binary:
            return data
        declaration = re.search(rb"encoding=[\"']([A-Za-z0-9._-]+)[\"']", data[:512], re.IGNORECASE)
        encoding = declaration.group(1).decode("ascii") if declaration else "utf-8"
        return data.decode(encoding, errors="replace")
    except (LookupError, OSError):
        _reject("无法读取 EPUB 资源")


def _parse_package(root_dir: str) -> tuple[list[tuple[str, str]], dict[str, tuple[str, str, str]], str, str]:
    container = _xml(os.path.join(root_dir, "META-INF", "container.xml"))
    rootfile = next((element for element in _elements(container, "rootfile")), None)
    opf_member = rootfile.get("full-path", "") if rootfile is not None else ""
    if not opf_member or not opf_member.lower().endswith(".opf"):
        _reject("EPUB 缺少有效的 OPF 文件")
    opf_member = _href_path("", opf_member)
    opf_path = os.path.join(root_dir, *opf_member.split("/"))
    package = _xml(opf_path)
    opf_dir = posixpath.dirname(opf_member)

    manifest: dict[str, tuple[str, str, str]] = {}
    for item in _elements(package, "item"):
        item_id, href = item.get("id", ""), item.get("href", "")
        if not item_id or not href:
            continue
        member = _href_path(opf_dir, href)
        manifest[item_id] = (member, item.get("media-type", ""), item.get("properties", ""))

    spine: list[tuple[str, str]] = []
    for ref in _elements(package, "itemref"):
        item = manifest.get(ref.get("idref", ""))
        if item and item[1].lower() in {"application/xhtml+xml", "text/html"}:
            spine.append((item[0], item[2]))

    title_element = next((element for element in _elements(package, "title")), None)
    title = (title_element.text or "").strip() if title_element is not None else ""
    return spine, manifest, title, opf_member


def _nav_members(root_dir: str, manifest: dict[str, tuple[str, str, str]]) -> list[str]:
    """读取 EPUB 3 manifest 中 properties=nav 的导航文档。"""
    for member, media_type, properties in manifest.values():
        if "nav" not in properties.split() or media_type.lower() not in {"application/xhtml+xml", "text/html"}:
            continue
        content = _read_member(root_dir, member)
        return _links_from_nav(content, member)
    return []


def _links_from_nav(content: str, nav_member: str) -> list[str]:
    links = re.findall(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>", content, re.IGNORECASE)
    base = posixpath.dirname(nav_member)
    return [_href_path(base, link.split("#", 1)[0]) for link in links if link.split("#", 1)[0]]


def _ncx_links(root_dir: str, manifest: dict[str, tuple[str, str, str]]) -> list[str]:
    """读取 EPUB 2 manifest 中 NCX 的 spine 导航顺序。"""
    for member, media_type, _ in manifest.values():
        if media_type.lower() != "application/x-dtbncx+xml":
            continue
        root = _xml(os.path.join(root_dir, *member.split("/")))
        base = posixpath.dirname(member)
        return [
            _href_path(base, node.get("src", "").split("#", 1)[0])
            for node in _elements(root, "content")
            if node.get("src", "").split("#", 1)[0]
        ]
    return []


def _extract_body_content(content: str) -> str:
    """只返回 XHTML/HTML 的 body 内容，避免把 XML 声明和 head 元数据当正文。"""
    body_match = re.search(r"<body\b[^>]*>(.*?)</body\s*>", content, re.IGNORECASE | re.DOTALL)
    if body_match:
        return body_match.group(1)

    # 少数 EPUB 页面没有完整的 body 标签，仍需去掉 head，避免泄漏 title、style 等元数据。
    content = re.sub(r"<head\b[^>]*>.*?</head\s*>", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<\?(?:xml)\b[^>]*\?>", "", content, flags=re.IGNORECASE)
    return re.sub(r"</?(?:html|body)\b[^>]*>", "", content, flags=re.IGNORECASE)


def _replace_image_links(content: str, chapter_member: str, root_dir: str, images_dir: str, image_map: dict[str, str]) -> str:
    base = posixpath.dirname(chapter_member)

    def replace(match: re.Match[str]) -> str:
        raw = html.unescape(match.group(1)).strip()
        if not raw or raw.startswith(("data:", "http:", "https:", "#")):
            return match.group(0)
        member = _href_path(base, raw.split("#", 1)[0])
        if not member:
            return match.group(0)
        source = os.path.join(root_dir, *member.split("/"))
        if not os.path.isfile(source):
            return match.group(0)
        if member not in image_map:
            ext = os.path.splitext(member)[1].lower() or ".bin"
            name = f"image_{len(image_map) + 1:04d}{ext}"
            target = os.path.join(images_dir, name)
            shutil.copyfile(source, target)
            image_map[member] = f"images/{name}"
        return f'src="{image_map[member]}"'

    return re.sub(r"src\s*=\s*[\"']([^\"']+)[\"']", replace, content, flags=re.IGNORECASE)


def _ordered_spine(
    spine: list[tuple[str, str]],
    preferred_members: list[str],
) -> list[tuple[str, str]]:
    spine_by_member = {member: properties for member, properties in spine}
    preferred = []
    seen: set[str] = set()
    for member in preferred_members:
        if member in spine_by_member and member not in seen:
            preferred.append((member, spine_by_member[member]))
            seen.add(member)
    return preferred + [(member, properties) for member, properties in spine if member not in seen]


def convert_epub(root_dir: str) -> tuple[str, int, int, int, str]:
    """解析 EPUB 并生成 output.md，返回内容与统计。"""
    container_path = os.path.join(root_dir, "META-INF", "container.xml")
    if not os.path.isfile(container_path):
        _reject("EPUB 缺少 container.xml")
    spine, _, title, _ = _parse_package(root_dir)
    if not spine:
        _reject("EPUB 缺少可解析的章节")
    # OPF spine defines the EPUB default reading order; nav/NCX are navigation metadata.
    output_dir = os.path.dirname(root_dir)
    images_dir = os.path.join(output_dir, "output", "images")
    os.makedirs(images_dir, exist_ok=True)
    image_map: dict[str, str] = {}
    chapters: list[str] = []
    for member, _ in spine:
        content = _read_member(root_dir, member)
        content = _extract_body_content(content)
        content = _replace_image_links(content, member, root_dir, images_dir, image_map)
        markdown = markdownify(content, heading_style="ATX", strip=["script", "style", "noscript"])
        markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
        if markdown:
            chapters.append(markdown)
    full_markdown = "\n\n---\n\n".join(chapters)
    if title:
        normalized_title = re.sub(r"\s+", " ", title).strip()
        first_heading = re.match(r"^#{1,6}\s+(.+?)\s*$", full_markdown)
        has_title_heading = first_heading and first_heading.group(1).strip() == normalized_title
        if not has_title_heading:
            full_markdown = f"# {normalized_title}\n\n{full_markdown}" if full_markdown else f"# {normalized_title}"
    output_path = os.path.join(os.path.dirname(root_dir), "output.md")
    with open(output_path, "w", encoding="utf-8") as stream:
        stream.write(full_markdown)
    return full_markdown, len(chapters), _count_tables(full_markdown), len(image_map), title


def _read_chapter_count(task_dir: str, markdown: str) -> int:
    """读取转换时记录的章节数，旧任务则按分隔线回退计算。"""
    count_path = os.path.join(task_dir, CHAPTER_COUNT_FILE)
    try:
        with open(count_path, encoding="utf-8") as stream:
            chapter_count = int(stream.read().strip())
        if chapter_count >= 0:
            return chapter_count
    except (OSError, ValueError):
        pass

    if not markdown.strip():
        return 0
    return markdown.count("\n\n---\n\n") + 1


def _task_path(task_id: str) -> str:
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")
    task_dir = get_task_dir(task_id)
    root = os.path.abspath(TEMP_DIR)
    if os.path.commonpath([root, os.path.abspath(task_dir)]) != root:
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")
    return task_dir


def get_preview_detail(task_id: str) -> GetPreviewResponse:
    task_dir = _task_path(task_id)
    md_path = os.path.join(task_dir, "output.md")
    meta_path = os.path.join(task_dir, "meta.txt")
    if not os.path.isfile(md_path):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "转换结果不存在")
    with open(md_path, encoding="utf-8") as stream:
        markdown = stream.read()
    filename = "output.epub"
    if os.path.isfile(meta_path):
        with open(meta_path, encoding="utf-8") as stream:
            filename = stream.read().strip() or filename
    images_dir = os.path.join(task_dir, "output", "images")
    image_count = len([name for name in os.listdir(images_dir)]) if os.path.isdir(images_dir) else 0
    return GetPreviewResponse(
        markdown_content=markdown,
        chapter_count=_read_chapter_count(task_dir, markdown),
        table_count=_count_tables(markdown),
        image_count=image_count,
        filename=filename,
    )


def create_download_zip(task_id: str) -> tuple[str, str]:
    task_dir = _task_path(task_id)
    md_path = os.path.join(task_dir, "output.md")
    if not os.path.isfile(md_path):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "转换结果不存在")
    # 使用唯一文件名，避免并发下载互相截断；下载前清理旧包
    for name in os.listdir(task_dir):
        if name.startswith("epub_markdown_") and name.endswith(".zip"):
            try:
                os.remove(os.path.join(task_dir, name))
            except OSError:
                pass
    zip_path = os.path.join(task_dir, f"epub_markdown_{uuid.uuid4().hex[:8]}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(md_path, "book.md")
        images_dir = os.path.join(task_dir, "output", "images")
        if os.path.isdir(images_dir):
            for name in sorted(os.listdir(images_dir)):
                image_path = os.path.join(images_dir, name)
                if os.path.isfile(image_path):
                    archive.write(image_path, os.path.join("images", name))
    filename = "epub_markdown.zip"
    meta_path = os.path.join(task_dir, "meta.txt")
    if os.path.isfile(meta_path):
        with open(meta_path, encoding="utf-8") as stream:
            original = stream.read().strip()
        stem = os.path.splitext(os.path.basename(original))[0] or "epub_markdown"
        filename = f"{stem}.zip"
    return zip_path, filename
