"""PDF 转 Markdown 接口"""

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import FileResponse

from app.schemas.response import success, error, ApiResponse
from app.schemas.tools.pdf_to_markdown import (
    ConvertResponse,
    GetPreviewResponse,
    GetPreviewRequest,
    GetProgressResponse,
    GetProgressRequest,
)
from app.services.tools import pdf_to_markdown as services_pdf
from app.services.tools import pdf_to_markdown_deep as services_pdf_deep
from app.utils.exception import ServiceException
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/v1/tools/pdf-to-markdown", tags=["pdf-to-markdown"])


@router.post("/convert", response_model=ApiResponse[ConvertResponse])
def convert_pdf(
    file: UploadFile = File(...),
    deep_parse: bool = Form(False),
):
    """上传 PDF 并转换为 Markdown（deep_parse=true 时使用 MinerU 深度解析）"""
    logger.info(f"API 转换请求: file={file.filename} deep={deep_parse}")
    try:
        if deep_parse:
            result = services_pdf_deep.convert_pdf_deep(file)
        else:
            result = services_pdf.convert_pdf(file)
        return success(data=result)
    except ServiceException as e:
        return error(code=e.code, message=e.message)


@router.post("/progress", response_model=ApiResponse[GetProgressResponse])
def get_progress(body: GetProgressRequest):
    """查询深度解析进度"""
    logger.info(f"API 进度查询: task_id={body.task_id}")
    try:
        result = services_pdf_deep.get_progress_detail(body.task_id)
        return success(data=result)
    except ServiceException as e:
        return error(code=e.code, message=e.message)


@router.post("/preview", response_model=ApiResponse[GetPreviewResponse])
def get_preview(body: GetPreviewRequest):
    """获取 Markdown 预览内容"""
    logger.info(f"API 预览查询: task_id={body.task_id}")
    try:
        result = services_pdf.get_preview_detail(body.task_id)
        return success(data=result)
    except ServiceException as e:
        return error(code=e.code, message=e.message)


@router.post("/download")
def download_md(body: GetPreviewRequest):
    """下载 Markdown 文件"""
    logger.info(f"API 下载请求: task_id={body.task_id}")
    try:
        file_path = services_pdf.download_md(body.task_id)
        return FileResponse(
            path=file_path,
            filename=f"{body.task_id}.md",
            media_type="text/markdown",
        )
    except ServiceException as e:
        return error(code=e.code, message=e.message)
