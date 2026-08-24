"""Markdown 转 Word 接口。"""

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.schemas.response import ApiResponse, error, success
from app.schemas.tools.markdown_to_word import ConvertResponse, DownloadRequest
from app.services.tools import markdown_to_word as services_markdown_to_word
from app.utils.exception import ServiceException
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/v1/tools/markdown-to-word", tags=["markdown-to-word"])


@router.post("/convert", response_model=ApiResponse[ConvertResponse])
def convert_markdown_to_word(
    file: UploadFile = File(...),
    output_format: str = Form("docx"),
):
    """上传 Markdown 或资源 ZIP 并转换为 Word。"""
    logger.info(
        "API Markdown 转 Word 请求: file=%s format=%s",
        file.filename,
        output_format,
    )
    try:
        result = services_markdown_to_word.convert_markdown_to_word(file, output_format)
        return success(data=result)
    except ServiceException as exc:
        return error(code=exc.code, message=exc.message)


@router.post("/download")
def download_word(body: DownloadRequest):
    """下载 Markdown 转换结果。"""
    logger.info("API Markdown 转 Word 下载请求: task_id=%s", body.task_id)
    try:
        file_path, filename, media_type = services_markdown_to_word.download_word(body.task_id)
        return FileResponse(path=file_path, filename=filename, media_type=media_type)
    except ServiceException as exc:
        return error(code=exc.code, message=exc.message)
