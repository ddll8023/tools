"""兼容导出 Markdown 转 Word 业务能力。"""

from app.modules.markdown_to_word.service import (
    CONVERT_TIMEOUT,
    DOC_MEDIA_TYPE,
    DOCX_MEDIA_TYPE,
    OutputFormat,
    convert_markdown_to_word,
    download_word,
)

__all__ = [
    "CONVERT_TIMEOUT",
    "DOC_MEDIA_TYPE",
    "DOCX_MEDIA_TYPE",
    "OutputFormat",
    "convert_markdown_to_word",
    "download_word",
]
