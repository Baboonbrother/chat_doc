"""XLSX-003 儲存格值與型別抽取｜把 ``<c>`` 讀成有型別、有出處的值。

型別判定完全確定性：由 ``t`` 屬性與數值格式決定，不交給模型猜。
`ARCHITECTURE.md` §2 把「cell 的值是什麼型別」明確列在 deterministic 那一邊。

字串在 XLSX 有兩種編碼（sharedStrings 索引與 inlineStr），本模組兩種都認，
而且把用了哪一種記在 ``string_encoding``——不記的話 render 會統一成一種，
round-trip 表面上會過，實際上已經改寫了檔案的儲存方式。

io: in=worksheet 的 <c> 元素 + sharedStrings + 樣式表; out=CellValue
依賴: docengine.parsers.xlsx.{refs,dates,styles}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from docengine.core.document_ir.model import ValueType, normalize_number
from docengine.core.errors import ParseError
from docengine.parsers.ooxml import MAIN_NS, OoxmlPackage, qn, serialize_element
from docengine.parsers.xlsx.dates import serial_to_iso
from docengine.parsers.xlsx.loader import MAIN_NS
from docengine.parsers.xlsx.refs import parse_cell_ref
from docengine.parsers.xlsx.styles import StyleTable

SHARED_STRINGS_PART = "xl/sharedStrings.xml"


@dataclass
class CellValue:
    ref: str
    row: int
    col: int
    style_index: int | None
    value: Any
    value_type: ValueType
    formula: str | None = None
    #: ``<f>`` 的完整屬性。共用公式 ``<f t="shared" ref="L9:AD9" si="0">`` 的 ref/si
    #: 是它能被其他格引用的關鍵；只留 t 會讓整批共用公式失效。
    formula_attrs: dict[str, str] = field(default_factory=dict)
    #: 這一格是不是公式格。**以 ``<f>`` 元素是否存在判定**，不以公式文字是否為空判定——
    #: 共用公式的後續格長這樣：``<f t="shared" si="0"/>``，沒有文字，但它確實是公式格。
    is_formula: bool = False
    #: shared | inline | None（非字串）。保留它，round-trip 才驗得到儲存方式沒被改寫。
    string_encoding: str | None = None
    #: 公式格的快取結果型別，例如 ``str``（字串結果）或 ``b``（布林結果）。
    cached_type: str | None = None
    #: 日期的儲存方式：``serial``（數字序列，最常見）或 ``iso``（``t="d"``，ECMA-376 允許）。
    date_encoding: str | None = None
    #: 富文字的原始 ``<si>`` XML。保留它，段內字型才不會在重寫時消失。
    rich_text_xml: str | None = None


@dataclass
class SharedStrings:
    """字串池。

    富文字（一個 ``<si>`` 裡有多個帶各自格式的 ``<r>`` 分段）的處理方式是兩件事並行：
    ``texts`` 給語意層用串接後的純文字（欄位推論要的是「這格寫什麼」），
    ``raw`` 保留原始 ``<si>`` XML 讓 renderer 原樣寫回（段內字型才不會消失）。
    只做前者會靜默丟掉格式；只做後者則沒有可比對的文字值。
    """

    texts: list[str] = field(default_factory=list)
    raw: list[str] = field(default_factory=list)
    rich: list[bool] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.texts)

    @property
    def rich_count(self) -> int:
        return sum(self.rich)


def load_shared_strings(pkg: OoxmlPackage) -> SharedStrings:
    table = SharedStrings()
    if not pkg.has(SHARED_STRINGS_PART):
        return table
    root = pkg.xml(SHARED_STRINGS_PART)
    for si in root.findall(qn(MAIN_NS, "si")):
        is_rich = si.find(qn(MAIN_NS, "r")) is not None
        table.texts.append(_si_text(si))
        table.rich.append(is_rich)
        table.raw.append(serialize_element(si, default_namespace=MAIN_NS) if is_rich else "")
    return table


def _si_text(si) -> str:
    direct = si.find(qn(MAIN_NS, "t"))
    if direct is not None:
        return direct.text or ""
    chunks = []
    for run in si.findall(qn(MAIN_NS, "r")):
        t = run.find(qn(MAIN_NS, "t"))
        if t is not None:
            chunks.append(t.text or "")
    return "".join(chunks)


def parse_cell(el, shared: SharedStrings, styles: StyleTable, date1904: bool = False) -> CellValue:
    """把一個 ``<c>`` 元素解析成 CellValue。

    型別判定順序刻意固定，因為它們會互相覆蓋：
    1. 有 ``<f>`` -> 這是公式格（``value`` 存的是快取結果，``formula`` 存算式）。
    2. ``t`` 屬性決定字串 / 布林 / 錯誤。
    3. 都不是就是數字；再看數值格式是否為日期格式，決定 number 還是 date。
    """
    ref = el.get("r")
    if not ref:
        raise ParseError("儲存格缺少 r 參照，無法定位")
    row, col = parse_cell_ref(ref)
    style_index = int(el.get("s")) if el.get("s") is not None else None
    cell_type = el.get("t", "n")

    formula_el = el.find(qn(MAIN_NS, "f"))
    is_formula = formula_el is not None
    formula = formula_el.text if is_formula else None
    formula_attrs = dict(formula_el.attrib) if is_formula else {}

    v_el = el.find(qn(MAIN_NS, "v"))
    raw = v_el.text if v_el is not None else None

    value: Any = None
    value_type = ValueType.NULL
    string_encoding: str | None = None

    date_encoding: str | None = None
    rich_text_xml: str | None = None

    if cell_type == "s":
        string_encoding = "shared"
        index = _shared_index(raw, shared, ref)
        value, value_type = shared.texts[index], ValueType.STRING
        if shared.rich[index]:
            rich_text_xml = shared.raw[index]
    elif cell_type == "d":
        # ECMA-376 允許直接寫 ISO 8601 字串而不是序列數字。實測真實 Excel 檔會用到。
        value, value_type, date_encoding = (raw or ""), ValueType.DATE, "iso"
    elif cell_type == "inlineStr":
        string_encoding = "inline"
        is_el = el.find(qn(MAIN_NS, "is"))
        value = _si_text(is_el) if is_el is not None else ""
        value_type = ValueType.STRING
    elif cell_type == "str":
        # 公式的字串結果，直接放在 <v> 裡，不走字串池。
        string_encoding = "formula_result"
        value, value_type = (raw or ""), ValueType.STRING
    elif cell_type == "b":
        value, value_type = raw in ("1", "true"), ValueType.BOOLEAN
    elif cell_type == "e":
        value, value_type = (raw or ""), ValueType.ERROR
    elif raw is not None:
        number = _to_number(raw, ref)
        if styles.is_date_style(style_index):
            value, value_type, date_encoding = serial_to_iso(number, date1904), ValueType.DATE, "serial"
        else:
            value, value_type = number, ValueType.NUMBER

    if is_formula:
        # 公式格保留快取結果，但型別記成 FORMULA——「這一格是算出來的」是重要的語意，
        # 之後 TPL-009 推導計算規則、GEN-004 決定哪些格不該直接填值，都靠它。
        return CellValue(
            ref=ref,
            row=row,
            col=col,
            style_index=style_index,
            value=value,
            value_type=ValueType.FORMULA,
            formula=formula,
            formula_attrs=formula_attrs,
            is_formula=True,
            string_encoding=string_encoding,
            cached_type=cell_type if cell_type != "n" else None,
            date_encoding=date_encoding,
            rich_text_xml=rich_text_xml,
        )

    return CellValue(
        ref=ref,
        row=row,
        col=col,
        style_index=style_index,
        value=value,
        value_type=value_type,
        string_encoding=string_encoding,
        date_encoding=date_encoding,
        rich_text_xml=rich_text_xml,
    )


def _shared_index(raw: str | None, shared: SharedStrings, ref: str) -> int:
    if raw is None:
        raise ParseError("共用字串格缺少索引", ref=ref)
    try:
        index = int(raw)
    except ValueError as exc:
        raise ParseError("共用字串索引不是整數", ref=ref, value=raw) from exc
    if not 0 <= index < len(shared):
        raise ParseError("共用字串索引超出範圍", ref=ref, index=index, size=len(shared))
    return index


def _to_number(raw: str, ref: str):
    try:
        return normalize_number(float(raw))
    except (ValueError, TypeError) as exc:
        raise ParseError("儲存格數值無法解析", ref=ref, value=raw) from exc


__all__ = [
    "SHARED_STRINGS_PART",
    "CellValue",
    "SharedStrings",
    "load_shared_strings",
    "parse_cell",
]
