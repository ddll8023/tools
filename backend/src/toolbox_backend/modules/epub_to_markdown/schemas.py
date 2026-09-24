"""EPUB 转 Markdown 工具 Schema"""

from pydantic import BaseModel, ConfigDict, Field


class GetPreviewRequest(BaseModel):
    """预览和下载请求"""

    task_id: str = Field(..., description="任务 ID")


class ConvertResponse(BaseModel):
    """EPUB 转换结果"""

    task_id: str = Field(..., description="任务 ID")
    filename: str = Field(..., description="原始文件名")
    chapter_count: int = Field(0, ge=0, description="章节数量")
    image_count: int = Field(0, ge=0, description="导出的图片数量")

    model_config = ConfigDict(from_attributes=True)


class GetPreviewResponse(BaseModel):
    """EPUB Markdown 预览"""

    markdown_content: str = Field(..., description="Markdown 文本内容")
    chapter_count: int = Field(..., ge=0, description="章节数量")
    table_count: int = Field(..., ge=0, description="表格数量")
    image_count: int = Field(..., ge=0, description="导出的图片数量")
    filename: str = Field(..., description="原始文件名")

    model_config = ConfigDict(from_attributes=True)
