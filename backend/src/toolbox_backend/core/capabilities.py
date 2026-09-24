"""管理启动期探测到的本地运行能力状态。"""

from dataclasses import dataclass
from threading import RLock

CAPABILITY_LIBREOFFICE = "libreoffice"
CAPABILITY_ID_PHOTO = "id_photo"


@dataclass(frozen=True)
class CapabilityStatus:
    """描述单项本地能力是否可用及不可用原因。"""

    available: bool
    reason: str | None = None


class CapabilityRegistry:
    """线程安全地保存应用级能力状态，供工具目录和运行时检查读取。"""

    def __init__(self) -> None:
        """初始化已知能力的默认不可用状态。"""
        self._lock = RLock()
        self._statuses: dict[str, CapabilityStatus] = {
            CAPABILITY_LIBREOFFICE: CapabilityStatus(False, "未检测到 LibreOffice"),
            CAPABILITY_ID_PHOTO: CapabilityStatus(
                False,
                "证件照模型或运行依赖不可用",
            ),
        }

    def set(
        self,
        name: str,
        available: bool,
        reason: str | None = None,
    ) -> None:
        """更新能力状态，并在未提供新原因时保留已有原因。"""
        with self._lock:
            current = self._statuses.get(name)
            retained_reason = reason if reason is not None else (
                current.reason if current is not None else None
            )
            self._statuses[name] = CapabilityStatus(available, retained_reason)

    def get(self, name: str) -> CapabilityStatus:
        """读取能力状态；未知能力按不可用处理。"""
        with self._lock:
            return self._statuses.get(
                name,
                CapabilityStatus(False, "未注册的运行能力"),
            )


capabilities = CapabilityRegistry()
