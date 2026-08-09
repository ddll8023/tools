import os
import sys
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./data/toolbox.db"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 4740
    MINERU_MODEL_PATH: str = ""
    ID_PHOTO_MODEL_PATH: str = ""
    LIBREOFFICE_PATH: str = ""

    ROOT_PATH: str = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    @property
    def mineru_model_path(self) -> str:
        if self.MINERU_MODEL_PATH:
            return os.path.join(self.ROOT_PATH, self.MINERU_MODEL_PATH)
        return os.path.join(self.ROOT_PATH, "resources", "mineru")

    @property
    def id_photo_model_path(self) -> str:
        """获取证件照本地模型目录。"""
        if self.ID_PHOTO_MODEL_PATH:
            return os.path.join(self.ROOT_PATH, self.ID_PHOTO_MODEL_PATH)
        return os.path.join(self.ROOT_PATH, "resources", "id_photo")

    @property
    def libreoffice_path(self) -> str:
        """获取 LibreOffice 可执行文件路径，按优先级：
        1. .env 中显式指定的 LIBREOFFICE_PATH
        2. 项目内便携版（Windows）
           - backend/resources/LibreOfficePortable/LibreOfficePortable.exe
        3. macOS 标准安装路径
        4. 系统 PATH 中的 soffice
        """
        if self.LIBREOFFICE_PATH:
            return self.LIBREOFFICE_PATH

        # Windows 便携版
        portable = os.path.join(
            self.ROOT_PATH,
            "resources",
            "LibreOfficePortable",
            "LibreOfficePortable.exe",
        )
        if os.path.exists(portable):
            return portable

        # macOS 标准安装路径
        mac_soffice = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        if sys.platform == "darwin" and os.path.exists(mac_soffice):
            return mac_soffice

        return "soffice"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
