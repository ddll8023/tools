"""二维码生成接口"""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from toolbox_backend.schemas.response import ApiResponse, success
from toolbox_backend.modules.qr_code.schemas import GenerateResponse
from toolbox_backend.modules.qr_code import service as qr_code_service
from toolbox_backend.core.logging import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/tools/qr-code", tags=["qr-code"])


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
    result = qr_code_service.generate_qr_code(content, file)
    return success(data=result)
