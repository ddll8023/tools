"""本地模型管理服务。

模型下载由设置页显式触发；业务工具只检查模型是否已就绪，不在业务请求中隐式下载。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from app.core.config import settings
from app.schemas.response import ErrorCode
from app.core.errors import ServiceException
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

MINERU_PIPELINE_MODEL_ID = "mineru-pipeline"
_MODEL_STATE_FILENAME = ".download-state.json"
_MODEL_APPROX_SIZE_BYTES = 2 * 1024 * 1024 * 1024
# Windows 无创建符号链接权限时，ModelScope 可能留下 ._____temp；
# 以 pipeline 的关键文件作为完整性依据，不把符号链接告警误判为下载失败。
_REQUIRED_PIPELINE_FILES = (
    "models/Layout/PP-DocLayoutV2/config.json",
    "models/Layout/PP-DocLayoutV2/model.safetensors",
    "models/MFR/unimernet_hf_small_2503/config.json",
    "models/MFR/unimernet_hf_small_2503/model.safetensors",
    "models/OCR/paddleocr_torch/ch_PP-OCRv4_rec_infer.pth",
    "models/TabRec/SlanetPlus/slanet-plus.onnx",
    "models/TabRec/UnetStructure/unet.onnx",
    "models/TabCls/paddle_table_cls/PP-LCNet_x1_0_table_cls.onnx",
    "models/MFR/pp_formulanet_plus_m/PP-FormulaNet_plus-M.pth",
)
_PROGRESS_RE = re.compile(r"(?<!\d)(\d{1,3})\s*%")


@dataclass
class _DownloadJob:
    job_id: str
    status: str = "downloading"
    progress: int | None = None
    stage: str = "正在准备模型下载..."
    error: str | None = None
    process: subprocess.Popen[str] | None = None
    cancel_requested: bool = False
    output_tail: list[str] = field(default_factory=list)


_DOWNLOAD_LOCK = threading.RLock()
_ACTIVE_JOB: _DownloadJob | None = None


def _model_cache_dir() -> Path:
    return Path(settings.mineru_model_path).resolve()


def _state_path() -> Path:
    return _model_cache_dir() / _MODEL_STATE_FILENAME


def _write_state_locked(job: _DownloadJob) -> None:
    """原子写入最近一次下载状态，供重启后识别中断任务。"""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    payload = {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "error": job.error,
    }
    try:
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_state() -> dict[str, object] | None:
    try:
        with _state_path().open("r", encoding="utf-8") as source:
            value = json.load(source)
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def _model_cache_ready(cache_dir: Path | None = None) -> bool:
    """按 pipeline 关键文件检查模型是否完整。

    ModelScope 在 Windows 无符号链接权限时可能保留临时目录，但已下载的
    物理文件仍可被 MinerU 使用，因此不能仅以临时目录是否存在判定失败。
    """
    root = cache_dir or _model_cache_dir()
    model_root = root / "modelscope" / "models" / "OpenDataLab" / "PDF-Extract-Kit-1___0"
    return all((model_root / relative_path).is_file() for relative_path in _REQUIRED_PIPELINE_FILES)


def is_mineru_model_ready() -> bool:
    return _model_cache_ready()


def get_mineru_runtime_env() -> dict[str, str]:
    """返回 MinerU 下载和转换共同使用的缓存环境变量。"""
    cache_dir = _model_cache_dir()
    hf_cache = cache_dir / "huggingface"
    modelscope_cache = cache_dir / "modelscope"
    hf_cache.mkdir(parents=True, exist_ok=True)
    modelscope_cache.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["HF_HOME"] = str(hf_cache)
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env["MINERU_MODEL_SOURCE"] = "modelscope"
    env["MODELSCOPE_CACHE"] = str(modelscope_cache)
    # 将 MinerU 自身的模型配置也放入统一用户数据目录，避免写入用户主目录。
    env["MINERU_TOOLS_CONFIG_JSON"] = str(cache_dir / "mineru.json")
    return env


def get_mineru_download_command() -> list[str]:
    """返回开发或打包环境中的 MinerU 模型下载命令。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--toolbox-mineru-models"]

    bin_dir = os.path.dirname(sys.executable)
    suffix = ".exe" if os.name == "nt" else ""
    return [os.path.join(bin_dir, f"mineru-models-download{suffix}")]


def get_mineru_convert_command() -> list[str]:
    """返回开发或打包环境中的 MinerU 转换命令。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--toolbox-mineru"]

    bin_dir = os.path.dirname(sys.executable)
    suffix = ".exe" if os.name == "nt" else ""
    return [os.path.join(bin_dir, f"mineru{suffix}")]


def _model_payload(
    *,
    status: str,
    progress: int | None,
    stage: str,
    error: str | None,
    job_id: str | None,
) -> dict[str, object]:
    return {
        "model_id": MINERU_PIPELINE_MODEL_ID,
        "name": "MinerU Pipeline",
        "description": "PDF 深度解析模型",
        "source": "ModelScope",
        "path": str(_model_cache_dir()),
        "approx_size_bytes": _MODEL_APPROX_SIZE_BYTES,
        "status": status,
        "progress": progress,
        "stage": stage,
        "error": error,
        "job_id": job_id,
    }


def _payload_from_job(job: _DownloadJob) -> dict[str, object]:
    return _model_payload(
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        error=job.error,
        job_id=job.job_id,
    )


def get_mineru_model_status() -> dict[str, object]:
    """获取模型状态；软件重启后不会把未恢复的下载误报为进行中。"""
    with _DOWNLOAD_LOCK:
        if _ACTIVE_JOB is not None:
            return _payload_from_job(_ACTIVE_JOB)

    if _model_cache_ready():
        return _model_payload(
            status="ready",
            progress=100,
            stage="模型已就绪",
            error=None,
            job_id=None,
        )

    state = _read_state() or {}
    state_status = state.get("status")
    if state_status == "downloading":
        return _model_payload(
            status="interrupted",
            progress=state.get("progress") if isinstance(state.get("progress"), int) else None,
            stage="上次下载未完成，请继续下载",
            error="上次下载已中断",
            job_id=state.get("job_id") if isinstance(state.get("job_id"), str) else None,
        )
    if state_status in {"failed", "cancelled"}:
        return _model_payload(
            status=state_status,
            progress=state.get("progress") if isinstance(state.get("progress"), int) else None,
            stage=str(state.get("stage") or "模型未就绪"),
            error=str(state.get("error")) if state.get("error") else None,
            job_id=state.get("job_id") if isinstance(state.get("job_id"), str) else None,
        )

    return _model_payload(
        status="not_downloaded",
        progress=None,
        stage="尚未下载模型",
        error=None,
        job_id=None,
    )


def require_mineru_model() -> None:
    """阻止深度解析隐式下载模型，要求用户先在设置页完成准备。"""
    status = get_mineru_model_status()
    if status["status"] == "ready":
        return

    if status["status"] == "downloading":
        message = "MinerU 模型正在下载，请在设置页面等待下载完成后再使用深度解析"
    elif status["status"] in {"failed", "interrupted", "cancelled"}:
        message = "MinerU 模型尚未就绪，请前往设置页面重试下载"
    else:
        message = "MinerU 模型尚未下载，请前往设置页面手动下载"
    raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, message)


def start_mineru_download() -> dict[str, object]:
    """启动或复用唯一的 MinerU 下载任务。"""
    global _ACTIVE_JOB

    with _DOWNLOAD_LOCK:
        if _ACTIVE_JOB is not None and _ACTIVE_JOB.status == "downloading":
            return _payload_from_job(_ACTIVE_JOB)

    if _model_cache_ready():
        return get_mineru_model_status()

    with _DOWNLOAD_LOCK:
        if _ACTIVE_JOB is not None and _ACTIVE_JOB.status == "downloading":
            return _payload_from_job(_ACTIVE_JOB)

        job = _DownloadJob(job_id=uuid.uuid4().hex[:12])
        _ACTIVE_JOB = job
        _write_state_locked(job)
        thread = threading.Thread(
            target=_run_download,
            args=(job.job_id,),
            name="mineru-model-download",
            daemon=True,
        )
        thread.start()
        return _payload_from_job(job)


def cancel_mineru_download() -> dict[str, object]:
    """取消当前下载；已写入的临时缓存由下一次下载命令负责续传或校验。"""
    with _DOWNLOAD_LOCK:
        job = _ACTIVE_JOB
        if job is None or job.status != "downloading":
            return get_mineru_model_status()
        job.cancel_requested = True
        process = job.process
        job.stage = "正在取消模型下载..."
        if process is not None:
            _kill_process(process)
        return _payload_from_job(job)


def _update_progress(job_id: str, line: str) -> None:
    match = _PROGRESS_RE.search(line)
    with _DOWNLOAD_LOCK:
        job = _ACTIVE_JOB
        if job is None or job.job_id != job_id or job.status != "downloading":
            return

        clean_line = line.strip()
        if clean_line:
            job.output_tail.append(clean_line[-1000:])
            if len(job.output_tail) > 30:
                del job.output_tail[:-30]

        changed = False
        if match:
            progress = min(100, max(0, int(match.group(1))))
            if job.progress != progress:
                job.progress = progress
                changed = True
        if line.strip() and job.stage != "正在下载 MinerU 模型...":
            job.stage = "正在下载 MinerU 模型..."
            changed = True
        if changed and job.progress is not None:
            _write_state_locked(job)


def _get_output_tail(job_id: str) -> list[str]:
    with _DOWNLOAD_LOCK:
        job = _ACTIVE_JOB
        if job is None or job.job_id != job_id:
            return []
        return list(job.output_tail)


def _read_download_output(job_id: str, stream: IO[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            _update_progress(job_id, line)
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _finish_job(job_id: str, status: str, stage: str, error: str | None = None) -> None:
    global _ACTIVE_JOB
    with _DOWNLOAD_LOCK:
        job = _ACTIVE_JOB
        if job is None or job.job_id != job_id:
            return
        job.status = status
        job.stage = stage
        job.error = error
        job.process = None
        if status == "ready":
            job.progress = 100
        _write_state_locked(job)
        _ACTIVE_JOB = None


def _get_download_failure_feedback(output_tail: list[str]) -> tuple[str, str]:
    """将常见的运行时故障转换为设置页可理解的提示。"""
    output = "\n".join(output_tail)
    if "WinError 1114" in output or "c10.dll" in output:
        return (
            "PyTorch 运行环境不可用，请升级 Windows 或修复 Python 运行依赖后重试",
            "PyTorch 原生 DLL 初始化失败",
        )
    if "ProxyError" in output or "ConnectTimeout" in output or "ConnectionError" in output:
        return (
            "模型下载失败，请检查网络或代理设置后重试",
            "模型源连接失败",
        )
    return "模型下载失败，请检查网络后重试", "模型下载进程执行失败"


def _run_download(job_id: str) -> None:
    command = get_mineru_download_command()
    process: subprocess.Popen[str] | None = None
    reader: threading.Thread | None = None

    try:
        if not getattr(sys, "frozen", False) and not Path(command[0]).is_file():
            raise RuntimeError("MinerU 模型下载命令不可用，请先完成后端依赖安装")

        process = subprocess.Popen(
            command + ["-s", "modelscope", "-m", "pipeline"],
            cwd=str(_model_cache_dir()),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=get_mineru_runtime_env(),
        )
        with _DOWNLOAD_LOCK:
            job = _ACTIVE_JOB
            if job is None or job.job_id != job_id:
                _kill_process(process)
                return
            job.process = process
            job.stage = "正在下载 MinerU 模型..."
            _write_state_locked(job)
            if job.cancel_requested:
                _kill_process(process)

        if process.stdout is not None:
            reader = threading.Thread(
                target=_read_download_output,
                args=(job_id, process.stdout),
                name="mineru-model-download-output",
                daemon=True,
            )
            reader.start()

        returncode = process.wait(timeout=settings.MINERU_MODEL_DOWNLOAD_TIMEOUT)
        if reader is not None:
            reader.join(timeout=2)

        with _DOWNLOAD_LOCK:
            cancelled = bool(_ACTIVE_JOB and _ACTIVE_JOB.job_id == job_id and _ACTIVE_JOB.cancel_requested)

        output_tail = _get_output_tail(job_id)
        if cancelled:
            _finish_job(job_id, "cancelled", "模型下载已取消", "模型下载已取消")
        elif returncode != 0:
            stage, error = _get_download_failure_feedback(output_tail)
            _finish_job(job_id, "failed", stage, error)
            logger.error(
                "MinerU 模型下载失败: job_id=%s rc=%s output=%s",
                job_id,
                returncode,
                "\n".join(output_tail[-20:]),
            )
        elif not _model_cache_ready():
            _finish_job(job_id, "failed", "模型下载未完成，请重试", "下载命令结束，但未检测到完整模型")
            logger.error(
                "MinerU 模型缓存校验失败: job_id=%s output=%s",
                job_id,
                "\n".join(output_tail[-20:]),
            )
        else:
            _finish_job(job_id, "ready", "模型已就绪")
            logger.info("MinerU 模型下载完成: job_id=%s", job_id)
    except subprocess.TimeoutExpired:
        if process is not None:
            _kill_process(process)
        _finish_job(
            job_id,
            "failed",
            "模型下载超时，请检查网络后重试",
            f"模型下载超过 {settings.MINERU_MODEL_DOWNLOAD_TIMEOUT // 60} 分钟",
        )
        logger.error("MinerU 模型下载超时: job_id=%s", job_id)
    except FileNotFoundError:
        _finish_job(job_id, "failed", "模型下载命令不可用，请先完成后端依赖安装", "未找到 MinerU 模型下载命令")
        logger.error("MinerU 模型下载命令不存在: job_id=%s", job_id)
    except Exception as exc:
        if process is not None:
            _kill_process(process)
        _finish_job(job_id, "failed", "模型下载失败，请稍后重试", "模型下载任务异常")
        logger.error("MinerU 模型下载异常: job_id=%s error=%s", job_id, exc, exc_info=True)


def _kill_process(process: subprocess.Popen[str]) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            process.terminate()
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
    try:
        process.wait(timeout=5)
    except Exception:
        pass
