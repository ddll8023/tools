"""管理证件照模型状态、使用占用和受限删除。"""

import os
import shutil
import threading
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar

from toolbox_backend.core.config import settings
from toolbox_backend.core.errors import ServiceException
from toolbox_backend.schemas.response import ErrorCode
from toolbox_backend.modules.id_photo.inference import reset_model_sessions
from toolbox_backend.modules.id_photo.model_resources import (
    MATTE_MODEL_CANDIDATES,
    _find_matte_model,
    _model_directory,
    _mtcnn_weight_paths,
)


_MODEL_USE_CONDITION = threading.Condition()


_ACTIVE_MODEL_USES = 0


_MODEL_DELETE_IN_PROGRESS = False


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
        if _ACTIVE_MODEL_USES or _MODEL_DELETE_IN_PROGRESS:
            return False, "证件照正在处理中，暂不能删除模型"
    return True, None


def get_model_management_status() -> dict[str, object]:
    """返回设置页所需的证件照资源位置、状态和删除边界。"""
    available, reason = get_model_status()
    model_dir = Path(_model_directory())
    model_files_ready = _find_matte_model() is not None and all(
        os.path.isfile(path) for path in _mtcnn_weight_paths().values()
    )
    if available:
        status = "ready"
        stage = "证件照模型已就绪"
    elif not model_dir.is_dir():
        status = "not_downloaded"
        stage = "证件照模型未准备"
    elif not model_files_ready:
        status = "incomplete"
        stage = "证件照模型文件不完整"
    else:
        status = "unavailable"
        stage = "证件照运行依赖不可用"

    if _managed_model_directory() is not None:
        source = "用户数据目录"
    elif settings.ID_PHOTO_MODEL_PATH:
        source = "自定义路径"
    else:
        bundled_dir = Path(
            os.path.abspath(Path(settings.ROOT_PATH) / "resources" / "id_photo")
        )
        source = "应用内置资源" if model_dir == bundled_dir else "其他本地路径"

    can_delete, delete_reason = _photo_delete_state()
    return {
        "model_id": "id-photo",
        "name": "证件照模型",
        "description": "本地人脸检测与人像抠图模型",
        "source": source,
        "path": str(model_dir),
        "approx_size_bytes": None,
        "status": status,
        "progress": None,
        "stage": stage,
        "error": reason or None,
        "job_id": None,
        "can_delete": can_delete,
        "delete_reason": delete_reason,
    }


def delete_id_photo_model() -> dict[str, object]:
    """删除用户数据目录中的证件照模型，并释放已加载的会话。"""
    global _MODEL_DELETE_IN_PROGRESS

    model_dir = _managed_model_directory()
    if model_dir is None:
        raise ServiceException(ErrorCode.PARAM_ERROR, "证件照模型不在受管理的用户数据目录中，不能删除")

    with _MODEL_USE_CONDITION:
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
