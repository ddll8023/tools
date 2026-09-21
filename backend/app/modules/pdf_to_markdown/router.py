"""PDF 转 Markdown 接口"""

import json
from urllib.parse import quote

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import FileResponse

from app.schemas.response import ApiResponse, success
from app.modules.pdf_to_markdown.schemas import (
    ConvertResponse,
    GetPreviewResponse,
    GetPreviewRequest,
    GetProgressResponse,
    GetProgressRequest,
    DownloadRequest,
)
from app.modules.pdf_to_markdown import deep_service as services_pdf_deep
from app.modules.pdf_to_markdown import service as services_pdf
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/tools/pdf-to-markdown", tags=["pdf-to-markdown"])


@router.post("/convert", response_model=ApiResponse[ConvertResponse])
def convert_pdf(
    file: UploadFile = File(...),
    deep_parse: bool = Form(False),
):
    """上传 PDF 并转换为 Markdown（deep_parse=true 时使用 MinerU 深度解析）"""
    logger.info(f"API 转换请求: file={file.filename} deep={deep_parse}")
    if deep_parse:
        result = services_pdf_deep.convert_pdf_deep(file)
    else:
        result = services_pdf.convert_pdf(file)
    return success(data=result)


@router.post("/progress", response_model=ApiResponse[GetProgressResponse])
def get_progress(body: GetProgressRequest):
    """查询深度解析进度"""
    logger.info(f"API 进度查询: task_id={body.task_id}")
    result = services_pdf_deep.get_progress_detail(body.task_id)
    return success(data=result)


@router.post("/preview", response_model=ApiResponse[GetPreviewResponse])
def get_preview(body: GetPreviewRequest):
    """获取 Markdown 预览内容"""
    logger.info(f"API 预览查询: task_id={body.task_id}")
    result = services_pdf.get_preview_detail(body.task_id)
    return success(data=result)


_MISSING_ASSETS_HEADER = "X-Missing-Assets"
_MISSING_ASSETS_NAMES_LIMIT = 10


@router.post("/download")
def download_md(body: DownloadRequest):
    """下载 Markdown；存在图片等引用资源时返回 ZIP 包（含当前编辑内容）"""
    logger.info(f"API 下载请求: task_id={body.task_id}")
    file_path, filename, media_type, missing = services_pdf.download_md(
        body.task_id, body.markdown_content
    )
    response = FileResponse(path=file_path, filename=filename, media_type=media_type)
    if missing:
        # 通过响应头告知前端解析结果中本就缺失、未打入 ZIP 的图片
        payload = {"total": len(missing), "names": missing[:_MISSING_ASSETS_NAMES_LIMIT]}
        response.headers[_MISSING_ASSETS_HEADER] = quote(
            json.dumps(payload, ensure_ascii=False)
        )
    return response
