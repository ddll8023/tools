"""工具列表获取服务"""

from app.schemas.tools.list import ToolListItem

# 全局可用性状态，由 init_tool_list() 在启动时设定
_libreoffice_available = False


def set_libreoffice_available(available: bool):
    """设置 LibreOffice 可用性（由 main.py lifespan 调用）"""
    global _libreoffice_available
    _libreoffice_available = available


_TOOLS = [
    ToolListItem(
        id="pdf-to-markdown",
        name="PdfToMarkdown",
        path="pdf-to-markdown",
        display_name="PDF 转 Markdown",
        description="将 PDF 文件转换为 Markdown 格式，保留文本、表格与图片",
        icon="fas fa-file-pdf",
        available=True,
    ),
    ToolListItem(
        id="image-converter",
        name="ImageConverter",
        path="image-converter",
        display_name="图片格式转换",
        description="将图片文件转换为 PNG、JPEG、WebP、BMP、GIF、TIFF 等格式，支持单张和批量转换",
        icon="fas fa-image",
        available=True,
    ),
]


def get_tool_list():
    """获取工具列表（动态填充可用性状态）"""
    result = list(_TOOLS)

    word_tool = ToolListItem(
        id="word-to-pdf",
        name="WordToPdf",
        path="word-to-pdf",
        display_name="Word 转 PDF",
        description="将 Word 文档（.doc/.docx）转换为 PDF 格式",
        icon="fas fa-file-word",
        available=_libreoffice_available,
    )
    result.append(word_tool)

    return result
