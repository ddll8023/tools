import os
import sys
from pydantic_settings import BaseSettings


def _runtime_root() -> str:
    """返回内置资源根目录；兼容源码运行和 PyInstaller 运行。"""
    if getattr(sys, "frozen", False):
        return os.path.abspath(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./data/toolbox.db"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 4740
    MINERU_MODEL_PATH: str = ""
    # 深度解析：模型下载与转换分别计时，避免首次下载被短超时误杀
    MINERU_MODEL_DOWNLOAD_TIMEOUT: int = 1800
    MINERU_CONVERT_TIMEOUT: int = 600
    ID_PHOTO_MODEL_PATH: str = ""
    LIBREOFFICE_PATH: str = ""
    TOOLBOX_DATA_DIR: str = ""

    ROOT_PATH: str = _runtime_root()

    @property
    def data_root(self) -> str:
        """返回开发和打包一致的可写用户数据目录。"""
        if self.TOOLBOX_DATA_DIR:
            return os.path.abspath(self.TOOLBOX_DATA_DIR)
        return DEFAULT_DATA_ROOT

    @property
    def database_url(self) -> str:
        """将相对 SQLite 路径解析到统一用户数据目录。"""
        if not self.DATABASE_URL.startswith("sqlite:///"):
            return self.DATABASE_URL

        database_path = self.DATABASE_URL[len("sqlite:///"):]
        if database_path == ":memory:":
            return self.DATABASE_URL
        if not os.path.isabs(database_path):
            database_path = os.path.join(self.data_root, database_path)
        return f"sqlite:///{os.path.normpath(database_path)}"

    @staticmethod
    def _resolve_path(value: str, base: str) -> str:
        if os.path.isabs(value):
            return value
        return os.path.join(base, value)

    @property
    def mineru_model_path(self) -> str:
        if self.MINERU_MODEL_PATH:
            return self._resolve_path(self.MINERU_MODEL_PATH, self.data_root)
        # MinerU 会在运行时下载模型，不能写入只读的应用包目录。
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
