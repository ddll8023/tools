"""PDF 转 Markdown 工具 Schema"""
from enum import IntEnum
from pydantic import BaseModel, ConfigDict


# ========== 辅助类（Support）==========

class TaskStatus(IntEnum):
    PROCESSING = 0
    COMPLETED = 1
    FAILED = 2


# ========== 请求类（Request）==========

# 文件上传使用 multipart，不强制请求类（§7.5）


class GetPreviewRequest(BaseModel):
    task_id: str


# ========== 响应类（Response）==========

class ConvertResponse(BaseModel):
    task_id: str
    filename: str
    page_count: int

    model_config = ConfigDict(from_attributes=True)


class GetPreviewResponse(BaseModel):
    markdown_content: str
    page_count: int
    table_count: int
    image_count: int

    model_config = ConfigDict(from_attributes=True)
