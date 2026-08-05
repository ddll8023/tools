import os
import subprocess
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.v1.health import router as health_router
from app.api.v1.tools.list import router as tools_list_router
from app.api.v1.tools import pdf_to_markdown as router_pdf_to_markdown
from app.api.v1.tools import word_to_pdf as router_word_to_pdf
from app.api.v1.tools import image_converter as router_image_converter
from app.api.v1.tools import epub_to_markdown as router_epub_to_markdown
from app.api.v1.tools import pdf_to_word as router_pdf_to_word
from app.schemas.response import ErrorCode
from app.utils.logger_config import setup_logger
from app.utils.exception import ServiceException
from app.utils.temp_cleanup import cleanup_expired_temp
from app.services.tools.list import set_libreoffice_available
from app.core.config import settings

logger = setup_logger(__name__)


def check_libreoffice():
    """检测 LibreOffice 是否可用"""
    soffice_path = settings.libreoffice_path
    try:
        result = subprocess.run(
            [soffice_path, "--version"],
            check=True, capture_output=True, timeout=10,
        )
        version = result.stdout.decode().strip()
        logger.info(f"LibreOffice 检测成功: {version}")
        return True
    except FileNotFoundError:
        if soffice_path == "soffice":
            logger.warning("LibreOffice 未安装（soffice 不在 PATH 中）")
        else:
            logger.warning(f"LibreOffice 便携版未找到: {soffice_path}")
        return False
    except Exception as e:
        logger.warning(f"LibreOffice 检测失败: {e}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("启动清理过期临时文件...")
    cleanup_expired_temp()

    logger.info("检测 LibreOffice...")
    libreoffice_ok = check_libreoffice()
    set_libreoffice_available(libreoffice_ok)
    yield


app = FastAPI(title="工具盒子", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(health_router)
app.include_router(tools_list_router)
app.include_router(router_pdf_to_markdown.router)
app.include_router(router_word_to_pdf.router)
app.include_router(router_image_converter.router)
app.include_router(router_epub_to_markdown.router)
app.include_router(router_pdf_to_word.router)


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
