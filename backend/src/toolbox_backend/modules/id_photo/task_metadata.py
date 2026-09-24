"""校验证件照任务目录并读写任务元数据。"""

import json
import os

from toolbox_backend.core.errors import ServiceException
from toolbox_backend.schemas.response import ErrorCode
from toolbox_backend.infrastructure.task_storage.workspace import (
    ensure_task_path,
    get_task_dir,
    validate_task_id,
)
from toolbox_backend.modules.id_photo.types import FaceDetection


def _task_dir_checked(task_id: str) -> str:
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = ensure_task_path(get_task_dir(task_id))
    if not task_dir.is_dir():
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "文件不存在或已过期")
    return str(task_dir)


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


def _face_from_metadata(metadata: dict) -> FaceDetection:
    try:
        face_data = metadata["face"]
        landmarks = tuple(
            (int(point["x"]), int(point["y"]))
            for point in face_data["landmarks"]
        )
        if len(landmarks) != 5:
            raise ValueError("invalid landmarks")
        return FaceDetection(
            x=int(face_data["x"]),
            y=int(face_data["y"]),
            width=int(face_data["width"]),
            height=int(face_data["height"]),
            landmarks=landmarks,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "任务人脸数据不存在或已损坏") from exc


def _write_json(path: str, data: dict) -> None:
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, separators=(",", ":"))
    os.replace(temp_path, path)
