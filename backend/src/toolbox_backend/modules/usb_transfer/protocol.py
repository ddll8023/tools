"""USB 私有 JSON 行协议：严格消息关联、有限帧长，不承载文件内容。"""

from __future__ import annotations

from typing import BinaryIO, Literal

from pydantic import Field, JsonValue, ValidationError, model_validator

from toolbox_backend.core.config import settings
from toolbox_backend.modules.usb_transfer.schemas import Identifier, UsbModel

PROTOCOL_VERSION = 2
Operation = Literal["scan", "open", "close", "list", "plan", "step", "finish", "shutdown"]


class ProtocolError(Exception):
    """通道损坏必须失效进程，不能忽略后继续写设备。"""


class WireError(UsbModel):
    kind: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=4096)


class Message(UsbModel):
    protocol: Literal[2] = PROTOCOL_VERSION
    generation: Identifier
    kind: Literal["ready", "request", "result", "progress", "event", "cancel"]
    request_id: int | None = Field(None, ge=1, le=0x7FFFFFFFFFFFFFFF)
    task_id: Identifier | None = None
    op: Operation | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    error: WireError | None = None

    @model_validator(mode="after")
    def check_shape(self) -> Message:
        if self.kind == "ready":
            if self.request_id is not None or self.op is not None or self.task_id is not None:
                raise ValueError("握手不能携带请求")
        elif self.request_id is None:
            raise ValueError("缺少请求关联")
        if self.kind == "request" and self.op is None:
            raise ValueError("缺少操作")
        if self.kind != "result" and self.error is not None:
            raise ValueError("错误只允许出现在结果中")
        if self.kind != "request" and self.op is not None:
            raise ValueError("非请求消息不能携带操作")
        if self.kind in {"ready", "cancel"} and self.payload:
            raise ValueError("握手和取消不能携带操作数据")
        if self.kind == "request":
            task_operation = self.op in {"plan", "step", "finish"}
            if task_operation != (self.task_id is not None):
                raise ValueError("操作与任务关联不符")
        return self


def encode_message(message: Message) -> bytes:
    data = message.model_dump_json().encode("utf-8") + b"\n"
    if len(data) > settings.USB_TRANSFER_MAX_MESSAGE_BYTES:
        raise ProtocolError("USB 消息超过预算")
    return data


def read_message(stream: BinaryIO) -> Message | None:
    """单次读取有界；不允许用无限 readline 吞入原生输出。"""
    line = stream.readline(settings.USB_TRANSFER_MAX_MESSAGE_BYTES + 1)
    if not line:
        return None
    if len(line) > settings.USB_TRANSFER_MAX_MESSAGE_BYTES or not line.endswith(b"\n"):
        raise ProtocolError("USB 消息过长或不完整")
    try:
        return Message.model_validate_json(line, strict=True)
    except (ValidationError, ValueError) as exc:
        raise ProtocolError("USB 消息格式或版本无效") from exc
