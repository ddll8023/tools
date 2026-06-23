import os

from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)


def save_file(content: bytes, path: str) -> str:
    logger.info(f"保存文件: path={path} size={len(content)}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path
