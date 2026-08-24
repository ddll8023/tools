"""工具列表获取服务"""

from app.schemas.tools.list import ToolListItem

# 全局可用性状态，由 main.py lifespan 在启动时设定
_libreoffice_available = False
_libreoffice_unavailable_reason = "未检测到 LibreOffice"
_id_photo_available = False
_id_photo_unavailable_reason = "证件照模型或运行依赖不可用"


def set_libreoffice_available(available: bool, reason: str | None = None):
    """设置 LibreOffice 可用性（由 main.py lifespan 调用）"""
    global _libreoffice_available, _libreoffice_unavailable_reason
    _libreoffice_available = available
    if reason:
        _libreoffice_unavailable_reason = reason


def set_id_photo_available(available: bool, reason: str | None = None):
    """设置证件照工具可用性（由 main.py lifespan 调用）"""
    global _id_photo_available, _id_photo_unavailable_reason
    _id_photo_available = available
    if reason:
        _id_photo_unavailable_reason = reason


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
        id="pdf-to-word",
        name="PdfToWord",
        path="pdf-to-word",
        display_name="PDF 转 Word",
        description="将包含文字层的 PDF 文件转换为可编辑的 Word 文档",
        icon="fas fa-file-word",
        available=True,
    ),
    ToolListItem(
        id="markdown-to-word",
        name="MarkdownToWord",
        path="markdown-to-word",
        display_name="Markdown 转 Word",
        description="将 Markdown 文件或带 images 目录的 ZIP 转换为 DOCX 或 DOC",
        icon="fas fa-file-word",
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
    ToolListItem(
        id="epub-to-markdown",
        name="EpubToMarkdown",
        path="epub-to-markdown",
        display_name="EPUB 转 Markdown",
        description="将 EPUB 电子书转换为 Markdown，保留章节结构和图片资源",
        icon="fas fa-book",
        available=True,
    ),
    ToolListItem(
        id="qr-code",
        name="QrCode",
        path="qr-code",
        display_name="文本/文件转二维码",
        description="将文本或小文件生成可预览、可下载的二维码图片",
        icon="fas fa-qrcode",
        available=True,
    ),
]


def get_tool_list():
    """获取工具列表（动态填充可用性状态）"""
    result = list(_TOOLS)

    id_photo_tool = ToolListItem(
        id="id-photo",
        name="IdPhoto",
        path="id-photo",
        display_name="证件照",
        description="本地生成证件照，支持抠图、换背景、规格调整和六寸排版",
        icon="fas fa-id-card",
        available=_id_photo_available,
        unavailable_reason=None if _id_photo_available else _id_photo_unavailable_reason,
    )
    result.append(id_photo_tool)

    word_tool = ToolListItem(
        id="word-to-pdf",
        name="WordToPdf",
        path="word-to-pdf",
        display_name="Word 转 PDF",
        description="将 Word 文档（.doc/.docx）转换为 PDF 格式",
        icon="fas fa-file-word",
        available=_libreoffice_available,
        unavailable_reason=None if _libreoffice_available else _libreoffice_unavailable_reason,
    )
    result.append(word_tool)

    return result
