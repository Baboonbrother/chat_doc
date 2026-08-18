"""XLSX-004 合併區抽取｜把 ``<mergeCells>`` 讀成明確的區塊，並驗證它們不重疊。

為什麼要驗重疊：兩個合併區交疊在 Excel 裡會造成未定義行為，而在我們的生成端會讓
「值該寫進哪一格」沒有答案。與其之後在 renderer 出現難查的錯位，不如解析時就拒絕。

io: in=worksheet 元素; out=MergedRegion 清單
依賴: docengine.parsers.xlsx.refs
"""

from __future__ import annotations

from dataclasses import dataclass

from docengine.core.errors import ParseError
from docengine.parsers.ooxml import qn
from docengine.parsers.xlsx.loader import MAIN_NS
from docengine.parsers.xlsx.refs import make_cell_ref, parse_range_ref


@dataclass(frozen=True)
class MergedRegion:
    ref: str
    start_row: int
    start_col: int
    end_row: int
    end_col: int

    @property
    def anchor(self) -> str:
        """左上角那一格。合併區的值只存在這一格，其餘是被覆蓋的空格。"""
        return make_cell_ref(self.start_row, self.start_col)

    @property
    def rows(self) -> int:
        return self.end_row - self.start_row + 1

    @property
    def cols(self) -> int:
        return self.end_col - self.start_col + 1

    @property
    def orientation(self) -> str:
        if self.rows > 1 and self.cols > 1:
            return "both"
        if self.rows > 1:
            return "vertical"
        if self.cols > 1:
            return "horizontal"
        return "single"

    def covers(self, row: int, col: int) -> bool:
        return self.start_row <= row <= self.end_row and self.start_col <= col <= self.end_col


def extract_merges(worksheet) -> list[MergedRegion]:
    container = worksheet.find(qn(MAIN_NS, "mergeCells"))
    if container is None:
        return []

    regions: list[MergedRegion] = []
    for el in container.findall(qn(MAIN_NS, "mergeCell")):
        ref = el.get("ref")
        if not ref:
            raise ParseError("mergeCell 缺少 ref")
        r1, c1, r2, c2 = parse_range_ref(ref)
        regions.append(MergedRegion(ref=ref, start_row=r1, start_col=c1, end_row=r2, end_col=c2))

    _assert_no_overlap(regions)
    # 依左上角排序，讓輸出順序與檔案裡的書寫順序無關（IR 必須是確定性的）。
    return sorted(regions, key=lambda m: (m.start_row, m.start_col, m.end_row, m.end_col))


def _assert_no_overlap(regions: list[MergedRegion]) -> None:
    for i, a in enumerate(regions):
        for b in regions[i + 1 :]:
            if a.start_row <= b.end_row and b.start_row <= a.end_row and a.start_col <= b.end_col and b.start_col <= a.end_col:
                raise ParseError("合併區互相重疊", first=a.ref, second=b.ref)


def find_covering(regions: list[MergedRegion], row: int, col: int) -> MergedRegion | None:
    for region in regions:
        if region.covers(row, col):
            return region
    return None


__all__ = ["MergedRegion", "extract_merges", "find_covering"]
