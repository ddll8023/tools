"""EPUB 转 Markdown 接口。"""

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse

from app.schemas.response import ApiResponse, success
from app.schemas.tools.epub_to_markdown import (
    ConvertResponse,
    GetPreviewRequest,
    GetPreviewResponse,
)
from app.services.tools import epub_to_markdown as services_epub
from app.services.tools import epub_to_markdown_helpers as helpers_epub

router = APIRouter(prefix="/tools/epub-to-markdown", tags=["epub-to-markdown"])


@router.post("/convert", response_model=ApiResponse[ConvertResponse])
def convert_epub(file: UploadFile = File(...)):
    """上传并同步转换 EPUB。"""
    return success(data=services_epub.convert_epub_file(file))


@router.post("/preview", response_model=ApiResponse[GetPreviewResponse])
def preview_epub(body: GetPreviewRequest):
    """返回 EPUB 转换后的 Markdown 预览。"""
    return success(data=helpers_epub.get_preview_detail(body.task_id))


@router.post("/download")
def download_epub(body: GetPreviewRequest):
    """下载 Markdown 和图片资源 ZIP 包。"""
    path, filename = services_epub.download_epub_markdown(body.task_id)
    return FileResponse(path=path, filename=filename, media_type="application/zip")
