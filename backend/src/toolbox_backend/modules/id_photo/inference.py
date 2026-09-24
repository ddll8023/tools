"""封装证件照人脸检测和人像抠图推理。"""

import os
import threading
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from toolbox_backend.core.errors import ServiceException
from toolbox_backend.schemas.response import ErrorCode
from toolbox_backend.modules.id_photo.model_resources import (
    _find_matte_model,
    _mtcnn_weight_paths,
)
from toolbox_backend.modules.id_photo.types import FaceDetection


MAX_PIXEL_COUNT = 40_000_000


MAX_PROCESSING_EDGE = 2000


MATTE_INPUT_SIZE = 512


_MATTE_SESSION = None


_MATTE_SESSION_PATH: str | None = None


_MATTE_LOCK = threading.Lock()


_MTCNN_INSTANCE = None


_MTCNN_LOCK = threading.Lock()


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
    """初始化 MTCNN，并把其权重路径重定向到当前模型资源目录。"""
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
                "MTCNN 人脸检测模型加载失败，请检查当前模型资源文件",
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


def _detect_face(image: np.ndarray) -> FaceDetection:
    detector = _get_mtcnn()
    height, width = image.shape[:2]

    def detect(target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        try:
            boxes, landmarks = detector.detect(
                target,
                min_face_size=20.0,
                thresholds=[0.8, 0.8, 0.8],
                nms_thresholds=[0.6, 0.7, 0.8],
            )
            return (
                np.asarray(boxes, dtype=np.float32).reshape((-1, 5)),
                np.asarray(landmarks, dtype=np.float32).reshape((-1, 10)),
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
        boxes, landmarks = detect(target)
        if len(boxes) == 1:
            boxes[:, :4] *= scale
            landmarks *= scale
        else:
            boxes, landmarks = detect(image)
    else:
        boxes, landmarks = detect(image)

    if len(boxes) != 1:
        raise ServiceException(
            ErrorCode.UNSUPPORTED_CONTENT,
            f"需要包含且只能包含一张主要人脸，当前检测到 {len(boxes)} 张",
        )
    if len(landmarks) != 1:
        raise ServiceException(ErrorCode.AI_SERVICE_ERROR, "人脸关键点检测结果异常")

    x1, y1, x2, y2 = [float(value) for value in boxes[0][:4]]
    x1 = max(0.0, min(x1, width - 1))
    y1 = max(0.0, min(y1, height - 1))
    x2 = max(x1 + 1.0, min(x2, width))
    y2 = max(y1 + 1.0, min(y2, height))

    points = tuple(
        (
            round(max(0.0, min(float(landmarks[0][index]), width - 1))),
            round(max(0.0, min(float(landmarks[0][index + 5]), height - 1))),
        )
        for index in range(5)
    )
    return FaceDetection(
        x=round(x1),
        y=round(y1),
        width=max(1, round(x2 - x1)),
        height=max(1, round(y2 - y1)),
        landmarks=points,
    )


def _matting(image: np.ndarray) -> tuple[np.ndarray, str]:
    model_path = _find_matte_model()
    if model_path is None:
        raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "缺少人像抠图模型")

    session = _get_matting_session(model_path)
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    source_height, source_width = image.shape[:2]
    scale = min(MATTE_INPUT_SIZE / source_width, MATTE_INPUT_SIZE / source_height)
    resized_width = max(1, round(source_width * scale))
    resized_height = max(1, round(source_height * scale))
    resized = cv2.resize(
        image,
        (resized_width, resized_height),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
    )
    offset_x = (MATTE_INPUT_SIZE - resized_width) // 2
    offset_y = (MATTE_INPUT_SIZE - resized_height) // 2
    model_canvas = np.full(
        (MATTE_INPUT_SIZE, MATTE_INPUT_SIZE, 3),
        127,
        dtype=np.uint8,
    )
    model_canvas[
        offset_y:offset_y + resized_height,
        offset_x:offset_x + resized_width,
    ] = resized
    model_image = model_canvas.astype(np.float32) / 255.0
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
    if matte.shape != (MATTE_INPUT_SIZE, MATTE_INPUT_SIZE):
        matte = cv2.resize(
            matte,
            (MATTE_INPUT_SIZE, MATTE_INPUT_SIZE),
            interpolation=cv2.INTER_LINEAR,
        )
    matte = np.nan_to_num(matte, nan=0.0, posinf=1.0, neginf=0.0)
    matte_min = float(matte.min())
    matte_max = float(matte.max())
    if matte_min < 0.0 or matte_max > 1.0:
        if matte_max <= 255.0 and matte_min >= 0.0:
            matte = matte / 255.0
        elif matte_max > matte_min:
            matte = (matte - matte_min) / (matte_max - matte_min)
    matte = np.clip(matte, 0.0, 1.0)
    matte = matte[
        offset_y:offset_y + resized_height,
        offset_x:offset_x + resized_width,
    ]
    alpha_float = cv2.resize(
        matte,
        (source_width, source_height),
        interpolation=cv2.INTER_LINEAR,
    )
    # 只清理接近全透明/全不透明的数值噪声，保留发丝的半透明过渡。
    alpha_float[alpha_float < 0.005] = 0.0
    alpha_float[alpha_float > 0.995] = 1.0
    alpha = np.clip(np.rint(alpha_float * 255.0), 0, 255).astype(np.uint8)
    b, g, r = cv2.split(image)
    return cv2.merge((b, g, r, alpha)), os.path.basename(model_path)



def reset_model_sessions() -> None:
    """释放抠图与人脸检测会话，供受限模型删除流程调用。"""
    global _MATTE_SESSION, _MATTE_SESSION_PATH, _MTCNN_INSTANCE
    with _MATTE_LOCK:
        _MATTE_SESSION = None
        _MATTE_SESSION_PATH = None
    with _MTCNN_LOCK:
        _MTCNN_INSTANCE = None
