"""Markdown 转 Word 接口。"""

from typing import Annotated

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
    file: Annotated[UploadFile | None, File(description="Markdown 或资源 ZIP 文件")] = None,
    output_format: Annotated[str, Form(description="输出格式 docx 或 doc")] = "docx",
    source_path: Annotated[str | None, Form(description="桌面端本地 Markdown 绝对路径")] = None,
):
    """上传 Markdown/资源 ZIP，或按本地路径读取 Markdown 并转换为 Word。"""
    logger.info(
        "API Markdown 转 Word 请求: file=%s source_path=%s format=%s",
        file.filename if file is not None else None,
        source_path,
        output_format,
    )
    try:
        result = services_markdown_to_word.convert_markdown_to_word(file, output_format, source_path)
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
