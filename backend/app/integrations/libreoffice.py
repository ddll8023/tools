"""隔离 LibreOffice 进程调用、能力探测和输出校验。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.core.config import settings
from app.core.errors import ServiceException
from app.schemas.response import ErrorCode
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

DEFAULT_TIMEOUT = 600

_POPEN_KWARGS: dict[str, int] = {}
if os.name == "nt":
    _POPEN_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW


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
    timeout: int = DEFAULT_TIMEOUT,
) -> None:
    """使用独立 LibreOffice profile 转换文件，并校验 PDF 已生成。"""
    libreoffice_path = settings.libreoffice_path
    if not libreoffice_path:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "未检测到 LibreOffice，无法生成 PDF")

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
        "pdf",
        "--outdir",
        str(output_path.parent),
        str(input_path),
    ]

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_POPEN_KWARGS,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_tree(process)
            raise ServiceException(ErrorCode.TIMEOUT, "PDF 转换超时，文档可能过大或格式复杂")
        if process.returncode != 0:
            detail = (stderr or stdout or "未知错误".encode("utf-8")).decode(
                errors="replace"
            ).strip()
            logger.error("LibreOffice PDF 转换失败: %s", detail)
            raise ServiceException(
                ErrorCode.CONVERSION_FAILED,
                "PDF 转换失败，请确认 LibreOffice 可用",
            )
    except FileNotFoundError as exc:
        raise ServiceException(
            ErrorCode.SERVICE_UNAVAILABLE,
            "未检测到 LibreOffice，无法生成 PDF",
        ) from exc

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "PDF 转换未生成有效文件")


def convert_to_doc(
    input_path: Path,
    output_path: Path,
    task_dir: Path,
    timeout: int = DEFAULT_TIMEOUT,
) -> None:
    """使用 LibreOffice 将 DOCX 转为旧版 DOC，并校验输出文件。"""
    libreoffice_path = settings.libreoffice_path
    if not libreoffice_path:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "DOC 格式需要 LibreOffice")

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
        "doc:MS Word 97",
        "--outdir",
        str(output_path.parent),
        str(input_path),
    ]

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_POPEN_KWARGS,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_tree(process)
            raise ServiceException(ErrorCode.TIMEOUT, "DOC 转换超时，文档可能过大或格式复杂")
        if process.returncode != 0:
            detail = (stderr or stdout or "未知错误".encode("utf-8")).decode(
                errors="replace"
            ).strip()
            logger.error("LibreOffice DOC 转换失败: %s", detail)
            raise ServiceException(
                ErrorCode.CONVERSION_FAILED,
                "DOC 转换失败，请确认 LibreOffice 可用",
            )
    except FileNotFoundError as exc:
        raise ServiceException(
            ErrorCode.SERVICE_UNAVAILABLE,
            "未检测到 LibreOffice，无法生成 DOC",
        ) from exc

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "DOC 转换未生成有效文件")


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
