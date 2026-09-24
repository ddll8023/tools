"""定位证件照模型资源，不负责模型状态和处理流程。"""

import os

from toolbox_backend.core.config import settings


MATTE_MODEL_CANDIDATES = (
    "hivision_modnet.onnx",
    "modnet_photographic_portrait_matting.onnx",
)


MTCNN_WEIGHT_NAMES = ("pnet.onnx", "rnet.onnx", "onet.onnx")


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
