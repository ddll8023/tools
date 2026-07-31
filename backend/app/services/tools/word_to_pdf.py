"""Word 转 PDF 服务"""

import os
import re
import json
import uuid
import subprocess

from fastapi import UploadFile

from app.core.config import settings
from app.utils.file import save_file, safe_filename
from app.utils.temp_cleanup import TEMP_DIR, get_task_dir, validate_task_id
from app.utils.exception import ServiceException
from app.schemas.response import ErrorCode
from app.schemas.tools.word_to_pdf import ConvertResponse
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

LIBREOFFICE_PATH = settings.libreoffice_path
CONVERT_TIMEOUT = 120
MAX_FILE_SIZE = 50 * 1024 * 1024

SUPPORTED_EXTENSIONS = (".docx", ".doc")

# Windows 下隐藏 LibreOffice 启动时弹出的终端窗口
_POPEN_KWARGS = {}
if os.name == "nt":
    _POPEN_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW


def _kill_process_tree(proc: subprocess.Popen):
    """超时后终止 LibreOffice 进程（Windows 下连子进程一起终止）。"""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
            )
        else:
            proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def convert_word(file: UploadFile) -> ConvertResponse:
    """转换 Word 文档为 PDF"""
    safe_name = safe_filename(file.filename, "output")
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ServiceException(
            ErrorCode.UNSUPPORTED_FILE_FORMAT,
            "仅支持 .doc/.docx 格式",
        )

    if file.size and file.size > MAX_FILE_SIZE:
        raise ServiceException(
            ErrorCode.FILE_TOO_LARGE,
            "文件大小不能超过 50MB",
        )

    task_id = uuid.uuid4().hex[:12]
    task_dir = get_task_dir(task_id)
    os.makedirs(task_dir, exist_ok=True)

    input_filename = f"output{ext}"
    input_path = os.path.join(task_dir, input_filename)
    save_file(file.file.read(), input_path)

    output_pdf = os.path.join(task_dir, "output.pdf")

    logger.info(f"开始 Word 转 PDF: task_id={task_id} filename={safe_name}")

    try:
        proc = subprocess.Popen(
            [
                LIBREOFFICE_PATH,
                "--headless",
                "--norestore",
                "--convert-to", "pdf",
                "--outdir", task_dir,
                input_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_POPEN_KWARGS,
        )
        try:
            _stdout, stderr = proc.communicate(timeout=CONVERT_TIMEOUT)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            raise ServiceException(
                ErrorCode.TIMEOUT,
                "转换超时，文档可能过大或格式复杂",
            )
        if proc.returncode != 0:
            err = stderr.decode(errors="replace") if stderr else "未知错误"
            raise ServiceException(
                ErrorCode.CONVERSION_FAILED,
                f"转换失败: {err}",
            )
    except FileNotFoundError:
        raise ServiceException(
            ErrorCode.SERVICE_UNAVAILABLE,
            "未检测到 LibreOffice，请先安装",
        )

    if not os.path.exists(output_pdf):
        raise ServiceException(
            ErrorCode.CONVERSION_FAILED,
            "转换未生成输出文件",
        )

    # 保存原始文件名供下载时使用
    meta = {"original_filename": safe_name}
    meta_path = os.path.join(task_dir, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    logger.info(f"Word 转换完成: task_id={task_id} filename={safe_name}")
    return ConvertResponse(task_id=task_id, filename=safe_name)


def download_pdf(task_id: str) -> tuple:
    """获取 PDF 文件下载路径及原始文件名"""
    logger.info(f"下载文件: task_id={task_id}")
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = get_task_dir(task_id)
    root = os.path.abspath(TEMP_DIR)
    if os.path.commonpath([root, os.path.abspath(task_dir)]) != root:
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    pdf_path = os.path.join(task_dir, "output.pdf")
    if not os.path.exists(pdf_path):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "文件不存在")

    # 读取原始文件名，若无则回退到 task_id
    original_filename = f"{task_id}.pdf"
    meta_path = os.path.join(task_dir, "meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            raw = meta.get("original_filename", "")
            if raw:
                pdf_name = re.sub(r"\.(docx?)$", ".pdf", raw, flags=re.IGNORECASE)
                original_filename = pdf_name
        except (json.JSONDecodeError, OSError):
            pass

    logger.info(f"文件下载返回: task_id={task_id} filename={original_filename}")
    return pdf_path, original_filename
