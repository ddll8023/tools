"""PDF 深度解析服务（MinerU CLI）"""

import os
import sys
import uuid
import subprocess
import concurrent.futures
import re

from fastapi import UploadFile

from app.core.config import settings
from app.utils.file import save_file
from app.utils.exception import ServiceException
from app.utils.logger_config import setup_logger
from app.schemas.response import ErrorCode
from app.schemas.tools.pdf_to_markdown import ConvertResponse, GetProgressResponse
from app.services.tools.pdf_to_markdown_helpers import (
    TEMP_DIR,
    validate_task_id,
    write_status_atomic,
)

logger = setup_logger(__name__)

_STAGE_PATTERNS = [
    (r"模型加载", 15, "正在加载深度学习模型..."),
    (r"OCR|文字识别", 35, "正在 OCR 文字识别..."),
    (r"布局|版面", 55, "正在分析布局与结构..."),
    (r"表格|公式|图片", 75, "正在提取表格与图片..."),
    (r"生成|输出|Markdown", 90, "正在生成 Markdown 文档..."),
]

# ========== 公共入口函数 ==========


def convert_pdf_deep(file: UploadFile):
    """启动深度异步解析（MinerU CLI）"""
    if not file.filename.lower().endswith(".pdf"):
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "不支持的文件格式")
    if file.size > 50 * 1024 * 1024:
        raise ServiceException(ErrorCode.FILE_TOO_LARGE, "文件大小不能超过 50MB")

    task_id = uuid.uuid4().hex[:12]
    task_dir = os.path.join(TEMP_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)
    pdf_path = os.path.join(task_dir, "input.pdf")
    save_file(file.file.read(), pdf_path)

    write_status_atomic(task_dir, 0, "排队等待中...")

    executor = concurrent.futures.ProcessPoolExecutor(max_workers=1)
    executor.submit(_run_mineru_convert, task_id, pdf_path, task_dir)
    executor.shutdown(wait=False)

    return ConvertResponse(task_id=task_id, filename=file.filename, page_count=0)


def get_progress_detail(task_id: str):
    """查询深度解析进度"""
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = os.path.join(TEMP_DIR, task_id)
    resolved = os.path.abspath(task_dir)
    if not resolved.startswith(os.path.abspath(TEMP_DIR)):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    status_path = os.path.join(task_dir, "deep_status.json")
    if not os.path.exists(status_path):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "任务不存在或非深度模式")

    import json
    with open(status_path, encoding="utf-8") as f:
        data = json.load(f)

    return GetProgressResponse(progress=data["progress"], stage=data["stage"])


"""辅助函数"""


def _run_mineru_convert(task_id: str, pdf_path: str, task_dir: str):
    """后台进程执行 MinerU CLI 转换"""
    try:
        write_status_atomic(task_dir, 5, "正在准备解析环境...")

        # 准备 MinerU 输出目录
        mineru_out = os.path.join(task_dir, "mineru_output")
        os.makedirs(mineru_out, exist_ok=True)

        # MinerU 模型缓存目录
        cache_dir = os.path.join(settings.ROOT_PATH, "..", "models", "mineru")
        cache_dir = os.path.abspath(cache_dir)
        os.makedirs(cache_dir, exist_ok=True)
        hf_cache = os.path.join(cache_dir, "huggingface")
        os.makedirs(hf_cache, exist_ok=True)

        write_status_atomic(task_dir, 10, "正在初始化 MinerU 引擎...")

        env = dict(os.environ)
        modelscope_cache = os.path.join(cache_dir, "modelscope")
        os.makedirs(modelscope_cache, exist_ok=True)

        env["HF_HOME"] = hf_cache
        env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        env["MINERU_MODEL_SOURCE"] = "modelscope"
        env["MODELSCOPE_CACHE"] = modelscope_cache

        write_status_atomic(task_dir, 15, "正在加载深度学习模型...")

        # 使用 venv 中 mineru 的完整路径，避免子进程 PATH 找不到可执行文件
        mineru_exe = os.path.join(os.path.dirname(sys.executable), "mineru.exe")

        result = subprocess.run(
            [
                mineru_exe,
                "-p", pdf_path,
                "-o", mineru_out,
                "-b", "pipeline",
                "-l", "ch",
            ],
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )

        # 解析 MinerU 标准输出中的进度
        _parse_mineru_output(task_dir, result.stdout)

        if result.returncode != 0:
            err_msg = result.stderr.strip()[-300:] if result.stderr else "未知错误"
            write_status_atomic(task_dir, -1, f"深度解析失败: {err_msg}")
            logger.error(f"MinerU 转换失败: task_id={task_id} rc={result.returncode} stderr={result.stderr}")
            return

        write_status_atomic(task_dir, 92, "正在处理转换结果...")

        # 从 MinerU 输出目录查找 .md 文件，归一化到 task_dir/output.md
        _collect_output(mineru_out, task_dir)

        write_status_atomic(task_dir, 100, "解析完成")
        logger.info(f"深度解析完成: task_id={task_id}")

    except subprocess.TimeoutExpired:
        write_status_atomic(task_dir, -1, "深度解析超时，请重试")
        logger.error(f"MinerU 超时: task_id={task_id}")
    except Exception as e:
        write_status_atomic(task_dir, -1, "深度解析失败，请稍后重试")
        logger.error(f"深度解析异常: task_id={task_id} error={e}", exc_info=True)


def _parse_mineru_output(task_dir: str, stdout: str):
    """从 MinerU 标准输出中解析阶段信息"""
    for pattern, progress, stage in _STAGE_PATTERNS:
        if re.search(pattern, stdout, re.IGNORECASE):
            write_status_atomic(task_dir, progress, stage)
            return


def _collect_output(mineru_out: str, task_dir: str):
    """将 MinerU 输出目录中的 .md 文件收集到 task_dir/output.md"""
    md_target = os.path.join(task_dir, "output.md")

    # MinerU 输出结构: {mineru_out}/{pdf_stem}/{method}/{pdf_stem}.md
    for root, _dirs, files in os.walk(mineru_out):
        for f in files:
            if f.endswith(".md"):
                src = os.path.join(root, f)
                with open(src, encoding="utf-8") as fr:
                    content = fr.read()
                with open(md_target, "w", encoding="utf-8") as fw:
                    fw.write(content)
                logger.info(f"MinerU 输出收集完成: {src} -> {md_target}")
                return

    logger.warning(f"MinerU 输出中未找到 .md 文件: {mineru_out}")
