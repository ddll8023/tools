"""工具列表条目 Schema"""
from pydantic import BaseModel, Field


# ========== 辅助类（Support）==========


class ToolListItem(BaseModel):
    """工具列表条目"""
    id: str = Field(..., description="工具唯一标识")
    name: str = Field(..., description="PascalCase 路由名，如 PdfToMarkdown")
    path: str = Field(..., description="路由路径")
    display_name: str = Field(..., description="前端显示名称")
    description: str = Field(..., description="工具功能描述")
    icon: str = Field(..., description="图标类名，格式如 fas fa-file-pdf")


class GetToolListResponse(BaseModel):
    """工具列表响应"""
    tools: list[ToolListItem]
