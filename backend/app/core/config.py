import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./data/toolbox.db"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 4740
    MINERU_MODEL_PATH: str = ""
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
    def libreoffice_path(self) -> str:
        """获取 LibreOffice 可执行文件路径，按优先级：
        1. .env 中显式指定的 LIBREOFFICE_PATH
        2. 项目内便携版（PortableApps.com 结构 → 使用启动器）
           - backend/resources/LibreOfficePortable/LibreOfficePortable.exe
        3. 系统 PATH 中的 soffice
        """
        if self.LIBREOFFICE_PATH:
            return self.LIBREOFFICE_PATH

        portable = os.path.join(
            self.ROOT_PATH,
            "resources",
            "LibreOfficePortable",
            "LibreOfficePortable.exe",
        )
        if os.path.exists(portable):
            return portable

        return "soffice"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
