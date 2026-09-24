"""软件设置接口。"""

from fastapi import APIRouter

from toolbox_backend.core.capabilities import CAPABILITY_ID_PHOTO, capabilities
from toolbox_backend.core.errors import ServiceException
from toolbox_backend.schemas.response import ApiResponse, ErrorCode, success
from toolbox_backend.schemas.settings import (
    ModelActionResponse,
    ModelRequest,
    ModelStatusResponse,
)
from toolbox_backend.modules.model_management.service import (
    MINERU_PIPELINE_MODEL_ID,
    cancel_mineru_download,
    delete_mineru_model,
    get_mineru_model_status,
    start_mineru_download,
)
from toolbox_backend.modules.id_photo import model_management as id_photo_model_management

router = APIRouter(prefix="/settings", tags=["settings"])


def _get_id_photo_status() -> dict[str, object]:
    """读取证件照模型状态并同步工具目录可用性。"""
    status = id_photo_model_management.get_model_management_status()
    reason = status.get("error")
    capabilities.set(
        CAPABILITY_ID_PHOTO,
        status.get("status") == "ready",
        reason if isinstance(reason, str) else "",
    )
    return status


def _get_model_status(model_id: str) -> dict[str, object]:
    """校验模型标识并读取对应资源状态。"""
    if model_id == MINERU_PIPELINE_MODEL_ID:
        return get_mineru_model_status()
    if model_id == "id-photo":
        return _get_id_photo_status()
    raise ServiceException(ErrorCode.PARAM_ERROR, "不支持的模型")


def _action_model(model_id: str, action: str) -> dict[str, object]:
    """仅对 MinerU 执行下载或取消操作。"""
    if model_id != MINERU_PIPELINE_MODEL_ID:
        raise ServiceException(ErrorCode.PARAM_ERROR, "该模型不支持此操作")
    if action == "download":
        return start_mineru_download()
    return cancel_mineru_download()


@router.post("/models/status", response_model=ApiResponse[ModelStatusResponse])
def get_models_status() -> dict[str, object]:
    """返回设置页可管理的本地模型状态。"""
    return success(data={"models": [get_mineru_model_status(), _get_id_photo_status()]})


@router.post("/models/download", response_model=ApiResponse[ModelActionResponse])
def download_model(body: ModelRequest) -> dict[str, object]:
    """手动启动 MinerU 模型下载；重复请求会复用当前任务。"""
    return success(data=_action_model(body.model_id, "download"))


@router.post("/models/progress", response_model=ApiResponse[ModelActionResponse])
def get_model_progress(body: ModelRequest) -> dict[str, object]:
    """查询模型下载任务状态。"""
    return success(data=_get_model_status(body.model_id))


@router.post("/models/cancel", response_model=ApiResponse[ModelActionResponse])
def cancel_model_download(body: ModelRequest) -> dict[str, object]:
    """取消当前模型下载任务。"""
    return success(data=_action_model(body.model_id, "cancel"))


@router.post("/models/delete", response_model=ApiResponse[ModelActionResponse])
def delete_model(body: ModelRequest) -> dict[str, object]:
    """删除位于受管理用户数据目录中的模型资源。"""
    if body.model_id == MINERU_PIPELINE_MODEL_ID:
        return success(data=delete_mineru_model())
    if body.model_id == "id-photo":
        status = id_photo_model_management.delete_id_photo_model()
        _get_id_photo_status()
        return success(data=status)
    raise ServiceException(ErrorCode.PARAM_ERROR, "不支持的模型")
