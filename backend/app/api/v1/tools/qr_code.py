"""二维码生成接口"""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from app.schemas.response import ApiResponse, error, success
from app.schemas.tools.qr_code import GenerateResponse
from app.services.tools import qr_code as qr_code_service
from app.utils.exception import ServiceException
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/v1/tools/qr-code", tags=["qr-code"])


@router.post("/generate", response_model=ApiResponse[GenerateResponse])
def generate_qr_code(
    content: Annotated[str | None, Form(description="要编码的文本内容")] = None,
    file: Annotated[UploadFile | None, File(description="要编码的文件")] = None,
):
    """生成文本或文件二维码。"""
    logger.info(
        "API 二维码生成请求: source_type=%s file_name=%s",
        "file" if file is not None else "text",
        file.filename if file is not None else None,
    )
    try:
        result = qr_code_service.generate_qr_code(content, file)
        return success(data=result)
    except ServiceException as exc:
        return error(code=exc.code, message=exc.message)
