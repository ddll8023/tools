"""隔离 MinerU 模型文件布局、命令行参数和运行环境变量。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from toolbox_backend.core.config import settings

# Windows 无符号链接权限时，ModelScope 可能留下临时目录；按 Pipeline 关键文件判断完整性。
_REQUIRED_PIPELINE_FILES = (
    "models/Layout/PP-DocLayoutV2/config.json",
    "models/Layout/PP-DocLayoutV2/model.safetensors",
    "models/MFR/unimernet_hf_small_2503/config.json",
    "models/MFR/unimernet_hf_small_2503/model.safetensors",
    "models/OCR/paddleocr_torch/ch_PP-OCRv4_rec_infer.pth",
    "models/TabRec/SlanetPlus/slanet-plus.onnx",
    "models/TabRec/UnetStructure/unet.onnx",
    "models/TabCls/paddle_table_cls/PP-LCNet_x1_0_table_cls.onnx",
    "models/MFR/pp_formulanet_plus_m/PP-FormulaNet_plus-M.pth",
)


def get_model_cache_dir() -> Path:
    """返回配置的 MinerU 模型缓存目录。"""
    return Path(settings.mineru_model_path).resolve()


def is_model_ready(cache_dir: Path | None = None) -> bool:
    """根据 MinerU Pipeline 关键文件检查模型完整性。"""
    root = cache_dir or get_model_cache_dir()
    model_root = root / "modelscope" / "models" / "OpenDataLab" / "PDF-Extract-Kit-1___0"
    return all((model_root / relative_path).is_file() for relative_path in _REQUIRED_PIPELINE_FILES)


def get_runtime_env() -> dict[str, str]:
    """构造 MinerU 下载与转换共用的本地缓存环境变量。"""
    cache_dir = get_model_cache_dir()
    hf_cache = cache_dir / "huggingface"
    modelscope_cache = cache_dir / "modelscope"
    hf_cache.mkdir(parents=True, exist_ok=True)
    modelscope_cache.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["HF_HOME"] = str(hf_cache)
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env["MINERU_MODEL_SOURCE"] = "modelscope"
    env["MODELSCOPE_CACHE"] = str(modelscope_cache)
    # MinerU 自身配置也放入统一用户数据目录，避免写入用户主目录。
    env["MINERU_TOOLS_CONFIG_JSON"] = str(cache_dir / "mineru.json")
    return env


def get_download_executable() -> list[str]:
    """返回 MinerU 模型下载 CLI 的可执行入口。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--toolbox-mineru-models"]

    bin_dir = os.path.dirname(sys.executable)
    suffix = ".exe" if os.name == "nt" else ""
    return [os.path.join(bin_dir, f"mineru-models-download{suffix}")]


def get_convert_executable() -> list[str]:
    """返回 MinerU 转换 CLI 的可执行入口。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--toolbox-mineru"]

    bin_dir = os.path.dirname(sys.executable)
    suffix = ".exe" if os.name == "nt" else ""
    return [os.path.join(bin_dir, f"mineru{suffix}")]


def build_download_command() -> list[str]:
    """构造下载 Pipeline 模型所需的 MinerU 命令。"""
    return get_download_executable() + ["-s", "modelscope", "-m", "pipeline"]


def build_convert_command(pdf_path: str, output_dir: str) -> list[str]:
    """构造 PDF Pipeline 深度解析所需的 MinerU 命令。"""
    return get_convert_executable() + [
        "-p",
        pdf_path,
        "-o",
        output_dir,
        "-b",
        "pipeline",
        "-l",
        "ch",
    ]
