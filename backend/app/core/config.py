from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./data/toolbox.db"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 4740

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
