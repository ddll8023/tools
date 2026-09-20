"""统一调用 LibreOffice 完成桌面文档到 PDF 的转换。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.core.config import settings
from app.schemas.response import ErrorCode
from app.utils.exception import ServiceException
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

DEFAULT_TIMEOUT = 600

_POPEN_KWARGS: dict[str, int] = {}
if os.name == "nt":
    _POPEN_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW


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
            detail = (stderr or stdout or "未知错误".encode("utf-8")).decode(errors="replace").strip()
            logger.error("LibreOffice PDF 转换失败: %s", detail)
            raise ServiceException(ErrorCode.CONVERSION_FAILED, "PDF 转换失败，请确认 LibreOffice 可用")
    except FileNotFoundError as exc:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "未检测到 LibreOffice，无法生成 PDF") from exc

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "PDF 转换未生成有效文件")


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
