"""准备证件照所需的本地模型资源。

模型统一保存到 backend/resources/id_photo，不使用用户目录缓存。
运行前请先通过项目 uv 环境安装 backend/pyproject.toml 中的依赖。
"""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
MODEL_DIR = BACKEND_DIR / "resources" / "id_photo"
MTCNN_DIR = MODEL_DIR / "mtcnn"
MODNET_URL = (
    "https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/"
    "pretrained-model/hivision_modnet.onnx"
)


def download_file(url: str, target: Path) -> None:
    """下载到临时文件后原子替换，避免留下不完整模型。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.download")
    request = urllib.request.Request(url, headers={"User-Agent": "tools-id-photo"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()


def copy_mtcnn_weights() -> None:
    """将 mtcnn-runtime wheel 内置权重复制到项目资源目录。"""
    try:
        import mtcnnruntime
    except ImportError as exc:
        raise SystemExit("请先安装 mtcnn-runtime，再准备 MTCNN 模型文件") from exc

    source_dir = Path(mtcnnruntime.__file__).resolve().parent / "weights"
    for filename in ("pnet.onnx", "rnet.onnx", "onet.onnx"):
        source = source_dir / filename
        target = MTCNN_DIR / filename
        if not source.is_file():
            raise SystemExit(f"MTCNN 权重不存在: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        print(f"已保存: {target}")


def main() -> None:
    modnet_path = MODEL_DIR / "hivision_modnet.onnx"
    if not modnet_path.is_file():
        print(f"下载 MODNet: {modnet_path}")
        download_file(MODNET_URL, modnet_path)
    else:
        print(f"已存在，跳过: {modnet_path}")

    copy_mtcnn_weights()
    print(f"证件照模型资源目录: {MODEL_DIR}")


if __name__ == "__main__":
    main()
