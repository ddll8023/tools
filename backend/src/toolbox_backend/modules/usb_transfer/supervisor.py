"""监管单个 USB 工作进程，严格关联协议代次，并独立发送取消控制。"""

from __future__ import annotations

import os
import select
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import JsonValue

from toolbox_backend.core import runtime
from toolbox_backend.core.config import settings
from toolbox_backend.core.logging import setup_logger
from toolbox_backend.modules.usb_transfer.protocol import Message, Operation, ProtocolError, encode_message, read_message
from toolbox_backend.modules.usb_transfer.schemas import UsbProgress

logger = setup_logger(__name__)
STARTUP_TIMEOUT_SECONDS = 20.0
SCAN_TIMEOUT_SECONDS = 20.0
OPEN_TIMEOUT_SECONDS = 30.0
LIST_TIMEOUT_SECONDS = 30.0
CLOSE_TIMEOUT_SECONDS = 10.0


class WorkerError(Exception):
    def __init__(self, kind: str, message: str) -> None:
        self.kind, self.message = kind, message
        super().__init__(message)


class WorkerUnavailableError(WorkerError):
    pass


class WorkerTimeoutError(WorkerError):
    pass


@dataclass
class _Pending:
    task_id: str | None
    on_progress: Callable[[UsbProgress], None] | None
    on_event: Callable[[dict[str, JsonValue]], None] | None
    event: threading.Event = field(default_factory=threading.Event)
    response: Message | None = None
    error: WorkerError | None = None
    last_change: float = field(default_factory=time.monotonic)
    progress_key: tuple[object, ...] | None = None
    stage: str = "starting"
    cancel_at: float | None = None


def _worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--toolbox-usb-worker"]
    return [sys.executable, "-m", "toolbox_backend.modules.usb_transfer.worker"]


def _worker_env(generation: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["TOOLBOX_USB_GENERATION"] = generation
    if not getattr(sys, "frozen", False):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        env["PYTHONPATH"] = os.pathsep.join(part for part in (root, env.get("PYTHONPATH")) if part)
    return env

def _worker_launch(generation: str) -> tuple[list[str], dict[str, str], dict[str, object]]:
    """macOS 上把应用所有权描述符交给 worker，使其存活期间仍阻止第二个实例。"""
    env = _worker_env(generation)
    if sys.platform != "darwin":
        return _worker_command(), env, {}
    try:
        descriptor = runtime.worker_ownership_fd()
    except RuntimeError as exc:
        # 没有所有权就不能保证写入归属，宁可拒绝启动也不降级。
        raise WorkerUnavailableError("unavailable", "缺少应用所有权，禁止启动 USB 工作进程") from exc
    env["TOOLBOX_OWNER_FD"] = str(descriptor)
    return _worker_command(), env, {"pass_fds": (descriptor,)}


class UsbWorkerSupervisor:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._start_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._retired: subprocess.Popen[bytes] | None = None
        self._generation: str | None = None
        self._ready = threading.Event()
        self._pending: dict[int, _Pending] = {}
        self._next_id = 0
        self._on_failure: Callable[[str, str], None] | None = None
        # 关闭后不得重新拉起 worker；否则停止确认随时可能被新一轮启动推翻。
        self._closing = False

    def set_failure_handler(self, handler: Callable[[str, str], None]) -> None:
        self._on_failure = handler

    @property
    def generation(self) -> str | None:
        with self._lock:
            return self._generation if self._ready.is_set() else None

    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None and self._ready.is_set()

    def _start(self) -> None:
        with self._start_lock:
            if self._closing:
                raise WorkerUnavailableError("unavailable", "USB 工作进程正在停止，不再接受新的设备操作")
            with self._lock:
                if self._retired is not None:
                    if self._retired.poll() is None:
                        raise WorkerUnavailableError("unavailable", "旧 USB 进程尚未确认退出，禁止建立新连接")
                    self._retired = None
            if self.is_running():
                return
            with self._lock:
                old = self._generation
            if old:
                self.fail_generation(old, "USB 工作进程已失效")
            with self._lock:
                if self._retired is not None and self._retired.poll() is None:
                    raise WorkerUnavailableError("unavailable", "旧 USB 进程尚未确认退出，禁止建立新连接")
            generation = uuid.uuid4().hex
            try:
                command, env, launch_options = _worker_launch(generation)
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, env=env, bufsize=0, **launch_options)
                if process.stdin is None:
                    raise OSError("工作进程输入通道缺失")
                os.set_blocking(process.stdin.fileno(), False)
            except OSError as exc:
                raise WorkerUnavailableError("unavailable", "无法启动 USB 工作进程") from exc
            with self._lock:
                self._process, self._generation = process, generation
                self._ready.clear()
            threading.Thread(target=self._read_stdout, args=(process, generation), daemon=True, name="usb-protocol-reader").start()
            threading.Thread(target=self._read_stderr, args=(process,), daemon=True, name="usb-native-logs").start()
            deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if self._ready.wait(0.05):
                    with self._lock:
                        if self._process is process and process.poll() is None:
                            return
                    break
                with self._lock:
                    if self._process is not process:
                        break
                if process.poll() is not None:
                    break
            self.fail_generation(generation, "USB 工作进程握手失败")
            raise WorkerUnavailableError("unavailable", "USB 工作进程无法完成协议握手")

    def _send(self, process: subprocess.Popen[bytes], message: Message) -> None:
        data = encode_message(message)
        if not self._write_lock.acquire(timeout=2):
            raise OSError("USB 控制通道繁忙")
        try:
            if process.stdin is None:
                raise BrokenPipeError("USB 控制通道关闭")
            fd = process.stdin.fileno()
            deadline = time.monotonic() + 2.0
            offset = 0
            while offset < len(data):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
                    raise TimeoutError("USB 控制消息写入超时")
                try:
                    offset += os.write(fd, data[offset:])
                except BlockingIOError:
                    continue
        finally:
            self._write_lock.release()

    def call(
        self, op: Operation, payload: dict[str, JsonValue] | None = None,
        timeout: float = LIST_TIMEOUT_SECONDS, *, task_id: str | None = None,
        expected_generation: str | None = None, long_operation: bool = False,
        on_progress: Callable[[UsbProgress], None] | None = None,
        on_event: Callable[[dict[str, JsonValue]], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> dict[str, JsonValue]:
        if expected_generation is None:
            self._start()
        with self._lock:
            process, generation = self._process, self._generation
            if process is None or generation is None or not self._ready.is_set() or process.poll() is not None:
                raise WorkerUnavailableError("unavailable", "USB 工作进程已退出")
            if expected_generation is not None and expected_generation != generation:
                raise WorkerUnavailableError("unavailable", "USB 工作进程代次已变化")
            if self._pending:
                raise WorkerError("busy", "设备正忙，请稍后操作")
            self._next_id += 1
            request_id = self._next_id
            request = Message(generation=generation, kind="request", request_id=request_id,
                              task_id=task_id, op=op, payload=payload or {})
            try:
                encode_message(request)
            except ProtocolError as exc:
                raise WorkerError("budget", "设备归属信息超过通信预算，请缩小所选范围") from exc
            pending = _Pending(task_id, on_progress, on_event)
            self._pending[request_id] = pending
        try:
            self._send(process, request)
        except (OSError, ValueError, ProtocolError) as exc:
            self.fail_generation(generation, "USB 控制通道写入失败")
            raise WorkerUnavailableError("unavailable", "USB 控制通道写入失败") from exc
        started = time.monotonic()
        while not pending.event.wait(0.05):
            if cancel is not None and cancel.is_set():
                self.request_cancel(task_id)
            now = time.monotonic()
            with self._lock:
                cancel_at, last_change, stage = pending.cancel_at, pending.last_change, pending.stage
            if cancel_at is not None and now - cancel_at > settings.USB_TRANSFER_CANCEL_GRACE:
                error = WorkerTimeoutError("cancel_timeout", "取消未能及时停止，已强制中断设备连接")
            elif long_operation:
                allowance = settings.USB_TRANSFER_STALL_TIMEOUT if stage in {"uploading", "downloading"} else settings.USB_TRANSFER_METADATA_TIMEOUT
                error = WorkerTimeoutError("timeout", "设备操作停滞，已强制中断连接") if now - last_change > allowance else None
            else:
                error = WorkerTimeoutError("timeout", "设备操作超时，连接已中断") if now - started > timeout else None
            if error is not None:
                self.fail_generation(generation, error.message, error)
                raise error
        with self._lock:
            if self._pending.get(request_id) is pending:
                self._pending.pop(request_id)
        if pending.error is not None:
            raise pending.error
        response = pending.response
        if response is None:
            raise WorkerUnavailableError("unavailable", "USB 工作进程没有返回结果")
        if response.error is not None:
            raise WorkerError(response.error.kind, response.error.message)
        return response.payload

    def request_cancel(self, task_id: str | None) -> None:
        with self._lock:
            match = next(((key, item) for key, item in self._pending.items() if item.task_id == task_id), None)
            process, generation = self._process, self._generation
            if match is None or process is None or generation is None:
                return
            request_id, pending = match
            if pending.cancel_at is not None or pending.event.is_set():
                return
            pending.cancel_at = time.monotonic()
        try:
            self._send(process, Message(generation=generation, kind="cancel", request_id=request_id, task_id=task_id))
        except (OSError, ValueError, ProtocolError):
            self.fail_generation(generation, "取消控制通道失效")

    def _read_stdout(self, process: subprocess.Popen[bytes], generation: str) -> None:
        try:
            if process.stdout is None:
                raise ProtocolError("缺少协议通道")
            while (message := read_message(process.stdout)) is not None:
                with self._lock:
                    if self._process is not process:
                        return
                    if message.generation != generation:
                        raise ProtocolError("工作进程代次不匹配")
                    if message.kind == "ready":
                        if self._ready.is_set():
                            raise ProtocolError("重复握手")
                        self._ready.set()
                        continue
                    if not self._ready.is_set():
                        raise ProtocolError("握手前收到操作消息")
                    pending = self._pending.get(message.request_id)
                    if pending is None or message.task_id != pending.task_id or pending.event.is_set():
                        raise ProtocolError("消息没有有效的在途关联")
                if message.kind == "progress":
                    progress = UsbProgress.model_validate(message.payload)
                    key = (progress.stage, progress.current_name, progress.discovered, progress.processed, progress.current_sent)
                    with self._lock:
                        if key != pending.progress_key:
                            pending.progress_key, pending.last_change = key, time.monotonic()
                        pending.stage = progress.stage
                    if pending.on_progress:
                        pending.on_progress(progress)
                elif message.kind == "event":
                    if pending.on_event is None:
                        raise ProtocolError("当前操作不接受条目事件")
                    pending.on_event(message.payload)
                    with self._lock:
                        pending.last_change = time.monotonic()
                elif message.kind == "result":
                    pending.response = message
                    pending.event.set()
                else:
                    raise ProtocolError("工作进程返回了不允许的消息类型")
        except Exception as exc:
            logger.error("USB 协议通道失效: %s", exc)
        finally:
            self.fail_generation(generation, "USB 工作进程退出或协议通道损坏")

    @staticmethod
    def _read_stderr(process: subprocess.Popen[bytes]) -> None:
        if process.stderr is None:
            return
        window, count = time.monotonic(), 0
        while True:
            data = process.stderr.readline(4096)
            if not data:
                return
            if time.monotonic() - window >= 1:
                window, count = time.monotonic(), 0
            count += 1
            if count <= 5:
                logger.info("[usb-worker] %s", data.decode("utf-8", errors="replace").rstrip())

    def fail_generation(self, generation: str, reason: str, error: WorkerError | None = None) -> None:
        with self._lock:
            if self._generation != generation:
                return
            process = self._process
            self._retired = process
            self._process, self._generation = None, None
            self._ready.clear()
            pending = list(self._pending.values())
            self._pending.clear()
            for item in pending:
                item.error = error or WorkerUnavailableError("unavailable", reason)
                item.event.set()
        # 不在监管锁内调用业务层，避免与会话锁互相等待。
        if self._on_failure:
            self._on_failure(generation, reason)
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                logger.error("USB 工作进程未能确认退出")
            with self._lock:
                if self._retired is process and process.poll() is not None:
                    self._retired = None
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def shutdown(self, deadline: float | None = None, *, seal: bool = True) -> bool:
        """关闭启动入口，并确认当前与 retired 进程都已退出。

        seal=True 用于应用级停止，此后不再允许启动新的工作进程；
        丢弃无效响应对应的 worker 时用 seal=False，保留后续重连能力。
        """
        if seal:
            self._closing = True
        limit = deadline if deadline is not None else time.monotonic() + settings.APP_SHUTDOWN_TIMEOUT_SECONDS
        with self._lock:
            generation = self._generation
            idle = not self._pending
        if generation is not None:
            if idle and self.is_running():
                try:
                    self.call("shutdown", timeout=3, expected_generation=generation)
                except WorkerError:
                    pass
            self.fail_generation(generation, "USB 工作进程已关闭")
        return self._confirm_exit(limit)

    def _confirm_exit(self, limit: float) -> bool:
        """轮询进程表直到退出；超时后强杀并再次确认，不把信号当作已结束。"""
        while True:
            with self._lock:
                alive = [item for item in (self._process, self._retired) if item is not None and item.poll() is None]
                if not alive:
                    self._retired = None
                    return True
            if time.monotonic() >= limit:
                break
            time.sleep(0.05)
        for process in alive:
            try:
                process.kill()
            except OSError:
                pass
        for process in alive:
            try:
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        with self._lock:
            remaining = [item for item in (self._process, self._retired) if item is not None and item.poll() is None]
            if not remaining:
                self._retired = None
            return not remaining
