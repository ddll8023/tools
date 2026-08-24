"""Markdown 转 Word 工具 Schema"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DownloadRequest(BaseModel):
    """下载请求。"""

    task_id: str = Field(..., description="任务 ID")


class ConvertResponse(BaseModel):
    """Markdown 转 Word 转换结果。"""

    task_id: str = Field(..., description="任务 ID")
    filename: str = Field(..., description="Markdown 或 ZIP 文件名")
    output_filename: str = Field(..., description="输出文件名")
    output_format: Literal["docx", "doc"] = Field(..., description="输出格式")
    warnings: list[str] = Field(default_factory=list, description="转换警告")

    model_config = ConfigDict(from_attributes=True)
