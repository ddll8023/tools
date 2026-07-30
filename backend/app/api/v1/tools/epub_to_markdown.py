"""EPUB 转 Markdown 接口。"""

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse

from app.schemas.response import ApiResponse, error, success
from app.schemas.tools.epub_to_markdown import (
    ConvertResponse,
    GetPreviewRequest,
    GetPreviewResponse,
)
from app.services.tools import epub_to_markdown as services_epub
from app.services.tools import epub_to_markdown_helpers as helpers_epub
from app.utils.exception import ServiceException
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/v1/tools/epub-to-markdown", tags=["epub-to-markdown"])


@router.post("/convert", response_model=ApiResponse[ConvertResponse])
def convert_epub(file: UploadFile = File(...)):
    try:
        return success(data=services_epub.convert_epub_file(file))
    except ServiceException as exc:
        return error(code=exc.code, message=exc.message)


@router.post("/preview", response_model=ApiResponse[GetPreviewResponse])
def preview_epub(body: GetPreviewRequest):
    try:
        return success(data=helpers_epub.get_preview_detail(body.task_id))
    except ServiceException as exc:
        return error(code=exc.code, message=exc.message)


@router.post("/download")
def download_epub(body: GetPreviewRequest):
    try:
        path, filename = services_epub.download_epub_markdown(body.task_id)
        return FileResponse(path=path, filename=filename, media_type="application/zip")
    except ServiceException as exc:
        return error(code=exc.code, message=exc.message)
