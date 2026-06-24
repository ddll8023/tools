"""工具列表获取服务"""
from app.schemas.tools.list import ToolListItem

_TOOLS = [
    ToolListItem(
        id="pdf-to-markdown",
        name="PdfToMarkdown",
        path="pdf-to-markdown",
        display_name="PDF 转 Markdown",
        description="将 PDF 文件转换为 Markdown 格式，保留文本、表格与图片",
        icon="fas fa-file-pdf",
    ),
]


def get_tool_list():
    """获取工具列表"""
    return _TOOLS
