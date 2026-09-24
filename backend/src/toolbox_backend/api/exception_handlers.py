"""注册 API 层统一业务异常和未知异常处理器。"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from toolbox_backend.core.errors import ServiceException
from toolbox_backend.schemas.response import ErrorCode
from toolbox_backend.core.logging import setup_logger

logger = setup_logger(__name__)


async def handle_service_exception(
    _request: Request,
    exc: ServiceException,
) -> JSONResponse:
    """将业务异常转换为项目约定的统一错误响应。"""
    return JSONResponse(
        status_code=200,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


async def handle_unexpected_exception(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    """记录未知异常并返回不泄露内部细节的错误响应。"""
    logger.error("全局异常: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=200,
        content={
            "code": ErrorCode.INTERNAL_ERROR,
            "message": "系统内部错误",
            "data": None,
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """为 FastAPI 应用注册统一异常处理器。"""
    app.add_exception_handler(ServiceException, handle_service_exception)
    app.add_exception_handler(Exception, handle_unexpected_exception)
