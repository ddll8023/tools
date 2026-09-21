"""兼容导出 Markdown 统计能力，避免迁移期间破坏旧模块导入。"""

from app.modules.markdown_document.metrics import count_tables

__all__ = ["count_tables"]
