"""证件照处理服务。

处理链路参考 HivisionIDPhotos：本地人脸检测、人像抠图、规格裁切、换底和排版。
用户照片只在本地临时任务目录中流转，模型资源从项目 resources 目录读取。
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import threading
import time
import uuid
from io import BytesIO
from typing import NamedTuple

import cv2
import numpy as np
from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings
from app.schemas.response import ErrorCode
from app.schemas.tools.id_photo import IdPhotoFileItem, IdPhotoResponse
from app.utils.exception import ServiceException
from app.utils.file import safe_filename
from app.utils.logger_config import setup_logger
from app.utils.temp_cleanup import TEMP_DIR, get_task_dir, validate_task_id

logger = setup_logger(__name__)

MAX_FILE_SIZE = 20 * 1024 * 1024
MAX_PIXEL_COUNT = 40_000_000
MAX_PROCESSING_EDGE = 2000
MAX_OUTPUT_DIMENSION = 3000
MAX_OUTPUT_PIXEL_COUNT = 9_000_000

STANDARD_QUALITY = 95
LAYOUT_WIDTH = 1795
LAYOUT_HEIGHT = 1205
PHOTO_INTERVAL = 30
LAYOUT_SIDE_INTERVAL_W = 70
LAYOUT_SIDE_INTERVAL_H = 50

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MATTE_MODEL_CANDIDATES = (
    "hivision_modnet.onnx",
    "modnet_photographic_portrait_matting.onnx",
)
MTCNN_WEIGHT_NAMES = ("pnet.onnx", "rnet.onnx", "onet.onnx")

BACKGROUND_PRESETS: dict[str, tuple[tuple[int, int, int], str]] = {
    # OpenCV uses BGR; labels and API values remain human-readable names.
    "white": ((255, 255, 255), "white"),
    "blue": ((219, 142, 67), "blue"),
    "red": ((27, 0, 217), "red"),
}


class TemplateConfig(NamedTuple):
    template_id: str
    name: str
    width: int
    height: int


TEMPLATES: dict[str, TemplateConfig] = {
    "one-inch": TemplateConfig("one-inch", "一寸（25×35毫米）", 295, 413),
    "small-two-inch": TemplateConfig("small-two-inch", "小二寸（35×45毫米）", 413, 531),
    "two-inch": TemplateConfig("two-inch", "二寸（35×49毫米）", 413, 579),
}

_MATTE_SESSION = None
_MATTE_SESSION_PATH: str | None = None
_MATTE_LOCK = threading.Lock()
_MTCNN_INSTANCE = None
_MTCNN_LOCK = threading.Lock()
_RENDER_LOCK = threading.RLock()


def _model_directory() -> str:
    return os.path.abspath(settings.id_photo_model_path)


def _find_matte_model() -> str | None:
    model_dir = _model_directory()
    for filename in MATTE_MODEL_CANDIDATES:
        path = os.path.join(model_dir, filename)
        if os.path.isfile(path):
            return path
    return None


def _mtcnn_weight_paths() -> dict[str, str]:
    model_dir = os.path.join(_model_directory(), "mtcnn")
    return {
        name: os.path.join(model_dir, name)
        for name in MTCNN_WEIGHT_NAMES
    }


def get_model_status() -> tuple[bool, str]:
    """检查证件照所需依赖和项目内模型资源是否可用。"""
    matte_model = _find_matte_model()
    if matte_model is None:
        names = "、".join(MATTE_MODEL_CANDIDATES)
        return False, f"缺少人像抠图模型，请准备项目 resources/id_photo 目录中的模型（需要 {names}）"

    missing_mtcnn = [
        path for path in _mtcnn_weight_paths().values() if not os.path.isfile(path)
    ]
    if missing_mtcnn:
        return False, "缺少 MTCNN 模型文件，请准备项目 resources/id_photo/mtcnn 目录中的 pnet.onnx、rnet.onnx、onet.onnx"

    try:
        import mtcnnruntime  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError as exc:
        return False, f"证件照运行依赖不可用: {exc.name or 'onnxruntime/mtcnn-runtime'}"

    return True, ""


def _get_matting_session(model_path: str):
    global _MATTE_SESSION, _MATTE_SESSION_PATH

    with _MATTE_LOCK:
        if _MATTE_SESSION is None or _MATTE_SESSION_PATH != model_path:
            try:
                import onnxruntime

                _MATTE_SESSION = onnxruntime.InferenceSession(
                    model_path,
                    providers=["CPUExecutionProvider"],
                )
                _MATTE_SESSION_PATH = model_path
            except Exception as exc:
                raise ServiceException(
                    ErrorCode.AI_SERVICE_ERROR,
                    "人像抠图模型加载失败，请检查本地模型文件",
                ) from exc
        return _MATTE_SESSION


def _get_mtcnn():
    """初始化 MTCNN，并把其权重路径重定向到项目 resources 目录。"""
    global _MTCNN_INSTANCE

    with _MTCNN_LOCK:
        if _MTCNN_INSTANCE is not None:
            return _MTCNN_INSTANCE

        try:
            from mtcnnruntime import MTCNN

            paths = _mtcnn_weight_paths()
            # mtcnn-runtime 1.0.0 的权重路径是类私有属性；在不修改第三方包的
            # 前提下将它指向项目内资源，避免运行时使用用户目录或包外缓存。
            setattr(MTCNN, "_MTCNN__BASE_DIR", os.path.dirname(paths["pnet.onnx"]))
            setattr(MTCNN, "_MTCNN__PNET", paths["pnet.onnx"])
            setattr(MTCNN, "_MTCNN__RNET", paths["rnet.onnx"])
            setattr(MTCNN, "_MTCNN__ONET", paths["onet.onnx"])
            _MTCNN_INSTANCE = MTCNN()
            return _MTCNN_INSTANCE
        except ServiceException:
            raise
        except Exception as exc:
            raise ServiceException(
                ErrorCode.AI_SERVICE_ERROR,
                "MTCNN 人脸检测模型加载失败，请检查项目内模型文件",
            ) from exc


def _check_pixel_limit(width: int, height: int, filename: str) -> None:
    if width <= 0 or height <= 0 or width * height > MAX_PIXEL_COUNT:
        raise ServiceException(
            ErrorCode.PARAM_ERROR,
            f"图片分辨率过高或无效: {filename}（最大 {MAX_PIXEL_COUNT // 10_000_000}000 万像素）",
        )


def _load_image(content: bytes, filename: str) -> np.ndarray:
    if not content:
        raise ServiceException(ErrorCode.PARAM_ERROR, "上传文件为空")

    try:
        with Image.open(BytesIO(content)) as source:
            _check_pixel_limit(source.width, source.height, filename)
            oriented = ImageOps.exif_transpose(source)
            if oriented.mode in ("RGBA", "LA"):
                rgba = oriented.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel("A"))
                rgb = background
            else:
                rgb = oriented.convert("RGB")
            array = np.asarray(rgb)
            image = cv2.cvtColor(array, cv2.COLOR_RGB2BGR)
            if rgb is not oriented:
                rgb.close()
            if oriented is not source and oriented is not rgb:
                oriented.close()
            return image.copy()
    except UnidentifiedImageError as exc:
        raise ServiceException(
            ErrorCode.UNSUPPORTED_FILE_FORMAT,
            f"无法识别的图片文件: {filename}",
        ) from exc
    except ServiceException:
        raise
    except Exception as exc:
        raise ServiceException(
            ErrorCode.UNSUPPORTED_FILE_FORMAT,
            f"无法读取图片文件: {filename}",
        ) from exc


def _limit_processing_size(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    max_edge = max(height, width)
    if max_edge <= MAX_PROCESSING_EDGE:
        return image

    scale = MAX_PROCESSING_EDGE / max_edge
    return cv2.resize(
        image,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def _detect_face(image: np.ndarray) -> tuple[int, int, int, int]:
    detector = _get_mtcnn()
    height, width = image.shape[:2]

    def detect(target: np.ndarray):
        try:
            return detector.detect(
                target,
                min_face_size=20.0,
                thresholds=[0.8, 0.8, 0.8],
                nms_thresholds=[0.6, 0.7, 0.8],
            )
        except ValueError:
            # mtcnn-runtime 在 P-Net 没有候选框时会抛出空数组拼接异常，按未检测到人脸处理。
            return np.empty((0, 5), dtype=np.float32), np.empty((0, 10), dtype=np.float32)
        except Exception as exc:
            raise ServiceException(
                ErrorCode.AI_SERVICE_ERROR,
                "MTCNN 人脸检测推理失败，请检查本地模型文件",
            ) from exc

    scale = 2 if min(height, width) >= 240 else 1
    if scale > 1:
        target = cv2.resize(
            image,
            (max(1, width // scale), max(1, height // scale)),
            interpolation=cv2.INTER_AREA,
        )
        boxes, _ = detect(target)
        if len(boxes) == 1:
            boxes = np.asarray(boxes, dtype=np.float32) * scale
        else:
            boxes, _ = detect(image)
    else:
        boxes, _ = detect(image)

    if len(boxes) != 1:
        raise ServiceException(
            ErrorCode.UNSUPPORTED_CONTENT,
            f"需要包含且只能包含一张主要人脸，当前检测到 {len(boxes)} 张",
        )

    x1, y1, x2, y2 = [float(value) for value in boxes[0][:4]]
    x1 = max(0.0, min(x1, width - 1))
    y1 = max(0.0, min(y1, height - 1))
    x2 = max(x1 + 1.0, min(x2, width))
    y2 = max(y1 + 1.0, min(y2, height))
    face_width = max(1, round(x2 - x1))
    face_height = max(1, round(y2 - y1))
    return round(x1), round(y1), face_width, face_height


def _matting(image: np.ndarray) -> tuple[np.ndarray, str]:
    model_path = _find_matte_model()
    if model_path is None:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "缺少人像抠图模型")

    session = _get_matting_session(model_path)
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    model_image = cv2.resize(image, (512, 512), interpolation=cv2.INTER_AREA)
    model_image = model_image.astype(np.float32) / 255.0
    model_image = (model_image - 0.5) / 0.5
    model_image = np.transpose(model_image, (2, 0, 1))[None, ...].astype(np.float32)

    try:
        matte = session.run([output_name], {input_name: model_image})[0]
    except Exception as exc:
        raise ServiceException(
            ErrorCode.AI_SERVICE_ERROR,
            "人像抠图推理失败，请检查模型文件或重试",
        ) from exc

    matte = np.squeeze(matte)
    if matte.ndim != 2:
        raise ServiceException(ErrorCode.AI_SERVICE_ERROR, "人像抠图模型输出格式异常")
    matte = np.nan_to_num(matte, nan=0.0, posinf=1.0, neginf=0.0)
    matte_min = float(matte.min())
    matte_max = float(matte.max())
    if matte_min < 0.0 or matte_max > 1.0:
        if matte_max <= 255.0 and matte_min >= 0.0:
            matte = matte / 255.0
        elif matte_max > matte_min:
            matte = (matte - matte_min) / (matte_max - matte_min)
    matte = np.clip(matte, 0.0, 1.0)
    alpha = cv2.resize(
        (matte * 255.0).astype(np.uint8),
        (image.shape[1], image.shape[0]),
        interpolation=cv2.INTER_AREA,
    )
    b, g, r = cv2.split(image)
    return cv2.merge((b, g, r, alpha)), os.path.basename(model_path)


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
    return TemplateConfig("custom", f"自定义（{width}×{height}像素）", width, height)


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
    face: tuple[int, int, int, int],
    template: TemplateConfig,
    crop_scale: float,
    offset_x: float,
    offset_y: float,
) -> tuple[int, int, int, int]:
    if not 0.85 <= crop_scale <= 1.25:
        raise ServiceException(ErrorCode.PARAM_ERROR, "裁切范围必须在 0.85～1.25 之间")
    if not -0.15 <= offset_x <= 0.15 or not -0.15 <= offset_y <= 0.15:
        raise ServiceException(ErrorCode.PARAM_ERROR, "裁切偏移必须在 -0.15～0.15 之间")

    x, y, face_width, face_height = face
    face_area = max(1, face_width * face_height)
    # 人脸约占最终裁切区域面积的 20%，与 Hivision 的默认参数保持一致。
    crop_area = face_area / 0.20 * (crop_scale**2)
    crop_height = max(
        1,
        round(math.sqrt(crop_area * template.height / template.width)),
    )
    crop_width = max(1, round(crop_height * template.width / template.height))

    face_center_x = x + face_width / 2
    face_center_y = y + face_height / 2
    crop_left = round(face_center_x - crop_width / 2 + offset_x * crop_width)
    crop_top = round(
        face_center_y - crop_height * 0.45 + offset_y * crop_height
    )
    return crop_left, crop_top, crop_left + crop_width, crop_top + crop_height


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


def _compose_background(
    image: np.ndarray,
    background: tuple[int, int, int],
) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] != 4:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "人像中间结果格式异常")

    alpha = image[:, :, 3].astype(np.float32) / 255.0
    background_image = np.empty(image.shape[:2] + (3,), dtype=np.uint8)
    background_image[:, :] = background
    foreground = image[:, :, :3].astype(np.float32)
    background_float = background_image.astype(np.float32)
    result = foreground * alpha[:, :, None] + background_float * (1.0 - alpha[:, :, None])
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


def _task_dir_checked(task_id: str) -> str:
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = os.path.abspath(get_task_dir(task_id))
    temp_root = os.path.abspath(TEMP_DIR)
    try:
        if os.path.commonpath([temp_root, task_dir]) != temp_root:
            raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")
    except ValueError as exc:
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误") from exc

    if not os.path.isdir(task_dir):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "文件不存在或已过期")
    return task_dir


def _read_metadata(task_dir: str) -> dict:
    metadata_path = os.path.join(task_dir, "metadata.json")
    try:
        with open(metadata_path, "r", encoding="utf-8") as file:
            metadata = json.load(file)
    except (OSError, ValueError) as exc:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "任务数据不存在或已损坏") from exc
    if not isinstance(metadata, dict):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "任务数据不存在或已损坏")
    return metadata


def _write_json(path: str, data: dict) -> None:
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, separators=(",", ":"))
    os.replace(temp_path, path)


def _render_task(
    task_id: str,
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
        template = TemplateConfig(
            str(metadata["template_id"]),
            str(metadata["template_name"]),
            int(metadata["width"]),
            int(metadata["height"]),
        )
        face_data = metadata["face"]
        face = (
            int(face_data["x"]),
            int(face_data["y"]),
            int(face_data["width"]),
            int(face_data["height"]),
        )
        model_name = str(metadata["model"])
        original_stem = safe_filename(str(metadata.get("original_stem", "photo")), "photo")
    except (KeyError, TypeError, ValueError) as exc:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "任务元数据不存在或已损坏") from exc

    matting_path = os.path.join(task_dir, "matting.png")
    matting = cv2.imread(matting_path, cv2.IMREAD_UNCHANGED)
    if matting is None or matting.ndim != 3 or matting.shape[2] != 4:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "人像中间结果不存在或已损坏")

    background, background_key = _resolve_background(background_color)
    crop_rect = _calculate_crop(face, template, crop_scale, offset_x, offset_y)
    cropped = _crop_with_padding(matting, crop_rect)
    standard_rgba = cv2.resize(
        cropped,
        (template.width, template.height),
        interpolation=cv2.INTER_AREA,
    )
    standard = _compose_background(standard_rgba, background)

    hd_scale = max(1.0, 600 / min(template.width, template.height))
    hd_size = (
        max(template.width, round(template.width * hd_scale)),
        max(template.height, round(template.height * hd_scale)),
    )
    hd = cv2.resize(standard, hd_size, interpolation=cv2.INTER_CUBIC)
    layout = _generate_layout(standard) if include_layout else None

    base_name = f"{original_stem}_{template.template_id}_{background_key}"
    output_specs: list[tuple[int, str, str, np.ndarray]] = [
        (0, "standard", f"{base_name}.jpg", standard),
        (1, "hd", f"{base_name}_hd.jpg", hd),
    ]
    if layout is not None:
        output_specs.append((2, "layout", f"{base_name}_layout.jpg", layout))

    result_files: list[IdPhotoFileItem] = []
    with _RENDER_LOCK:
        prepared_files: list[tuple[int, str, str, str, str]] = []
        try:
            for index, kind, display_name, image in output_specs:
                internal_name = f"{index}_{display_name}"
                output_path = os.path.join(task_dir, internal_name)
                temp_path = f"{output_path}.tmp"
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
            for _, _, _, temp_path, _ in prepared_files:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise
        except Exception as exc:
            for _, _, _, temp_path, _ in prepared_files:
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
                "template_id": template.template_id,
                "template_name": template.name,
                "width": template.width,
                "height": template.height,
                "face": {
                    "x": face[0],
                    "y": face[1],
                    "width": face[2],
                    "height": face[3],
                },
                "source_width": int(image.shape[1]),
                "source_height": int(image.shape[0]),
                "model": model_name,
                "original_stem": original_stem,
            },
        )

        result = _render_task(
            task_id,
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
    background_color: str,
    crop_scale: float,
    offset_x: float,
    offset_y: float,
    include_layout: bool,
    quality: int = STANDARD_QUALITY,
    dpi: int = 300,
    max_file_size_kb: int | None = None,
) -> IdPhotoResponse:
    """使用任务中的抠图中间结果重新渲染证件照。"""
    return _render_task(
        task_id,
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
