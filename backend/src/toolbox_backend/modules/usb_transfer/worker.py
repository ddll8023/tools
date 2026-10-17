"""USB 子进程：原生调用单线程执行，独立读取取消和父通道关闭。"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import BinaryIO

from pydantic import Field, JsonValue, ValidationError

from toolbox_backend.core import runtime
from toolbox_backend.core.config import settings
from toolbox_backend.core.logging import setup_logger
from toolbox_backend.modules.usb_transfer import mtp
from toolbox_backend.modules.usb_transfer.local_files import LocalConflict, LocalFailure
from toolbox_backend.modules.usb_transfer.protocol import Message, ProtocolError, WireError, encode_message, read_message
from toolbox_backend.modules.usb_transfer.schemas import (
    FolderId, Identifier, StorageId, TransferStart, UsbModel, UsbProgress,
)
from toolbox_backend.modules.usb_transfer.transfer import TransferContext

logger = setup_logger(__name__)


class _Open(UsbModel):
    session_id: Identifier
    bus_location: int = Field(ge=0, le=0xFFFFFFFF)
    devnum: int = Field(ge=0, le=255)
    vendor_id: int = Field(ge=0, le=65535)
    product_id: int = Field(ge=0, le=65535)


class _Session(UsbModel):
    session_id: Identifier


class _List(_Session):
    storage_id: StorageId
    folder_id: FolderId


class _Step(_Session):
    entry_id: str = Field(min_length=1, max_length=64)


@dataclass
class _Frame:
    message: Message
    sent: threading.Event = field(default_factory=threading.Event)


class _Output:
    """只有输出线程写协议；原生回调只替换小型进度快照。"""

    def __init__(self, stream: BinaryIO, parent_closed: threading.Event) -> None:
        self.stream, self.parent_closed = stream, parent_closed
        self.frames: queue.Queue[_Frame] = queue.Queue(maxsize=32)
        self.lock = threading.Lock()
        self.latest: Message | None = None
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="usb-protocol-output")
        self.thread.start()

    def progress(self, message: Message) -> None:
        with self.lock:
            self.latest = message

    def send(self, message: Message, wait: bool = False) -> None:
        if message.kind == "result":
            with self.lock:
                self.latest = None
        frame = _Frame(message)
        while not self.parent_closed.is_set():
            try:
                self.frames.put(frame, timeout=0.1)
                break
            except queue.Full:
                continue
        else:
            raise BrokenPipeError("父进程已关闭通道")
        if wait:
            while not frame.sent.wait(0.1):
                if self.parent_closed.is_set():
                    raise BrokenPipeError("协议输出失败")

    def _write(self, message: Message) -> None:
        data = encode_message(message)
        offset = 0
        while offset < len(data):
            written = self.stream.write(data[offset:])
            if written is None or written <= 0:
                raise BrokenPipeError("协议输出关闭")
            offset += written

    def _run(self) -> None:
        try:
            while not self.stopping.is_set() or not self.frames.empty():
                try:
                    frame = self.frames.get(timeout=0.1)
                except queue.Empty:
                    with self.lock:
                        progress, self.latest = self.latest, None
                    if progress is not None:
                        self._write(progress)
                    continue
                self._write(frame.message)
                frame.sent.set()
        except (OSError, ValueError, ProtocolError):
            self.parent_closed.set()

    def close(self) -> None:
        self.stopping.set()
        self.thread.join(timeout=1)


class _Input:
    def __init__(self, generation: str, parent_closed: threading.Event) -> None:
        self.generation, self.parent_closed = generation, parent_closed
        self.commands: queue.Queue[tuple[Message, threading.Event]] = queue.Queue(maxsize=1)
        self.lock = threading.Lock()
        self.active: Message | None = None
        self.cancel = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="usb-control-input").start()
        threading.Thread(target=self._watch_parent, daemon=True, name="usb-parent-watch").start()

    def _run(self) -> None:
        try:
            while (message := read_message(sys.stdin.buffer)) is not None:
                if message.generation != self.generation:
                    raise ProtocolError("父进程代次不匹配")
                with self.lock:
                    if message.kind == "cancel":
                        if self.active is not None and (message.request_id, message.task_id) == (self.active.request_id, self.active.task_id):
                            self.cancel.set()
                        # 完成结果与迟到取消可以交错；不能把它作用于下一次请求。
                        continue
                    if message.kind != "request" or self.active is not None:
                        raise ProtocolError("请求类型或串行边界无效")
                    self.active, self.cancel = message, threading.Event()
                    self.commands.put_nowait((message, self.cancel))
        except (OSError, ValueError, ProtocolError, queue.Full):
            logger.error("USB 父控制通道已失效")
        finally:
            with self.lock:
                self.cancel.set()
            self.parent_closed.set()

    def finished(self) -> None:
        with self.lock:
            self.active = None

    def _watch_parent(self) -> None:
        self.parent_closed.wait()
        time.sleep(settings.USB_TRANSFER_CANCEL_GRACE)
        # 释放句柄也可能卡在原生调用中；失去父监管后必须有独立退出上限。
        os._exit(2)


class _Worker:
    def __init__(self, generation: str, output: _Output) -> None:
        self.generation, self.output = generation, output
        self.device: mtp.MtpDevice | None = None
        self.session_id: str | None = None
        self.transfer: TransferContext | None = None

    def close_device(self) -> None:
        if self.transfer is not None:
            self.transfer.close()
            self.transfer = None
        device, self.device = self.device, None
        self.session_id = None
        if device is not None:
            device.release()

    def _require_session(self, session_id: str) -> mtp.MtpDevice:
        if self.device is None or self.session_id != session_id:
            raise mtp.MtpError("not_open", "设备会话已失效")
        return self.device

    def handle(self, message: Message, cancel: threading.Event) -> dict[str, JsonValue]:
        def progress(value: UsbProgress) -> None:
            self.output.progress(Message(generation=self.generation, kind="progress", request_id=message.request_id,
                                         task_id=message.task_id, payload=value.model_dump(mode="json")))

        def event(value: dict[str, JsonValue]) -> None:
            mtp.check_cancel(cancel)
            self.output.send(Message(generation=self.generation, kind="event", request_id=message.request_id,
                                     task_id=message.task_id, payload=value))

        if message.op == "scan":
            if self.device is not None:
                raise mtp.MtpError("busy", "已有设备会话，不能并发扫描")
            return {"devices": [item.__dict__ for item in mtp.detect_devices()]}
        if message.op == "open":
            arguments = _Open.model_validate(message.payload)
            if self.device is not None:
                raise mtp.MtpError("busy", "已有设备会话")
            device = mtp.open_device(arguments.bus_location, arguments.devnum, arguments.vendor_id, arguments.product_id)
            try:
                info = device.info()
                storages = device.storages()
                if not storages:
                    raise mtp.MtpError("storage_failed", "设备没有暴露可用存储")
            except BaseException:
                device.release()
                raise
            self.device, self.session_id = device, arguments.session_id
            return {"device": info, "storages": [item.model_dump(mode="json") for item in storages]}
        if message.op == "shutdown":
            self.close_device()
            return {}
        if message.op == "list":
            arguments = _List.model_validate(message.payload)
            device = self._require_session(arguments.session_id)
            listing = device.list_directory(arguments.storage_id, arguments.folder_id, cancel,
                                            lambda count: progress(UsbProgress(stage="enumerating", processed=count)))
            return {"entries": [item.model_dump(mode="json") for item in listing.entries],
                    "missing_ids": listing.missing_ids, "complete": listing.complete}
        if message.op == "plan":
            arguments = TransferStart.model_validate(message.payload)
            device = self._require_session(arguments.request.session_id)
            if message.task_id != arguments.task_id or self.transfer is not None:
                raise mtp.MtpError("bad_request", "任务上下文关联无效")
            self.transfer = TransferContext(device, arguments, progress, event)
            return self.transfer.plan(cancel)
        if message.op == "step":
            arguments = _Step.model_validate(message.payload)
            self._require_session(arguments.session_id)
            transfer = self.transfer
            if transfer is None or transfer.start.task_id != message.task_id:
                raise mtp.MtpError("bad_request", "任务上下文不存在")
            # 每次操作重新绑定当前请求的输出关联，不能沿用 plan 请求 ID。
            transfer.progress, transfer.event = progress, event
            result = transfer.step(arguments.entry_id, cancel)
            return {"entry": result.model_dump(mode="json"), "connection_lost": transfer.connection_lost}
        if message.op in {"finish", "close"}:
            arguments = _Session.model_validate(message.payload)
            self._require_session(arguments.session_id)
            if message.op == "close":
                self.close_device()
            elif self.transfer is not None:
                if self.transfer.start.task_id != message.task_id:
                    raise mtp.MtpError("bad_request", "任务结束关联无效")
                self.transfer.close()
                self.transfer = None
            return {}
        raise mtp.MtpError("bad_request", "不支持的设备操作")


def main() -> int:
    generation = os.environ.get("TOOLBOX_USB_GENERATION", "")
    # 继承父进程的应用所有权：worker 存活期间第二个实例仍会被阻止。
    # 描述符保持打开到进程结束，不在这里重新加锁，也不生成凭据或恢复记录。
    try:
        _owner_fd = runtime.adopt_worker_ownership() if sys.platform == "darwin" else None
    except RuntimeError:
        return 2
    parent_closed = threading.Event()
    # 必须重定向 fd 1，而不是只替换 sys.stdout；libmtp 的 fprintf 不经过 Python。
    sys.stdout.flush()
    protocol_stream = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    output = _Output(protocol_stream, parent_closed)
    worker = _Worker(generation, output)
    control = _Input(generation, parent_closed)
    try:
        output.send(Message(generation=generation, kind="ready"), wait=True)
        while not parent_closed.is_set():
            try:
                message, cancel = control.commands.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                payload = worker.handle(message, cancel)
                result = Message(generation=generation, kind="result", request_id=message.request_id,
                                 task_id=message.task_id, payload=payload)
            except mtp.MtpError as exc:
                result = Message(generation=generation, kind="result", request_id=message.request_id,
                                 task_id=message.task_id, error=WireError(kind=exc.kind, message=exc.message))
            except (OSError, LocalFailure, LocalConflict) as exc:
                result = Message(generation=generation, kind="result", request_id=message.request_id,
                                 task_id=message.task_id, error=WireError(kind="local_path", message=(
                                     str(exc)[:4096] if isinstance(exc, (LocalFailure, LocalConflict)) else
                                     "本机路径不可访问，请检查实际目录、权限和符号链接"
                                 )))
            except ValidationError:
                result = Message(generation=generation, kind="result", request_id=message.request_id,
                                 task_id=message.task_id, error=WireError(kind="bad_request", message="设备操作参数无效"))
            except Exception:
                logger.error("USB 操作异常: op=%s", message.op, exc_info=True)
                result = Message(generation=generation, kind="result", request_id=message.request_id,
                                 task_id=message.task_id, error=WireError(kind="internal", message="设备操作未正常完成"))
            # 先释放输入槽位，再发最终结果；下一条请求只能在父进程收到结果后到达。
            control.finished()
            try:
                encode_message(result)
            except ProtocolError:
                result = Message(generation=generation, kind="result", request_id=message.request_id,
                                 task_id=message.task_id, error=WireError(kind="budget", message="设备结果超过通信预算，请缩小所选范围或目录"))
            output.send(result, wait=True)
            if message.op == "shutdown":
                break
    except (OSError, ValueError, ProtocolError):
        return 2
    finally:
        parent_closed.set()
        try:
            worker.close_device()
        finally:
            output.close()
            protocol_stream.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
