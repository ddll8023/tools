"""定义证件照业务使用的模板和人脸数据类型。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TemplateConfig:
    template_id: str
    label: str
    name: str
    width: int
    height: int
    width_mm: int | None
    height_mm: int | None
    description: str
    face_area_ratio: float = 0.20
    eye_line_ratio: float = 0.40


@dataclass(frozen=True, slots=True)
class FaceDetection:
    x: int
    y: int
    width: int
    height: int
    landmarks: tuple[tuple[int, int], ...]
