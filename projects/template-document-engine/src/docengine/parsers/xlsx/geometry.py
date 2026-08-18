"""XLSX-006 幾何抽取｜欄寬、列高、隱藏、凍結窗格。

這些全部是檔案直接寫明的事實，屬於 deterministic 那一半（`ARCHITECTURE.md` §2）。
特別注意「隱藏」：欄的隱藏在 ``<col hidden="1">``、列在 ``<row hidden="1">``、
工作表在 workbook.xml 的 ``state``——三個不同層級，不能混為一談，
而且隱藏的內容仍然要被解析（它有資料，只是不顯示）。

io: in=worksheet 元素; out=ColumnSpan / RowGeometry / SheetView
依賴: docengine.parsers.ooxml
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from docengine.parsers.ooxml import qn
from docengine.parsers.xlsx.loader import MAIN_NS


@dataclass
class ColumnSpan:
    """一段欄定義。XLSX 用 min/max 區段描述欄，而不是一欄一筆。"""

    min: int
    max: int
    width: float | None = None
    custom_width: bool = False
    hidden: bool = False
    style_index: int | None = None
    best_fit: bool = False
    outline_level: int | None = None
    collapsed: bool = False

    def to_geometry(self) -> dict[str, Any]:
        geo: dict[str, Any] = {"min": self.min, "max": self.max}
        if self.width is not None:
            geo["width"] = self.width
        for key, value in (
            ("custom_width", self.custom_width),
            ("hidden", self.hidden),
            ("best_fit", self.best_fit),
            ("collapsed", self.collapsed),
        ):
            if value:
                geo[key] = True
        if self.outline_level:
            geo["outline_level"] = self.outline_level
        return geo


@dataclass
class RowGeometry:
    index: int
    height: float | None = None
    custom_height: bool = False
    hidden: bool = False
    style_index: int | None = None
    custom_format: bool = False
    outline_level: int | None = None
    collapsed: bool = False
    spans: str | None = None

    def to_geometry(self) -> dict[str, Any]:
        geo: dict[str, Any] = {}
        if self.height is not None:
            geo["height"] = self.height
        for key, value in (
            ("custom_height", self.custom_height),
            ("hidden", self.hidden),
            ("custom_format", self.custom_format),
            ("collapsed", self.collapsed),
        ):
            if value:
                geo[key] = True
        if self.outline_level:
            geo["outline_level"] = self.outline_level
        if self.spans:
            geo["spans"] = self.spans
        return geo


@dataclass
class SheetView:
    """工作表的視圖狀態。凍結窗格住在這裡。"""

    pane: dict[str, Any] = field(default_factory=dict)
    tab_selected: bool = False
    show_grid_lines: bool | None = None
    zoom_scale: int | None = None
    default_row_height: float | None = None
    default_col_width: float | None = None

    def to_geometry(self) -> dict[str, Any]:
        geo: dict[str, Any] = {}
        if self.pane:
            geo["pane"] = self.pane
        if self.tab_selected:
            geo["tab_selected"] = True
        if self.show_grid_lines is not None:
            geo["show_grid_lines"] = self.show_grid_lines
        if self.zoom_scale is not None:
            geo["zoom_scale"] = self.zoom_scale
        if self.default_row_height is not None:
            geo["default_row_height"] = self.default_row_height
        if self.default_col_width is not None:
            geo["default_col_width"] = self.default_col_width
        return geo


def extract_columns(worksheet) -> list[ColumnSpan]:
    container = worksheet.find(qn(MAIN_NS, "cols"))
    if container is None:
        return []
    spans: list[ColumnSpan] = []
    for el in container.findall(qn(MAIN_NS, "col")):
        spans.append(
            ColumnSpan(
                min=int(el.get("min", "1")),
                max=int(el.get("max", "1")),
                width=_as_float(el.get("width")),
                custom_width=_flag(el.get("customWidth")),
                hidden=_flag(el.get("hidden")),
                style_index=int(el.get("style")) if el.get("style") is not None else None,
                best_fit=_flag(el.get("bestFit")),
                outline_level=int(el.get("outlineLevel")) if el.get("outlineLevel") else None,
                collapsed=_flag(el.get("collapsed")),
            )
        )
    return sorted(spans, key=lambda c: (c.min, c.max))


def extract_row_geometry(row_el) -> RowGeometry:
    return RowGeometry(
        index=int(row_el.get("r")),
        height=_as_float(row_el.get("ht")),
        custom_height=_flag(row_el.get("customHeight")),
        hidden=_flag(row_el.get("hidden")),
        style_index=int(row_el.get("s")) if row_el.get("s") is not None else None,
        custom_format=_flag(row_el.get("customFormat")),
        outline_level=int(row_el.get("outlineLevel")) if row_el.get("outlineLevel") else None,
        collapsed=_flag(row_el.get("collapsed")),
        spans=row_el.get("spans"),
    )


def extract_sheet_view(worksheet) -> SheetView:
    view = SheetView()

    fmt = worksheet.find(qn(MAIN_NS, "sheetFormatPr"))
    if fmt is not None:
        view.default_row_height = _as_float(fmt.get("defaultRowHeight"))
        view.default_col_width = _as_float(fmt.get("defaultColWidth"))

    views = worksheet.find(qn(MAIN_NS, "sheetViews"))
    if views is None:
        return view
    first = views.find(qn(MAIN_NS, "sheetView"))
    if first is None:
        return view

    view.tab_selected = _flag(first.get("tabSelected"))
    if first.get("showGridLines") is not None:
        view.show_grid_lines = _flag(first.get("showGridLines"))
    if first.get("zoomScale") is not None:
        view.zoom_scale = int(first.get("zoomScale"))

    pane = first.find(qn(MAIN_NS, "pane"))
    if pane is not None:
        data: dict[str, Any] = {}
        for attr, key in (
            ("xSplit", "x_split"),
            ("ySplit", "y_split"),
            ("topLeftCell", "top_left_cell"),
            ("activePane", "active_pane"),
            ("state", "state"),
        ):
            value = pane.get(attr)
            if value is not None:
                data[key] = _as_float(value) if attr in ("xSplit", "ySplit") else value
        view.pane = data
    return view


def _as_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _flag(value: str | None) -> bool:
    return value in ("1", "true")


__all__ = [
    "ColumnSpan",
    "RowGeometry",
    "SheetView",
    "extract_columns",
    "extract_row_geometry",
    "extract_sheet_view",
]
