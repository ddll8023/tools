"""图片格式转换 Schema"""

from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


# ========== 辅助类（Support）==========


class ImageFormat(str, Enum):
    """支持的图片输出格式"""
    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"
    BMP = "bmp"
    GIF = "gif"
    TIFF = "tiff"


# ========== 请求类（Request）==========


class DownloadRequest(BaseModel):
    task_id: str = Field(..., description="任务 ID")
    file_index: int | None = Field(None, description="文件索引（None 时下载全部 ZIP）")


class DownloadAllRequest(BaseModel):
    task_id: str = Field(..., description="任务 ID")


# ========== 响应类（Response）==========


class ConvertFileItem(BaseModel):
    """转换结果中的单个文件信息"""
    original_name: str = Field(..., description="原始文件名")
    converted_name: str = Field(..., description="转换后文件名")
    file_size: int = Field(..., description="文件大小（字节）")
    original_format: str = Field(..., description="原始格式")
    index: int = Field(..., description="文件索引，用于下载")

    model_config = ConfigDict(from_attributes=True)


class ConvertResponse(BaseModel):
    task_id: str = Field(..., description="任务 ID")
    files: list[ConvertFileItem] = Field(..., description="转换后的文件列表")
    is_batch: bool = Field(..., description="是否批量模式（≥2 张或多页 TIFF 拆分为多文件）")

    model_config = ConfigDict(from_attributes=True)
