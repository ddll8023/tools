"""PDF 转 Word 工具 Schema"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DownloadRequest(BaseModel):
    """下载请求。"""

    task_id: str = Field(..., description="任务 ID")


class ConvertResponse(BaseModel):
    """PDF 转 Word 转换结果。"""

    task_id: str = Field(..., description="任务 ID")
    filename: str = Field(..., description="原始文件名")
    output_filename: str = Field(..., description="输出文件名")
    page_count: int = Field(..., ge=0, description="PDF 总页数")
    engine: Literal["pdf2docx"] = Field("pdf2docx", description="转换引擎")
    warnings: list[str] = Field(default_factory=list, description="转换警告")

    model_config = ConfigDict(from_attributes=True)
