"""桌面运行时控制契约：只报告所属实例和 USB 停止确认，不公开凭据。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RuntimeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    instance_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    launch_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    pid: int = Field(ge=1)


class RuntimeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_instance_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class RuntimeStatus(RuntimeIdentity):
    phase: Literal["starting", "running", "stopping", "stopped", "interrupted"]
    usb_active_tasks: int = Field(ge=0)
    usb_busy: bool
    usb_stopped: bool
    usb_forced: bool
    record_errors: list[str]
