"""控制面认证中间件：校验桌面端专属凭据，保护本机全部工具 API。

中间件以纯 ASGI 方式实现，避免 BaseHTTPMiddleware 干扰流式下载响应与
后台任务；它只负责凭据校验与拒绝，业务异常仍由统一异常处理器映射。
"""

from __future__ import annotations

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from toolbox_backend.core.control_auth import verify_control_token
from toolbox_backend.schemas.response import ErrorCode

# 这些入口不携带用户数据，且被启动脚本与调试工具用作就绪探测，因此免凭据。
_EXEMPT_PATHS = frozenset({"/api/v1/health", "/docs", "/openapi.json", "/redoc"})
_BEARER_PREFIX = "bearer "
# 认证失败属于传输层拒绝，HTTP 状态码与业务错误码分别给出。
_UNAUTHORIZED_STATUS = 401


def _extract_bearer_token(headers: list[tuple[bytes, bytes]]) -> str | None:
    """从请求头中取出 Bearer 凭据，格式不符时返回 None。"""
    for name, value in headers:
        if name.lower() != b"authorization":
            continue
        decoded = value.decode("latin-1").strip()
        if decoded.lower().startswith(_BEARER_PREFIX):
            return decoded[len(_BEARER_PREFIX) :].strip()
        return None
    return None


class ControlAuthMiddleware:
    """拒绝未携带有效桌面端凭据的控制面请求。"""

    def __init__(self, app: ASGIApp) -> None:
        """保存被包装的 ASGI 应用。"""
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """放行预检与豁免路径，其余请求必须通过凭据校验。"""
        if scope.get("type") != "http" or not self._requires_auth(scope):
            await self._app(scope, receive, send)
            return

        token = _extract_bearer_token(scope.get("headers") or [])
        if verify_control_token(token):
            await self._app(scope, receive, send)
            return

        response = JSONResponse(
            status_code=_UNAUTHORIZED_STATUS,
            content={
                "code": ErrorCode.UNAUTHORIZED,
                "message": "未授权的控制面请求",
                "data": None,
            },
        )
        await response(scope, receive, send)

    @staticmethod
    def _requires_auth(scope: Scope) -> bool:
        """判断该请求是否需要控制面凭据。"""
        # 跨域预检不携带业务数据，由 CORS 中间件处理。
        if scope.get("method", "").upper() == "OPTIONS":
            return False
        return scope.get("path", "") not in _EXEMPT_PATHS
