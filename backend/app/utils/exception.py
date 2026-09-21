"""兼容导出核心业务异常，避免迁移期间破坏既有内部导入。"""

from app.core.errors import ServiceException

__all__ = ["ServiceException"]
