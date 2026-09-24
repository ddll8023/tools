"""编排证件照处理、重渲染和结果下载用例。"""

import os
import shutil
import time
import uuid

import cv2
from fastapi import UploadFile

from toolbox_backend.core.errors import ServiceException
from toolbox_backend.core.logging import setup_logger
from toolbox_backend.infrastructure.files import safe_filename
from toolbox_backend.infrastructure.task_storage.workspace import get_task_dir
from toolbox_backend.schemas.response import ErrorCode
from toolbox_backend.modules.id_photo.inference import (
    _detect_face,
    _limit_processing_size,
    _load_image,
    _matting,
)
from toolbox_backend.modules.id_photo.model_management import (
    _guard_model_use,
    get_model_status,
)
from toolbox_backend.modules.id_photo.rendering import _render_task
from toolbox_backend.modules.id_photo.schemas import IdPhotoResponse
from toolbox_backend.modules.id_photo.task_metadata import (
    _task_dir_checked,
    _write_json,
)
from toolbox_backend.modules.id_photo.templates import (
    STANDARD_QUALITY,
    _resolve_template,
    _validate_render_settings,
    list_templates,
)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_SIZE = 20 * 1024 * 1024

logger = setup_logger(__name__)


@_guard_model_use
def process_id_photo(
    file: UploadFile,
    template_id: str,
    width: int | None = None,
    height: int | None = None,
    background_color: str = "white",
    include_layout: bool = True,
    quality: int = STANDARD_QUALITY,
    dpi: int = 300,
    max_file_size_kb: int | None = None,
) -> IdPhotoResponse:
    """处理单张证件照。"""
    available, reason = get_model_status()
    if not available:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, reason)

    template = _resolve_template(template_id, width, height)
    _validate_render_settings(quality, dpi, max_file_size_kb)
    safe_name = safe_filename(file.filename, "photo.jpg")
    extension = os.path.splitext(safe_name)[1].lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ServiceException(
            ErrorCode.UNSUPPORTED_FILE_FORMAT,
            f"不支持的图片格式: {safe_name}",
        )

    content = file.file.read()
    if len(content) > MAX_FILE_SIZE:
        raise ServiceException(
            ErrorCode.FILE_TOO_LARGE,
            f"文件过大: {safe_name}（最大 20MB）",
        )

    image = _limit_processing_size(_load_image(content, safe_name))
    started_at = time.perf_counter()
    face = _detect_face(image)
    matting, model_name = _matting(image)

    task_id = uuid.uuid4().hex[:12]
    task_dir = get_task_dir(task_id)
    os.makedirs(task_dir, exist_ok=True)
    try:
        matting_path = os.path.join(task_dir, "matting.png")
        temp_matting_path = f"{matting_path}.tmp.png"
        if not cv2.imwrite(temp_matting_path, matting):
            raise ServiceException(ErrorCode.CONVERSION_FAILED, "人像中间结果写入失败")
        os.replace(temp_matting_path, matting_path)

        original_stem = os.path.splitext(safe_name)[0][:60] or "photo"
        _write_json(
            os.path.join(task_dir, "metadata.json"),
            {
                "task_id": task_id,
                "face": {
                    "x": face.x,
                    "y": face.y,
                    "width": face.width,
                    "height": face.height,
                    "landmarks": [
                        {"x": point_x, "y": point_y}
                        for point_x, point_y in face.landmarks
                    ],
                },
                "source_width": int(image.shape[1]),
                "source_height": int(image.shape[0]),
                "model": model_name,
                "original_stem": original_stem,
            },
        )

        result = _render_task(
            task_id,
            template,
            background_color,
            crop_scale=1.0,
            offset_x=0.0,
            offset_y=0.0,
            include_layout=include_layout,
            quality=quality,
            dpi=dpi,
            max_file_size_kb=max_file_size_kb,
        )
    except ServiceException:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "证件照处理失败，请重试") from exc

    elapsed = time.perf_counter() - started_at
    logger.info(
        "证件照处理完成: task_id=%s template=%s model=%s elapsed=%.2fs",
        task_id,
        template.template_id,
        model_name,
        elapsed,
    )
    return result


def render_id_photo(
    task_id: str,
    template_id: str,
    width: int | None,
    height: int | None,
    background_color: str,
    crop_scale: float,
    offset_x: float,
    offset_y: float,
    include_layout: bool,
    quality: int = STANDARD_QUALITY,
    dpi: int = 300,
    max_file_size_kb: int | None = None,
) -> IdPhotoResponse:
    """使用任务中的抠图中间结果按指定规格重新渲染证件照。"""
    template = _resolve_template(template_id, width, height)
    return _render_task(
        task_id,
        template,
        background_color,
        crop_scale,
        offset_x,
        offset_y,
        include_layout,
        quality,
        dpi,
        max_file_size_kb,
    )


def download_file(task_id: str, file_index: int) -> tuple[str, str]:
    """获取指定证件照结果文件。"""
    if not isinstance(file_index, int) or file_index < 0:
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = _task_dir_checked(task_id)
    prefix = f"{file_index}_"
    for name in os.listdir(task_dir):
        if not name.startswith(prefix) or not name.endswith(".jpg"):
            continue
        path = os.path.join(task_dir, name)
        if not os.path.isfile(path):
            continue
        display_name = name[len(prefix):]
        return path, display_name
    raise ServiceException(ErrorCode.DATA_NOT_FOUND, "文件不存在或已过期")
