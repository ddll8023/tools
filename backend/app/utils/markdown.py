"""Markdown 内容统计工具"""

import re

_TABLE_SEPARATOR_RE = re.compile(r"(?m)^\s*\|(?:\s*:?-+:?\s*\|)+\s*$")


def count_tables(markdown: str) -> int:
    """统计 Markdown 表格数量（按分隔行计数，而非表格行数）。"""
    return len(_TABLE_SEPARATOR_RE.findall(markdown))
