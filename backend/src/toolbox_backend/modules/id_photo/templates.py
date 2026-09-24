"""维护证件照规格、背景和裁切参数规则。"""

import math
import re

from toolbox_backend.core.errors import ServiceException
from toolbox_backend.schemas.response import ErrorCode
from toolbox_backend.modules.id_photo.schemas import IdPhotoTemplateItem
from toolbox_backend.modules.id_photo.types import FaceDetection, TemplateConfig


MAX_OUTPUT_DIMENSION = 3000


MAX_OUTPUT_PIXEL_COUNT = 9_000_000


STANDARD_QUALITY = 95


BACKGROUND_PRESETS: dict[str, tuple[tuple[int, int, int], str]] = {
    # OpenCV uses BGR; labels and API values remain human-readable names.
    "white": ((255, 255, 255), "white"),
    "blue": ((219, 142, 67), "blue"),
    "red": ((27, 0, 217), "red"),
}


TEMPLATES: dict[str, TemplateConfig] = {
    "one-inch": TemplateConfig(
        "one-inch",
        "一寸",
        "一寸（25×35毫米）",
        295,
        413,
        25,
        35,
        "25×35 mm · 295×413 px",
    ),
    "small-two-inch": TemplateConfig(
        "small-two-inch",
        "小二寸",
        "小二寸（35×45毫米）",
        413,
        531,
        35,
        45,
        "35×45 mm · 413×531 px",
    ),
    "two-inch": TemplateConfig(
        "two-inch",
        "二寸",
        "二寸（35×49毫米）",
        413,
        579,
        35,
        49,
        "35×49 mm · 413×579 px",
    ),
}


def list_templates() -> list[IdPhotoTemplateItem]:
    """返回由后端统一维护的证件照规格。"""
    presets = [
        IdPhotoTemplateItem(
            id=template.template_id,
            label=template.label,
            description=template.description,
            width=template.width,
            height=template.height,
            width_mm=template.width_mm,
            height_mm=template.height_mm,
        )
        for template in TEMPLATES.values()
    ]
    presets.append(
        IdPhotoTemplateItem(
            id="custom",
            label="自定义",
            description="输入目标像素尺寸",
            is_custom=True,
        )
    )
    return presets


def _resolve_template(
    template_id: str,
    width: int | None,
    height: int | None,
) -> TemplateConfig:
    if template_id in TEMPLATES:
        return TEMPLATES[template_id]
    if template_id != "custom":
        raise ServiceException(ErrorCode.PARAM_ERROR, f"不支持的证件照规格: {template_id}")

    if width is None or height is None:
        raise ServiceException(ErrorCode.PARAM_ERROR, "自定义规格必须提供宽度和高度")
    if not isinstance(width, int) or not isinstance(height, int):
        raise ServiceException(ErrorCode.PARAM_ERROR, "自定义规格必须为整数像素")
    if not (80 <= width <= MAX_OUTPUT_DIMENSION and 80 <= height <= MAX_OUTPUT_DIMENSION):
        raise ServiceException(
            ErrorCode.PARAM_ERROR,
            f"自定义规格必须在 80～{MAX_OUTPUT_DIMENSION} 像素范围内",
        )
    if width >= height or width * height > MAX_OUTPUT_PIXEL_COUNT:
        raise ServiceException(ErrorCode.PARAM_ERROR, "自定义证件照应为纵向且分辨率不能过高")
    return TemplateConfig(
        template_id="custom",
        label="自定义",
        name=f"自定义（{width}×{height}像素）",
        width=width,
        height=height,
        width_mm=None,
        height_mm=None,
        description=f"{width}×{height} px",
    )


def _resolve_background(value: str) -> tuple[tuple[int, int, int], str]:
    normalized = (value or "white").strip().lower()
    if normalized in BACKGROUND_PRESETS:
        return BACKGROUND_PRESETS[normalized]

    if not re.fullmatch(r"#[0-9a-f]{6}", normalized):
        raise ServiceException(
            ErrorCode.PARAM_ERROR,
            "背景色必须选择白、蓝、红，或使用 #RRGGBB 格式",
        )
    red = int(normalized[1:3], 16)
    green = int(normalized[3:5], 16)
    blue = int(normalized[5:7], 16)
    return (blue, green, red), f"custom-{normalized[1:]}"


def _validate_render_settings(
    quality: int,
    dpi: int,
    max_file_size_kb: int | None,
) -> None:
    if not isinstance(quality, int) or not 60 <= quality <= 100:
        raise ServiceException(ErrorCode.PARAM_ERROR, "JPEG 质量必须在 60～100 之间")
    if not isinstance(dpi, int) or not 72 <= dpi <= 600:
        raise ServiceException(ErrorCode.PARAM_ERROR, "DPI 必须在 72～600 之间")
    if max_file_size_kb is not None and not 10 <= max_file_size_kb <= 2048:
        raise ServiceException(ErrorCode.PARAM_ERROR, "文件大小上限必须在 10～2048KB 之间")


def _calculate_crop(
    face: FaceDetection,
    template: TemplateConfig,
    crop_scale: float,
    offset_x: float,
    offset_y: float,
    head_top: int | None = None,
) -> tuple[int, int, int, int]:
    if not 0.85 <= crop_scale <= 1.25:
        raise ServiceException(ErrorCode.PARAM_ERROR, "裁切范围必须在 0.85～1.25 之间")
    if not -0.15 <= offset_x <= 0.15 or not -0.15 <= offset_y <= 0.15:
        raise ServiceException(ErrorCode.PARAM_ERROR, "裁切偏移必须在 -0.15～0.15 之间")

    face_area = max(1, face.width * face.height)
    crop_area = face_area / template.face_area_ratio * (crop_scale**2)
    crop_height = max(
        1,
        round(math.sqrt(crop_area * template.height / template.width)),
    )
    crop_width = max(1, round(crop_height * template.width / template.height))

    if len(face.landmarks) >= 2:
        left_eye, right_eye = face.landmarks[:2]
        anchor_x = (left_eye[0] + right_eye[0]) / 2
        eye_y = (left_eye[1] + right_eye[1]) / 2
    else:
        anchor_x = face.x + face.width / 2
        eye_y = face.y + face.height * 0.35

    crop_left = round(anchor_x - crop_width / 2 + offset_x * crop_width)
    base_top = eye_y - crop_height * template.eye_line_ratio
    if head_top is not None:
        head_margin = max(2, round(crop_height * 0.035))
        base_top = min(base_top, head_top - head_margin)
    crop_top = round(base_top + offset_y * crop_height)
    return crop_left, crop_top, crop_left + crop_width, crop_top + crop_height
