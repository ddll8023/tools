import os

from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

_ILLEGAL_FILENAME_CHARS = {chr(c) for c in range(32)} | {"\x7f"}


def safe_filename(name: str | None, default: str = "file") -> str:
    """净化用户提供的文件名：取 basename、去除控制字符，防止路径穿越。"""
    # 统一分隔符后再取 basename，兼容 Windows 风格的 \\ 分隔
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    name = "".join(ch for ch in name if ch not in _ILLEGAL_FILENAME_CHARS)
    return name or default


def save_file(content: bytes, path: str) -> str:
    logger.info(f"保存文件: path={path} size={len(content)}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path
