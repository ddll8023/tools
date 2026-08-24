"""HTML 表格与 Markdown 管道表格的转换工具。

用于两处共享：
- Markdown 转 Word：MinerU 风格的原始 HTML 表格先归一化为管道表格再渲染；
- PDF 深度解析：MinerU 输出中的 HTML 表格在结果收集时归一化为管道表格。

仅处理规整的 <table>/<tr>/<td>/<th> 结构；合并单元格按"锚点保留文本、
覆盖位置留空"的展开网格处理，不还原视觉上的单元格合并。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# 单元格行列展开上限，防止异常属性值导致网格爆炸
_MAX_SPAN = 100

_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table\s*>", re.IGNORECASE | re.DOTALL)


class _TableGridParser(HTMLParser):
    """把单个 <table> 解析为按 rowspan/colspan 展开的二维文本网格。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.grid: dict[tuple[int, int], str] = {}
        self.row_count = 0
        self.col_count = 0
        self._row = -1
        self._cell: dict | None = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._row += 1
            self.row_count = max(self.row_count, self._row + 1)
            self._cell = None
        elif tag in ("td", "th") and self._row >= 0:
            attr_dict = {k.lower(): (v or "") for k, v in attrs}
            span = _clamp_span(attr_dict.get("rowspan"))
            colspan = _clamp_span(attr_dict.get("colspan"))
            col = 0
            while (self._row, col) in self.grid:
                col += 1
            self._cell = {"row": self._row, "col": col, "span": span, "colspan": colspan, "buf": []}

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["buf"].append(data)

    def handle_endtag(self, tag):
        if tag.lower() in ("td", "th") and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell["buf"])).strip()
            anchor_row, anchor_col = self._cell["row"], self._cell["col"]
            for row in range(anchor_row, anchor_row + self._cell["span"]):
                for col in range(anchor_col, anchor_col + self._cell["colspan"]):
                    is_anchor = row == anchor_row and col == anchor_col
                    self.grid[(row, col)] = text if is_anchor else ""
                    self.col_count = max(self.col_count, col + 1)
                    self.row_count = max(self.row_count, row + 1)
            self._cell = None


def _clamp_span(value: str | None) -> int:
    try:
        return min(max(int(str(value).strip()), 1), _MAX_SPAN)
    except (TypeError, ValueError):
        return 1


def parse_html_table(html: str) -> list[list[str]] | None:
    """解析单个 HTML 表格为文本网格；无内容或解析失败时返回 None。"""
    parser = _TableGridParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return None
    if parser.row_count == 0 or parser.col_count == 0:
        return None
    return [
        [parser.grid.get((row, col), "") for col in range(parser.col_count)]
        for row in range(parser.row_count)
    ]


def _grid_to_pipe_table(grid: list[list[str]]) -> str:
    width = max(len(row) for row in grid)

    def fmt_cell(text: str) -> str:
        cleaned = text.replace("|", "\\|").replace("\n", " ").strip()
        return cleaned or " "

    lines = []
    for index, row in enumerate(grid):
        padded = [fmt_cell(cell) for cell in row] + [" "] * (width - len(row))
        lines.append("| " + " | ".join(padded) + " |")
        if index == 0:
            lines.append("| " + " | ".join(["---"] * width) + " |")
    return "\n".join(lines)


def html_tables_to_markdown(text: str) -> tuple[str, int]:
    """把文本中的规整 HTML 表格替换为管道表格。

    返回 (新文本, 成功转换的表格数量)；无法解析的表格保持原样，
    由调用方决定后续行为（渲染告警或保留原文）。
    """
    converted = 0

    def replace(match: re.Match) -> str:
        nonlocal converted
        grid = parse_html_table(match.group(0))
        if grid is None:
            return match.group(0)
        converted += 1
        return f"\n\n{_grid_to_pipe_table(grid)}\n\n"

    return _TABLE_RE.sub(replace, text), converted
