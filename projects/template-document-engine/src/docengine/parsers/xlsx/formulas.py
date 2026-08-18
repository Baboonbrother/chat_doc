"""XLSX-007 公式依賴抽取｜從算式字串裡找出它引用了哪些格。

用途有三個，缺一不可：round-trip 要能還原公式；TPL-009 要從樣本推導計算規則；
GEN-004 要知道哪些格是算出來的、不該被資料直接覆蓋。

這是**詞法層**的抽取，不是公式求值。刻意不實作 Excel 函式庫——那是另一個量級的工程，
而且我們的生成端是把公式原樣寫回去，不需要自己算。

io: in=公式字串; out=FormulaReference 清單
依賴: docengine.parsers.xlsx.refs
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from docengine.parsers.xlsx.refs import parse_cell_ref

#: 字串字面值。必須先剝掉，否則 ="A1 欄位" 裡的 A1 會被當成參照。
_STRING_LITERAL = re.compile(r'"(?:[^"]|"")*"')

#: 工作表限定 + 儲存格或範圍。工作表名允許中日韓文字與帶引號的空白名稱。
_REFERENCE = re.compile(
    r"(?:(?:'(?P<quoted>[^']+)'|(?P<plain>[A-Za-z_一-鿿][\w.一-鿿]*))!)?"
    r"(?P<start>\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6})"
    r"(?::(?P<end>\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}))?"
)


@dataclass(frozen=True)
class FormulaReference:
    raw: str
    sheet: str | None
    start: str
    end: str | None

    @property
    def is_range(self) -> bool:
        return self.end is not None

    def cells(self) -> list[str]:
        """展開成單格清單。範圍太大時只回端點，避免把一整欄展開成一百萬筆。"""
        from docengine.parsers.xlsx.refs import iter_range, make_cell_ref, parse_range_ref

        if not self.is_range:
            return [_strip_absolute(self.start)]
        r1, c1, r2, c2 = parse_range_ref(f"{self.start}:{self.end}")
        if (r2 - r1 + 1) * (c2 - c1 + 1) > 4096:
            return [make_cell_ref(r1, c1), make_cell_ref(r2, c2)]
        return [make_cell_ref(r, c) for r, c in iter_range(r1, c1, r2, c2)]


def extract_references(formula: str) -> list[FormulaReference]:
    """從算式裡抽出所有儲存格/範圍參照，順序保留、重複去除。"""
    if not formula:
        return []

    # 用等長空白取代字串字面值，讓後續比對的位置資訊仍然對得上。
    masked = _STRING_LITERAL.sub(lambda m: " " * len(m.group(0)), formula)

    seen: set[tuple[str | None, str, str | None]] = set()
    out: list[FormulaReference] = []
    for m in _REFERENCE.finditer(masked):
        start, end = m.start(), m.end()

        # 後面緊接 "(" 代表這是函式名（LOG10( 看起來很像 LOG 欄第 10 列）。
        if end < len(masked) and masked[end] == "(":
            continue
        # 前面是識別字字元代表它是更長的名稱的一部分（例如 defined name ``MyA1``）。
        if start > 0 and (masked[start - 1].isalnum() or masked[start - 1] in "_.$"):
            continue

        ref_start = m.group("start")
        try:
            parse_cell_ref(ref_start)
        except Exception:
            continue

        sheet = m.group("quoted") or m.group("plain")
        key = (sheet, _strip_absolute(ref_start), _strip_absolute(m.group("end")) if m.group("end") else None)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            FormulaReference(
                raw=formula[m.start() : m.end()],
                sheet=sheet,
                start=ref_start,
                end=m.group("end"),
            )
        )
    return out


def _strip_absolute(ref: str | None) -> str:
    return ref.replace("$", "").upper() if ref else ""


__all__ = ["FormulaReference", "extract_references"]
