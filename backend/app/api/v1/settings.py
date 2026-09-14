"""软件设置接口。"""

from fastapi import APIRouter

from app.schemas.response import ApiResponse, ErrorCode, error, success
from app.schemas.settings import (
    ModelActionResponse,
    ModelRequest,
    ModelStatusResponse,
)
from app.services.model_manager import (
    MINERU_PIPELINE_MODEL_ID,
    cancel_mineru_download,
    get_mineru_model_status,
    start_mineru_download,
)
from app.utils.exception import ServiceException

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


def _get_model_status(model_id: str) -> dict[str, object]:
    if model_id != MINERU_PIPELINE_MODEL_ID:
        raise ServiceException(ErrorCode.PARAM_ERROR, "不支持的模型")
    return get_mineru_model_status()


def _action_model(model_id: str, action: str) -> dict[str, object]:
    if model_id != MINERU_PIPELINE_MODEL_ID:
        raise ServiceException(ErrorCode.PARAM_ERROR, "不支持的模型")
    if action == "download":
        return start_mineru_download()
    return cancel_mineru_download()


@router.post("/models/status", response_model=ApiResponse[ModelStatusResponse])
def get_models_status():
    """返回设置页可管理的本地模型状态。"""
    try:
        return success(data={"models": [get_mineru_model_status()]})
    except ServiceException as exc:
        return error(code=exc.code, message=exc.message)


@router.post("/models/download", response_model=ApiResponse[ModelActionResponse])
def download_model(body: ModelRequest):
    """手动启动 MinerU 模型下载；重复请求会复用当前任务。"""
    try:
        return success(data=_action_model(body.model_id, "download"))
    except ServiceException as exc:
        return error(code=exc.code, message=exc.message)


@router.post("/models/progress", response_model=ApiResponse[ModelActionResponse])
def get_model_progress(body: ModelRequest):
    """查询模型下载任务状态。"""
    try:
        return success(data=_get_model_status(body.model_id))
    except ServiceException as exc:
        return error(code=exc.code, message=exc.message)


@router.post("/models/cancel", response_model=ApiResponse[ModelActionResponse])
def cancel_model_download(body: ModelRequest):
    """取消当前模型下载任务。"""
    try:
        return success(data=_action_model(body.model_id, "cancel"))
    except ServiceException as exc:
        return error(code=exc.code, message=exc.message)
