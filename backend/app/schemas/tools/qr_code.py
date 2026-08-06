"""二维码生成 Schema"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GenerateResponse(BaseModel):
    """二维码生成结果"""

    image_data_url: str = Field(..., description="二维码 PNG Data URL")
    filename: str = Field(..., description="二维码图片文件名")
    source_type: Literal["text", "file"] = Field(..., description="内容来源类型")
    payload_size: int = Field(..., description="写入二维码的内容大小（字节）")

    model_config = ConfigDict(from_attributes=True)
