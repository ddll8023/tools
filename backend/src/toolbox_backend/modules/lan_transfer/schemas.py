"""局域网投送控制面 API Schema。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LanSessionState = Literal["idle", "starting", "active", "closing", "closed", "failed"]


class LanAddressItem(BaseModel):
    """一个可访问的局域网地址及其入口链接。"""

    address: str = Field(..., description="网卡 IPv4 地址")
    url: str = Field(..., description="包含会话凭据的浏览器入口链接")
    is_recommended: bool = Field(False, description="是否为默认出口地址")


class LanCleanupFailure(BaseModel):
    """关闭会话时未能清理的隔离内容。"""

    path: str = Field(..., description="残留内容路径")
    size_bytes: int = Field(0, description="残留内容字节数")


class LanSessionResponse(BaseModel):
    """会话状态快照，开启、查询、停止与口令接口共用。"""

    state: LanSessionState = Field(..., description="会话状态")
    expires_at: str | None = Field(None, description="会话自动关闭时间")
    remaining_seconds: int = Field(0, description="距离自动关闭的剩余秒数")
    transfer_active: bool = Field(False, description="是否有正在进行的上传或下载")
    device_name: str = Field("", description="浏览器页面展示的设备名")
    has_passphrase: bool = Field(False, description="是否已设置访问口令")
    pending_count: int = Field(0, description="等待确认接收的文件数量")
    used_bytes: int = Field(0, description="隔离区已占用字节数")
    max_bytes: int = Field(0, description="本次会话隔离区可占用上限")
    addresses: list[LanAddressItem] = Field(default_factory=list, description="可用地址")
    free_disk_bytes: int | None = Field(None, description="接收盘可用空间")
    cleanup_failures: list[LanCleanupFailure] = Field(
        default_factory=list,
        description="关闭时清理失败、仍占用磁盘的隔离内容",
    )
    message: str = Field("", description="面向用户的说明")

    model_config = ConfigDict(from_attributes=True)


class LanPendingItem(BaseModel):
    """一个等待用户确认的接收内容。"""

    upload_id: str = Field(..., description="待确认内容标识")
    name: str = Field(..., description="净化后的文件名")
    size_bytes: int = Field(0, description="文件字节数")
    uploaded_at: str = Field("", description="上传完成时间")


class LanPendingListResponse(BaseModel):
    """待接收列表。"""

    files: list[LanPendingItem] = Field(default_factory=list, description="待确认内容")


class PendingFileRequest(BaseModel):
    """接收或拒绝某个待确认内容。"""

    upload_id: str = Field(..., min_length=1, max_length=64, description="待确认内容标识")


class AddOutgoingRequest(BaseModel):
    """把本机文件加入待取件清单；路径必须为绝对路径。"""

    paths: list[str] = Field(..., min_length=1, description="文件绝对路径")


class RemoveOutgoingRequest(BaseModel):
    """从待取件清单移除文件。"""

    file_id: str = Field(..., min_length=1, max_length=64, description="待取件内容标识")


class LanOutgoingItem(BaseModel):
    """一个等待对方取件的文件。"""

    file_id: str = Field(..., description="待取件内容标识")
    name: str = Field(..., description="文件名")
    size_bytes: int = Field(0, description="文件字节数")
    available: bool = Field(True, description="源文件当前是否仍可读取")


class LanOutgoingListResponse(BaseModel):
    """待取件清单。"""

    files: list[LanOutgoingItem] = Field(default_factory=list, description="待取件文件")


class LanPreferencesResponse(BaseModel):
    """设备名与接收目录的生效值及自定义状态。"""

    device_name: str = Field("", description="生效的设备名")
    receive_dir: str = Field("", description="生效的接收目录")
    default_device_name: str = Field("", description="设备名的回退值")
    default_receive_dir: str = Field("", description="接收目录的回退值")
    is_customized: bool = Field(False, description="是否已有偏好被用户自定义")


class LanPreferencesUpdateRequest(BaseModel):
    """更新偏好；字段传空字符串表示清除该项并回退默认值，不传表示不修改。"""

    device_name: str | None = Field(None, max_length=60, description="设备名")
    receive_dir: str | None = Field(None, max_length=1024, description="接收目录绝对路径")


class LanReceiveRecordItem(BaseModel):
    """一条接收成功记录。"""

    name: str = Field(..., description="文件名")
    size_bytes: int = Field(0, description="文件字节数")
    received_at: str = Field("", description="接收时间")
    destination: str = Field("", description="目标绝对路径")


class LanReceiveRecordListResponse(BaseModel):
    """接收记录列表。"""

    records: list[LanReceiveRecordItem] = Field(default_factory=list, description="接收记录")


class LanRecoveryResponse(BaseModel):
    """本次启动回收上次异常终止遗留内容的结果。"""

    recovered: bool = Field(False, description="本次启动是否执行过回收")
    removed_files: int = Field(0, description="已回收文件数")
    removed_bytes: int = Field(0, description="已回收字节数")
    failures: list[str] = Field(default_factory=list, description="回收失败的残留路径")


class PassphraseRequest(BaseModel):
    """设置或清除访问口令；空字符串表示清除。"""

    passphrase: str = Field("", max_length=128, description="访问口令")
