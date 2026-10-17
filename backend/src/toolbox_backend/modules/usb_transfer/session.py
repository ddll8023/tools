"""USB 会话内对象归属及目录链；旧会话引用不用于重连恢复。"""

from __future__ import annotations

from dataclasses import dataclass, field

from toolbox_backend.core.config import settings
from toolbox_backend.modules.usb_transfer.schemas import UsbDeviceItem, UsbDirectoryEntry, UsbStorageItem

ROOT_FOLDER_ID = 0xFFFFFFFF


class ReferenceBudgetError(ValueError):
    """会话引用已满，不再累积整个设备的对象索引。"""


@dataclass
class UsbSession:
    session_id: str
    generation: str
    device: UsbDeviceItem
    storages: list[UsbStorageItem]
    created_at: float
    last_response_at: float
    closing: bool = False
    objects: dict[tuple[int, int], UsbDirectoryEntry] = field(default_factory=dict)
    complete_folders: set[tuple[int, int]] = field(default_factory=set)

    def has_storage(self, storage_id: int) -> bool:
        return any(storage.id == storage_id for storage in self.storages)

    def chain(self, storage_id: int, object_id: int) -> list[UsbDirectoryEntry]:
        """追溯到已知存储根；循环、断链及跨存储均拒绝。"""
        if not self.has_storage(storage_id):
            raise ValueError("存储不属于当前会话")
        chain: list[UsbDirectoryEntry] = []
        visited: set[int] = set()
        while object_id != ROOT_FOLDER_ID:
            if object_id in visited or len(chain) >= 128:
                raise ValueError("设备对象归属链异常")
            visited.add(object_id)
            item = self.objects.get((storage_id, object_id))
            if item is None:
                raise ValueError("对象引用已失效，请重新浏览")
            if chain and not item.is_folder:
                raise ValueError("设备对象父项不是目录")
            chain.append(item)
            object_id = item.parent_id
        return list(reversed(chain))

    def allows_folder(self, storage_id: int, folder_id: int) -> bool:
        try:
            chain = self.chain(storage_id, folder_id)
            return not chain or chain[-1].is_folder
        except ValueError:
            return False

    def remember_listing(
        self, storage_id: int, folder_id: int, entries: list[UsbDirectoryEntry], complete: bool,
    ) -> None:
        """刷新直接子项，删除不再返回的旧子树引用，不把缺项登记成空目录。"""
        current_ids = {item.object_id for item in entries}
        removed = {
            item.object_id for item in self.objects.values()
            if item.storage_id == storage_id and item.parent_id == folder_id
            and item.object_id not in current_ids
        }
        while removed:
            next_removed = {
                item.object_id for item in self.objects.values()
                if item.storage_id == storage_id and item.parent_id in removed
            }
            for object_id in removed:
                self.objects.pop((storage_id, object_id), None)
                self.complete_folders.discard((storage_id, object_id))
            removed = next_removed
        new_keys = {(item.storage_id, item.object_id) for item in entries}
        if len(self.objects.keys() | new_keys) > settings.USB_TRANSFER_MAX_ENTRIES:
            raise ReferenceBudgetError("会话对象引用超过预算，请断开重连后缩小浏览范围")
        for item in entries:
            if item.storage_id != storage_id or item.parent_id != folder_id:
                raise ValueError("设备返回了目录边界之外的对象")
            self.objects[(storage_id, item.object_id)] = item
        key = (storage_id, folder_id)
        if complete:
            self.complete_folders.add(key)
        else:
            self.complete_folders.discard(key)
