"""PDF 深度解析服务（MinerU CLI）"""

import os
import sys
import uuid
import re
import shutil
import threading
import subprocess
import concurrent.futures

from fastapi import UploadFile

from app.core.config import settings
from app.utils.file import save_file, safe_filename
from app.utils.exception import ServiceException
from app.utils.logger_config import setup_logger
from app.schemas.response import ErrorCode
from app.schemas.tools.pdf_to_markdown import ConvertResponse, GetProgressResponse
from app.services.tools.pdf_to_markdown_helpers import (
    TEMP_DIR,
    UPLOADS_DIR,
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

CONVERT_TIMEOUT = 600  # 秒，与前端轮询容忍度匹配

# ========== 公共入口函数 ==========


def convert_pdf_deep(file: UploadFile):
    """启动深度异步解析（MinerU CLI）"""
    safe_name = safe_filename(file.filename, "input.pdf")
    if not safe_name.lower().endswith(".pdf"):
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "不支持的文件格式")
    if file.size > 50 * 1024 * 1024:
        raise ServiceException(ErrorCode.FILE_TOO_LARGE, "文件大小不能超过 50MB")

    task_id = uuid.uuid4().hex[:12]
    task_dir = os.path.join(TEMP_DIR, "tasks", task_id)
    os.makedirs(task_dir, exist_ok=True)

    # 保存原始 PDF 到 uploads/（带 task_id 前缀）
    upload_filename = f"{task_id}-{safe_name}"
    upload_path = os.path.join(UPLOADS_DIR, upload_filename)
    save_file(file.file.read(), upload_path)

    # 复制到任务目录
    pdf_path = os.path.join(task_dir, "input.pdf")
    shutil.copy2(upload_path, pdf_path)

    write_status_atomic(task_dir, 0, "排队等待中...")

    executor = concurrent.futures.ProcessPoolExecutor(max_workers=1)
    executor.submit(_run_mineru_convert, task_id, pdf_path, task_dir)
    executor.shutdown(wait=False)

    return ConvertResponse(task_id=task_id, filename=safe_name, page_count=0)


def get_progress_detail(task_id: str):
    """查询深度解析进度"""
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = os.path.join(TEMP_DIR, "tasks", task_id)
    root = os.path.abspath(TEMP_DIR)
    if os.path.commonpath([root, os.path.abspath(task_dir)]) != root:
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    status_path = os.path.join(task_dir, "deep_status.json")
    if not os.path.exists(status_path):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "任务不存在或非深度模式")

    import json
    with open(status_path, encoding="utf-8") as f:
        data = json.load(f)

    return GetProgressResponse(progress=data["progress"], stage=data["stage"])


"""辅助函数"""


def _match_stage(task_dir: str, line: str, reached: set):
    """逐行匹配阶段关键词并写状态（同一进度只写一次）。"""
    for pattern, progress, stage in _STAGE_PATTERNS:
        if re.search(pattern, line, re.IGNORECASE):
            if progress not in reached:
                reached.add(progress)
                write_status_atomic(task_dir, progress, stage)
            return


def _drain_stream(stream, on_line):
    """daemon 线程逐行读取子进程输出，避免管道缓冲死锁。"""
    try:
        for line in iter(stream.readline, ""):
            on_line(line)
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _run_mineru_convert(task_id: str, pdf_path: str, task_dir: str):
    """后台进程执行 MinerU CLI 转换（子进程中运行）"""
    try:
        write_status_atomic(task_dir, 5, "正在准备解析环境...")

        # 准备 MinerU 输出目录
        mineru_out = os.path.join(task_dir, "mineru_output")
        os.makedirs(mineru_out, exist_ok=True)

        # MinerU 模型缓存目录（项目内）
        cache_dir = settings.mineru_model_path
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
        mineru_bin = os.path.dirname(sys.executable)
        mineru_exe = os.path.join(mineru_bin, "mineru.exe" if os.name == "nt" else "mineru")

        proc = subprocess.Popen(
            [
                mineru_exe,
                "-p", pdf_path,
                "-o", mineru_out,
                "-b", "pipeline",
                "-l", "ch",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        # 实时读取 stdout/stderr，匹配阶段关键词更新进度
        reached: set = set()

        def on_line(line: str):
            _match_stage(task_dir, line, reached)

        readers = [
            threading.Thread(target=_drain_stream, args=(proc.stdout, on_line), daemon=True),
            threading.Thread(target=_drain_stream, args=(proc.stderr, on_line), daemon=True),
        ]
        for reader in readers:
            reader.start()

        try:
            returncode = proc.wait(timeout=CONVERT_TIMEOUT)
        except subprocess.TimeoutExpired:
            _kill_process(proc)
            write_status_atomic(task_dir, -1, "深度解析超时，请重试")
            logger.error(f"MinerU 超时: task_id={task_id}")
            return

        if returncode != 0:
            write_status_atomic(task_dir, -1, "深度解析失败，请稍后重试")
            logger.error(f"MinerU 转换失败: task_id={task_id} rc={returncode}")
            return

        write_status_atomic(task_dir, 92, "正在处理转换结果...")

        # 从 MinerU 输出目录查找 .md 文件，归一化到 task_dir/output.md
        _collect_output(mineru_out, task_dir)

        write_status_atomic(task_dir, 100, "解析完成")
        logger.info(f"深度解析完成: task_id={task_id}")

    except Exception as e:
        write_status_atomic(task_dir, -1, "深度解析失败，请稍后重试")
        logger.error(f"深度解析异常: task_id={task_id} error={e}", exc_info=True)


def _kill_process(proc: subprocess.Popen):
    """终止子进程（Windows 下连进程树一起终止）。"""
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


_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")


def _copy_referenced_assets(md_dir: str, md_content: str, task_dir: str):
    """补齐 md 中引用但未随目录复制的图片资源（兼容引用在 md 目录外的情况）。"""
    for raw in _IMAGE_REF_RE.findall(md_content):
        ref = raw.split("#", 1)[0].split("?", 1)[0]
        if not ref or ref.startswith(("http://", "https://", "data:", "/")):
            continue
        src = os.path.normpath(os.path.join(md_dir, ref))
        if not os.path.isfile(src):
            continue
        rel = os.path.relpath(src, md_dir)
        dst = os.path.join(task_dir, *rel.split(os.sep))
        if os.path.isfile(dst):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            shutil.copyfile(src, dst)
        except OSError:
            pass


def _collect_output(mineru_out: str, task_dir: str):
    """将 MinerU 输出收集到任务目录：md → output.md，图片资源保持相对引用。"""
    for root, _dirs, files in os.walk(mineru_out):
        for f in files:
            if not f.endswith(".md"):
                continue
            md_src = os.path.join(root, f)
            md_dir = os.path.dirname(md_src)

            # 复制 md 所在目录（含 images/ 等资源目录），保持相对引用
            shutil.copytree(md_dir, task_dir, dirs_exist_ok=True)

            # 补齐引用到 md 目录之外的资源
            try:
                with open(os.path.join(task_dir, f), encoding="utf-8") as fr:
                    md_content = fr.read()
            except OSError:
                md_content = ""
            if md_content:
                _copy_referenced_assets(md_dir, md_content, task_dir)

            # 重命名主 md 为 output.md，清理多余 md
            output_path = os.path.join(task_dir, "output.md")
            if os.path.abspath(os.path.join(task_dir, f)) != os.path.abspath(output_path):
                os.replace(os.path.join(task_dir, f), output_path)
            for name in os.listdir(task_dir):
                if name.endswith(".md") and name != "output.md":
                    try:
                        os.remove(os.path.join(task_dir, name))
                    except OSError:
                        pass

            logger.info(f"MinerU 输出收集完成: {md_src} -> {output_path}")
            return

    logger.warning(f"MinerU 输出中未找到 .md 文件: {mineru_out}")
