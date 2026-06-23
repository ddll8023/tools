"""PDF 转 Markdown 接口"""
import os
import tempfile
import re
from pathlib import Path

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse

from app.schemas.response import success, error, ApiResponse, ErrorCode
from app.schemas.tools.pdf_to_markdown import ConvertResponse, GetPreviewResponse, GetPreviewRequest
from app.services.tools import pdf_to_markdown as services_pdf
from app.utils.exception import ServiceException

router = APIRouter(prefix="/api/v1/tools/pdf-to-markdown", tags=["pdf-to-markdown"])

TEMP_ROOT = Path(__file__).resolve().parents[4] / "temp"


def _validate_task_id(task_id: str) -> bool:
    """校验 task_id 仅含合法字符"""
    return bool(re.match(r'^[a-f0-9]{12}$', task_id))


@router.post("/convert", response_model=ApiResponse[ConvertResponse])
def convert_pdf(file: UploadFile = File(...)):
    """上传 PDF 并转换为 Markdown"""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return error(code=ErrorCode.UNSUPPORTED_FILE_FORMAT, message="不支持的文件格式")

    if file.size and file.size > 50 * 1024 * 1024:
        return error(code=ErrorCode.FILE_TOO_LARGE, message="文件大小不能超过 50MB")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = file.file.read()
            tmp.write(content)
            tmp_path = tmp.name

        result = services_pdf.convert_pdf(tmp_path, file.filename)
        return success(data=result)
    except ServiceException as e:
        return error(code=e.code, message=e.message)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.post("/preview", response_model=ApiResponse[GetPreviewResponse])
def get_preview(body: GetPreviewRequest):
    """获取 Markdown 预览内容"""
    try:
        result = services_pdf.get_preview_detail(body.task_id)
        return success(data=result)
    except ServiceException as e:
        return error(code=e.code, message=e.message)


@router.post("/download")
def download_md(body: GetPreviewRequest):
    """下载 Markdown 文件"""
    task_id = body.task_id
    if not _validate_task_id(task_id):
        return JSONResponse(
            status_code=200,
            content={"code": ErrorCode.PARAM_ERROR, "message": "参数错误", "data": None},
        )

    resolved = (TEMP_ROOT / task_id / "output.md").resolve()
    if not str(resolved).startswith(str(TEMP_ROOT.resolve())):
        return JSONResponse(
            status_code=200,
            content={"code": ErrorCode.PARAM_ERROR, "message": "参数错误", "data": None},
        )

    if not resolved.exists():
        return JSONResponse(
            status_code=200,
            content={"code": ErrorCode.DATA_NOT_FOUND, "message": "文件不存在", "data": None},
        )

    return FileResponse(
        path=str(resolved),
        filename=f"{task_id}.md",
        media_type="text/markdown",
    )
