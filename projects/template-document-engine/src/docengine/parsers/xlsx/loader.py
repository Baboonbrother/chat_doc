"""XLSX-001 活頁簿載入與安全檢查｜把一個 zip 確認成「可以當試算表處理」的東西。

和 `parsers/ooxml.py` 的分工：那一層檢查「這是不是一個安全的 OOXML 封裝」，
這一層檢查「這個封裝是不是一個結構完整的試算表」——workbook 在不在、關聯解不解得開、
每張表的 part 存不存在。缺任何一項就在入口爆掉，而不是留到 compiler 才丟出難懂的 KeyError。

io: in=.xlsx 路徑; out=XlsxWorkbook（封裝 + 工作表清單 + 全域旗標）
依賴: docengine.parsers.ooxml
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docengine.core.errors import InputError, ParseError
from docengine.parsers.ooxml import (
    MAIN_NS,
    PKG_REL_NS,
    REL_NS,
    OoxmlPackage,
    load_package,
    local_name,
    qn,
    serialize_element,
)

WORKBOOK_PART = "xl/workbook.xml"
WORKBOOK_RELS_PART = "xl/_rels/workbook.xml.rels"

#: workbook.xml 裡我們自己建模的元素。其餘一律「登記 + 逐字保留」。
#: ``definedNames``（具名範圍、列印區域）就住在這裡——只登記不保留的話，
#: 重寫 workbook.xml 會讓所有具名範圍消失，而 round-trip 反而會因為兩邊都沒有它而全綠。
#: ``workbookPr`` 刻意**不**列為已建模：我們只從它讀 date1904，但它還帶著
#: defaultThemeVersion 等我們不理解的屬性。列為已建模就等於用一個只有 date1904 的版本
#: 覆蓋掉原件；當成 passthrough 則是原樣保留、只是順便讀一個值。
WORKBOOK_MODELLED = {"sheets"}


@dataclass
class SheetEntry:
    """workbook.xml 裡的一張工作表。"""

    index: int
    name: str
    sheet_id: str
    state: str  # visible | hidden | veryHidden
    rel_id: str
    part: str

    @property
    def visible(self) -> bool:
        return self.state == "visible"


@dataclass
class XlsxWorkbook:
    package: OoxmlPackage
    sheets: list[SheetEntry] = field(default_factory=list)
    #: 影響日期序列原點的全域旗標。1904 制的檔案若被當成 1900 制解讀，所有日期會差 1462 天。
    date1904: bool = False
    unsupported: list[dict[str, Any]] = field(default_factory=list)
    #: workbook.xml 內未建模但逐字保留的頂層元素，renderer 會原樣寫回。
    passthrough: list[dict[str, str]] = field(default_factory=list)
    #: 原始子元素的標籤順序。renderer 依它還原順序，而不是依 schema 順序表——
    #: 依順序表會讓表上沒有的元素（例如 mc:AlternateContent）被靜默丟掉。
    child_sequence: list[str] = field(default_factory=list)

    @property
    def sha256(self) -> str:
        return self.package.sha256

    @property
    def path(self) -> str | None:
        return self.package.path

    def sheet_by_name(self, name: str) -> SheetEntry:
        for sheet in self.sheets:
            if sheet.name == name:
                return sheet
        raise ParseError("找不到工作表", name=name)


def load_workbook(path: str | Path) -> XlsxWorkbook:
    """載入 .xlsx 並驗證它是一個結構完整的試算表。"""
    pkg = load_package(path)

    if not pkg.has(WORKBOOK_PART):
        raise InputError(
            "缺少 xl/workbook.xml：這不是試算表（可能是 .docx 或其他 OOXML 文件）",
            path=str(path),
        )

    rels = _read_relationships(pkg, WORKBOOK_RELS_PART)
    root = pkg.xml(WORKBOOK_PART)

    workbook = XlsxWorkbook(package=pkg)

    pr = root.find(qn(MAIN_NS, "workbookPr"))
    if pr is not None:
        workbook.date1904 = pr.get("date1904", "false") in ("1", "true")

    sheets_el = root.find(qn(MAIN_NS, "sheets"))
    if sheets_el is None or len(sheets_el) == 0:
        raise ParseError("活頁簿裡沒有任何工作表", path=str(path))

    seen_names: set[str] = set()
    for index, el in enumerate(sheets_el.findall(qn(MAIN_NS, "sheet"))):
        name = el.get("name")
        rel_id = el.get(qn(REL_NS, "id"))
        if not name:
            raise ParseError("工作表缺少名稱", index=index)
        if name in seen_names:
            raise ParseError("活頁簿出現重複的工作表名稱", name=name)
        seen_names.add(name)
        if not rel_id:
            raise ParseError("工作表缺少關聯 id", name=name)
        target = rels.get(rel_id)
        if target is None:
            raise ParseError("工作表的關聯解不開", name=name, rel_id=rel_id)
        part = _resolve_part("xl", target)
        if not pkg.has(part):
            raise ParseError("工作表的 part 不存在於封裝內", name=name, part=part)
        workbook.sheets.append(
            SheetEntry(
                index=index,
                name=name,
                sheet_id=el.get("sheetId", str(index + 1)),
                state=el.get("state", "visible"),
                rel_id=rel_id,
                part=part,
            )
        )

    for child in root:
        tag = local_name(child.tag)
        workbook.child_sequence.append(tag)
        if tag in WORKBOOK_MODELLED:
            continue
        workbook.passthrough.append({"tag": tag, "xml": serialize_element(child, default_namespace=MAIN_NS)})
        workbook.unsupported.append(
            {
                "part": WORKBOOK_PART,
                "element": tag,
                "count": 1,
                "note": "未建模，但已逐字保留；renderer 會原樣寫回",
            }
        )

    return workbook


def _read_relationships(pkg: OoxmlPackage, rels_part: str) -> dict[str, str]:
    """讀 ``_rels/*.rels``，回傳 ``rId -> Target``。"""
    if not pkg.has(rels_part):
        return {}
    root = pkg.xml(rels_part)
    out: dict[str, str] = {}
    for rel in root.findall(qn(PKG_REL_NS, "Relationship")):
        rid, target = rel.get("Id"), rel.get("Target")
        if rid and target:
            out[rid] = target
    return out


def _resolve_part(base_dir: str, target: str) -> str:
    """把關聯的 Target 解析成封裝內的絕對 part 名稱。"""
    if target.startswith("/"):
        return target.lstrip("/")
    parts: list[str] = []
    for chunk in f"{base_dir}/{target}".split("/"):
        if chunk in ("", "."):
            continue
        if chunk == "..":
            if parts:
                parts.pop()
            continue
        parts.append(chunk)
    return "/".join(parts)


__all__ = [
    "MAIN_NS",
    "REL_NS",
    "PKG_REL_NS",
    "WORKBOOK_PART",
    "WORKBOOK_MODELLED",
    "SheetEntry",
    "XlsxWorkbook",
    "load_workbook",
]
