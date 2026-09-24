"""设置页相关 API Schema。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ModelId = Literal["mineru-pipeline", "id-photo"]
ModelStatus = Literal[
    "not_downloaded",
    "downloading",
    "ready",
    "failed",
    "interrupted",
    "cancelled",
    "incomplete",
    "unavailable",
]


class ModelRequest(BaseModel):
    model_id: ModelId = Field(..., description="模型标识")


class ModelStatusItem(BaseModel):
    model_id: str
    name: str
    description: str
    source: str
    path: str
    approx_size_bytes: int | None = Field(None, ge=0)
    status: ModelStatus
    progress: int | None = Field(None, ge=0, le=100)
    stage: str
    error: str | None = None
    job_id: str | None = None
    can_delete: bool = False
    delete_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ModelStatusResponse(BaseModel):
    models: list[ModelStatusItem]

    model_config = ConfigDict(from_attributes=True)


class ModelActionResponse(ModelStatusItem):
    pass
