"""Markdown 转 PDF 接口：复用 DOCX 排版后由 LibreOffice 输出 PDF。"""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.schemas.response import ApiResponse, success
from app.modules.markdown_to_pdf.schemas import ConvertResponse, DownloadRequest
from app.modules.markdown_to_pdf import service as services_markdown_to_pdf

router = APIRouter(prefix="/tools/markdown-to-pdf", tags=["markdown-to-pdf"])


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
    result = services_markdown_to_pdf.convert_markdown_to_pdf(
        file,
        source_path,
        landscape=landscape,
        margin_mm=margin_mm,
        font_size=font_size,
        page_numbers=page_numbers,
    )
    return success(data=result)


@router.post("/download")
def download_pdf(body: DownloadRequest):
    """下载 Markdown 转换得到的 PDF。"""
    file_path, filename, media_type = services_markdown_to_pdf.download_pdf(body.task_id)
    return FileResponse(path=file_path, filename=filename, media_type=media_type)
