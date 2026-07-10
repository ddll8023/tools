"""图片格式转换接口"""

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import FileResponse
from typing import Annotated

from app.schemas.response import success, error, ApiResponse
from app.schemas.tools.image_converter import (
    ConvertResponse,
    DownloadRequest,
    DownloadAllRequest,
)
from app.services.tools import image_converter as services_image_converter
from app.utils.exception import ServiceException
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/v1/tools/image-converter", tags=["image-converter"])


@router.post("/convert", response_model=ApiResponse[ConvertResponse])
def convert_images(
    files: Annotated[list[UploadFile], File(..., description="图片文件（支持多文件）")],
    target_format: Annotated[str, Form(..., description="目标格式: png/jpeg/webp/bmp/gif/tiff")],
    quality: Annotated[int, Form()] = 85,
):
    """上传图片并转换格式"""
    logger.info(f"API 转换请求: files={[f.filename for f in files]} target={target_format}")
    try:
        result = services_image_converter.convert_images(files, target_format, quality)
        return success(data=result)
    except ServiceException as e:
        return error(code=e.code, message=e.message)


@router.post("/download")
def download_image(body: DownloadRequest):
    """下载转换后的单张图片"""
    logger.info(f"API 下载请求: task_id={body.task_id} file_index={body.file_index}")
    try:
        file_path, original_filename = services_image_converter.download_file(
            body.task_id, body.file_index,
        )

        ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else "png"
        media_type_map = {
            "png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg",
            "webp": "image/webp", "bmp": "image/bmp", "gif": "image/gif",
            "tiff": "image/tiff", "tif": "image/tiff",
        }
        media_type = media_type_map.get(ext, "application/octet-stream")

        return FileResponse(
            path=file_path,
            filename=original_filename,
            media_type=media_type,
        )
    except ServiceException as e:
        return error(code=e.code, message=e.message)


@router.post("/download-all")
def download_all(body: DownloadAllRequest):
    """以 ZIP 包下载所有转换后的文件"""
    logger.info(f"API 批量下载请求: task_id={body.task_id}")
    try:
        file_path, zip_filename = services_image_converter.download_file(body.task_id)
        return FileResponse(
            path=file_path,
            filename=zip_filename,
            media_type="application/zip",
        )
    except ServiceException as e:
        return error(code=e.code, message=e.message)
