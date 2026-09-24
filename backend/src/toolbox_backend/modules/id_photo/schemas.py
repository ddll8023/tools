"""证件照工具 Schema"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class IdPhotoTemplate(str, Enum):
    """证件照规格模板"""

    ONE_INCH = "one-inch"
    SMALL_TWO_INCH = "small-two-inch"
    TWO_INCH = "two-inch"
    CUSTOM = "custom"


class IdPhotoTemplateItem(BaseModel):
    """可选择的证件照规格"""

    id: str = Field(..., description="规格 ID")
    label: str = Field(..., description="规格显示名称")
    description: str = Field(..., description="规格说明")
    width: int | None = Field(None, description="输出宽度（像素）")
    height: int | None = Field(None, description="输出高度（像素）")
    width_mm: int | None = Field(None, description="物理宽度（毫米）")
    height_mm: int | None = Field(None, description="物理高度（毫米）")
    is_custom: bool = Field(False, description="是否为自定义规格")


class IdPhotoFileItem(BaseModel):
    """证件照任务中的单个结果文件"""

    kind: str = Field(..., description="结果类型：standard/hd/layout")
    filename: str = Field(..., description="结果文件名")
    file_size: int = Field(..., description="文件大小（字节）")
    index: int = Field(..., description="下载索引")

    model_config = ConfigDict(from_attributes=True)


class IdPhotoResponse(BaseModel):
    """证件照处理结果"""

    task_id: str = Field(..., description="任务 ID")
    template_id: str = Field(..., description="规格模板 ID")
    template_name: str = Field(..., description="规格模板名称")
    width: int = Field(..., description="输出宽度（像素）")
    height: int = Field(..., description="输出高度（像素）")
    background_color: str = Field(..., description="背景色")
    model: str = Field(..., description="使用的人像抠图模型")
    quality: int = Field(..., description="JPEG 质量设置")
    dpi: int = Field(..., description="输出 DPI")
    max_file_size_kb: int | None = Field(None, description="文件大小上限（KB）")
    files: list[IdPhotoFileItem] = Field(..., description="结果文件列表")

    model_config = ConfigDict(from_attributes=True)


class IdPhotoRenderRequest(BaseModel):
    """基于已完成人像抠图任务重新渲染结果"""

    task_id: str = Field(..., min_length=12, max_length=12, description="任务 ID")
    template_id: IdPhotoTemplate = Field(
        IdPhotoTemplate.ONE_INCH,
        description="本次渲染使用的照片规格",
    )
    width: int | None = Field(None, ge=80, le=3000, description="自定义宽度（像素）")
    height: int | None = Field(None, ge=80, le=3000, description="自定义高度（像素）")
    background_color: str = Field(
        "white", min_length=1, max_length=16, description="背景色"
    )
    crop_scale: float = Field(1.0, ge=0.85, le=1.25, description="裁切范围比例")
    offset_x: float = Field(0.0, ge=-0.15, le=0.15, description="水平方向偏移比例")
    offset_y: float = Field(0.0, ge=-0.15, le=0.15, description="垂直方向偏移比例")
    include_layout: bool = Field(True, description="是否生成六寸排版照")
    quality: int = Field(95, ge=60, le=100, description="JPEG 初始质量")
    dpi: int = Field(300, ge=72, le=600, description="输出 DPI")
    max_file_size_kb: int | None = Field(
        None, ge=10, le=2048, description="单个文件大小上限（KB）"
    )


class IdPhotoDownloadRequest(BaseModel):
    """证件照结果下载请求"""

    task_id: str = Field(..., min_length=12, max_length=12, description="任务 ID")
    file_index: int = Field(..., ge=0, description="结果文件索引")
