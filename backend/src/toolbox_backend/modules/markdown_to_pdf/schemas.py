"""Markdown 转 PDF 的转换结果与下载请求。"""

from pydantic import BaseModel, ConfigDict, Field


class DownloadRequest(BaseModel):
    """PDF 结果下载请求。"""

    task_id: str = Field(..., description="任务 ID")


class ConvertResponse(BaseModel):
    """Markdown 转 PDF 转换结果。"""

    task_id: str
    filename: str
    output_filename: str
    warnings: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
