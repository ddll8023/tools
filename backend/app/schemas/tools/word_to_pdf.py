"""Word 转 PDF 工具 Schema"""

from pydantic import BaseModel, ConfigDict, Field


# ========== 请求类（Request）==========


class DownloadRequest(BaseModel):
    task_id: str = Field(..., description="任务 ID")


# ========== 响应类（Response）==========


class ConvertResponse(BaseModel):
    task_id: str = Field(..., description="任务 ID")
    filename: str = Field(..., description="原始文件名")

    model_config = ConfigDict(from_attributes=True)
