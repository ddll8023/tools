"""管理应用配置与用户数据目录解析。"""
import ctypes.util
import os
import sys
from pydantic import Field
from pydantic_settings import BaseSettings


def _runtime_root() -> str:
    """返回内置资源根目录；兼容源码运行和 PyInstaller 运行。"""
    if getattr(sys, "frozen", False):
        return os.path.abspath(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )


def _default_data_root() -> str:
    """返回开发和打包都使用的统一用户数据目录。"""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.abspath(os.path.join(base, "工具盒子"))


DEFAULT_DATA_ROOT = _default_data_root()

# 有线传输：libmtp 随包资源位置，以及开发态常见安装位置；仅做路径解析，不加载库。
USB_TRANSFER_BUNDLED_LIBRARY = ("usb", "lib", "libmtp.dylib")
DEV_MTP_LIBRARY_CANDIDATES = (
    "/opt/homebrew/opt/libmtp/lib/libmtp.dylib",
    "/opt/homebrew/lib/libmtp.dylib",
    "/usr/local/opt/libmtp/lib/libmtp.dylib",
    "/usr/local/lib/libmtp.dylib",
)


class Settings(BaseSettings):
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 18740
    MINERU_MODEL_PATH: str = ""
    # 深度解析：模型下载与转换分别计时，避免首次下载被短超时误杀
    MINERU_MODEL_DOWNLOAD_TIMEOUT: int = 1800
    MINERU_CONVERT_TIMEOUT: int = 600
    ID_PHOTO_MODEL_PATH: str = ""
    LIBREOFFICE_PATH: str = ""
    TOOLBOX_DATA_DIR: str = ""
    TOOLBOX_LAUNCH_ID: str = ""
    APP_SHUTDOWN_TIMEOUT_SECONDS: float = Field(30.0, ge=5, le=120)
    # 局域网投送：仅在用户显式开启会话期间监听，默认首选端口避开控制面 18740。
    LAN_TRANSFER_HOST: str = "0.0.0.0"
    LAN_TRANSFER_PORT: int = 18751
    # 会话基础有效期；有在途传输时可顺延，上限由 LAN_TRANSFER_MAX_EXTEND_SECONDS 控制。
    LAN_TRANSFER_TTL_SECONDS: int = 1800
    # 接收方向限额：上传中与待确认内容共同占用同一份会话预算。
    LAN_TRANSFER_MAX_FILE_BYTES: int = 2 * 1024 * 1024 * 1024
    LAN_TRANSFER_MAX_SESSION_BYTES: int = 8 * 1024 * 1024 * 1024
    LAN_TRANSFER_MAX_CONCURRENT_UPLOADS: int = 3
    LAN_TRANSFER_MAX_PENDING_FILES: int = 50
    LAN_TRANSFER_MIN_FREE_DISK_BYTES: int = 1024 * 1024 * 1024
    # 发送方向只登记路径不复制内容，因此只约束清单条数。
    LAN_TRANSFER_MAX_SEND_FILES: int = 100
    # 传输进行中允许顺延自动关闭，但会话总存活时间不超过 TTL 加该值。
    LAN_TRANSFER_MAX_EXTEND_SECONDS: int = 7200
    # 接收记录只保留最近若干条，避免历史文件无限增长。
    LAN_TRANSFER_MAX_RECEIVE_RECORDS: int = 100
    # 留空时按用户下载目录下的子目录接收，阶段四再做可配置界面。
    LAN_TRANSFER_RECEIVE_DIR: str = ""
    # 有线传输：显式指定 libmtp 动态库路径，留空时按随包资源与系统位置解析。
    USB_TRANSFER_LIBRARY_PATH: str = ""
    # USB 的预算独立于 LAN 和通用临时任务；到达上限时拒绝，不静默丢弃异常记录。
    USB_TRANSFER_MAX_QUEUE: int = Field(20, ge=1, le=100)
    USB_TRANSFER_MAX_RECORDS: int = Field(100, ge=1, le=1000)
    USB_TRANSFER_MAX_ENTRIES: int = Field(10000, ge=100, le=100000)
    USB_TRANSFER_MAX_DEPTH: int = Field(64, ge=1, le=128)
    USB_TRANSFER_MAX_MESSAGE_BYTES: int = Field(262144, ge=65536, le=1048576)
    USB_TRANSFER_MAX_RECORD_BYTES: int = Field(67108864, ge=1048576, le=268435456)
    # 同时用于提交凭据有效期和当前实例完成记录的保留条件；历史记录回收由任务管理器判定。
    USB_TRANSFER_SUBMISSION_TTL: int = Field(1800, ge=60, le=86400)
    USB_TRANSFER_METADATA_TIMEOUT: float = Field(60.0, ge=5, le=600)
    USB_TRANSFER_STALL_TIMEOUT: float = Field(120.0, ge=10, le=3600)
    USB_TRANSFER_CANCEL_GRACE: float = Field(8.0, ge=1, le=60)

    ROOT_PATH: str = _runtime_root()

    @property
    def data_root(self) -> str:
        """返回开发和打包一致的可写用户数据目录。"""
        if self.TOOLBOX_DATA_DIR:
            return os.path.abspath(self.TOOLBOX_DATA_DIR)
        return DEFAULT_DATA_ROOT

    @property
    def ownership_lock_path(self) -> str:
        """固定用户作用域的协调锁；不能随业务数据根变化而允许并行实例。"""
        return os.path.join(DEFAULT_DATA_ROOT, "runtime", "backend.lock")

    @property
    def runtime_dir(self) -> str:
        """返回运行期凭据目录，不存放用户文件。"""
        return os.path.join(self.data_root, "runtime")

    @property
    def lan_transfer_root(self) -> str:
        """返回投送隔离区根目录，与任务临时空间分离。"""
        return os.path.join(self.data_root, "lan_transfer")

    @property
    def lan_transfer_receive_dir(self) -> str:
        """返回接收目录；未配置时使用用户下载目录下的专用子目录。"""
        if self.LAN_TRANSFER_RECEIVE_DIR:
            return self._resolve_path(self.LAN_TRANSFER_RECEIVE_DIR, self.data_root)

        home = os.path.expanduser("~")
        if sys.platform == "win32":
            downloads = os.path.join(
                os.environ.get("USERPROFILE") or home,
                "Downloads",
            )
        else:
            downloads = os.environ.get("XDG_DOWNLOAD_DIR") or os.path.join(home, "Downloads")
        return os.path.join(downloads, "工具盒子")

    @property
    def usb_transfer_root(self) -> str:
        """返回 USB 状态目录；不存放传输内容，不参与通用临时清理。"""
        return os.path.join(self.data_root, "usb_transfer")

    @property
    def usb_transfer_library_path(self) -> str | None:
        """解析 libmtp 动态库路径：显式配置 → 随包资源 → 仅源码态的常见位置。

        只返回实际存在的路径，不加载库；找不到时返回 None，由调用方转换为
        “运行依赖不可用”状态，避免在 API 进程里 dlopen 原生库。
        """
        if self.USB_TRANSFER_LIBRARY_PATH:
            configured = self._resolve_path(self.USB_TRANSFER_LIBRARY_PATH, self.data_root)
            return configured if os.path.exists(configured) else None

        bundled = os.path.join(self.ROOT_PATH, "resources", *USB_TRANSFER_BUNDLED_LIBRARY)
        if os.path.exists(bundled):
            return bundled
        # 打包产物缺依赖时明确失败，不借用用户机器上未知 ABI 的 Homebrew 库。
        if getattr(sys, "frozen", False):
            return None

        for candidate in DEV_MTP_LIBRARY_CANDIDATES:
            if os.path.exists(candidate):
                return candidate

        try:
            found = ctypes.util.find_library("mtp")
        except (OSError, TypeError):
            # 系统库探测在少数环境下会失败，按“未安装”处理。
            return None
        if found and os.path.exists(found):
            return found
        return None

    @staticmethod
    def _resolve_path(value: str, base: str) -> str:
        if os.path.isabs(value):
            return value
        return os.path.join(base, value)

    @property
    def mineru_model_path(self) -> str:
        if self.MINERU_MODEL_PATH:
            return self._resolve_path(self.MINERU_MODEL_PATH, self.data_root)
        # MinerU 模型由设置页手动下载，不能写入只读的应用包目录。
        return os.path.join(self.data_root, "resources", "mineru")

    @property
    def id_photo_model_path(self) -> str:
        """获取证件照本地模型目录，优先读取应用包内资源。"""
        if self.ID_PHOTO_MODEL_PATH:
            return self._resolve_path(self.ID_PHOTO_MODEL_PATH, self.data_root)

        bundled = os.path.join(self.ROOT_PATH, "resources", "id_photo")
        if os.path.isdir(bundled):
            return bundled
        return os.path.join(self.data_root, "resources", "id_photo")

    @property
    def libreoffice_path(self) -> str:
        """获取 LibreOffice 可执行文件路径，按优先级：
        1. .env 中显式指定的 LIBREOFFICE_PATH
        2. 应用包内便携版（Windows）
        3. macOS 标准安装路径
        4. 系统 PATH 中的 soffice
        """
        if self.LIBREOFFICE_PATH:
            return self._resolve_path(self.LIBREOFFICE_PATH, self.data_root)

        portable = os.path.join(
            self.ROOT_PATH,
            "resources",
            "LibreOfficePortable",
            "LibreOfficePortable.exe",
        )
        if os.path.exists(portable):
            return portable

        mac_soffice = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        if sys.platform == "darwin" and os.path.exists(mac_soffice):
            return mac_soffice

        return "soffice"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
