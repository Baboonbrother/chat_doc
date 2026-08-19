"""A1 參照工具｜儲存格座標與欄名的雙向轉換。

單獨拆出來的理由：合併區、欄寬區段、公式依賴、renderer 都要用，而且它是純函式，
最適合用「已知答案」直接驗證，不需要任何檔案。

io: in=A1 字串 / (row, col) 整數; out=另一種表示
依賴: 無
"""

from __future__ import annotations

import re

from docengine.core.errors import ParseError

_CELL_REF = re.compile(r"^\$?([A-Z]{1,3})\$?([1-9][0-9]{0,6})$")
_RANGE_REF = re.compile(r"^(\$?[A-Z]{1,3}\$?[0-9]+):(\$?[A-Z]{1,3}\$?[0-9]+)$")


def column_to_index(letters: str) -> int:
    """``A`` -> 1、``Z`` -> 26、``AA`` -> 27。"""
    letters = letters.upper().lstrip("$")
    if not letters or not letters.isalpha():
        raise ParseError("不是合法的欄名", value=letters)
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index


def index_to_column(index: int) -> str:
    """1 -> ``A``、27 -> ``AA``。"""
    if index < 1:
        raise ParseError("欄索引必須 >= 1", value=index)
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def parse_cell_ref(ref: str) -> tuple[int, int]:
    """``B7`` -> ``(7, 2)``（列, 欄），兩者都是 1 起算。"""
    m = _CELL_REF.match(ref.strip().upper())
    if not m:
        raise ParseError("不是合法的儲存格參照", ref=ref)
    return int(m.group(2)), column_to_index(m.group(1))


def make_cell_ref(row: int, col: int) -> str:
    return f"{index_to_column(col)}{row}"


def parse_range_ref(ref: str) -> tuple[int, int, int, int]:
    """``A1:D3`` -> ``(1, 1, 3, 4)``＝(起始列, 起始欄, 結束列, 結束欄)。

    單格參照（``B7``）視為 1×1 區塊，因為合併區與條件格式都可能只涵蓋一格。
    """
    text = ref.strip().upper()
    m = _RANGE_REF.match(text)
    if not m:
        row, col = parse_cell_ref(text)
        return row, col, row, col
    r1, c1 = parse_cell_ref(m.group(1))
    r2, c2 = parse_cell_ref(m.group(2))
    return min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)


def make_range_ref(r1: int, c1: int, r2: int, c2: int) -> str:
    return f"{make_cell_ref(r1, c1)}:{make_cell_ref(r2, c2)}"


def iter_range(r1: int, c1: int, r2: int, c2: int):
    for row in range(r1, r2 + 1):
        for col in range(c1, c2 + 1):
            yield row, col


__all__ = [
    "column_to_index",
    "index_to_column",
    "parse_cell_ref",
    "make_cell_ref",
    "parse_range_ref",
    "make_range_ref",
    "iter_range",
]
