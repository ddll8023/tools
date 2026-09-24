"""Word 转 PDF 接口"""

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import FileResponse

from toolbox_backend.schemas.response import ApiResponse, success
from toolbox_backend.modules.word_to_pdf.schemas import (
    ConvertResponse,
    DownloadRequest,
)
from toolbox_backend.modules.word_to_pdf import service as services_word_to_pdf
from toolbox_backend.core.logging import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/tools/word-to-pdf", tags=["word-to-pdf"])


@router.post("/convert", response_model=ApiResponse[ConvertResponse])
def convert_word(
    file: UploadFile = File(...),
):
    """上传 Word 文档并转换为 PDF"""
    logger.info(f"API 转换请求: file={file.filename}")
    result = services_word_to_pdf.convert_word(file)
    return success(data=result)


@router.post("/download")
def download_pdf(body: DownloadRequest):
    """下载 PDF 文件"""
    logger.info(f"API 下载请求: task_id={body.task_id}")
    file_path, original_filename = services_word_to_pdf.download_pdf(body.task_id)
    return FileResponse(
        path=file_path,
        filename=original_filename,
        media_type="application/pdf",
    )
