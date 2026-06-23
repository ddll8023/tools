from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.v1.health import router as health_router
from app.api.v1.tools.list import router as tools_list_router
from app.api.v1.tools import pdf_to_markdown as router_pdf_to_markdown
from app.schemas.response import ErrorCode
from app.utils.logger_config import setup_logger
from app.utils.exception import ServiceException
from app.services.tools.pdf_to_markdown_helpers import cleanup_expired_temp

logger = setup_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("启动清理过期临时文件...")
    cleanup_expired_temp()
    yield


app = FastAPI(title="工具盒子", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(tools_list_router)
app.include_router(router_pdf_to_markdown.router)


@app.exception_handler(ServiceException)
async def service_exception_handler(request: Request, exc: ServiceException):
    return JSONResponse(
        status_code=200,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"全局异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=200,
        content={"code": ErrorCode.INTERNAL_ERROR, "message": "系统内部错误", "data": None},
    )
