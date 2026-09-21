"""兼容导出 Markdown 表格能力，避免迁移期间破坏旧模块导入。"""

from app.modules.markdown_document.tables import html_tables_to_markdown, parse_html_table

__all__ = ["html_tables_to_markdown", "parse_html_table"]
