"""PDF 转 Markdown 工具 Schema"""

from enum import IntEnum
from pydantic import BaseModel, ConfigDict, Field

# ========== 辅助类（Support）==========


class TaskStatus(IntEnum):
    PROCESSING = 0
    COMPLETED = 1
    FAILED = 2


# ========== 请求类（Request）==========


class GetPreviewRequest(BaseModel):
    task_id: str = Field(..., description="任务 ID")


class GetProgressRequest(BaseModel):
    task_id: str = Field(..., description="任务 ID")


# ========== 响应类（Response）==========


class ConvertResponse(BaseModel):
    task_id: str = Field(..., description="任务 ID")
    filename: str = Field(..., description="原始文件名")
    page_count: int = Field(0, ge=0, description="PDF 总页数（深度模式异步返回时为 0）")

    model_config = ConfigDict(from_attributes=True)


class GetPreviewResponse(BaseModel):
    markdown_content: str = Field(..., description="Markdown 文本内容")
    page_count: int = Field(..., ge=0, description="PDF 总页数")
    table_count: int = Field(..., ge=0, description="识别到的表格数量")
    image_count: int = Field(..., ge=0, description="识别到的图片数量")

    model_config = ConfigDict(from_attributes=True)


class GetProgressResponse(BaseModel):
    progress: int = Field(..., ge=-1, le=100, description="进度 0~100，-1 表示失败")
    stage: str = Field(..., description="当前阶段描述")

    model_config = ConfigDict(from_attributes=True)
