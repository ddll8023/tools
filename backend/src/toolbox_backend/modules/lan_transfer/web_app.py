"""局域网投送数据面应用：会话授权、浏览器页面、文件接收与文件下载。

该应用只服务于浏览器访问，与控制面使用不同的监听地址和端口，不提供任何
工具 API。这里的接口使用 GET/POST 是浏览器导航、表单提交、文件上传与文件
下载的必需形式，不适用控制面"全部 POST"的约定。
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import quote, unquote

import anyio
from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from toolbox_backend.api.exception_handlers import register_exception_handlers
from toolbox_backend.core.config import settings
from toolbox_backend.core.errors import ServiceException
from toolbox_backend.core.logging import setup_logger
from toolbox_backend.modules.lan_transfer import isolation
from toolbox_backend.modules.lan_transfer.pending import PendingFile
from toolbox_backend.modules.lan_transfer.session import LanSession, sessions
from toolbox_backend.schemas.response import ErrorCode

logger = setup_logger(__name__)

WEB_DIR = Path(__file__).parent / "web"
COOKIE_NAME = "toolbox_lan_session"
FILE_NAME_HEADER = "x-file-name"
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024

# 浏览器页面不使用公网依赖，全部随应用分发，且不允许缓存。
_PAGE_HEADERS = {"Cache-Control": "no-store"}


def _not_found() -> Response:
    """统一返回 404，不区分凭据错误与会话不存在。"""
    return Response(status_code=404, content="页面不存在")


def _resolve_session(request: Request) -> LanSession | None:
    """按 cookie 解析当前有效会话；凭据无效或会话已停止时返回 None。"""
    session = sessions.current()
    if session is None or not session.is_accepting:
        return None
    if not session.matches_cookie(request.cookies.get(COOKIE_NAME)):
        return None
    return session


def _grant_cookie(session: LanSession, redirect_to: str) -> RedirectResponse:
    """下发浏览器会话 cookie 并跳转到目标页面。"""
    response = RedirectResponse(url=redirect_to, status_code=303)
    # 明文 HTTP 下无法使用 Secure 属性，只能依赖 HttpOnly 限制脚本读取。
    response.set_cookie(
        COOKIE_NAME,
        session.cookie_secret,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


def _page(name: str) -> FileResponse:
    """返回浏览器页面文件。"""
    return FileResponse(WEB_DIR / name, media_type="text/html", headers=_PAGE_HEADERS)


def _initial_reservation(request: Request) -> int:
    """按声明长度预留额度；声明缺失时按单文件上限预留，不信任声明值本身。"""
    max_file_bytes = settings.LAN_TRANSFER_MAX_FILE_BYTES
    declared = request.headers.get("content-length")
    if not declared:
        return max_file_bytes
    try:
        declared_bytes = int(declared)
    except ValueError:
        return max_file_bytes
    return min(declared_bytes, max_file_bytes) if declared_bytes > 0 else max_file_bytes


def _remove_partial(path: Path) -> None:
    """删除未完成的上传内容；失败时保留痕迹，由下次启动回收。"""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("删除未完成的上传内容失败: %s", path)


async def _write_stream(
    request: Request,
    target: Path,
    reserved: int,
    cancelled: threading.Event,
) -> int:
    """把请求体流式写入隔离区，逐块校验取消标记、单文件上限与预留额度。"""
    written = 0
    async with await anyio.open_file(target, "wb") as handle:
        async for chunk in request.stream():
            if cancelled.is_set():
                raise ServiceException(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "投送会话已停止，上传已取消",
                )
            if not chunk:
                continue
            if written + len(chunk) > settings.LAN_TRANSFER_MAX_FILE_BYTES:
                raise ServiceException(ErrorCode.FILE_TOO_LARGE, "文件超过单文件上限")
            if written + len(chunk) > reserved:
                raise ServiceException(
                    ErrorCode.PARAM_ERROR,
                    "上传内容与声明的长度不一致，已终止接收",
                )
            await handle.write(chunk)
            written += len(chunk)
    return written


def _content_disposition(name: str) -> str:
    """按 RFC 5987 生成下载文件名，并给出不含引号的 ASCII 回退值。"""
    fallback = (
        name.encode("ascii", "ignore").decode("ascii").replace('"', "").replace("\\", "").strip()
    )
    return f"attachment; filename=\"{fallback or 'file'}\"; filename*=UTF-8''{quote(name, safe='')}"


async def _iter_download(
    path: str,
    size_bytes: int,
    session: LanSession,
) -> AsyncIterator[bytes]:
    """分块读取待取件文件；进入时登记在途操作，退出或取消时注销并关闭句柄。"""
    cancelled = threading.Event()
    handle = session.in_flight.register(cancelled.set)
    try:
        async with await anyio.open_file(path, "rb") as source:
            remaining = size_bytes
            while remaining > 0:
                if cancelled.is_set():
                    return
                chunk = await source.read(min(_DOWNLOAD_CHUNK_BYTES, remaining))
                if not chunk:
                    return
                remaining -= len(chunk)
                yield chunk
    finally:
        session.in_flight.unregister(handle)


def create_web_app() -> FastAPI:
    """创建数据面应用并注册浏览器路由。"""
    app = FastAPI(
        title="局域网投送",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # 与控制面共用统一响应壳，浏览器页面按 code 判断成败。
    register_exception_handlers(app)

    app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")

    @app.get("/s/{token}")
    def enter_session(token: str) -> Response:
        """校验链接凭据；无口令直接放行，有口令先进入口令页。"""
        session = sessions.current()
        if session is None or not session.is_accepting:
            return _not_found()
        if not session.matches_url_token(token):
            return _not_found()
        if session.passphrase is not None:
            return RedirectResponse(url="/unlock", status_code=303)
        return _grant_cookie(session, "/")

    @app.get("/unlock")
    def unlock_page() -> Response:
        """返回口令输入页；未设置口令时直接进入会话页。"""
        session = sessions.current()
        if session is None or not session.is_accepting:
            return _not_found()
        if session.passphrase is None:
            return RedirectResponse(url="/", status_code=303)
        return _page("unlock.html")

    @app.post("/unlock")
    def submit_passphrase(passphrase: str = Form("")) -> Response:
        """校验访问口令，通过后下发会话 cookie。"""
        session = sessions.current()
        if session is None or not session.is_accepting:
            return _not_found()
        if not session.verify_passphrase(passphrase):
            return RedirectResponse(url="/unlock?error=1", status_code=303)
        return _grant_cookie(session, "/")

    @app.get("/")
    def session_page(request: Request) -> Response:
        """返回会话状态页；未授权时退回口令页或直接拒绝。"""
        session = _resolve_session(request)
        if session is not None:
            return _page("index.html")
        current = sessions.current()
        if current is not None and current.is_accepting and current.passphrase is not None:
            return RedirectResponse(url="/unlock", status_code=303)
        return _not_found()

    @app.get("/api/session")
    def session_info(request: Request) -> Response:
        """返回浏览器页面展示所需的会话信息。"""
        session = _resolve_session(request)
        if session is None:
            return _not_found()
        return JSONResponse(
            {
                "device_name": session.device_name,
                "state": session.state.value,
                "remaining_seconds": session.remaining_seconds,
                "has_passphrase": session.passphrase is not None,
                "pending_count": session.pending.count(),
            }
        )

    @app.get("/api/files")
    def files_info(request: Request) -> Response:
        """返回浏览器页面展示的待取件清单。"""
        session = _resolve_session(request)
        if session is None:
            return _not_found()
        return JSONResponse(
            {
                "files": [
                    {
                        "id": item.file_id,
                        "name": item.name,
                        "size_bytes": item.size_bytes,
                        "available": item.is_available,
                    }
                    for item in session.outgoing.list_items()
                ]
            }
        )

    @app.get("/download/{file_id}")
    async def download_file(file_id: str, request: Request) -> Response:
        """按标识下载待取件文件；只接受清单内的条目，源文件缺失按不存在处理。"""
        session = _resolve_session(request)
        if session is None:
            return _not_found()

        item = session.outgoing.get(file_id)
        if item is None:
            return _not_found()
        try:
            size_bytes = os.path.getsize(item.path)
        except OSError:
            logger.warning("待取件文件已不可读: %s", item.name)
            return _not_found()

        return StreamingResponse(
            _iter_download(item.path, size_bytes, session),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": _content_disposition(item.name),
                "Content-Length": str(size_bytes),
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/upload")
    async def upload_file(request: Request) -> Response:
        """接收浏览器上传的单个文件，流式写入隔离区后进入待确认队列。"""
        session = _resolve_session(request)
        if session is None:
            return _not_found()

        name = isolation.sanitize_name(unquote(request.headers.get(FILE_NAME_HEADER, "")))
        upload_id = uuid.uuid4().hex
        target = isolation.upload_path(session.session_id, upload_id)

        cancelled = threading.Event()
        reserved = 0
        queued = False
        session.budget.acquire_upload_slot()
        handle = session.in_flight.register(cancelled.set)
        try:
            reserved = _initial_reservation(request)
            session.budget.reserve(reserved)
            target.parent.mkdir(parents=True, exist_ok=True)
            written = await _write_stream(request, target, reserved, cancelled)
            if written == 0:
                raise ServiceException(ErrorCode.PARAM_ERROR, "上传内容为空")

            # 上传占用转为待确认占用，不因请求结束释放预算。
            session.pending.add(
                PendingFile(
                    upload_id=upload_id,
                    original_name=name,
                    stored_name=name,
                    size_bytes=written,
                    stored_path=target,
                    uploaded_at=time.time(),
                )
            )
            queued = True
            session.budget.settle(reserved, written)
            logger.info("投送接收完成: 文件=%s 字节=%s", name, written)
            return JSONResponse(
                {"code": 0, "message": "success", "data": {"upload_id": upload_id}}
            )
        except BaseException:
            # 客户端断连可能以取消异常形式抛出，因此在这里统一释放预留并清理；
            # 已登记进待确认队列的内容不属于清理范围。
            if not queued:
                session.budget.release(reserved)
                _remove_partial(target)
            raise
        finally:
            session.in_flight.unregister(handle)
            session.budget.release_upload_slot(keep_pending_slot=queued)

    return app
