import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./data/toolbox.db"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 4740
    MINERU_MODEL_PATH: str = ""

    ROOT_PATH: str = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    @property
    def mineru_model_path(self) -> str:
        if self.MINERU_MODEL_PATH:
            return os.path.join(self.ROOT_PATH, self.MINERU_MODEL_PATH)
        return os.path.join(self.ROOT_PATH, "..", "models", "mineru")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
