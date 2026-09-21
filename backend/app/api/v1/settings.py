"""软件设置接口。"""

from fastapi import APIRouter

from app.core.errors import ServiceException
from app.schemas.response import ApiResponse, ErrorCode, success
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

router = APIRouter(prefix="/settings", tags=["settings"])


def _get_model_status(model_id: str) -> dict[str, object]:
    """校验模型标识并读取模型下载状态。"""
    if model_id != MINERU_PIPELINE_MODEL_ID:
        raise ServiceException(ErrorCode.PARAM_ERROR, "不支持的模型")
    return get_mineru_model_status()


def _action_model(model_id: str, action: str) -> dict[str, object]:
    """校验模型标识并执行下载或取消操作。"""
    if model_id != MINERU_PIPELINE_MODEL_ID:
        raise ServiceException(ErrorCode.PARAM_ERROR, "不支持的模型")
    if action == "download":
        return start_mineru_download()
    return cancel_mineru_download()


@router.post("/models/status", response_model=ApiResponse[ModelStatusResponse])
def get_models_status() -> dict[str, object]:
    """返回设置页可管理的本地模型状态。"""
    return success(data={"models": [get_mineru_model_status()]})


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
