"""仅供 USB 工作进程使用的 libmtp v1.1.23 公共 ABI 绑定。

不解引用私有 PTP 结构；Uncached 只避免全盘预取，元数据仍可能命中库内缓存。
"""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from toolbox_backend.core.config import settings
from toolbox_backend.core.logging import setup_logger
from toolbox_backend.modules.usb_transfer.schemas import UsbDirectoryEntry, UsbStorageItem
from toolbox_backend.modules.usb_transfer.session import ROOT_FOLDER_ID

logger = setup_logger(__name__)
FILETYPE_FOLDER = 0
FILETYPE_UNKNOWN = 44
_UINT64_UNKNOWN = 0xFFFFFFFFFFFFFFFF
_ProgressCallback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_void_p)


class MtpError(Exception):
    def __init__(self, kind: str, message: str, object_id: int | None = None) -> None:
        self.kind = kind
        self.message = message
        self.object_id = object_id
        super().__init__(message)


class _DeviceEntry(ctypes.Structure):
    _fields_ = [
        ("vendor", ctypes.c_char_p), ("vendor_id", ctypes.c_uint16),
        ("product", ctypes.c_char_p), ("product_id", ctypes.c_uint16),
        ("device_flags", ctypes.c_uint32),
    ]


class _RawDevice(ctypes.Structure):
    _fields_ = [("device_entry", _DeviceEntry), ("bus_location", ctypes.c_uint32), ("devnum", ctypes.c_uint8)]


class _File(ctypes.Structure):
    pass


_File._fields_ = [
    ("item_id", ctypes.c_uint32), ("parent_id", ctypes.c_uint32),
    ("storage_id", ctypes.c_uint32), ("filename", ctypes.c_char_p),
    ("filesize", ctypes.c_uint64), ("modificationdate", ctypes.c_long),
    ("filetype", ctypes.c_int), ("next", ctypes.POINTER(_File)),
]


class _Storage(ctypes.Structure):
    pass


_Storage._fields_ = [
    ("id", ctypes.c_uint32), ("storage_type", ctypes.c_uint16),
    ("filesystem_type", ctypes.c_uint16), ("access_capability", ctypes.c_uint16),
    ("max_capacity", ctypes.c_uint64), ("free_space_in_bytes", ctypes.c_uint64),
    ("free_space_in_objects", ctypes.c_uint64), ("description", ctypes.c_char_p),
    ("volume_identifier", ctypes.c_char_p), ("next", ctypes.POINTER(_Storage)),
    ("prev", ctypes.POINTER(_Storage)),
]


class _MtpDevice(ctypes.Structure):
    _fields_ = [
        ("object_bitsize", ctypes.c_uint8), ("params", ctypes.c_void_p),
        ("usbinfo", ctypes.c_void_p), ("storage", ctypes.POINTER(_Storage)),
    ]


class _Error(ctypes.Structure):
    pass


_Error._fields_ = [("errornumber", ctypes.c_int), ("error_text", ctypes.c_char_p), ("next", ctypes.POINTER(_Error))]


@dataclass(frozen=True)
class RawDevice:
    bus_location: int
    devnum: int
    vendor_id: int
    product_id: int
    vendor: str
    product: str
    device_flags: int


@dataclass
class DirectoryListing:
    entries: list[UsbDirectoryEntry]
    missing_ids: list[int]

    @property
    def complete(self) -> bool:
        return not self.missing_ids


_library: ctypes.CDLL | None = None


def _declare(library: ctypes.CDLL) -> None:
    device = ctypes.POINTER(_MtpDevice)
    signatures = {
        "LIBMTP_Init": ([], None),
        "LIBMTP_Detect_Raw_Devices": ([ctypes.POINTER(ctypes.POINTER(_RawDevice)), ctypes.POINTER(ctypes.c_int)], ctypes.c_int),
        "LIBMTP_Open_Raw_Device_Uncached": ([ctypes.POINTER(_RawDevice)], device),
        "LIBMTP_Release_Device": ([device], None),
        "LIBMTP_Get_Storage": ([device, ctypes.c_int], ctypes.c_int),
        "LIBMTP_Get_Children": ([device, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32))], ctypes.c_int),
        "LIBMTP_Get_Filemetadata": ([device, ctypes.c_uint32], ctypes.POINTER(_File)),
        "LIBMTP_destroy_file_t": ([ctypes.POINTER(_File)], None),
        "LIBMTP_Get_Errorstack": ([device], ctypes.POINTER(_Error)),
        "LIBMTP_Clear_Errorstack": ([device], None),
        "LIBMTP_FreeMemory": ([ctypes.c_void_p], None),
        "LIBMTP_Get_File_To_File_Descriptor": ([device, ctypes.c_uint32, ctypes.c_int, _ProgressCallback, ctypes.c_void_p], ctypes.c_int),
        "LIBMTP_Send_File_From_File_Descriptor": ([device, ctypes.c_int, ctypes.POINTER(_File), _ProgressCallback, ctypes.c_void_p], ctypes.c_int),
        "LIBMTP_Create_Folder": ([device, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32], ctypes.c_uint32),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(library, name)
        function.argtypes = arguments
        function.restype = result
    for name in ("Friendlyname", "Modelname", "Manufacturername", "Serialnumber"):
        function = getattr(library, f"LIBMTP_Get_{name}")
        function.argtypes = [device]
        function.restype = ctypes.c_void_p


def _load_library() -> ctypes.CDLL:
    global _library
    if _library is not None:
        return _library
    path = settings.usb_transfer_library_path
    if path is None:
        raise MtpError("unavailable", "未找到 MTP 运行库（libmtp）")
    try:
        library = ctypes.CDLL(path)
        _declare(library)
        library.LIBMTP_Init()
    except (OSError, AttributeError) as exc:
        logger.error("MTP 运行库加载或符号解析失败: %s", exc)
        raise MtpError("unavailable", "MTP 运行库无法加载或缺少所需接口") from exc
    _library = library
    return library


def display_text(value: str) -> str:
    return "".join(char for char in value if ord(char) >= 32 and ord(char) != 127).strip()[:4096]


def _decode(value: bytes | None) -> str:
    return (value or b"").decode("utf-8", errors="replace")


def _time(value: int) -> str | None:
    try:
        return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds") if value > 0 else None
    except (OSError, OverflowError, ValueError):
        return None


def check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise MtpError("cancelled", "操作已协作停止")


def detect_devices() -> list[RawDevice]:
    """发现可能打开 USB 描述符，不承诺对其他应用完全无影响。"""
    library = _load_library()
    pointer = ctypes.POINTER(_RawDevice)()
    count = ctypes.c_int()
    result = library.LIBMTP_Detect_Raw_Devices(ctypes.byref(pointer), ctypes.byref(count))
    try:
        if result == 5:
            return []
        if result != 0 or count.value < 0 or count.value > 1024 or (count.value and not pointer):
            raise MtpError("scan_failed", "无法枚举 USB 设备")
        return [RawDevice(
            bus_location=int(item.bus_location), devnum=int(item.devnum),
            vendor_id=int(item.device_entry.vendor_id), product_id=int(item.device_entry.product_id),
            vendor=display_text(_decode(item.device_entry.vendor)),
            product=display_text(_decode(item.device_entry.product)),
            device_flags=int(item.device_entry.device_flags),
        ) for item in (pointer[index] for index in range(count.value))]
    finally:
        if pointer:
            library.LIBMTP_FreeMemory(ctypes.cast(pointer, ctypes.c_void_p))


def open_device(bus_location: int, devnum: int, vendor_id: int, product_id: int) -> MtpDevice:
    library = _load_library()
    match = next((item for item in detect_devices() if (
        item.bus_location, item.devnum, item.vendor_id, item.product_id
    ) == (bus_location, devnum, vendor_id, product_id)), None)
    if match is None:
        raise MtpError("no_device", "设备已断开或无法访问，请重新扫描")
    raw = _RawDevice()
    raw.device_entry.vendor = match.vendor.encode("utf-8")
    raw.device_entry.product = match.product.encode("utf-8")
    raw.device_entry.vendor_id = match.vendor_id
    raw.device_entry.product_id = match.product_id
    raw.device_entry.device_flags = match.device_flags
    raw.bus_location = match.bus_location
    raw.devnum = match.devnum
    pointer = library.LIBMTP_Open_Raw_Device_Uncached(ctypes.byref(raw))
    if not pointer:
        raise MtpError("device_open_failed", "无法打开设备，请检查文件传输模式、连接和其他应用占用")
    return MtpDevice(library, pointer, raw)


class MtpDevice:
    def __init__(self, library: ctypes.CDLL, pointer: ctypes.POINTER(_MtpDevice), raw: _RawDevice) -> None:
        self._library = library
        self._pointer = pointer
        self._raw = raw  # 原生层复制了结构体，字符串的 Python 所有权仍需保持到释放。
        self._released = False

    def _begin(self) -> None:
        if self._released:
            raise MtpError("not_open", "设备会话已释放")
        self._library.LIBMTP_Clear_Errorstack(self._pointer)

    def _errors(self) -> list[int]:
        node = self._library.LIBMTP_Get_Errorstack(self._pointer)
        codes: list[int] = []
        while node and len(codes) < 100:
            codes.append(int(node.contents.errornumber))
            if len(codes) == 1:
                logger.debug("MTP 错误: %s", _decode(node.contents.error_text)[:300])
            node = node.contents.next
        self._library.LIBMTP_Clear_Errorstack(self._pointer)
        if any(code in {3, 5, 7} for code in codes):
            raise MtpError("disconnected", "设备通信失效，请重新连接")
        return codes

    def info(self) -> dict[str, str | None]:
        values: dict[str, str | None] = {}
        for key, suffix in (("name", "Friendlyname"), ("model", "Modelname"), ("manufacturer", "Manufacturername"), ("serial", "Serialnumber")):
            self._begin()
            address = getattr(self._library, f"LIBMTP_Get_{suffix}")(self._pointer)
            try:
                values[key] = display_text(_decode(ctypes.string_at(address))) if address else ""
            finally:
                if address:
                    self._library.LIBMTP_FreeMemory(address)
                self._errors()
        values["name"] = values["name"] or values["model"] or "MTP 设备"
        values["serial"] = values["serial"] or None
        return values

    def storages(self) -> list[UsbStorageItem]:
        self._begin()
        result = self._library.LIBMTP_Get_Storage(self._pointer, 0)
        errors = self._errors()
        if result not in {0, 1} or errors:
            raise MtpError("storage_failed", "无法读取设备存储信息")
        complete = result == 0
        values: list[UsbStorageItem] = []
        node = self._pointer.contents.storage
        seen: set[int] = set()
        while node:
            item = node.contents
            storage_id = int(item.id)
            if storage_id in seen or not 0 < storage_id < ROOT_FOLDER_ID or len(seen) >= 128:
                raise MtpError("storage_failed", "设备存储列表异常")
            seen.add(storage_id)
            capacity, free = int(item.max_capacity), int(item.free_space_in_bytes)
            values.append(UsbStorageItem(
                id=storage_id, description=display_text(_decode(item.description)) or "存储",
                capacity_bytes=capacity if complete and capacity != _UINT64_UNKNOWN else None,
                free_bytes=free if complete and free != _UINT64_UNKNOWN else None,
                access_capability=int(item.access_capability) if complete else None,
                information_complete=complete,
            ))
            node = item.next
        return values

    def children(self, storage_id: int, folder_id: int, cancel: threading.Event | None = None) -> list[int]:
        check_cancel(cancel)
        self._begin()
        pointer = ctypes.POINTER(ctypes.c_uint32)()
        count = self._library.LIBMTP_Get_Children(self._pointer, storage_id, folder_id, ctypes.byref(pointer))
        try:
            errors = self._errors()
            if count < 0 or errors or (count and not pointer):
                raise MtpError("list_failed", "无法枚举设备目录")
            if count > settings.USB_TRANSFER_MAX_ENTRIES:
                raise MtpError("budget", "该目录对象数量超过本次任务预算")
            values = [int(pointer[index]) for index in range(count)]
            if len(set(values)) != len(values) or any(not 0 < item < ROOT_FOLDER_ID for item in values):
                raise MtpError("list_failed", "设备返回了重复或无效对象标识")
            check_cancel(cancel)
            return values
        finally:
            if pointer:
                self._library.LIBMTP_FreeMemory(ctypes.cast(pointer, ctypes.c_void_p))

    def metadata(self, object_id: int) -> UsbDirectoryEntry:
        """字段是 libmtp 报告值，不将缓存命中称为设备实时核对。"""
        self._begin()
        pointer = self._library.LIBMTP_Get_Filemetadata(self._pointer, object_id)
        try:
            errors = self._errors()
            if not pointer:
                raise MtpError("metadata_failed", "无法读取对象信息")
            item = pointer.contents
            if int(item.item_id) != object_id:
                raise MtpError("metadata_failed", "设备元数据对象标识与请求不符")
            try:
                raw_name = (item.filename or b"").decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise MtpError("metadata_failed", "设备名称不是有效 UTF-8，无法安全处理") from exc
            if len(raw_name) > 4096:
                raise MtpError("metadata_failed", "设备名称超过处理预算")
            is_folder = int(item.filetype) == FILETYPE_FOLDER
            size = int(item.filesize)
            try:
                return UsbDirectoryEntry(
                    object_id=int(item.item_id), parent_id=int(item.parent_id) or ROOT_FOLDER_ID,
                    storage_id=int(item.storage_id), raw_name=raw_name,
                    name=display_text(raw_name) or "未命名项目", is_folder=is_folder,
                    size_bytes=None if is_folder or errors or size == _UINT64_UNKNOWN else size,
                    modified_at=_time(int(item.modificationdate)),
                )
            except ValueError as exc:
                raise MtpError("metadata_failed", "设备对象归属信息无效") from exc
        finally:
            if pointer:
                self._library.LIBMTP_destroy_file_t(pointer)

    def list_directory(
        self, storage_id: int, folder_id: int, cancel: threading.Event | None = None,
        progress: Callable[[int], None] | None = None,
    ) -> DirectoryListing:
        ids = self.children(storage_id, folder_id, cancel)
        if progress:
            progress(0)
        entries: list[UsbDirectoryEntry] = []
        missing: list[int] = []
        for index, object_id in enumerate(ids):
            check_cancel(cancel)
            try:
                item = self.metadata(object_id)
                if item.object_id != object_id or item.storage_id != storage_id or item.parent_id != folder_id:
                    raise MtpError("metadata_failed", "设备返回了目录范围之外的对象")
                entries.append(item)
            except MtpError as exc:
                if exc.kind in {"disconnected", "cancelled", "not_open"}:
                    raise
                missing.append(object_id)
            if progress:
                progress(index + 1)
        return DirectoryListing(entries, missing)

    def _callback(self, cancel: threading.Event, progress: Callable[[int, int], None]) -> _ProgressCallback:
        def callback(sent: int, total: int, _data: object) -> int:
            try:
                progress(sent, total)
                return 1 if cancel.is_set() else 0
            except Exception:
                cancel.set()
                return 1
        return _ProgressCallback(callback)

    def download(self, object_id: int, fd: int, cancel: threading.Event, progress: Callable[[int, int], None]) -> None:
        check_cancel(cancel)
        callback = self._callback(cancel, progress)
        self._begin()
        result = self._library.LIBMTP_Get_File_To_File_Descriptor(self._pointer, object_id, fd, callback, None)
        errors = self._errors()
        if result != 0:
            raise MtpError("cancelled" if 8 in errors or cancel.is_set() else "download_failed", "文件下载未正常完成")

    def upload(
        self, storage_id: int, folder_id: int, name: str, fd: int, size: int,
        cancel: threading.Event, progress: Callable[[int, int], None],
    ) -> int:
        check_cancel(cancel)
        name_buffer = ctypes.create_string_buffer(name.encode("utf-8"))
        # Python 拥有结构和可写名称，不能对其调用原生 destroy_file_t。
        data = _File()
        data.parent_id, data.storage_id = folder_id, storage_id
        data.filename = ctypes.cast(name_buffer, ctypes.c_char_p)
        data.filesize, data.filetype = size, FILETYPE_UNKNOWN
        callback = self._callback(cancel, progress)
        self._begin()
        result = self._library.LIBMTP_Send_File_From_File_Descriptor(self._pointer, fd, ctypes.byref(data), callback, None)
        object_id = int(data.item_id)
        reliable_id = object_id if 0 < object_id < ROOT_FOLDER_ID else None
        try:
            errors = self._errors()
        except MtpError as exc:
            exc.object_id = reliable_id
            raise
        if result != 0 or reliable_id is None:
            kind = "cancelled" if 8 in errors or cancel.is_set() else "upload_failed"
            raise MtpError(kind, "上传未正常完成，设备中可能已有不完整对象", reliable_id)
        return reliable_id

    def create_folder(self, storage_id: int, folder_id: int, name: str, cancel: threading.Event) -> int:
        check_cancel(cancel)
        buffer = ctypes.create_string_buffer(name.encode("utf-8"))
        self._begin()
        object_id = int(self._library.LIBMTP_Create_Folder(self._pointer, buffer, folder_id, storage_id))
        try:
            errors = self._errors()
        except MtpError as exc:
            exc.object_id = object_id if 0 < object_id < ROOT_FOLDER_ID else None
            raise
        if not 0 < object_id < ROOT_FOLDER_ID or errors:
            raise MtpError("create_failed", "设备目录创建结果未确认", object_id if 0 < object_id < ROOT_FOLDER_ID else None)
        return object_id

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._library.LIBMTP_Release_Device(self._pointer)
