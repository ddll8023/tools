"""兼容导出 Markdown 文档来源能力，避免迁移期间破坏旧模块导入。"""

from app.modules.markdown_document.source import (
    MAX_ARCHIVE_MEMBERS,
    MAX_ARCHIVE_UNPACKED_SIZE,
    MAX_FILE_SIZE,
    SUPPORTED_INPUT_EXTENSIONS,
    SUPPORTED_MARKDOWN_EXTENSIONS,
    MarkdownInputError,
    MarkdownSource,
    prepare_markdown_source,
    read_markdown,
)

__all__ = [
    "MAX_ARCHIVE_MEMBERS",
    "MAX_ARCHIVE_UNPACKED_SIZE",
    "MAX_FILE_SIZE",
    "SUPPORTED_INPUT_EXTENSIONS",
    "SUPPORTED_MARKDOWN_EXTENSIONS",
    "MarkdownInputError",
    "MarkdownSource",
    "prepare_markdown_source",
    "read_markdown",
]
