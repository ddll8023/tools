"""PDF 转 Markdown 服务（标准模式）。

按页面坐标重建阅读顺序：文本块、图片与表格统一按 y/x 排序输出，标题层级由字号
相对正文中位数的比例判定，不再插入人造的「第 N 页」标题。跨页表格在相邻页
同时满足列数、列边界与页顶位置条件时合并。
"""

import os
import unicodedata
import uuid
import shutil
from dataclasses import dataclass, field

import fitz
from fastapi import UploadFile

from toolbox_backend.infrastructure.files import save_file, safe_filename
from toolbox_backend.core.logging import setup_logger
from toolbox_backend.core.errors import ServiceException
from toolbox_backend.schemas.response import ErrorCode
from toolbox_backend.modules.pdf_to_markdown.schemas import ConvertResponse
from toolbox_backend.infrastructure.task_storage.workspace import UPLOADS_DIR, get_task_dir
from toolbox_backend.modules.pdf_to_markdown.result import (
    PAGE_SEPARATOR,
    download_md,
    get_preview_detail,
)

logger = setup_logger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024

# 标题判定阈值：相对正文中位字号的倍数。倍数越高越保守，避免把大字号正文误判为标题。
_HEADING_RATIOS = ((1.6, 1), (1.3, 2), (1.12, 3))
# 超过该长度的文本块不参与标题判定，长段落即使字号偏大也按正文处理。
_HEADING_MAX_CHARS = 120
# 文本块/图片与表格区域的覆盖比例阈值，超过即视为表格内容。
_TABLE_OVERLAP = 0.5
# 无框线检测会把整页版面误识别为表格，超过该页面占比的结果直接丢弃。
_TEXT_TABLE_MAX_PAGE_RATIO = 0.7
# 无框线检测产出的空单元格占比过高时视为误识别。
_TEXT_TABLE_MAX_EMPTY_RATIO = 0.4
# 跨页表格的列边界 x 坐标容差（磅）。超出版面常用列宽的一半即视为不同表格。
_CROSS_PAGE_COLUMN_TOLERANCE = 12.0
# 下一页表格顶边距页顶不超过该比例页高时，才可能是上一页表格的延续。
_CROSS_PAGE_TOP_RATIO = 0.35


# ========== 公共入口函数 ==========


def convert_pdf(file: UploadFile):
    """转换 PDF 为 Markdown（标准模式）"""
    safe_name = safe_filename(file.filename, "input.pdf")
    if not safe_name.lower().endswith(".pdf"):
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "不支持的文件格式")
    if file.size > MAX_FILE_SIZE:
        raise ServiceException(ErrorCode.FILE_TOO_LARGE, "文件大小不能超过 50MB")

    task_id = uuid.uuid4().hex[:12]
    task_dir = get_task_dir(task_id)
    os.makedirs(task_dir, exist_ok=True)

    # 记录原始文件名，供下载命名使用
    with open(os.path.join(task_dir, "meta.txt"), "w", encoding="utf-8") as f:
        f.write(safe_name)

    # 保存原始 PDF 到 uploads/（带 task_id 前缀）
    upload_filename = f"{task_id}-{safe_name}"
    upload_path = os.path.join(UPLOADS_DIR, upload_filename)
    save_file(file.file.read(), upload_path)

    # 复制到任务目录
    pdf_path = os.path.join(task_dir, "input.pdf")
    shutil.copy2(upload_path, pdf_path)

    logger.info(f"开始转换 PDF: task_id={task_id} filename={safe_name}")

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "无法解析 PDF 文件")

    try:
        if doc.needs_pass:
            raise ServiceException(ErrorCode.UNSUPPORTED_FILE_FORMAT, "PDF 已加密，暂不支持解析")
        page_count = len(doc)
        images_dir = os.path.join(task_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        body_size = _body_font_size(doc)
        pages: list[list[object]] = []
        image_count = 0
        table_count = 0

        for page_num in range(page_count):
            page = doc[page_num]
            logger.info(f"正在处理第 {page_num + 1} 页: task_id={task_id}")
            items, images, tables = _render_page(doc, page, page_num, images_dir, body_size)
            image_count += images
            table_count += tables
            pages.append(items)

        merged = _merge_cross_page_tables(pages)
        if merged:
            logger.info(f"合并跨页表格: task_id={task_id} count={merged}")
        page_markdown = [
            "\n\n".join(block.render() for block in blocks) for blocks in pages if blocks
        ]
        table_count = sum(1 for blocks in pages for block in blocks if block.kind == "table")
    except ServiceException:
        raise
    except Exception:
        raise ServiceException(ErrorCode.CONVERSION_FAILED, "PDF 解析失败，请确认文件未损坏")
    finally:
        doc.close()

    md_path = os.path.join(task_dir, "output.md")
    full_md = PAGE_SEPARATOR.join(page_markdown)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(full_md)

    logger.info(
        f"PDF 转换完成: task_id={task_id} pages={page_count} tables={table_count} images={image_count}"
    )
    return ConvertResponse(task_id=task_id, filename=safe_name, page_count=page_count)


# ========== 页面块 ==========


@dataclass
class _Block:
    """页面内一个待排序的输出块：文本、图片或表格。

    表格保留结构化行数据与列边界，以便跨页时与相邻页表格比对并合并。
    """

    y: float
    x: float
    kind: str
    markdown: str = ""
    rows: list[list[str]] = field(default_factory=list)
    column_xs: tuple[float, ...] = ()
    # 表格外框，用于跨页时比对左右边界。
    bounds: tuple[float, float, float, float] = ()
    # 块顶边距页顶占页高的比例，仅表格用于判断是否为页顶延续。
    top_ratio: float = 1.0

    def render(self) -> str:
        """输出块的 Markdown 文本。"""
        if self.kind == "table":
            return _render_table_rows(self.rows)
        return self.markdown


# ========== 单页重建 ==========


def _render_page(
    doc: "fitz.Document",
    page: "fitz.Page",
    page_num: int,
    images_dir: str,
    body_size: float,
) -> tuple[list[_Block], int, int]:
    """按坐标重建单页，返回 (已排序块列表, 图片数, 表格数)。"""
    tables = _detect_tables(page)
    table_regions = [tuple(table.bbox) for table in tables]
    page_height = float(page.rect.height) or 1.0

    blocks: list[_Block] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        bbox = tuple(block.get("bbox") or ())
        if not bbox or _inside_table(bbox, table_regions):
            continue
        markdown = _render_text_block(block, body_size)
        if markdown:
            blocks.append(_Block(y=bbox[1], x=bbox[0], kind="text", markdown=markdown))

    image_blocks, image_count = _render_images(
        doc, page, page_num, images_dir, table_regions
    )
    blocks.extend(image_blocks)

    for table in tables:
        rows = _table_rows(table)
        if not rows:
            continue
        bbox = tuple(table.bbox)
        blocks.append(
            _Block(
                y=bbox[1],
                x=bbox[0],
                kind="table",
                rows=rows,
                column_xs=_table_column_xs(table),
                bounds=bbox,
                top_ratio=max(0.0, min(1.0, bbox[1] / page_height)),
            )
        )

    blocks.sort(key=lambda item: (round(item.y, 1), item.x))
    return blocks, image_count, len(tables)


# ========== 跨页表格 ==========


def _merge_cross_page_tables(pages: list[list[_Block]]) -> int:
    """合并被页边界断开的表格，支持跨两页以上的表格链，返回合并次数。

    沿页序滚动维护一个「未闭合表格」：它总是当前页最后一张表，只有下一页第一张表
    同时满足形状一致与页顶位置条件时才继续合并，否则该表格闭合、由下一页最后一张表
    接替。这样既能拼回跨三页以上的长表，又不会把相邻但无关的表格并在一起。
    """
    merged = 0
    open_table: _Block | None = None
    for blocks in pages:
        first = _first_table(blocks)
        if (
            open_table is not None
            and first is not None
            and _same_table_shape(open_table, first)
            and first.top_ratio <= _CROSS_PAGE_TOP_RATIO
        ):
            rows = first.rows
            if rows and open_table.rows and rows[0] == open_table.rows[0]:
                # 续页重复表头时丢弃，避免合并后表头行出现两次。
                rows = rows[1:]
            open_table.rows.extend(rows)
            position = blocks.index(first)
            blocks.remove(first)
            merged += 1
            if position == len(blocks):
                # 被合并的表格原本是本页最后一个块，说明它又在页底被截断，保持开启。
                continue
        open_table = _last_table(blocks)
    return merged


def _last_table(blocks: list[_Block]) -> _Block | None:
    """取页面上位置最后的表格块。"""
    for block in reversed(blocks):
        if block.kind == "table":
            return block
    return None


def _first_table(blocks: list[_Block]) -> _Block | None:
    """取页面上位置最前的表格块。"""
    for block in blocks:
        if block.kind == "table":
            return block
    return None


def _same_table_shape(previous: _Block, current: _Block) -> bool:
    """判断两个表格是否为同一张表的续页：列数、列边界与左右外框都对齐。"""
    if len(previous.column_xs) < 2 or len(previous.column_xs) != len(current.column_xs):
        return False
    if not all(
        abs(left - right) <= _CROSS_PAGE_COLUMN_TOLERANCE
        for left, right in zip(previous.column_xs, current.column_xs)
    ):
        return False
    if len(previous.bounds) < 4 or len(current.bounds) < 4:
        return False
    # 左右边界同时比对：列起点相同但宽度不同的表格不应视为续页。
    return (
        abs(previous.bounds[0] - current.bounds[0]) <= _CROSS_PAGE_COLUMN_TOLERANCE
        and abs(previous.bounds[2] - current.bounds[2]) <= _CROSS_PAGE_COLUMN_TOLERANCE
    )


def _body_font_size(doc: "fitz.Document") -> float:
    """按字符数加权统计全文档正文中位字号，作为标题判定基准。

    用字号直方图而不是逐字符展开的列表，避免长文档把内存撑大。
    """
    histogram: dict[float, int] = {}
    total = 0
    for page in doc:
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    size = float(span.get("size", 0) or 0)
                    if not text.strip() or size <= 0:
                        continue
                    weight = len(text.strip())
                    histogram[size] = histogram.get(size, 0) + weight
                    total += weight
    if total == 0:
        return 0.0
    half = total / 2
    cumulative = 0
    for size in sorted(histogram):
        cumulative += histogram[size]
        if cumulative >= half:
            return size
    return max(histogram)


# ========== 文本块 ==========


def _render_text_block(block: dict, body_size: float) -> str:
    """把一个文本块渲染为段落或标题。"""
    lines: list[str] = []
    max_size = 0.0
    for line in block.get("lines", []):
        spans = line.get("spans", [])
        text = "".join(span.get("text", "") for span in spans).rstrip()
        if not text.strip():
            continue
        lines.append(text)
        for span in spans:
            max_size = max(max_size, float(span.get("size", 0) or 0))
    if not lines:
        return ""

    joined = _join_lines(lines)
    level = _heading_level(max_size, body_size, len(joined))
    return f"{'#' * level} {joined}" if level else joined


def _join_lines(lines: list[str]) -> str:
    """把同一段落内的多行拼成一行：中日韩字符之间不补空格，其余补一个空格。"""
    result = lines[0].strip()
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if result.endswith("-") or not _needs_space(result[-1], stripped[0]):
            result += stripped
        else:
            result += " " + stripped
    return result


def _needs_space(left: str, right: str) -> bool:
    """判断两个相邻字符之间是否需要空格。"""
    return not (_is_wide(left) and _is_wide(right))


def _is_wide(char: str) -> bool:
    """判断字符是否为全角字符（中日韩文字与全角标点）。"""
    return unicodedata.east_asian_width(char) in ("W", "F")


def _heading_level(font_size: float, body_size: float, char_count: int) -> int:
    """按字号相对正文的倍数判定标题级别，无法判定时返回 0 表示正文。"""
    if body_size <= 0 or font_size <= 0 or char_count > _HEADING_MAX_CHARS:
        return 0
    ratio = font_size / body_size
    for threshold, level in _HEADING_RATIOS:
        if ratio >= threshold:
            return level
    return 0


# ========== 图片 ==========


def _render_images(
    doc: "fitz.Document",
    page: "fitz.Page",
    page_num: int,
    images_dir: str,
    table_regions: list[tuple[float, float, float, float]],
) -> tuple[list[_Block], int]:
    """导出页面图片并登记为待排序块。

    同一 xref 在页面上重复出现时只导出一份，多个位置引用同一文件，
    避免重复落盘并使预览图片数虚高。
    """
    blocks: list[_Block] = []
    exported: dict[int, str] = {}
    count = 0
    for info in page.get_image_info(xrefs=True):
        bbox = tuple(info.get("bbox") or ())
        xref = info.get("xref") or 0
        if not bbox or not xref or _inside_table(bbox, table_regions):
            continue
        img_filename = exported.get(xref)
        if img_filename is None:
            try:
                extracted = doc.extract_image(xref)
            except Exception:
                logger.warning(f"图片提取失败: page={page_num + 1} xref={xref}")
                continue
            if not extracted or not extracted.get("image"):
                continue
            count += 1
            img_filename = f"page{page_num + 1}_{count}.{extracted.get('ext', 'png')}"
            with open(os.path.join(images_dir, img_filename), "wb") as f:
                f.write(extracted["image"])
            exported[xref] = img_filename
        blocks.append(
            _Block(
                y=bbox[1],
                x=bbox[0],
                kind="image",
                markdown=f"![图片](images/{img_filename})",
            )
        )
    return blocks, count


# ========== 表格 ==========


def _detect_tables(page: "fitz.Page") -> list:
    """合并有框线与无框线两种检测结果。

    有框线结果优先；无框线检测（strategy="text"）会把整页版面也当成表格，
    因此只在它不覆盖已识别区域、不占据整页且单元格填充率合理时才采纳。
    """
    tables = _find_tables(page, "lines")
    page_area = abs(page.rect)
    for table in _find_tables(page, "text"):
        if table.row_count < 2 or table.col_count < 2:
            continue
        bbox = tuple(table.bbox)
        if page_area > 0 and _area(bbox) / page_area > _TEXT_TABLE_MAX_PAGE_RATIO:
            continue
        if any(_iou(bbox, tuple(existing.bbox)) > 0 for existing in tables):
            continue
        if _empty_cell_ratio(table.extract()) > _TEXT_TABLE_MAX_EMPTY_RATIO:
            continue
        tables.append(table)
    return tables


def _find_tables(page: "fitz.Page", strategy: str) -> list:
    """按指定策略检测表格，失败时返回空列表而不影响整页转换。"""
    try:
        finder = page.find_tables(strategy=strategy)
    except Exception:
        logger.warning("表格检测失败: strategy=%s", strategy)
        return []
    return list(getattr(finder, "tables", None) or [])


def _empty_cell_ratio(rows: list[list]) -> float:
    """统计表格中空单元格占比，用于排除误识别的空壳表格。"""
    cells = [cell for row in rows for cell in row]
    if not cells:
        return 1.0
    empty = sum(1 for cell in cells if not _cell_text(cell))
    return empty / len(cells)


def _table_rows(table) -> list[list[str]]:
    """提取表格的行文本，过滤全空行。"""
    rows: list[list[str]] = []
    for row in table.extract():
        cells = [_cell_text(cell) for cell in row]
        if any(cells):
            rows.append(cells)
    return rows


def _table_column_xs(table) -> tuple[float, ...]:
    """从首行单元格的左边界推导列起始 x 坐标，用于跨页表格对齐比对。"""
    rows = getattr(table, "rows", None) or []
    if not rows:
        return ()
    cells = getattr(rows[0], "cells", None) or []
    return tuple(float(cell[0]) for cell in cells if cell)


def _render_table_rows(rows: list[list[str]]) -> str:
    """把行数据渲染为管道式 Markdown 表格，首行作为表头。"""
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    lines: list[str] = []
    for index, row in enumerate(rows):
        cells = list(row) + [""] * (width - len(row))
        lines.append("| " + " | ".join(cells) + " |")
        if index == 0:
            lines.append("| " + " | ".join(["---"] * width) + " |")
    return "\n".join(lines)


def _cell_text(cell: object) -> str:
    """把单元格内容规范成单行文本，避免换行破坏表格结构。"""
    return str(cell).replace("\n", " ").strip() if cell else ""


def _inside_table(
    bbox: tuple[float, float, float, float],
    table_regions: list[tuple[float, float, float, float]],
) -> bool:
    """判断文本块或图片是否落在表格区域内。

    用「与表格的交集 / 自身面积」而不是交并比：单元格文本块面积远小于整张表格，
    交并比会被表格面积稀释而永远达不到阈值。
    """
    area = _area(bbox)
    if area <= 0:
        return False
    return any(_intersection(bbox, region) / area >= _TABLE_OVERLAP for region in table_regions)


def _area(bbox: tuple[float, float, float, float]) -> float:
    """计算矩形面积，坐标不足四项时返回 0。"""
    if len(bbox) < 4:
        return 0.0
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _intersection(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    """计算两个矩形的交集面积。"""
    if len(first) < 4 or len(second) < 4:
        return 0.0
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    if right <= left or bottom <= top:
        return 0.0
    return (right - left) * (bottom - top)


def _iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    """计算两个矩形的交并比，用于表格之间去重。"""
    intersection = _intersection(first, second)
    if intersection <= 0:
        return 0.0
    union = _area(first) + _area(second) - intersection
    return intersection / union if union > 0 else 0.0
