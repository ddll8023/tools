"""Markdown 转 PDF 接口：复用 DOCX 排版后由 LibreOffice 输出 PDF。"""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.schemas.response import ApiResponse, error, success
from app.schemas.tools.markdown_to_pdf import ConvertResponse, DownloadRequest
from app.services.tools import markdown_to_pdf as services_markdown_to_pdf
from app.utils.exception import ServiceException

router = APIRouter(prefix="/api/v1/tools/markdown-to-pdf", tags=["markdown-to-pdf"])


@router.post("/convert", response_model=ApiResponse[ConvertResponse])
def convert_markdown_to_pdf(
    file: Annotated[UploadFile | None, File(description="Markdown 或资源 ZIP 文件")] = None,
    source_path: Annotated[str | None, Form(description="桌面端本地 Markdown 路径")] = None,
    landscape: Annotated[bool, Form(description="是否横向排版")] = False,
    margin_mm: Annotated[int, Form(description="页边距，单位 mm")] = 18,
    font_size: Annotated[int, Form(description="正文字号，单位 pt")] = 11,
    page_numbers: Annotated[bool, Form(description="是否显示页码")] = True,
) -> dict:
    """将 Markdown 或资源 ZIP 转换为 PDF。"""
    try:
        result = services_markdown_to_pdf.convert_markdown_to_pdf(
            file,
            source_path,
            landscape=landscape,
            margin_mm=margin_mm,
            font_size=font_size,
            page_numbers=page_numbers,
        )
        return success(data=result)
    except ServiceException as exc:
        return error(code=exc.code, message=exc.message)


@router.post("/download")
def download_pdf(body: DownloadRequest):
    """下载 Markdown 转换得到的 PDF。"""
    try:
        file_path, filename, media_type = services_markdown_to_pdf.download_pdf(body.task_id)
        return FileResponse(path=file_path, filename=filename, media_type=media_type)
    except ServiceException as exc:
        return error(code=exc.code, message=exc.message)
