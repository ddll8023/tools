"""PDF 转 Markdown 共享辅助函数"""

import os
import re
import json
import uuid
import zipfile
from urllib.parse import unquote

from app.utils.temp_cleanup import TEMP_DIR, UPLOADS_DIR, get_task_dir, validate_task_id
from app.utils.exception import ServiceException
from app.utils.markdown import count_tables
from app.schemas.response import ErrorCode
from app.utils.logger_config import setup_logger
from app.schemas.tools.pdf_to_markdown import GetPreviewResponse

logger = setup_logger(__name__)

_META_FILE = "meta.txt"
_DOWNLOAD_ZIP_PREFIX = "pdf_markdown_"

# Markdown 图片引用与 HTML img 标签（MinerU 部分输出使用内联 img）
_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
_IMG_TAG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)


def _check_task_path(task_dir: str):
    """校验任务目录仍位于临时目录内，防止路径逃逸。"""
    root = os.path.abspath(TEMP_DIR)
    if os.path.commonpath([root, os.path.abspath(task_dir)]) != root:
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")


def read_deep_status(task_dir: str) -> dict | None:
    """读取深度解析状态文件；不存在或损坏时返回 None。"""
    status_path = os.path.join(task_dir, "deep_status.json")
    if not os.path.exists(status_path):
        return None
    try:
        with open(status_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _raise_deep_failure_or_not_found(task_dir: str, default_message: str):
    """结果文件缺失时，优先透传深度解析的真实失败原因。"""
    status = read_deep_status(task_dir)
    if status and status.get("progress", 0) < 0:
        raise ServiceException(
            ErrorCode.CONVERSION_FAILED,
            status.get("stage") or "深度解析失败，请稍后重试",
        )
    raise ServiceException(ErrorCode.DATA_NOT_FOUND, default_message)


def get_preview_detail(task_id: str):
    """获取 Markdown 预览"""
    logger.info(f"获取预览: task_id={task_id}")
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = get_task_dir(task_id)
    _check_task_path(task_dir)

    if not os.path.exists(task_dir):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "任务不存在")

    md_path = os.path.join(task_dir, "output.md")
    if not os.path.exists(md_path):
        _raise_deep_failure_or_not_found(task_dir, "转换结果不存在")

    images_dir = os.path.join(task_dir, "images")
    image_count = len(os.listdir(images_dir)) if os.path.exists(images_dir) else 0

    with open(md_path, encoding="utf-8") as f:
        md_content = f.read()

    table_count = count_tables(md_content)
    page_count = md_content.count("\n---\n\n## 第")

    # 标准模式使用 ## 第 N 页 标记分页，MinerU 输出无此标记时从原始 PDF 获取页数
    if page_count == 0:
        pdf_path = os.path.join(task_dir, "input.pdf")
        if os.path.exists(pdf_path):
            try:
                import fitz
                doc = fitz.open(pdf_path)
                page_count = len(doc)
                doc.close()
            except Exception:
                pass

    logger.info(f"预览返回: task_id={task_id} pages={page_count} tables={table_count} images={image_count}")
    return GetPreviewResponse(
        markdown_content=md_content,
        page_count=page_count,
        table_count=table_count,
        image_count=image_count,
    )


def _read_original_stem(task_dir: str, task_id: str) -> str:
    """读取原始文件名主干：meta.txt 优先，历史任务从 uploads/{task_id}-{原名} 回退恢复。"""
    try:
        with open(os.path.join(task_dir, _META_FILE), encoding="utf-8") as f:
            original = f.read().strip()
    except OSError:
        original = ""
    if not original:
        prefix = f"{task_id}-"
        try:
            candidates = [n for n in os.listdir(UPLOADS_DIR) if n.startswith(prefix)]
        except OSError:
            candidates = []
        if candidates:
            original = candidates[0][len(prefix):]
    stem = os.path.splitext(os.path.basename(original))[0] if original else ""
    return stem or task_id


def _resolve_referenced_assets(
    task_dir: str, md_content: str
) -> tuple[list[tuple[str, str]], list[str]]:
    """解析 output.md 引用的本地相对资源。

    返回 (存在的资源列表 [(绝对路径, 压缩包内路径)], 缺失的资源相对路径列表)。
    远程、data: 和越界引用直接忽略；仅任务目录内不存在的本地引用计入缺失。
    """
    seen: set[str] = set()
    assets: list[tuple[str, str]] = []
    missing: list[str] = []
    for raw in [*_IMAGE_REF_RE.findall(md_content), *_IMG_TAG_RE.findall(md_content)]:
        ref = unquote(raw.split("#", 1)[0].split("?", 1)[0]).replace("\\", "/")
        if not ref or ref.startswith(("http://", "https://", "data:", "/")):
            continue
        parts = [p for p in ref.split("/") if p not in ("", ".")]
        if not parts or ".." in parts:
            continue
        src = os.path.join(task_dir, *parts)
        arcname = "/".join(parts)
        if src in seen or arcname in missing:
            continue
        seen.add(src)
        if os.path.isfile(src):
            assets.append((src, arcname))
        else:
            missing.append(arcname)
    return assets, missing


def _build_download_zip(task_dir: str, md_path: str, md_name: str, assets: list[tuple[str, str]]) -> str:
    """将 Markdown 与引用资源打包为 ZIP（唯一文件名，避免并发下载互相截断）。"""
    for name in os.listdir(task_dir):
        if name.startswith(_DOWNLOAD_ZIP_PREFIX) and name.endswith(".zip"):
            try:
                os.remove(os.path.join(task_dir, name))
            except OSError:
                pass

    zip_path = os.path.join(task_dir, f"{_DOWNLOAD_ZIP_PREFIX}{uuid.uuid4().hex[:8]}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(md_path, md_name)
        for src, arcname in assets:
            archive.write(src, arcname)
    return zip_path


def download_md(task_id: str, markdown_content: str | None = None):
    """获取 Markdown 下载产物路径、文件名、类型和缺失资源列表。

    存在图片等引用资源时打包 ZIP 返回，否则返回单个 .md 文件；
    提供 markdown_content 时以用户当前编辑内容为准；
    返回的缺失资源列表用于向用户提示解析结果中本就缺失的图片。
    """
    logger.info(f"下载文件: task_id={task_id}")
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = get_task_dir(task_id)
    _check_task_path(task_dir)

    md_path = os.path.join(task_dir, "output.md")
    if not os.path.exists(md_path):
        _raise_deep_failure_or_not_found(task_dir, "文件不存在")

    if markdown_content is not None and markdown_content != "":
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

    with open(md_path, encoding="utf-8") as f:
        md_content = f.read()

    stem = _read_original_stem(task_dir, task_id)
    assets, missing = _resolve_referenced_assets(task_dir, md_content)
    if missing:
        logger.warning(f"下载存在缺失引用资源: task_id={task_id} missing={missing}")

    if not assets:
        logger.info(f"文件下载返回: task_id={task_id} type=md")
        return md_path, f"{stem}.md", "text/markdown", missing

    zip_path = _build_download_zip(task_dir, md_path, f"{stem}.md", assets)
    logger.info(f"文件下载返回: task_id={task_id} type=zip assets={len(assets)}")
    return zip_path, f"{stem}.zip", "application/zip", missing


def normalize_output(task_dir: str, mineru_result):
    """将 MinerU 输出归一化为标准目录结构"""
    md_path = os.path.join(task_dir, "output.md")
    md_content = mineru_result.markdown if hasattr(mineru_result, "markdown") else str(mineru_result)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)


def write_status_atomic(task_dir: str, progress: int, stage: str):
    """原子写入进度状态文件（先写 .tmp 再 rename）"""
    os.makedirs(task_dir, exist_ok=True)
    tmp_path = os.path.join(task_dir, "deep_status.json.tmp")
    final_path = os.path.join(task_dir, "deep_status.json")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"progress": progress, "stage": stage}, f, ensure_ascii=False)
    os.replace(tmp_path, final_path)
