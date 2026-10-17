"""应用级系统持有锁与启动身份；USB 子进程延续锁，更新守卫不初始化业务。"""

from __future__ import annotations

import errno
import json
import os
import re
import stat
import sys
import threading
import time
import uuid

from toolbox_backend.core.config import settings
from toolbox_backend.schemas.runtime import RuntimeIdentity

# 取锁失败的常见 errno：POSIX 为 EAGAIN/EWOULDBLOCK，Windows 为 EACCES/EDEADLK。
_BUSY_ERRNOS = frozenset(
    code for code in (
        getattr(errno, "EAGAIN", None), getattr(errno, "EWOULDBLOCK", None),
        getattr(errno, "EACCES", None), getattr(errno, "EDEADLK", None),
    ) if code is not None
)

class OwnershipBusyError(RuntimeError):
    """另一个进程（含尚未退出的 USB 工作进程）仍持有应用所有权。"""

_lock = threading.RLock()
_lease_fd: int | None = None
_identity: RuntimeIdentity | None = None
_phase = "starting"


def acquire_ownership() -> RuntimeIdentity:
    """非阻塞取得当前用户的应用锁；失败时不读取或改写业务状态。"""
    global _lease_fd, _identity, _phase
    with _lock:
        if _lease_fd is not None:
            raise RuntimeError("当前进程已经持有应用锁")
        launch_id = settings.TOOLBOX_LAUNCH_ID or uuid.uuid4().hex
        if re.fullmatch(r"[a-f0-9]{32}", launch_id) is None:
            raise RuntimeError("启动标识格式无效")
        path = settings.ownership_lock_path
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise RuntimeError("应用锁不是普通文件")
            if sys.platform == "win32":
                import msvcrt

                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            # 只有真正的争用才转成“占用”提示，其他 I/O 失败照常抛出。
            if exc.errno in _BUSY_ERRNOS:
                raise OwnershipBusyError(
                    "另一个工具盒子进程或上次未退出的 USB 工作进程仍持有应用所有权"
                ) from exc
            raise
        except BaseException:
            os.close(fd)
            raise
        _lease_fd = fd
        _identity = RuntimeIdentity(instance_id=uuid.uuid4().hex, launch_id=launch_id, pid=os.getpid())
        _phase = "starting"
        return _identity.model_copy()


def release_ownership() -> None:
    """只关闭本进程描述符，不显式解锁；存活 worker 的共享锁继续有效。"""
    global _lease_fd
    with _lock:
        fd, _lease_fd = _lease_fd, None
    if fd is not None:
        os.close(fd)


def identity() -> RuntimeIdentity:
    with _lock:
        if _identity is None or _lease_fd is None:
            raise RuntimeError("尚未取得应用所有权")
        return _identity.model_copy()


def phase() -> str:
    with _lock:
        return _phase


def set_phase(value: str) -> None:
    global _phase
    if value not in {"starting", "running", "stopping", "stopped", "interrupted"}:
        raise ValueError("运行阶段无效")
    with _lock:
        _phase = value


def worker_ownership_fd() -> int:
    with _lock:
        if sys.platform != "darwin" or _lease_fd is None:
            raise RuntimeError("没有可传递的 USB 应用所有权")
        return _lease_fd


def adopt_worker_ownership() -> int:
    """校验私有启动通道传入的锁描述符，worker 仅持有而不重新加锁。"""
    value = os.environ.pop("TOOLBOX_OWNER_FD", "")
    if not value.isdecimal() or int(value) < 3:
        raise RuntimeError("USB 工作进程缺少应用所有权")
    fd = int(value)
    inherited = os.fstat(fd)
    current = os.stat(settings.ownership_lock_path, follow_symlinks=False)
    if not stat.S_ISREG(inherited.st_mode) or (inherited.st_dev, inherited.st_ino) != (current.st_dev, current.st_ino):
        raise RuntimeError("USB 应用所有权描述符无效")
    os.set_inheritable(fd, False)
    return fd


def run_update_guard() -> int:
    """等前一个实例释放应用锁后再持有；不生成凭据或业务记录。

    安装 helper 在替换前必须确认本进程已持锁，否则另一实例可能在替换期间启动。
    """
    deadline = time.monotonic() + settings.APP_SHUTDOWN_TIMEOUT_SECONDS + 150
    while True:
        try:
            owner = acquire_ownership()
            break
        except OwnershipBusyError:
            if time.monotonic() >= deadline:
                return 2
            time.sleep(0.2)
        except (OSError, RuntimeError, ValueError):
            return 2
    try:
        print(json.dumps({"kind": "ready", "launch_id": owner.launch_id, "pid": owner.pid}), flush=True)
        # 父 helper 在替换结束后关闭通道；不解释任何设备或文件操作指令。
        while sys.stdin.buffer.read(1):
            pass
        return 0
    finally:
        release_ownership()
