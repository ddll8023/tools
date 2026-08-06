"""文本和文件二维码生成服务。"""

import base64
import json
import os
from io import BytesIO
from typing import Literal

from fastapi import UploadFile
from PIL import Image, ImageDraw
from reportlab.graphics.barcode import qrencoder

from app.schemas.response import ErrorCode
from app.schemas.tools.qr_code import GenerateResponse
from app.utils.exception import ServiceException
from app.utils.file import safe_filename
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

# 单个 QR Code 的内容容量有限，保留安全余量避免编码器在边界处溢出。
MAX_QR_PAYLOAD_BYTES = 2_500
MAX_FILE_SIZE = 1_500
QR_ERROR_CORRECTION_LEVEL = "L"
QR_SCALE = 8
QR_BORDER = 4


def _validate_payload(payload: str) -> int:
    """校验二维码内容并返回 UTF-8 字节数。"""
    payload_size = len(payload.encode("utf-8"))
    if payload_size == 0:
        raise ServiceException(ErrorCode.PARAM_ERROR, "二维码内容不能为空")
    if payload_size > MAX_QR_PAYLOAD_BYTES:
        raise ServiceException(
            ErrorCode.PARAM_ERROR,
            f"内容过长：单个二维码最多支持约 {MAX_QR_PAYLOAD_BYTES / 1000:.1f}KB 编码内容",
        )
    return payload_size


def _normalize_content_type(content_type: str | None) -> str:
    """规范化文件 MIME 类型，避免把过长或带参数的值写入二维码。"""
    normalized = (content_type or "application/octet-stream").split(";", 1)[0].strip()
    if not normalized or len(normalized) > 100:
        return "application/octet-stream"
    return normalized


def _build_file_payload(file: UploadFile, content: bytes) -> tuple[str, str]:
    """将文件包装为带文件名和 MIME 类型的可恢复 JSON 内容。"""
    filename = safe_filename(file.filename, "file")[:60]
    payload = json.dumps(
        {
            "type": "file",
            "name": filename,
            "mime": _normalize_content_type(file.content_type),
            "data": base64.b64encode(content).decode("ascii"),
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    output_stem = os.path.splitext(filename)[0][:60] or "文件"
    return payload, f"{output_stem}_二维码.png"


def _render_qr_png(payload: str) -> str:
    """使用 ReportLab QR 编码器生成 PNG Data URL。"""
    qr = qrencoder.QRCode(
        None,
        getattr(qrencoder.QRErrorCorrectLevel, QR_ERROR_CORRECTION_LEVEL),
    )
    qr.addData(payload)

    try:
        qr.make()
    except Exception as exc:
        # 不记录 payload，避免把用户文本或文件内容写入日志。
        logger.warning(
            "二维码矩阵生成失败: payload_size=%s error_type=%s",
            len(payload.encode("utf-8")),
            type(exc).__name__,
        )
        raise ServiceException(
            ErrorCode.PARAM_ERROR,
            "内容超过单个二维码容量，请减少内容后重试",
        ) from exc

    module_count = qr.getModuleCount()
    image_size = (module_count + QR_BORDER * 2) * QR_SCALE
    image = Image.new("RGB", (image_size, image_size), "white")
    draw = ImageDraw.Draw(image)

    for row_index, row in enumerate(qr.modules):
        for column_index, is_dark in enumerate(row):
            if not is_dark:
                continue
            left = (column_index + QR_BORDER) * QR_SCALE
            top = (row_index + QR_BORDER) * QR_SCALE
            right = left + QR_SCALE - 1
            bottom = top + QR_SCALE - 1
            draw.rectangle((left, top, right, bottom), fill="black")

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    image.close()
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def generate_qr_code(
    content: str | None = None,
    file: UploadFile | None = None,
) -> GenerateResponse:
    """生成文本或文件二维码。"""
    if (content is None) == (file is None):
        raise ServiceException(ErrorCode.PARAM_ERROR, "请提供文本或文件，且只能选择一种内容")

    source_type: Literal["text", "file"]
    if file is not None:
        raw_content = file.file.read(MAX_FILE_SIZE + 1)
        if len(raw_content) > MAX_FILE_SIZE:
            raise ServiceException(
                ErrorCode.FILE_TOO_LARGE,
                f"文件过大：单个文件最大 {MAX_FILE_SIZE / 1000:.1f}KB（受二维码容量限制）",
            )
        if not raw_content:
            raise ServiceException(ErrorCode.PARAM_ERROR, "不能将空文件转换为二维码")
        payload, filename = _build_file_payload(file, raw_content)
        source_type = "file"
    else:
        if content == "":
            raise ServiceException(ErrorCode.PARAM_ERROR, "文本内容不能为空")
        payload = content
        filename = "二维码.png"
        source_type = "text"

    payload_size = _validate_payload(payload)
    image_data_url = _render_qr_png(payload)
    logger.info(
        "二维码生成完成: source_type=%s payload_size=%s",
        source_type,
        payload_size,
    )
    return GenerateResponse(
        image_data_url=image_data_url,
        filename=filename,
        source_type=source_type,
        payload_size=payload_size,
    )
