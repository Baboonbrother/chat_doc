"""XLSX-005 樣式指紋抽取｜把 styles.xml 的間接索引攤平成內容定址的 Style。

XLSX 的樣式是三層間接：``<c s="3">`` -> ``cellXfs[3]`` -> ``fontId/fillId/borderId/numFmtId``
-> ``fonts[2]`` / ``fills[1]`` / ...。IR 不保留這些索引（AD-003），因為 render 之後索引一定重排；
保留的是攤平後的內容，以及它的雜湊。

io: in=xl/styles.xml; out=索引 -> Style 的對照表 + 未支援登記
依賴: docengine.core.document_ir, docengine.parsers.ooxml
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from docengine.core.document_ir.model import Style
from docengine.parsers.ooxml import MAIN_NS, OoxmlPackage, local_name, qn, serialize_element

STYLES_PART = "xl/styles.xml"

#: Excel 內建數值格式。只列會影響型別判定與 round-trip 的那些；其餘用 numFmtId 原樣保留。
BUILTIN_FORMATS: dict[int, str] = {
    0: "General",
    1: "0",
    2: "0.00",
    3: "#,##0",
    4: "#,##0.00",
    9: "0%",
    10: "0.00%",
    11: "0.00E+00",
    12: "# ?/?",
    13: "# ??/??",
    14: "mm-dd-yy",
    15: "d-mmm-yy",
    16: "d-mmm",
    17: "mmm-yy",
    18: "h:mm AM/PM",
    19: "h:mm:ss AM/PM",
    20: "h:mm",
    21: "h:mm:ss",
    22: "m/d/yy h:mm",
    37: "#,##0 ;(#,##0)",
    38: "#,##0 ;[Red](#,##0)",
    39: "#,##0.00;(#,##0.00)",
    40: "#,##0.00;[Red](#,##0.00)",
    45: "mm:ss",
    46: "[h]:mm:ss",
    47: "mmss.0",
    48: "##0.0E+0",
    49: "@",
}

#: 內建的日期/時間格式 id。判定型別時直接查表，不必解析格式字串。
BUILTIN_DATE_IDS = frozenset(
    {14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58}
)

_QUOTED = re.compile(r'"[^"]*"')
_BRACKETED = re.compile(r"\[[^\]]*\]")
_ESCAPED = re.compile(r"\\.")
_DATE_TOKEN = re.compile(r"[ymdhs]", re.IGNORECASE)

#: styles.xml 裡我們自己建模的區塊。其餘一律「登記 + 逐字保留」。
#: ``cellStyleXfs`` 特別重要：cellXfs 的 ``xfId`` 指向它，丟掉它會讓樣式繼承鏈斷掉；
#: ``dxfs`` 則是 conditionalFormatting 的 ``dxfId`` 指向的地方，丟掉會讓條件格式失去外觀。
STYLES_MODELLED = {"numFmts", "fonts", "fills", "borders", "cellXfs"}


@dataclass
class StyleTable:
    """cellXfs 索引 -> Style，以及 Style 內容 -> 指紋 id。"""

    by_index: dict[int, Style] = field(default_factory=dict)
    number_formats: dict[int, str] = field(default_factory=dict)
    unsupported: list[dict[str, Any]] = field(default_factory=list)
    #: styles.xml 內未建模但逐字保留的頂層元素，renderer 會原樣寫回。
    passthrough: list[dict[str, str]] = field(default_factory=list)
    #: 原始子元素的標籤順序，理由同 XlsxWorkbook.child_sequence。
    child_sequence: list[str] = field(default_factory=list)

    def style_for(self, index: int | None) -> Style | None:
        if index is None:
            return None
        return self.by_index.get(index)

    def number_format_for(self, index: int | None) -> str | None:
        style = self.style_for(index)
        return style.number_format if style else None

    def is_date_style(self, index: int | None) -> bool:
        style = self.style_for(index)
        if style is None:
            return False
        num_fmt_id = style.extras.get("num_fmt_id")
        if isinstance(num_fmt_id, int) and num_fmt_id in BUILTIN_DATE_IDS:
            return True
        return is_date_format_code(style.number_format)


def is_date_format_code(code: str | None) -> bool:
    """判斷自訂數值格式字串是不是日期/時間格式。

    先剝掉引號字面值、方括號區段與跳脫字元，再看剩下的有沒有 y/m/d/h/s。
    不先剝就會被 ``"年"`` 這種中文字面值裡的字母、或 ``[Red]`` 誤導。
    """
    if not code or code == "General":
        return False
    stripped = _ESCAPED.sub("", _BRACKETED.sub("", _QUOTED.sub("", code)))
    return bool(_DATE_TOKEN.search(stripped))


def extract_styles(pkg: OoxmlPackage) -> StyleTable:
    table = StyleTable()
    if not pkg.has(STYLES_PART):
        # 沒有 styles.xml 是合法的（極簡活頁簿）。所有 cell 就只有預設樣式。
        return table

    root = pkg.xml(STYLES_PART)

    table.number_formats = dict(BUILTIN_FORMATS)
    num_fmts = root.find(qn(MAIN_NS, "numFmts"))
    if num_fmts is not None:
        for el in num_fmts.findall(qn(MAIN_NS, "numFmt")):
            fmt_id = el.get("numFmtId")
            code = el.get("formatCode")
            if fmt_id is not None and code is not None:
                table.number_formats[int(fmt_id)] = code

    fonts = [_parse_font(el) for el in _children(root, "fonts", "font")]
    fills = [_parse_fill(el) for el in _children(root, "fills", "fill")]
    borders = [_parse_border(el) for el in _children(root, "borders", "border")]

    cell_xfs = root.find(qn(MAIN_NS, "cellXfs"))
    if cell_xfs is not None:
        for index, xf in enumerate(cell_xfs.findall(qn(MAIN_NS, "xf"))):
            table.by_index[index] = _parse_xf(xf, fonts, fills, borders, table.number_formats)

    for child in root:
        tag = local_name(child.tag)
        table.child_sequence.append(tag)
        if tag in STYLES_MODELLED:
            continue
        table.passthrough.append({"tag": tag, "xml": serialize_element(child, default_namespace=MAIN_NS)})
        table.unsupported.append(
            {
                "part": STYLES_PART,
                "element": tag,
                "count": max(1, len(child)),
                "note": "未建模，但已逐字保留；renderer 會原樣寫回",
            }
        )
    return table


def _children(root, container: str, item: str) -> list:
    el = root.find(qn(MAIN_NS, container))
    return el.findall(qn(MAIN_NS, item)) if el is not None else []


def _parse_font(el) -> dict[str, Any]:
    font: dict[str, Any] = {}
    for flag in ("b", "i", "u", "strike", "outline", "shadow"):
        if el.find(qn(MAIN_NS, flag)) is not None:
            font[{"b": "bold", "i": "italic", "u": "underline"}.get(flag, flag)] = True
    for tag, key in (("sz", "size"), ("name", "name"), ("family", "family"), ("scheme", "scheme"), ("charset", "charset")):
        sub = el.find(qn(MAIN_NS, tag))
        if sub is not None and sub.get("val") is not None:
            value = sub.get("val")
            font[key] = _maybe_number(value) if key in ("size", "family", "charset") else value
    color = el.find(qn(MAIN_NS, "color"))
    if color is not None:
        font["color"] = _parse_color(color)
    return font


def _parse_fill(el) -> dict[str, Any]:
    pattern = el.find(qn(MAIN_NS, "patternFill"))
    if pattern is None:
        gradient = el.find(qn(MAIN_NS, "gradientFill"))
        return {"gradient": True} if gradient is not None else {}
    fill: dict[str, Any] = {"pattern_type": pattern.get("patternType", "none")}
    for tag, key in (("fgColor", "fg_color"), ("bgColor", "bg_color")):
        sub = pattern.find(qn(MAIN_NS, tag))
        if sub is not None:
            fill[key] = _parse_color(sub)
    return fill


def _parse_border(el) -> dict[str, Any]:
    border: dict[str, Any] = {}
    for side in ("left", "right", "top", "bottom", "diagonal"):
        sub = el.find(qn(MAIN_NS, side))
        if sub is None:
            continue
        style = sub.get("style")
        if style is None:
            continue
        entry: dict[str, Any] = {"style": style}
        color = sub.find(qn(MAIN_NS, "color"))
        if color is not None:
            entry["color"] = _parse_color(color)
        border[side] = entry
    for attr in ("diagonalUp", "diagonalDown"):
        if el.get(attr) in ("1", "true"):
            border[attr] = True
    return border


def _parse_color(el) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for attr, key in (("rgb", "rgb"), ("theme", "theme"), ("indexed", "indexed"), ("tint", "tint"), ("auto", "auto")):
        value = el.get(attr)
        if value is not None:
            out[key] = _maybe_number(value)
    return out


def _parse_xf(xf, fonts: list, fills: list, borders: list, number_formats: dict[int, str]) -> Style:
    num_fmt_id = int(xf.get("numFmtId", "0"))
    font_id = int(xf.get("fontId", "0"))
    fill_id = int(xf.get("fillId", "0"))
    border_id = int(xf.get("borderId", "0"))

    alignment: dict[str, Any] = {}
    al = xf.find(qn(MAIN_NS, "alignment"))
    if al is not None:
        for attr, key in (
            ("horizontal", "horizontal"),
            ("vertical", "vertical"),
            ("wrapText", "wrap_text"),
            ("textRotation", "text_rotation"),
            ("indent", "indent"),
            ("shrinkToFit", "shrink_to_fit"),
            ("readingOrder", "reading_order"),
        ):
            value = al.get(attr)
            if value is not None:
                alignment[key] = _maybe_bool_or_number(value)

    protection: dict[str, Any] = {}
    pr = xf.find(qn(MAIN_NS, "protection"))
    if pr is not None:
        for attr, key in (("locked", "locked"), ("hidden", "hidden")):
            value = pr.get(attr)
            if value is not None:
                protection[key] = value in ("1", "true")

    # apply* 旗標與 xfId 影響 Excel 的實際套用行為，所以要保留；不保留會在 round-trip 靜默丟失。
    extras: dict[str, Any] = {"num_fmt_id": num_fmt_id, "xf_id": int(xf.get("xfId", "0"))}
    for attr in ("applyNumberFormat", "applyFont", "applyFill", "applyBorder", "applyAlignment", "applyProtection", "quotePrefix", "pivotButton"):
        if xf.get(attr) in ("1", "true"):
            extras[attr] = True

    return Style(
        font=fonts[font_id] if font_id < len(fonts) else {},
        fill=fills[fill_id] if fill_id < len(fills) else {},
        border=borders[border_id] if border_id < len(borders) else {},
        alignment=alignment,
        number_format=number_formats.get(num_fmt_id, BUILTIN_FORMATS.get(num_fmt_id)),
        protection=protection,
        extras=extras,
    )


def _maybe_number(value: str) -> Any:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _maybe_bool_or_number(value: str) -> Any:
    if value in ("1", "true"):
        return True
    if value in ("0", "false"):
        return False
    return _maybe_number(value)


__all__ = [
    "STYLES_PART",
    "BUILTIN_FORMATS",
    "BUILTIN_DATE_IDS",
    "STYLES_MODELLED",
    "StyleTable",
    "extract_styles",
    "is_date_format_code",
]
