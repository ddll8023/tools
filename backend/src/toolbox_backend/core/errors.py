"""定义跨越 HTTP 边界的后端业务异常。"""

from toolbox_backend.schemas.response import ErrorCode


class ServiceException(Exception):
    """携带稳定业务错误码和用户可见消息的异常。"""

    def __init__(self, code: int | ErrorCode, message: str) -> None:
        """保存业务错误码和公开错误消息。"""
        self.code = code
        self.message = message
        super().__init__(message)
