"""把 LaTeX 公式与 SVG 图形转换为 DOCX 可嵌入的 PNG。

matplotlib 与 PyMuPDF 都在首次使用时延迟导入：纯文本文档不承担导入开销，
依赖缺失时由调用方降级为原文或代码块，而不是让整篇文档转换失败。
"""

from __future__ import annotations

import re
from io import BytesIO

from toolbox_backend.core.logging import setup_logger

logger = setup_logger(__name__)

# SVG 光栅化分辨率：200dpi 在正文宽度下已足够清晰，且不会让 PNG 过大。
_SVG_DPI = 200
# 公式与图形的像素上限，避免异常输入产生超大位图占满内存。
_MAX_PIXELS = 40_000_000
# 公式渲染的 DPI；300dpi 保证 Word 缩放后仍清晰。
_FORMULA_DPI = 300
# mathtext 字体不含中日韩字形，含这类字符时直接降级为原文，避免输出豆腐块。
_CJK_PATTERN = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")


def render_formula_png(latex: str, font_size_pt: float) -> BytesIO | None:
    """把 LaTeX 公式渲染为 PNG；语法或字体不受支持时返回 None。"""
    if not latex.strip():
        return None
    if _CJK_PATTERN.search(latex):
        return None
    try:
        import matplotlib

        matplotlib.use("Agg", force=False)
        from matplotlib import mathtext
        from matplotlib.font_manager import FontProperties
    except Exception as exc:  # pragma: no cover - 依赖缺失属于环境问题
        logger.warning("公式渲染不可用: %s", exc)
        return None

    buffer = BytesIO()
    try:
        mathtext.math_to_image(
            f"${latex}$",
            buffer,
            prop=FontProperties(size=font_size_pt),
            dpi=_FORMULA_DPI,
            format="png",
        )
    except Exception:
        # mathtext 只覆盖 LaTeX 子集（如 cases 环境不支持），交给调用方降级处理。
        return None
    if buffer.getbuffer().nbytes == 0:
        return None
    buffer.seek(0)
    return buffer


def render_svg_png(svg_text: str) -> BytesIO | None:
    """把 SVG 图形光栅化为 PNG；内容非法或超出像素上限时返回 None。"""
    if "<svg" not in svg_text:
        return None
    try:
        import pymupdf
    except Exception as exc:  # pragma: no cover - 依赖缺失属于环境问题
        logger.warning("SVG 光栅化不可用: %s", exc)
        return None

    document = None
    pdf_document = None
    try:
        document = pymupdf.open(stream=svg_text.encode("utf-8"), filetype="svg")
        pdf_document = pymupdf.open("pdf", document.convert_to_pdf())
        if pdf_document.page_count == 0:
            return None
        page = pdf_document[0]
        pixmap = page.get_pixmap(dpi=_SVG_DPI)
        if pixmap.width * pixmap.height > _MAX_PIXELS:
            return None
        buffer = BytesIO(pixmap.tobytes("png"))
    except Exception:
        return None
    finally:
        for handle in (pdf_document, document):
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
    if buffer.getbuffer().nbytes == 0:
        return None
    buffer.seek(0)
    return buffer
