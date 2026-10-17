"""局域网投送会话的状态、凭据、资源预算与在途操作登记。

会话只存在于内存：应用重启后不恢复旧会话，也不复用旧凭据。模块不负责
监听与文件读写，仅提供状态、凭据判定与本会话的预算、待确认队列、待取件
清单，供数据面授权和关闭协调使用。
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from toolbox_backend.modules.lan_transfer.budget import SessionBudget
from toolbox_backend.modules.lan_transfer.outgoing import OutgoingList
from toolbox_backend.modules.lan_transfer.pending import PendingQueue

_URL_TOKEN_BYTES = 32
_COOKIE_SECRET_BYTES = 32
_SESSION_ID_BYTES = 8


class SessionState(StrEnum):
    """会话生命周期状态。"""

    IDLE = "idle"
    STARTING = "starting"
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


class InFlightRegistry:
    """登记会话内正在进行的长耗时操作，供关闭时统一取消。

    上传与下载在开始读写前登记、结束时注销；关闭序列据此先取消在途操作，
    再释放监听与文件句柄。
    """

    def __init__(self) -> None:
        """初始化空登记表。"""
        self._lock = threading.RLock()
        self._handlers: dict[int, Callable[[], None]] = {}
        self._next_handle = 0

    def register(self, cancel: Callable[[], None]) -> int:
        """登记一个可取消操作并返回句柄。"""
        with self._lock:
            self._next_handle += 1
            self._handlers[self._next_handle] = cancel
            return self._next_handle

    def unregister(self, handle: int) -> None:
        """注销已经结束的操作。"""
        with self._lock:
            self._handlers.pop(handle, None)

    def count(self) -> int:
        """返回当前登记的在途操作数量。"""
        with self._lock:
            return len(self._handlers)

    def cancel_all(self) -> int:
        """取消全部在途操作并清空登记表，返回被取消的数量。"""
        with self._lock:
            handlers = list(self._handlers.values())
            self._handlers.clear()
        for cancel in handlers:
            cancel()
        return len(handlers)


def _constant_time_equal(expected: str, candidate: str | None) -> bool:
    """在候选缺失时也执行常量时间比对，避免长度差异泄露信息。"""
    return hmac.compare_digest(expected, candidate or "")


@dataclass
class LanSession:
    """一次局域网投送会话的凭据、有效期、最长存活时间与运行状态。"""

    url_token: str
    cookie_secret: str
    device_name: str
    session_id: str
    created_at: float
    expires_at: float
    hard_deadline: float
    state: SessionState = SessionState.STARTING
    port: int | None = None
    error: str | None = None
    passphrase: str | None = None
    in_flight: InFlightRegistry = field(default_factory=InFlightRegistry)
    budget: SessionBudget = field(default_factory=SessionBudget)
    pending: PendingQueue = field(default_factory=PendingQueue)
    outgoing: OutgoingList = field(default_factory=OutgoingList)

    @property
    def remaining_seconds(self) -> int:
        """返回距离自动关闭的剩余秒数，已过期时为 0。"""
        return max(0, int(self.expires_at - time.time()))

    @property
    def has_active_transfer(self) -> bool:
        """判断是否存在正在进行的上传或下载。"""
        return self.in_flight.count() > 0

    @property
    def is_accepting(self) -> bool:
        """判断会话当前是否接受新的数据面操作。"""
        return self.state is SessionState.ACTIVE

    def matches_url_token(self, candidate: str | None) -> bool:
        """常量时间比对会话链接中的凭据。"""
        return _constant_time_equal(self.url_token, candidate)

    def matches_cookie(self, candidate: str | None) -> bool:
        """常量时间比对浏览器持有的会话 cookie。"""
        return _constant_time_equal(self.cookie_secret, candidate)

    def verify_passphrase(self, candidate: str) -> bool:
        """常量时间比对访问口令；未设置口令时视为通过。"""
        if self.passphrase is None:
            return True
        return _constant_time_equal(self.passphrase, candidate)

    def rotate_cookie_secret(self) -> None:
        """轮换 cookie 凭据，使已经进入的浏览器必须重新通过口令。"""
        self.cookie_secret = secrets.token_urlsafe(_COOKIE_SECRET_BYTES)


def create_session(device_name: str, ttl_seconds: int, max_extend_seconds: int) -> LanSession:
    """生成新的会话凭据、有效期、最长存活时间与资源预算。"""
    now = time.time()
    return LanSession(
        url_token=secrets.token_urlsafe(_URL_TOKEN_BYTES),
        cookie_secret=secrets.token_urlsafe(_COOKIE_SECRET_BYTES),
        device_name=device_name,
        session_id=secrets.token_hex(_SESSION_ID_BYTES),
        created_at=now,
        expires_at=now + ttl_seconds,
        hard_deadline=now + ttl_seconds + max_extend_seconds,
        budget=SessionBudget(),
        pending=PendingQueue(),
        outgoing=OutgoingList(),
    )


class LanSessionManager:
    """串行保存当前会话，保证并发启停不会同时存在两个会话。"""

    def __init__(self) -> None:
        """初始化空会话槽位。"""
        self._lock = threading.RLock()
        self._session: LanSession | None = None

    def current(self) -> LanSession | None:
        """返回当前会话，未开启时为 None。"""
        with self._lock:
            return self._session

    def install(self, session: LanSession) -> None:
        """登记新会话。"""
        with self._lock:
            self._session = session

    def clear(self) -> None:
        """清空会话槽位。"""
        with self._lock:
            self._session = None


sessions = LanSessionManager()
