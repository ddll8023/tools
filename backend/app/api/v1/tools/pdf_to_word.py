"""PDF 转 Word 接口。"""

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse

from app.schemas.response import ApiResponse, error, success
from app.schemas.tools.pdf_to_word import ConvertResponse, DownloadRequest
from app.services.tools import pdf_to_word as services_pdf_to_word
from app.utils.exception import ServiceException
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/v1/tools/pdf-to-word", tags=["pdf-to-word"])


@router.post("/convert", response_model=ApiResponse[ConvertResponse])
def convert_pdf_to_word(file: UploadFile = File(...)):
    """上传 PDF 并转换为 Word。"""
    logger.info("API PDF 转 Word 请求: file=%s", file.filename)
    try:
        result = services_pdf_to_word.convert_pdf_to_word(file)
        return success(data=result)
    except ServiceException as exc:
        return error(code=exc.code, message=exc.message)


@router.post("/download")
def download_word(body: DownloadRequest):
    """下载 Word 文件。"""
    logger.info("API PDF 转 Word 下载请求: task_id=%s", body.task_id)
    try:
        file_path, filename = services_pdf_to_word.download_docx(body.task_id)
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type=services_pdf_to_word.DOCX_MEDIA_TYPE,
        )
    except ServiceException as exc:
        return error(code=exc.code, message=exc.message)
