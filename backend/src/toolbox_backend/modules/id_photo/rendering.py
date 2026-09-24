"""处理证件照裁切、换底、排版和结果文件渲染。"""

import os
import re
import threading

import cv2
import numpy as np
from PIL import Image

from toolbox_backend.core.errors import ServiceException
from toolbox_backend.infrastructure.files import safe_filename
from toolbox_backend.schemas.response import ErrorCode
from toolbox_backend.modules.id_photo.schemas import IdPhotoFileItem, IdPhotoResponse
from toolbox_backend.modules.id_photo.task_metadata import (
    _face_from_metadata,
    _read_metadata,
    _task_dir_checked,
)
from toolbox_backend.modules.id_photo.templates import (
    _calculate_crop,
    _resolve_background,
    _validate_render_settings,
)
from toolbox_backend.modules.id_photo.types import FaceDetection, TemplateConfig


LAYOUT_WIDTH = 1795


LAYOUT_HEIGHT = 1205


PHOTO_INTERVAL = 30


LAYOUT_SIDE_INTERVAL_W = 70


LAYOUT_SIDE_INTERVAL_H = 50


_RENDER_LOCK = threading.RLock()


def _find_head_top(image: np.ndarray, face: FaceDetection) -> int | None:
    """在脸部附近的 Alpha 轮廓中寻找头顶，过滤远离人物的遮罩噪点。"""
    alpha = image[:, :, 3]
    left = max(0, face.x - face.width // 2)
    right = min(image.shape[1], face.x + round(face.width * 1.5))
    bottom = min(image.shape[0], face.y + face.height)
    if left >= right or bottom <= 0:
        return None
    row_counts = np.count_nonzero(alpha[:bottom, left:right] >= 48, axis=1)
    minimum_width = max(2, round(face.width * 0.08))
    rows = np.where(row_counts >= minimum_width)[0]
    return int(rows[0]) if rows.size else None


def _crop_with_padding(image: np.ndarray, rect: tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = rect
    crop_width = max(1, x2 - x1)
    crop_height = max(1, y2 - y1)
    # 透明区域使用白色 RGB，避免缩放透明边缘产生黑色晕边。
    result = np.full((crop_height, crop_width, 4), 0, dtype=np.uint8)
    result[:, :, :3] = 255

    source_x1 = max(0, x1)
    source_y1 = max(0, y1)
    source_x2 = min(image.shape[1], x2)
    source_y2 = min(image.shape[0], y2)
    if source_x1 >= source_x2 or source_y1 >= source_y2:
        return result

    target_x1 = source_x1 - x1
    target_y1 = source_y1 - y1
    target_x2 = target_x1 + (source_x2 - source_x1)
    target_y2 = target_y1 + (source_y2 - source_y1)
    result[target_y1:target_y2, target_x1:target_x2] = image[
        source_y1:source_y2, source_x1:source_x2
    ]
    return result


def _resize_rgba_on_background(
    image: np.ndarray,
    size: tuple[int, int],
    background: tuple[int, int, int],
) -> np.ndarray:
    """使用预乘 Alpha 缩放并换底，避免透明像素颜色污染发丝边缘。"""
    if image.ndim != 3 or image.shape[2] != 4:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "人像中间结果格式异常")

    target_width, target_height = size
    source_height, source_width = image.shape[:2]
    interpolation = (
        cv2.INTER_AREA
        if target_width <= source_width and target_height <= source_height
        else cv2.INTER_CUBIC
    )
    alpha = image[:, :, 3].astype(np.float32) / 255.0
    premultiplied = image[:, :, :3].astype(np.float32) * alpha[:, :, None]
    resized_alpha = cv2.resize(
        alpha,
        (target_width, target_height),
        interpolation=interpolation,
    )
    resized_foreground = cv2.resize(
        premultiplied,
        (target_width, target_height),
        interpolation=interpolation,
    )
    resized_alpha = np.clip(resized_alpha, 0.0, 1.0)
    background_color = np.asarray(background, dtype=np.float32)
    result = resized_foreground + background_color * (1.0 - resized_alpha[:, :, None])
    return np.clip(np.rint(result), 0, 255).astype(np.uint8)


def _generate_layout(photo: np.ndarray) -> np.ndarray:
    canvas = np.full((LAYOUT_HEIGHT, LAYOUT_WIDTH, 3), 255, dtype=np.uint8)
    photo_height, photo_width = photo.shape[:2]
    limit_width = LAYOUT_WIDTH - 2 * LAYOUT_SIDE_INTERVAL_W
    limit_height = LAYOUT_HEIGHT - 2 * LAYOUT_SIDE_INTERVAL_H

    def fit_image(image: np.ndarray) -> np.ndarray:
        height, width = image.shape[:2]
        scale = min(1.0, limit_width / width, limit_height / height)
        if scale == 1.0:
            return image
        return cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )

    candidates: list[tuple[int, np.ndarray]] = []
    for rotate in (False, True):
        candidate = cv2.rotate(photo, cv2.ROTATE_90_CLOCKWISE) if rotate else photo
        candidate = fit_image(candidate)
        height, width = candidate.shape[:2]
        columns = max(1, (limit_width + PHOTO_INTERVAL) // (width + PHOTO_INTERVAL))
        rows = max(1, (limit_height + PHOTO_INTERVAL) // (height + PHOTO_INTERVAL))
        candidates.append((columns * rows, candidate))

    _, selected = max(candidates, key=lambda item: item[0])
    photo_height, photo_width = selected.shape[:2]
    columns = max(
        1,
        (limit_width + PHOTO_INTERVAL) // (photo_width + PHOTO_INTERVAL),
    )
    rows = max(
        1,
        (limit_height + PHOTO_INTERVAL) // (photo_height + PHOTO_INTERVAL),
    )
    block_width = columns * photo_width + (columns - 1) * PHOTO_INTERVAL
    block_height = rows * photo_height + (rows - 1) * PHOTO_INTERVAL
    start_x = (LAYOUT_WIDTH - block_width) // 2
    start_y = (LAYOUT_HEIGHT - block_height) // 2

    for row in range(rows):
        for column in range(columns):
            x = start_x + column * (photo_width + PHOTO_INTERVAL)
            y = start_y + row * (photo_height + PHOTO_INTERVAL)
            canvas[y:y + photo_height, x:x + photo_width] = selected
    return canvas


def _save_jpeg(
    image: np.ndarray,
    path: str,
    quality: int,
    dpi: int,
    max_file_size_kb: int | None,
) -> None:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(rgb)
    current_quality = max(30, min(100, quality))
    size_limit = max_file_size_kb * 1024 if max_file_size_kb else None
    try:
        while True:
            pil_image.save(
                path,
                format="JPEG",
                quality=current_quality,
                dpi=(dpi, dpi),
                optimize=True,
            )
            if size_limit is None or os.path.getsize(path) <= size_limit:
                return
            if current_quality <= 30:
                raise ServiceException(
                    ErrorCode.CONVERSION_FAILED,
                    f"无法将结果压缩到 {max_file_size_kb}KB 以内，请提高文件大小上限",
                )
            current_quality = max(30, current_quality - 5)
    finally:
        pil_image.close()


def _render_task(
    task_id: str,
    template: TemplateConfig,
    background_color: str,
    crop_scale: float,
    offset_x: float,
    offset_y: float,
    include_layout: bool,
    quality: int,
    dpi: int,
    max_file_size_kb: int | None,
) -> IdPhotoResponse:
    _validate_render_settings(quality, dpi, max_file_size_kb)
    task_dir = _task_dir_checked(task_id)
    metadata = _read_metadata(task_dir)

    try:
        face = _face_from_metadata(metadata)
        model_name = str(metadata["model"])
        original_stem = safe_filename(str(metadata.get("original_stem", "photo")), "photo")
    except (KeyError, TypeError, ValueError) as exc:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "任务元数据不存在或已损坏") from exc

    matting_path = os.path.join(task_dir, "matting.png")
    matting = cv2.imread(matting_path, cv2.IMREAD_UNCHANGED)
    if matting is None or matting.ndim != 3 or matting.shape[2] != 4:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "人像中间结果不存在或已损坏")

    background, background_key = _resolve_background(background_color)
    crop_rect = _calculate_crop(
        face,
        template,
        crop_scale,
        offset_x,
        offset_y,
        head_top=_find_head_top(matting, face),
    )
    cropped = _crop_with_padding(matting, crop_rect)
    standard = _resize_rgba_on_background(
        cropped,
        (template.width, template.height),
        background,
    )

    hd_scale = max(1.0, 600 / min(template.width, template.height))
    hd_size = (
        max(template.width, round(template.width * hd_scale)),
        max(template.height, round(template.height * hd_scale)),
    )
    # 高清照片直接从带 Alpha 的高分辨率裁切结果渲染，避免放大标准成片。
    hd = _resize_rgba_on_background(cropped, hd_size, background)
    layout = _generate_layout(standard) if include_layout else None

    template_key = (
        template.template_id
        if template.template_id != "custom"
        else f"custom-{template.width}x{template.height}"
    )
    base_name = f"{original_stem}_{template_key}_{background_key}"
    output_specs: list[tuple[int, str, str, np.ndarray]] = [
        (0, "standard", f"{base_name}.jpg", standard),
        (1, "hd", f"{base_name}_hd.jpg", hd),
    ]
    if layout is not None:
        output_specs.append((2, "layout", f"{base_name}_layout.jpg", layout))

    result_files: list[IdPhotoFileItem] = []
    with _RENDER_LOCK:
        prepared_files: list[tuple[int, str, str, str, str]] = []
        temp_paths: list[str] = []
        try:
            for index, kind, display_name, image in output_specs:
                internal_name = f"{index}_{display_name}"
                output_path = os.path.join(task_dir, internal_name)
                temp_path = f"{output_path}.tmp"
                temp_paths.append(temp_path)
                _save_jpeg(
                    image,
                    temp_path,
                    quality=quality,
                    dpi=dpi,
                    max_file_size_kb=max_file_size_kb,
                )
                prepared_files.append((index, kind, display_name, temp_path, output_path))

            for index, kind, display_name, temp_path, output_path in prepared_files:
                os.replace(temp_path, output_path)
                result_files.append(
                    IdPhotoFileItem(
                        kind=kind,
                        filename=display_name,
                        file_size=os.path.getsize(output_path),
                        index=index,
                    )
                )
        except ServiceException:
            for temp_path in temp_paths:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise
        except Exception as exc:
            for temp_path in temp_paths:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise ServiceException(ErrorCode.CONVERSION_FAILED, "证件照结果写入失败") from exc

        current_internal_names = {
            f"{index}_{display_name}" for index, _, display_name, _ in output_specs
        }
        for name in os.listdir(task_dir):
            if (
                name.endswith(".jpg")
                and re.match(r"^[012]_", name)
                and name not in current_internal_names
            ):
                try:
                    os.remove(os.path.join(task_dir, name))
                except OSError:
                    pass

    return IdPhotoResponse(
        task_id=task_id,
        template_id=template.template_id,
        template_name=template.name,
        width=template.width,
        height=template.height,
        background_color=background_color.strip().lower(),
        model=model_name,
        quality=quality,
        dpi=dpi,
        max_file_size_kb=max_file_size_kb,
        files=result_files,
    )
