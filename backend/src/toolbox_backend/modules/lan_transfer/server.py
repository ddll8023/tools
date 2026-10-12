"""局域网投送数据面服务的启动、端口绑定与关闭。

服务运行在独立线程中，与控制面的事件循环互不影响。关闭不依赖进程信号，
而是由会话关闭序列设置 should_exit 后等待线程退出。
"""

from __future__ import annotations

import socket
import sys
import threading
import time

import uvicorn

from toolbox_backend.core.errors import ServiceException
from toolbox_backend.core.logging import setup_logger
from toolbox_backend.modules.lan_transfer.web_app import create_web_app
from toolbox_backend.schemas.response import ErrorCode

logger = setup_logger(__name__)

_START_TIMEOUT_SECONDS = 5.0
_SHUTDOWN_TIMEOUT_SECONDS = 5.0
_LISTEN_BACKLOG = 128


def _bind_listening_socket(host: str, preferred_port: int) -> socket.socket:
    """优先绑定首选端口，被占用时回退到系统分配的空闲端口。"""
    for port in (preferred_port, 0):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Windows 下 SO_REUSEADDR 会允许抢占已占用端口，因此仅在 POSIX 启用。
        if sys.platform != "win32":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((host, port))
        except OSError as exc:
            listener.close()
            if port == 0:
                raise ServiceException(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    f"无法监听局域网端口：{exc}",
                ) from exc
            logger.warning("局域网端口 %s 不可用，改用系统分配端口", port)
            continue
        listener.listen(_LISTEN_BACKLOG)
        return listener

    raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "无法监听局域网端口")


class LanWebServer:
    """在后台线程中运行数据面应用，并暴露实际绑定端口。"""

    def __init__(self) -> None:
        """初始化未启动状态。"""
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._listener: socket.socket | None = None
        self._port: int | None = None

    @property
    def port(self) -> int | None:
        """返回实际绑定的端口，未启动时为 None。"""
        return self._port

    def start(self, host: str, preferred_port: int) -> int:
        """绑定端口并启动数据面服务，返回实际端口。"""
        listener = _bind_listening_socket(host, preferred_port)
        # 数据面不信任客户端转发头，也不接管项目日志配置。
        config = uvicorn.Config(
            create_web_app(),
            host=host,
            port=0,
            log_config=None,
            log_level="warning",
            access_log=False,
            proxy_headers=False,
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(
            target=server.run,
            kwargs={"sockets": [listener]},
            name="lan-transfer-web",
            daemon=True,
        )
        thread.start()

        deadline = time.monotonic() + _START_TIMEOUT_SECONDS
        while not server.started:
            if not thread.is_alive():
                listener.close()
                raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "局域网服务启动失败")
            if time.monotonic() > deadline:
                server.should_exit = True
                thread.join(_SHUTDOWN_TIMEOUT_SECONDS)
                listener.close()
                raise ServiceException(ErrorCode.SERVICE_UNAVAILABLE, "局域网服务启动超时")
            time.sleep(0.02)

        self._server = server
        self._thread = thread
        self._listener = listener
        self._port = listener.getsockname()[1]
        logger.info("局域网投送服务已监听 %s:%s", host, self._port)
        return self._port

    def stop(self) -> None:
        """停止数据面服务并等待线程退出；滞留连接由强制退出断开。"""
        server, thread, listener = self._server, self._thread, self._listener
        self._server, self._thread, self._listener, self._port = None, None, None, None
        if server is None:
            return

        server.should_exit = True
        if thread is not None:
            thread.join(_SHUTDOWN_TIMEOUT_SECONDS)
            if thread.is_alive():
                # uvicorn 的优雅关闭会一直等待已建立的连接；停滞的连接必须强制
                # 断开，否则会话已标记关闭而服务线程仍在运行。
                logger.warning("局域网投送服务未在超时内退出，改为强制断开连接")
                server.force_exit = True
                thread.join(_SHUTDOWN_TIMEOUT_SECONDS)
            if thread.is_alive():
                logger.warning("局域网投送服务线程仍未退出")
        if listener is not None:
            try:
                listener.close()
            except OSError:
                # socket 已由 uvicorn 的事件循环关闭。
                pass
        logger.info("局域网投送服务已停止")
