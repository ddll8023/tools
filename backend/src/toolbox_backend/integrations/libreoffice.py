"""隔离 LibreOffice 进程调用、并发控制、输入消毒和输出校验。"""

from __future__ import annotations

import os
import subprocess
import threading
import xml.etree.ElementTree as ElementTree
import zipfile
from pathlib import Path

from toolbox_backend.core.config import settings
from toolbox_backend.core.errors import ServiceException
from toolbox_backend.schemas.response import ErrorCode
from toolbox_backend.core.logging import setup_logger

logger = setup_logger(__name__)

DEFAULT_TIMEOUT = 600

_POPEN_KWARGS: dict[str, int] = {}
if os.name == "nt":
    _POPEN_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW

# 并发额度在模块级共享：Word 转 PDF 与 Markdown 转 Word 的 DOC 输出共用同一批 soffice，
# 各自加锁会让两条链路叠加后仍超出机器承受范围。
_SLOT = threading.BoundedSemaphore(settings.LIBREOFFICE_MAX_CONCURRENCY)

# OOXML 中会带来外部交互或宏执行的部件前缀，消毒时整项丢弃。
_DROP_PREFIXES = ("word/vbaProject.bin", "word/activeX/", "word/embeddings/")
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def check_available() -> bool:
    """检测 LibreOffice 是否可执行，并记录启动期诊断信息。"""
    soffice_path = settings.libreoffice_path
    try:
        result = subprocess.run(
            [soffice_path, "--version"],
            check=True,
            capture_output=True,
            timeout=10,
        )
        version = result.stdout.decode(errors="replace").strip()
        logger.info("LibreOffice 检测成功: %s", version)
        return True
    except FileNotFoundError:
        if soffice_path == "soffice":
            logger.warning("LibreOffice 未安装（soffice 不在 PATH 中）")
        else:
            logger.warning("LibreOffice 便携版未找到: %s", soffice_path)
        return False
    except Exception as exc:
        logger.warning("LibreOffice 检测失败: %s", exc)
        return False


def convert_to_pdf(
    input_path: Path,
    output_path: Path,
    task_dir: Path,
    timeout: int | None = None,
) -> None:
    """使用独立 LibreOffice profile 转换文件，并校验 PDF 已生成。"""
    _run_conversion(
        input_path=input_path,
        output_path=output_path,
        task_dir=task_dir,
        convert_to="pdf",
        output_suffix=".pdf",
        timeout=timeout,
        missing_message="未检测到 LibreOffice，无法生成 PDF",
        failure_message="PDF 转换失败，请确认 LibreOffice 可用",
        timeout_message="PDF 转换超时，文档可能过大或格式复杂",
        empty_message="PDF 转换未生成有效文件",
    )


def convert_to_doc(
    input_path: Path,
    output_path: Path,
    task_dir: Path,
    timeout: int | None = None,
) -> None:
    """使用 LibreOffice 将 DOCX 转为旧版 DOC，并校验输出文件。"""
    _run_conversion(
        input_path=input_path,
        output_path=output_path,
        task_dir=task_dir,
        convert_to="doc:MS Word 97",
        output_suffix=".doc",
        timeout=timeout,
        missing_message="DOC 格式需要 LibreOffice",
        failure_message="DOC 转换失败，请确认 LibreOffice 可用",
        timeout_message="DOC 转换超时，文档可能过大或格式复杂",
        empty_message="DOC 转换未生成有效文件",
    )


def sanitize_office_document(path: Path, extension: str) -> bool:
    """就地清理 OOXML 文档中的宏、ActiveX、嵌入对象与外部关系。

    只处理 .docx；.doc 是 OLE 复合文档，重写会破坏结构，因此直接跳过。
    消毒属于纵深防御：解析失败时保留原文件继续转换，不阻断正常业务。
    返回是否实际改写了文件。
    """
    if extension.lower() != ".docx":
        logger.info("跳过消毒（非 OOXML 格式）: extension=%s", extension)
        return False

    temp_path = path.with_name(path.name + ".sanitized")
    try:
        dropped_parts = _rewrite_ooxml(path, temp_path)
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        logger.warning("文档消毒失败，继续使用原始文件: error=%s", exc)
        temp_path.unlink(missing_ok=True)
        return False

    if dropped_parts == 0:
        temp_path.unlink(missing_ok=True)
        return False

    os.replace(temp_path, path)
    logger.info("文档消毒完成: removed_parts=%s", dropped_parts)
    return True


def _rewrite_ooxml(source: Path, target: Path) -> int:
    """重写 ZIP，丢弃危险部件与指向它们的内部关系，返回丢弃的部件数量。"""
    with zipfile.ZipFile(source) as origin:
        infos = origin.infolist()
        dropped = {info.filename for info in infos if info.filename.startswith(_DROP_PREFIXES)}
        if not dropped:
            # 没有危险部件时直接复制，避免无谓地重写整份文档。
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as rebuilt:
                for info in infos:
                    rebuilt.writestr(info, origin.read(info.filename))
            return 0

        kept = {info.filename for info in infos} - dropped
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as rebuilt:
            for info in infos:
                name = info.filename
                if name in dropped:
                    continue
                data = origin.read(name)
                if name.endswith(".rels"):
                    data = _strip_relationships(data, name, dropped)
                elif name == "[Content_Types].xml":
                    data = _strip_part_overrides(data, dropped)
                rebuilt.writestr(info, data)
        return len(dropped)


def _strip_relationships(data: bytes, rels_name: str, dropped: set[str]) -> bytes:
    """移除外部关系与指向已丢弃部件的关系。

    只处理这两类明确危险的关系；指向其他不存在部件的关系保持原样，
    避免因目标解析偏差误删正常关系而损坏文档。
    """
    root = ElementTree.fromstring(data)
    removed = False
    for relationship in list(root):
        if relationship.get("TargetMode") == "External":
            root.remove(relationship)
            removed = True
            continue
        target = _resolve_rel_target(rels_name, relationship.get("Target") or "")
        if target in dropped:
            root.remove(relationship)
            removed = True
    if not removed:
        return data
    ElementTree.register_namespace("", _RELS_NS)
    return ElementTree.tostring(root, encoding="UTF-8", xml_declaration=True)


def _strip_part_overrides(data: bytes, dropped: set[str]) -> bytes:
    """移除 [Content_Types].xml 中指向已丢弃部件的 Override 声明。"""
    root = ElementTree.fromstring(data)
    removed = False
    for override in list(root):
        part_name = (override.get("PartName") or "").lstrip("/")
        if part_name in dropped:
            root.remove(override)
            removed = True
    if not removed:
        return data
    ElementTree.register_namespace("", _CONTENT_TYPES_NS)
    return ElementTree.tostring(root, encoding="UTF-8", xml_declaration=True)


def _resolve_rel_target(rels_name: str, target: str) -> str:
    """把关系目标解析为 ZIP 内的部件名，用于判断它是否属于被丢弃的部件。"""
    if target.startswith("/"):
        return target.lstrip("/")
    # 关系文件的宿主部件目录：word/_rels/document.xml.rels → word
    owner_dir = os.path.dirname(os.path.dirname(rels_name))
    normalized = os.path.normpath(os.path.join(owner_dir, target))
    return normalized.replace(os.sep, "/").lstrip("/")


def _run_conversion(
    *,
    input_path: Path,
    output_path: Path,
    task_dir: Path,
    convert_to: str,
    output_suffix: str,
    timeout: int | None,
    missing_message: str,
    failure_message: str,
    timeout_message: str,
    empty_message: str,
) -> None:
    """在并发额度内执行一次 LibreOffice 转换，并处理输出名偏离的情况。"""
    libreoffice_path = settings.libreoffice_path
    if not libreoffice_path:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, missing_message)

    if not _SLOT.acquire(timeout=settings.LIBREOFFICE_QUEUE_TIMEOUT):
        logger.warning("LibreOffice 排队超时: input=%s", input_path.name)
        raise ServiceException(
            ErrorCode.TIMEOUT,
            "当前有较多文档正在转换，请稍后重试",
        )

    try:
        profile_dir = task_dir / "libreoffice-profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            libreoffice_path,
            "--headless",
            "--nologo",
            "--nodefault",
            "--norestore",
            "--nofirststartwizard",
            f"-env:UserInstallation={profile_dir.as_uri()}",
            "--convert-to",
            convert_to,
            "--outdir",
            str(output_path.parent),
            str(input_path),
        ]
        _execute(
            command,
            timeout or settings.LIBREOFFICE_CONVERT_TIMEOUT,
            timeout_message,
            failure_message,
        )
        _ensure_output(output_path, output_suffix, empty_message)
    finally:
        _SLOT.release()


def _execute(
    command: list[str],
    timeout: int,
    timeout_message: str,
    failure_message: str,
) -> None:
    """启动 LibreOffice 子进程并在超时或非零退出时抛出业务异常。"""
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_POPEN_KWARGS,
        )
    except FileNotFoundError as exc:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, failure_message) from exc

    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        raise ServiceException(ErrorCode.TIMEOUT, timeout_message)

    if process.returncode != 0:
        detail = (stderr or stdout or "未知错误".encode("utf-8")).decode(errors="replace").strip()
        logger.error("LibreOffice 转换失败: %s", detail)
        raise ServiceException(ErrorCode.CONVERSION_FAILED, failure_message)


def _ensure_output(output_path: Path, suffix: str, empty_message: str) -> None:
    """确认输出存在且非空；部分版本会按文档标题命名，因此回落到目录内同扩展名文件。"""
    if not output_path.is_file() or output_path.stat().st_size == 0:
        candidate = _find_converted_file(output_path.parent, suffix)
        if candidate is None:
            raise ServiceException(ErrorCode.CONVERSION_FAILED, empty_message)
        logger.info("输出文件名与预期不一致，已回落使用: %s", candidate.name)
        os.replace(candidate, output_path)

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, empty_message)


def _find_converted_file(directory: Path, suffix: str) -> Path | None:
    """在输出目录内查找唯一符合条件的转换结果，避免误取其他任务产物。"""
    try:
        matches = [
            item
            for item in directory.iterdir()
            if item.is_file() and item.suffix.lower() == suffix and item.stat().st_size > 0
        ]
    except OSError:
        return None
    if len(matches) != 1:
        return None
    return matches[0]


def _kill_process_tree(process: subprocess.Popen[bytes]) -> None:
    """终止超时的 LibreOffice 进程及其子进程。"""
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
