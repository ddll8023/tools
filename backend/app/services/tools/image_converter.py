"""图片格式转换服务"""

import os
import uuid
import shutil
import zipfile
from io import BytesIO

from fastapi import UploadFile
from PIL import Image, ImageOps

from app.utils.file import safe_filename
from app.utils.temp_cleanup import TEMP_DIR, get_task_dir, validate_task_id
from app.utils.exception import ServiceException
from app.schemas.response import ErrorCode
from app.schemas.tools.image_converter import ConvertResponse, ConvertFileItem
from app.utils.logger_config import setup_logger

logger = setup_logger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_BATCH_COUNT = 20
MAX_PIXEL_COUNT = 40_000_000

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif"}
TARGET_FORMAT_MAP = {
    "png": ("PNG", ".png"),
    "jpeg": ("JPEG", ".jpg"),
    "webp": ("WEBP", ".webp"),
    "bmp": ("BMP", ".bmp"),
    "gif": ("GIF", ".gif"),
    "tiff": ("TIFF", ".tiff"),
}


"""辅助函数"""


def _get_source_format(filename: str) -> str:
    """从文件名推断来源格式"""
    ext = os.path.splitext(filename)[1].lower()
    fmt_map = {
        ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg",
        ".webp": "webp", ".bmp": "bmp", ".gif": "gif",
        ".tiff": "tiff", ".tif": "tiff",
    }
    return fmt_map.get(ext, "unknown")


def _normalize_mode(img: Image.Image, target_fmt: str) -> Image.Image:
    """色彩模式标准化，确保目标格式兼容"""
    # 调色板模式 → RGBA/RGB
    if img.mode == "P":
        img = img.convert("RGBA" if "transparency" in img.info else "RGB")
    # CMYK → RGB
    if img.mode == "CMYK":
        img = img.convert("RGB")
    # 灰度/灰度+Alpha → RGB/RGBA
    if img.mode in ("L", "LA", "I", "F"):
        img = img.convert("RGBA" if img.mode in ("LA",) else "RGB")
    # RGBA → RGB（目标不支持透明度）
    if img.mode == "RGBA" and target_fmt in ("JPEG", "BMP"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background
    return img


def _save_single(img: Image.Image, path: str, target_fmt: str, quality: int):
    """保存单张图片"""
    kwargs = {}
    if target_fmt in ("JPEG", "WEBP"):
        kwargs["quality"] = quality
    if target_fmt == "TIFF":
        # 大图自动启用 BigTIFF
        kwargs["bigtiff"] = True
    img.save(path, format=target_fmt, **kwargs)
    img.close()


def _check_pixel_limit(width: int, height: int, filename: str):
    """校验单帧像素规模（多页/动画的每一帧都要校验）。"""
    if width * height > MAX_PIXEL_COUNT:
        raise ServiceException(
            ErrorCode.PARAM_ERROR,
            f"图片分辨率过高: {filename}（最大 4000 万像素）",
        )


def _process_tiff_multi_page(img: Image.Image, task_dir: str, original_stem: str,
                             original_name: str, target_fmt: str, quality: int,
                             results: list):
    """处理多页 TIFF，每页单独保存（文件名以结果索引为前缀，与下载匹配）"""
    _, target_ext = TARGET_FORMAT_MAP[target_fmt.lower()]
    pages_saved = 0

    try:
        while True:
            img.seek(img.tell())
            page = img.copy()
            page = ImageOps.exif_transpose(page) or page
            _check_pixel_limit(page.width, page.height, original_name)
            page = _normalize_mode(page, target_fmt)

            index = len(results)
            page_name = f"{original_stem}_p{pages_saved}_converted{target_ext}"
            page_path = os.path.join(task_dir, f"{index}_{page_name}")
            _save_single(page, page_path, target_fmt, quality)

            results.append(ConvertFileItem(
                original_name=original_name,
                converted_name=page_name,
                file_size=os.path.getsize(page_path),
                original_format="tiff",
                index=index,
            ))
            pages_saved += 1
            img.seek(img.tell() + 1)
    except EOFError:
        pass


def _process_animated_gif(img: Image.Image, task_dir: str, original_stem: str,
                          original_name: str, target_fmt: str, quality: int,
                          results: list):
    """处理动画 GIF → WebP 保留动画"""
    _, target_ext = TARGET_FORMAT_MAP[target_fmt.lower()]
    frames, durations = [], []

    try:
        while True:
            img.seek(img.tell())
            frame = img.copy()
            _check_pixel_limit(frame.width, frame.height, original_name)
            frames.append(frame)
            durations.append(img.info.get("duration", 100))
            img.seek(img.tell() + 1)
    except EOFError:
        pass

    if len(frames) <= 1:
        # 静态 GIF，走普通单张流程
        for f in frames:
            f.close()
        img.seek(0)  # 复位到第一帧，交给普通单张流程
        return False

    for i, f in enumerate(frames):
        frames[i] = _normalize_mode(f, target_fmt)

    index = len(results)
    converted_name = f"{original_stem}_converted{target_ext}"
    converted_path = os.path.join(task_dir, f"{index}_{converted_name}")

    kwargs = {"quality": quality} if target_fmt == "WEBP" else {}
    frames[0].save(
        converted_path, format=target_fmt,
        save_all=True, append_images=frames[1:],
        duration=durations, loop=0, **kwargs,
    )

    for f in frames:
        f.close()

    results.append(ConvertFileItem(
        original_name=original_name,
        converted_name=converted_name,
        file_size=os.path.getsize(converted_path),
        original_format="gif",
        index=index,
    ))
    return True


# ========== 公共入口函数 ==========


def convert_images(files: list[UploadFile], target_format: str, quality: int = 85) -> ConvertResponse:
    """转换图片格式"""
    target_fmt = target_format.upper()
    if target_fmt not in ("PNG", "JPEG", "WEBP", "BMP", "GIF", "TIFF"):
        raise ServiceException(ErrorCode.PARAM_ERROR, f"不支持的目标格式: {target_format}")

    if not files:
        raise ServiceException(ErrorCode.PARAM_ERROR, "请至少上传一个文件")

    if len(files) > MAX_BATCH_COUNT:
        raise ServiceException(ErrorCode.PARAM_ERROR, f"单次最多上传 {MAX_BATCH_COUNT} 张图片")

    _, target_ext = TARGET_FORMAT_MAP[target_format.lower()]

    task_id = uuid.uuid4().hex[:12]
    task_dir = get_task_dir(task_id)
    os.makedirs(task_dir, exist_ok=True)

    result_files = []

    try:
        for idx, file in enumerate(files):
            original_name = safe_filename(file.filename, f"image_{idx}")
            ext = os.path.splitext(original_name)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                raise ServiceException(
                    ErrorCode.UNSUPPORTED_FILE_FORMAT,
                    f"不支持的文件格式: {file.filename}",
                )

            # 文件大小校验
            content = file.file.read()
            if len(content) > MAX_FILE_SIZE:
                raise ServiceException(
                    ErrorCode.FILE_TOO_LARGE,
                    f"文件过大: {original_name}（最大 50MB）",
                )

            # Pillow 打开
            try:
                img = Image.open(BytesIO(content))
            except Exception:
                raise ServiceException(
                    ErrorCode.UNSUPPORTED_FILE_FORMAT,
                    f"无法识别的图片文件: {original_name}",
                )

            # 像素校验（首帧）
            _check_pixel_limit(img.width, img.height, original_name)

            source_fmt = _get_source_format(original_name)
            original_stem = os.path.splitext(original_name)[0][:60]

            # 多页 TIFF 源文件 → 每页单独处理
            if ext in (".tiff", ".tif"):
                try:
                    img.seek(1)  # 尝试跳转到第二帧
                    has_multiple = True
                except (EOFError, AttributeError):
                    has_multiple = False
                finally:
                    img.seek(0)

                if has_multiple:
                    _process_tiff_multi_page(
                        img, task_dir, original_stem, original_name,
                        target_fmt, quality, result_files,
                    )
                    continue

            # 动画 GIF → WebP 保留动画
            if ext == ".gif" and target_fmt == "WEBP":
                if _process_animated_gif(
                    img, task_dir, original_stem, original_name,
                    target_fmt, quality, result_files,
                ):
                    continue
            elif ext == ".gif":
                # GIF → 其他格式，只取第一帧
                pass

            # 普通单张转换
            img = ImageOps.exif_transpose(img) or img
            img = _normalize_mode(img, target_fmt)

            index = len(result_files)
            converted_name = f"{original_stem}_converted{target_ext}"
            converted_path = os.path.join(task_dir, f"{index}_{converted_name}")
            _save_single(img, converted_path, target_fmt, quality)

            result_files.append(ConvertFileItem(
                original_name=original_name,
                converted_name=converted_name,
                file_size=os.path.getsize(converted_path),
                original_format=source_fmt,
                index=index,
            ))
    except ServiceException:
        # 失败时清理已生成的部分结果，避免孤儿任务目录
        shutil.rmtree(task_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise

    logger.info(f"图片转换完成: task_id={task_id} 文件数={len(result_files)}")
    return ConvertResponse(
        task_id=task_id,
        files=result_files,
        is_batch=len(files) > 1 or len(result_files) > 1,
    )


def download_file(task_id: str, file_index: int | None = None) -> tuple:
    """获取下载文件路径和文件名"""
    if not validate_task_id(task_id):
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    task_dir = get_task_dir(task_id)
    root = os.path.abspath(TEMP_DIR)
    if os.path.commonpath([root, os.path.abspath(task_dir)]) != root:
        raise ServiceException(ErrorCode.PARAM_ERROR, "参数错误")

    if not os.path.exists(task_dir):
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "文件不存在或已过期")

    if file_index is not None:
        # 下载单张：文件名前缀即为结果索引，与转换响应一一对应
        for name in os.listdir(task_dir):
            if name.startswith(f"{file_index}_"):
                file_path = os.path.join(task_dir, name)
                display_name = name.split("_", 1)[1] if "_" in name else name
                return file_path, display_name
        raise ServiceException(ErrorCode.DATA_NOT_FOUND, "文件不存在")

    # 下载全部（ZIP 包）：唯一文件名避免并发下载互相截断，先清理旧包
    for name in os.listdir(task_dir):
        if name.startswith("all_converted_") and name.endswith(".zip"):
            try:
                os.remove(os.path.join(task_dir, name))
            except OSError:
                pass
    zip_path = os.path.join(task_dir, f"all_converted_{uuid.uuid4().hex[:8]}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(os.listdir(task_dir)):
            if name.startswith("all_converted_") or name.endswith(".json"):
                continue
            file_path = os.path.join(task_dir, name)
            if os.path.isfile(file_path):
                display_name = name.split("_", 1)[1] if "_" in name and name.count("_") >= 1 else name
                zf.write(file_path, display_name)

    zip_display = f"图片转换_{task_id}.zip"
    return zip_path, zip_display
