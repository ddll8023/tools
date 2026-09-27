"""管理证件照模型状态、使用占用和受限删除。"""

import os
import shutil
import threading
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar

from toolbox_backend.core.config import settings
from toolbox_backend.core.errors import ServiceException
from toolbox_backend.core.logging import setup_logger
from toolbox_backend.schemas.response import ErrorCode
from toolbox_backend.modules.id_photo.inference import reset_model_sessions
from toolbox_backend.modules.id_photo.model_resources import (
    MATTE_MODEL_CANDIDATES,
    MTCNN_WEIGHT_NAMES,
    _find_matte_model,
    _model_directory,
    _mtcnn_weight_paths,
)


logger = setup_logger(__name__)
_MODEL_USE_CONDITION = threading.Condition()


_ACTIVE_MODEL_USES = 0


_MODEL_DELETE_IN_PROGRESS = False


_MODNET_MODEL_URL = (
    "https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/"
    "pretrained-model/hivision_modnet.onnx"
)
_DOWNLOAD_LOCK = threading.RLock()


@dataclass
class _IdPhotoDownloadJob:
    """保存单个证件照模型下载任务的可见状态。"""

    job_id: str
    status: str = "downloading"
    progress: int | None = None
    stage: str = "正在准备证件照模型下载..."
    error: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    response: object | None = None


_ACTIVE_DOWNLOAD: _IdPhotoDownloadJob | None = None
_LAST_DOWNLOAD: _IdPhotoDownloadJob | None = None


P = ParamSpec("P")


R = TypeVar("R")


def get_model_status() -> tuple[bool, str]:
    """检查证件照所需依赖和当前模型资源是否可用。"""
    matte_model = _find_matte_model()
    if matte_model is None:
        names = "、".join(MATTE_MODEL_CANDIDATES)
        return False, f"缺少人像抠图模型，当前资源目录需包含：{names}"

    missing_mtcnn = [
        path for path in _mtcnn_weight_paths().values() if not os.path.isfile(path)
    ]
    if missing_mtcnn:
        return False, "当前资源目录缺少 MTCNN 模型文件：pnet.onnx、rnet.onnx、onet.onnx"

    try:
        import mtcnnruntime  # noqa: F401
        import onnxruntime  # noqa: F401
    except (ImportError, OSError) as exc:
        dependency = getattr(exc, "name", None) or type(exc).__name__
        return False, f"证件照运行依赖不可用: {dependency}"

    return True, ""


def _managed_model_directory() -> str | None:
    """只允许删除默认用户数据目录中的证件照模型资源。"""
    data_root = Path(settings.data_root).resolve()
    expected = Path(os.path.abspath(data_root / "resources" / "id_photo"))
    configured = Path(_model_directory())
    if configured != expected or expected.is_symlink():
        return None

    resolved = expected.resolve()
    if resolved == data_root or not resolved.is_relative_to(data_root):
        return None
    return str(resolved)


def _photo_delete_state() -> tuple[bool, str | None]:
    model_dir = _managed_model_directory()
    if model_dir is None:
        return False, "模型位于应用内置或自定义目录，不能从设置中删除"
    if not os.path.isdir(model_dir):
        return False, "没有可删除的用户数据模型"
    with _MODEL_USE_CONDITION:
        with _DOWNLOAD_LOCK:
            downloading = _ACTIVE_DOWNLOAD is not None
        if downloading:
            return False, "证件照模型下载中，暂不能删除"
        if _ACTIVE_MODEL_USES or _MODEL_DELETE_IN_PROGRESS:
            return False, "证件照正在处理中，暂不能删除模型"
    return True, None


def get_model_management_status() -> dict[str, object]:
    """返回设置页所需的证件照资源位置、状态和管理操作边界。"""
    available, reason = get_model_status()
    model_dir = Path(_model_directory())
    model_files_ready = _find_matte_model() is not None and all(
        os.path.isfile(path) for path in _mtcnn_weight_paths().values()
    )
    with _DOWNLOAD_LOCK:
        active_job = _ACTIVE_DOWNLOAD
        last_job = _LAST_DOWNLOAD

    if active_job is not None:
        status = "downloading"
        stage = active_job.stage
        progress = active_job.progress
        error = None
        job_id = active_job.job_id
    elif available:
        status = "ready"
        stage = "证件照模型已就绪"
        progress = 100
        error = None
        job_id = None
    elif last_job is not None and last_job.status in {"failed", "cancelled"}:
        status = last_job.status
        stage = last_job.stage
        progress = last_job.progress
        error = last_job.error or reason or None
        job_id = last_job.job_id
    elif not model_dir.is_dir():
        status = "not_downloaded"
        stage = "证件照模型未准备"
        progress = None
        error = reason or None
        job_id = None
    elif not model_files_ready:
        status = "incomplete"
        stage = "证件照模型文件不完整"
        progress = None
        error = reason or None
        job_id = None
    else:
        status = "unavailable"
        stage = "证件照运行依赖不可用"
        progress = None
        error = reason or None
        job_id = None

    managed_dir = _managed_model_directory()
    if managed_dir is not None:
        source = "用户数据目录"
    elif settings.ID_PHOTO_MODEL_PATH:
        source = "自定义路径"
    else:
        bundled_dir = Path(
            os.path.abspath(Path(settings.ROOT_PATH) / "resources" / "id_photo")
        )
        source = "应用内置资源" if model_dir == bundled_dir else "其他本地路径"

    can_delete, delete_reason = _photo_delete_state()
    can_download = (
        managed_dir is not None
        and not available
        and (reason.startswith("缺少人像抠图模型") or reason.startswith("当前资源目录缺少 MTCNN"))
        and active_job is None
    )
    return {
        "model_id": "id-photo",
        "name": "证件照模型",
        "description": "本地人脸检测与人像抠图模型",
        "source": source,
        "path": str(model_dir),
        "approx_size_bytes": None,
        "status": status,
        "progress": progress,
        "stage": stage,
        "error": error,
        "job_id": job_id,
        "can_delete": can_delete,
        "delete_reason": delete_reason,
        "can_download": can_download,
    }


class _IdPhotoDownloadCancelled(Exception):
    """表示用户取消了证件照模型下载。"""


def _job_cancelled(job_id: str) -> bool:
    with _DOWNLOAD_LOCK:
        job = _ACTIVE_DOWNLOAD
        return job is None or job.job_id != job_id or job.cancel_event.is_set()


def _update_download_progress(job_id: str, stage: str, progress: int | None) -> None:
    with _DOWNLOAD_LOCK:
        job = _ACTIVE_DOWNLOAD
        if job is None or job.job_id != job_id:
            return
        job.stage = stage
        job.progress = progress


def _safe_model_path(model_dir: Path, target: Path) -> Path:
    root = model_dir.resolve()
    parent = target.parent.resolve()
    if parent != root and not parent.is_relative_to(root):
        raise PermissionError("模型资源路径越过用户数据目录")
    if target.is_symlink():
        raise PermissionError("模型资源文件不能是符号链接")
    return target


def _download_modnet_model(job_id: str, model_dir: Path) -> None:
    target = _safe_model_path(model_dir, model_dir / MATTE_MODEL_CANDIDATES[0])
    temporary = _safe_model_path(
        model_dir,
        target.with_name(f".{target.name}.{job_id}.download"),
    )
    request = urllib.request.Request(
        _MODNET_MODEL_URL,
        headers={"User-Agent": "toolbox-id-photo-model-manager"},
    )
    response = urllib.request.urlopen(request, timeout=30)
    with _DOWNLOAD_LOCK:
        job = _ACTIVE_DOWNLOAD
        if job is None or job.job_id != job_id or job.cancel_event.is_set():
            response.close()
            raise _IdPhotoDownloadCancelled
        job.response = response

    received = 0
    try:
        total = int(response.headers.get("Content-Length") or 0)
        _update_download_progress(job_id, "正在下载人像抠图模型...", 0 if total else None)
        with response, temporary.open("xb") as output:
            while True:
                if _job_cancelled(job_id):
                    raise _IdPhotoDownloadCancelled
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                progress = min(90, int(received * 90 / total)) if total else None
                _update_download_progress(job_id, "正在下载人像抠图模型...", progress)

        if _job_cancelled(job_id):
            raise _IdPhotoDownloadCancelled
        if received == 0 or (total and received != total):
            raise OSError("模型文件下载不完整")
        os.replace(temporary, target)
    finally:
        with _DOWNLOAD_LOCK:
            job = _ACTIVE_DOWNLOAD
            if job is not None and job.job_id == job_id:
                job.response = None
        if temporary.exists():
            temporary.unlink()


def _cleanup_stale_download_parts(model_dir: Path) -> None:
    """清理由进程异常退出遗留的证件照模型临时文件。"""
    resources = (
        (model_dir, MATTE_MODEL_CANDIDATES),
        (model_dir / "mtcnn", MTCNN_WEIGHT_NAMES),
    )
    root = model_dir.resolve()
    for directory, filenames in resources:
        if not directory.exists():
            continue
        if directory.is_symlink():
            raise PermissionError("模型临时目录不能是符号链接")
        parent = directory.resolve()
        if parent != root and not parent.is_relative_to(root):
            raise PermissionError("模型临时目录越过用户数据目录")
        for filename in filenames:
            for pattern in (f".{filename}.*.download", f"{filename}.download"):
                for temporary in directory.glob(pattern):
                    if temporary.is_dir() and not temporary.is_symlink():
                        continue
                    temporary.unlink()


def _copy_mtcnn_weights(job_id: str, model_dir: Path) -> None:
    import mtcnnruntime

    package_file = getattr(mtcnnruntime, "__file__", None)
    if not package_file:
        raise FileNotFoundError("MTCNN 模型资源不可用")
    source_dir = Path(package_file).resolve().parent / "weights"
    target_dir = model_dir / "mtcnn"
    if target_dir.is_symlink():
        raise PermissionError("MTCNN 模型目录不能是符号链接")
    target_dir.mkdir(parents=True, exist_ok=True)
    _safe_model_path(model_dir, target_dir)

    for index, filename in enumerate(MTCNN_WEIGHT_NAMES, start=1):
        if _job_cancelled(job_id):
            raise _IdPhotoDownloadCancelled
        source = source_dir / filename
        target = _safe_model_path(model_dir, target_dir / filename)
        temporary = _safe_model_path(
            model_dir,
            target.with_name(f".{target.name}.{job_id}.download"),
        )
        if not source.is_file() or source.stat().st_size == 0:
            raise FileNotFoundError("MTCNN 模型资源不可用")
        if not target.is_file() or target.stat().st_size == 0:
            try:
                with source.open("rb") as source_file, temporary.open("xb") as output:
                    shutil.copyfileobj(source_file, output)
                if _job_cancelled(job_id):
                    raise _IdPhotoDownloadCancelled
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink()
        progress = 90 + int(index * 9 / len(MTCNN_WEIGHT_NAMES))
        _update_download_progress(job_id, "正在准备人脸检测模型...", progress)


def _finish_id_photo_download(
    job_id: str,
    status: str,
    stage: str,
    error: str | None = None,
) -> None:
    global _ACTIVE_DOWNLOAD, _LAST_DOWNLOAD
    with _DOWNLOAD_LOCK:
        job = _ACTIVE_DOWNLOAD
        if job is None or job.job_id != job_id:
            return
        job.status = status
        job.stage = stage
        job.error = error
        job.response = None
        if status == "ready":
            job.progress = 100
        _LAST_DOWNLOAD = job
        _ACTIVE_DOWNLOAD = None


def _run_id_photo_download(job_id: str) -> None:
    model_dir = _managed_model_directory()
    try:
        if model_dir is None:
            raise PermissionError("证件照模型只能下载到默认用户数据目录")
        target_dir = Path(model_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        _cleanup_stale_download_parts(target_dir)

        if _find_matte_model() is None:
            _download_modnet_model(job_id, target_dir)
        _copy_mtcnn_weights(job_id, target_dir)

        if _job_cancelled(job_id):
            raise _IdPhotoDownloadCancelled
        available, reason = get_model_status()
        if not available:
            model_files_ready = _find_matte_model() is not None and all(
                os.path.isfile(path) for path in _mtcnn_weight_paths().values()
            )
            if model_files_ready:
                _finish_id_photo_download(
                    job_id,
                    "unavailable",
                    "模型文件已准备，运行依赖不可用",
                    reason,
                )
                return
            raise RuntimeError(reason or "模型资源校验未通过")
        _finish_id_photo_download(job_id, "ready", "证件照模型已就绪")
    except _IdPhotoDownloadCancelled:
        _finish_id_photo_download(
            job_id,
            "cancelled",
            "证件照模型下载已取消",
            "下载已取消，可重新准备模型。",
        )
    except Exception as exc:
        if _job_cancelled(job_id):
            _finish_id_photo_download(
                job_id,
                "cancelled",
                "证件照模型下载已取消",
                "下载已取消，可重新准备模型。",
            )
        else:
            logger.error(
                "证件照模型下载失败: job_id=%s error_type=%s",
                job_id,
                type(exc).__name__,
                exc_info=True,
            )
            _finish_id_photo_download(
                job_id,
                "failed",
                "证件照模型准备失败",
                "下载失败，请检查网络或本地模型资源后重试。",
            )


def start_id_photo_download() -> dict[str, object]:
    """启动证件照模型下载，仅写入默认受管理的用户数据目录。"""
    global _ACTIVE_DOWNLOAD, _LAST_DOWNLOAD
    model_dir = _managed_model_directory()
    if model_dir is None:
        raise ServiceException(
            ErrorCode.PARAM_ERROR,
            "当前证件照模型位于应用内置或自定义目录，不能从设置页下载。",
        )

    available, reason = get_model_status()
    if available:
        return get_model_management_status()
    if not (
        reason.startswith("缺少人像抠图模型")
        or reason.startswith("当前资源目录缺少 MTCNN")
    ):
        raise ServiceException(
            ErrorCode.SERVICE_UNAVAILABLE,
            reason or "当前证件照模型状态不支持下载。",
        )

    with _MODEL_USE_CONDITION:
        if _MODEL_DELETE_IN_PROGRESS or _ACTIVE_MODEL_USES:
            raise ServiceException(
                ErrorCode.SERVICE_UNAVAILABLE,
                "证件照正在处理中，暂不能下载模型。",
            )
        with _DOWNLOAD_LOCK:
            if _ACTIVE_DOWNLOAD is not None:
                return get_model_management_status()
            job = _IdPhotoDownloadJob(job_id=uuid.uuid4().hex[:12])
            _ACTIVE_DOWNLOAD = job
            _LAST_DOWNLOAD = job
            threading.Thread(
                target=_run_id_photo_download,
                args=(job.job_id,),
                name="id-photo-model-download",
                daemon=True,
            ).start()

    return get_model_management_status()


def cancel_id_photo_download() -> dict[str, object]:
    """请求取消证件照模型下载并关闭当前网络响应。"""
    with _DOWNLOAD_LOCK:
        job = _ACTIVE_DOWNLOAD
        response = None if job is None else job.response
        if job is not None:
            job.cancel_event.set()
            job.stage = "正在取消证件照模型下载..."
    if response is not None:
        close_response = getattr(response, "close", None)
        if callable(close_response):
            try:
                close_response()
            except OSError:
                pass
    return get_model_management_status()


def delete_id_photo_model() -> dict[str, object]:
    """删除用户数据目录中的证件照模型，并释放已加载的会话。"""
    global _MODEL_DELETE_IN_PROGRESS

    model_dir = _managed_model_directory()
    if model_dir is None:
        raise ServiceException(ErrorCode.PARAM_ERROR, "证件照模型不在受管理的用户数据目录中，不能删除")

    with _MODEL_USE_CONDITION:
        with _DOWNLOAD_LOCK:
            if _ACTIVE_DOWNLOAD is not None:
                raise ServiceException(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "证件照模型下载中，暂不能删除模型",
                )
        if _MODEL_DELETE_IN_PROGRESS or _ACTIVE_MODEL_USES:
            raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "证件照正在处理中，暂不能删除模型")
        if not os.path.isdir(model_dir):
            raise ServiceException(ErrorCode.DATA_NOT_FOUND, "没有可删除的用户数据模型")
        _MODEL_DELETE_IN_PROGRESS = True

    try:
        reset_model_sessions()
        shutil.rmtree(model_dir)
    except OSError as exc:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "删除证件照模型资源失败") from exc
    finally:
        with _MODEL_USE_CONDITION:
            _MODEL_DELETE_IN_PROGRESS = False
            _MODEL_USE_CONDITION.notify_all()

    return get_model_management_status()


def _guard_model_use(function: Callable[P, R]) -> Callable[P, R]:
    """登记整个人像处理过程，防止清理时模型仍被使用。"""
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        global _ACTIVE_MODEL_USES
        with _MODEL_USE_CONDITION:
            if _MODEL_DELETE_IN_PROGRESS:
                raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "证件照模型正在删除，请稍后重试")
            _ACTIVE_MODEL_USES += 1
        try:
            return function(*args, **kwargs)
        finally:
            with _MODEL_USE_CONDITION:
                _ACTIVE_MODEL_USES = max(0, _ACTIVE_MODEL_USES - 1)
                _MODEL_USE_CONDITION.notify_all()

    return wrapped
