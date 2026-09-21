"""证件照工具接口"""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.schemas.response import ApiResponse, success
from app.schemas.tools.id_photo import (
    IdPhotoDownloadRequest,
    IdPhotoRenderRequest,
    IdPhotoResponse,
    IdPhotoTemplateItem,
)
from app.services.tools import id_photo as services_id_photo

router = APIRouter(prefix="/tools/id-photo", tags=["id-photo"])


@router.post("/templates", response_model=ApiResponse[list[IdPhotoTemplateItem]])
def list_id_photo_templates():
    """返回证件照预设规格。"""
    return success(data=services_id_photo.list_templates())


@router.post("/process", response_model=ApiResponse[IdPhotoResponse])
def process_id_photo(
    file: Annotated[UploadFile, File(..., description="单张人像照片")],
    template_id: Annotated[str, Form(..., description="证件照规格模板")],
    width: Annotated[int | None, Form(description="自定义宽度（像素）")] = None,
    height: Annotated[int | None, Form(description="自定义高度（像素）")] = None,
    background_color: Annotated[str, Form(description="背景色")] = "white",
    include_layout: Annotated[bool, Form(description="是否生成六寸排版照")] = True,
    quality: Annotated[int, Form(description="JPEG 初始质量")] = 95,
    dpi: Annotated[int, Form(description="输出 DPI")] = 300,
    max_file_size_kb: Annotated[int | None, Form(description="单个文件大小上限（KB）")] = None,
):
    """上传照片并生成证件照结果。"""
    result = services_id_photo.process_id_photo(
        file=file,
        template_id=template_id,
        width=width,
        height=height,
        background_color=background_color,
        include_layout=include_layout,
        quality=quality,
        dpi=dpi,
        max_file_size_kb=max_file_size_kb,
    )
    return success(data=result)


@router.post("/render", response_model=ApiResponse[IdPhotoResponse])
def render_id_photo(body: IdPhotoRenderRequest):
    """根据任务中的抠图结果重新渲染证件照。"""
    result = services_id_photo.render_id_photo(
        task_id=body.task_id,
        template_id=body.template_id.value,
        width=body.width,
        height=body.height,
        background_color=body.background_color,
        crop_scale=body.crop_scale,
        offset_x=body.offset_x,
        offset_y=body.offset_y,
        include_layout=body.include_layout,
        quality=body.quality,
        dpi=body.dpi,
        max_file_size_kb=body.max_file_size_kb,
    )
    return success(data=result)


@router.post("/download")
def download_id_photo(body: IdPhotoDownloadRequest):
    """下载证件照结果文件。"""
    file_path, filename = services_id_photo.download_file(
        body.task_id,
        body.file_index,
    )
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="image/jpeg",
    )
