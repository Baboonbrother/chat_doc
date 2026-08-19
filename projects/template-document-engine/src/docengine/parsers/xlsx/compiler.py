"""XLSX-008 編譯器｜把六個抽取器的結果組成一份 Document IR。

一個關鍵取捨要講清楚。renderer 會**重寫** worksheet XML（因為要能從 IR 生成新文件），
所以：

- 我們沒建模的**整個 part**（例如 drawings、theme），renderer 可以原封不動複製過去。
- 我們沒建模的**worksheet 內部元素**（例如 conditionalFormatting），一旦重寫就會消失。

只把後者登記進 ``unsupported`` 而不保留內容，round-trip 會全綠（兩邊都沒有它），
使用者卻拿到一份掉了條件格式的檔案。所以這裡兩件事一起做：
**登記**（讓「我們不懂它」看得見）＋**逐字保留**（讓它不會消失）。

io: in=.xlsx 路徑; out=DocumentIR
依賴: docengine.parsers.xlsx.*
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docengine.core.document_ir.model import (
    DocumentIR,
    FormatInfo,
    Node,
    NodeKind,
    Relationship,
    SourceInfo,
    SourceKind,
    SourceRef,
    Style,
    UnsupportedFeature,
    ValueType,
    make_node_id,
)
from docengine.parsers.ooxml import MAIN_NS, local_name, qn, serialize_element
from docengine.parsers.xlsx.cells import load_shared_strings, parse_cell
from docengine.parsers.xlsx.formulas import extract_references
from docengine.parsers.xlsx.geometry import extract_columns, extract_row_geometry, extract_sheet_view
from docengine.parsers.xlsx.loader import WORKBOOK_PART, XlsxWorkbook, load_workbook
from docengine.parsers.xlsx.merges import extract_merges
from docengine.parsers.xlsx.refs import make_cell_ref
from docengine.parsers.xlsx.styles import extract_styles

#: worksheet 裡我們自己建模的元素。其餘一律走「登記 + 逐字保留」。
MODELLED_WORKSHEET_ELEMENTS = {
    "dimension",  # 由 sheetData 重算，不必保留
    "sheetViews",
    "sheetFormatPr",
    "cols",
    "sheetData",
    "mergeCells",
}


def parse_xlsx(path: str | Path) -> DocumentIR:
    workbook = load_workbook(path)
    styles = extract_styles(workbook.package)
    shared = load_shared_strings(workbook.package)

    style_table: dict[str, Style] = {}
    nodes: list[Node] = []
    relationships: list[Relationship] = []
    unsupported: list[UnsupportedFeature] = []

    for item in workbook.unsupported:
        unsupported.append(UnsupportedFeature(**item))
    for item in styles.unsupported:
        unsupported.append(UnsupportedFeature(**item))

    # 文件根節點。workbook.xml 與 styles.xml 裡未建模但要逐字保留的東西掛在這裡，
    # 而不是放進 metadata——metadata 預設不參與 diff，放那裡等於讓它從驗證中消失。
    root_id = make_node_id("document")
    root_attrs: dict[str, Any] = {
        "date1904": workbook.date1904,
        "workbook_child_sequence": workbook.child_sequence,
        "styles_child_sequence": styles.child_sequence,
    }
    if workbook.passthrough:
        root_attrs["workbook_passthrough_xml"] = workbook.passthrough
    if styles.passthrough:
        root_attrs["styles_passthrough_xml"] = styles.passthrough
    nodes.append(
        Node(
            id=root_id,
            kind=NodeKind.DOCUMENT,
            parent_id=None,
            order=0,
            attrs=root_attrs,
            source_ref=SourceRef(part=WORKBOOK_PART),
        )
    )



    def style_ref(index: int | None) -> str | None:
        style = styles.style_for(index)
        if style is None:
            return None
        sid = style.fingerprint()
        style_table[sid] = style
        return sid

    # 儲存格 id -> 節點 id，供公式依賴解析成真正的關係。
    cell_index: dict[tuple[str, str], str] = {}
    pending_refs: list[tuple[str, str, Any]] = []

    for sheet in workbook.sheets:
        worksheet = workbook.package.xml(sheet.part)
        sheet_node_id = make_node_id("sheet", sheet.index)
        view = extract_sheet_view(worksheet)

        passthrough, sheet_unsupported, child_sequence = _collect_passthrough(worksheet, sheet.part)
        unsupported.extend(sheet_unsupported)

        sheet_attrs: dict[str, Any] = {
            "name": sheet.name,
            "sheet_id": sheet.sheet_id,
            "state": sheet.state,
            "part": sheet.part,
            "child_sequence": child_sequence,
        }
        if passthrough:
            sheet_attrs["passthrough_xml"] = passthrough

        nodes.append(
            Node(
                id=sheet_node_id,
                kind=NodeKind.SHEET,
                parent_id=root_id,
                order=sheet.index,
                attrs=sheet_attrs,
                geometry=view.to_geometry(),
                source_ref=SourceRef(part=sheet.part, sheet=sheet.name),
            )
        )

        order = 0
        for span in extract_columns(worksheet):
            nodes.append(
                Node(
                    id=make_node_id(sheet_node_id, "col", f"{span.min}-{span.max}"),
                    kind=NodeKind.COLUMN,
                    parent_id=sheet_node_id,
                    order=order,
                    geometry=span.to_geometry(),
                    style_ref=style_ref(span.style_index),
                    source_ref=SourceRef(part=sheet.part, sheet=sheet.name),
                )
            )
            order += 1

        for region in extract_merges(worksheet):
            nodes.append(
                Node(
                    id=make_node_id(sheet_node_id, "merge", region.ref),
                    kind=NodeKind.MERGED_REGION,
                    parent_id=sheet_node_id,
                    order=order,
                    attrs={
                        "ref": region.ref,
                        "start_row": region.start_row,
                        "start_col": region.start_col,
                        "end_row": region.end_row,
                        "end_col": region.end_col,
                        "anchor": region.anchor,
                        "orientation": region.orientation,
                    },
                    source_ref=SourceRef(part=sheet.part, sheet=sheet.name, cell=region.anchor),
                )
            )
            order += 1

        sheet_data = worksheet.find(qn(MAIN_NS, "sheetData"))
        if sheet_data is None:
            continue

        for row_el in sheet_data.findall(qn(MAIN_NS, "row")):
            row_geo = extract_row_geometry(row_el)
            row_node_id = make_node_id(sheet_node_id, "row", row_geo.index)
            nodes.append(
                Node(
                    id=row_node_id,
                    kind=NodeKind.ROW,
                    parent_id=sheet_node_id,
                    order=order,
                    attrs={"index": row_geo.index},
                    geometry=row_geo.to_geometry(),
                    style_ref=style_ref(row_geo.style_index),
                    source_ref=SourceRef(part=sheet.part, sheet=sheet.name),
                )
            )
            order += 1

            cell_order = 0
            for cell_el in row_el.findall(qn(MAIN_NS, "c")):
                cell = parse_cell(cell_el, shared, styles, workbook.date1904)
                cell_node_id = make_node_id(sheet_node_id, "cell", cell.ref)
                cell_index[(sheet.name, cell.ref)] = cell_node_id

                attrs: dict[str, Any] = {"ref": cell.ref, "row": cell.row, "col": cell.col}
                if cell.is_formula:
                    attrs["is_formula"] = True
                    if cell.formula is not None:
                        attrs["formula"] = cell.formula
                    if cell.formula_attrs:
                        attrs["formula_attrs"] = cell.formula_attrs
                if cell.string_encoding:
                    attrs["string_encoding"] = cell.string_encoding
                if cell.cached_type:
                    attrs["cached_type"] = cell.cached_type
                if cell.date_encoding:
                    attrs["date_encoding"] = cell.date_encoding
                if cell.rich_text_xml:
                    attrs["rich_text_xml"] = cell.rich_text_xml

                nodes.append(
                    Node(
                        id=cell_node_id,
                        kind=NodeKind.CELL,
                        parent_id=row_node_id,
                        order=cell_order,
                        value=cell.value,
                        value_type=cell.value_type,
                        style_ref=style_ref(cell.style_index),
                        attrs=attrs,
                        source_ref=SourceRef(
                            part=sheet.part,
                            sheet=sheet.name,
                            cell=cell.ref,
                            original_index=cell.style_index,
                        ),
                    )
                )
                cell_order += 1

                if cell.formula:
                    for reference in extract_references(cell.formula):
                        pending_refs.append((cell_node_id, sheet.name, reference))

    for source_id, home_sheet, reference in pending_refs:
        target_sheet = reference.sheet or home_sheet
        for target_ref in reference.cells():
            target_id = cell_index.get((target_sheet, target_ref))
            relationships.append(
                Relationship(
                    id=make_node_id("dep", source_id, target_sheet, target_ref),
                    kind="formula_dependency",
                    source_id=source_id,
                    target_id=target_id,
                    attrs={
                        "sheet": target_sheet,
                        "ref": target_ref,
                        "cross_sheet": reference.sheet is not None,
                        # 指到空格是正常的（SUM 涵蓋的範圍可能有空格），但必須看得出來，
                        # 否則「依賴解不開」和「依賴到空格」會被混為一談。
                        "resolved": target_id is not None,
                    },
                )
            )

    # 我們從頭到尾沒有讀過的 part（theme、docProps、drawings…）。
    # 不登記它們，round-trip 會全綠（parser 兩邊都沒讀），但檔案其實掉了東西——
    # 這正是 AD-004 要防的那種靜默遺失，只是發生在 part 層級而不是元素層級。
    consumed = {
        "[Content_Types].xml",
        "_rels/.rels",
        WORKBOOK_PART,
        "xl/_rels/workbook.xml.rels",
        "xl/styles.xml",
        "xl/sharedStrings.xml",
        *(s.part for s in workbook.sheets),
    }
    for part_name in workbook.package.part_order:
        if part_name not in consumed:
            unsupported.append(
                UnsupportedFeature(
                    part=part_name,
                    element="(整個 part)",
                    count=1,
                    note="parser 未讀取；renderer 需由來源封裝帶過（carry_over_parts）才不會遺失",
                )
            )

    # 富文字的登記量以「IR 實際承載幾格」為準，而不是「字串池裡有幾筆」。
    # 兩者會不一樣：字串池可能留著沒有任何儲存格引用的舊項目，
    # 而 renderer 只會寫出被引用到的字串。用池子的數量當登記量，
    # round-trip 兩側就會對不起來，而那個差異其實不代表任何資料遺失。
    rich_cells = sum(1 for n in nodes if n.kind is NodeKind.CELL and n.attrs.get("rich_text_xml"))
    if rich_cells:
        unsupported.append(
            UnsupportedFeature(
                part="xl/sharedStrings.xml",
                element="r",
                count=rich_cells,
                note="富文字分段格式未建模；純文字進 IR，原始 <si> 逐字保留供 renderer 原樣寫回",
            )
        )

    referenced = {n.value for n in nodes if n.kind is NodeKind.CELL and n.attrs.get("string_encoding") == "shared"}
    orphaned = sum(1 for text in shared.texts if text not in referenced)

    document_id = f"xlsx-{workbook.sha256[:16]}"
    ir = DocumentIR(
        document_id=document_id,
        source=SourceInfo(
            kind=SourceKind.XLSX,
            sha256=workbook.sha256,
            filename=Path(workbook.path).name if workbook.path else None,
        ),
        format=FormatInfo(type="xlsx", flags={"date1904": workbook.date1904}),
        nodes=nodes,
        styles=style_table,
        relationships=relationships,
        unsupported=_merge_unsupported(unsupported),
        metadata={
            "sheet_count": len(workbook.sheets),
            "parser": "docengine.parsers.xlsx",
            # 已宣告的正規化：字串池裡沒有任何儲存格引用的項目，重建時不會被寫出。
            # 它們是編輯過程留下的垃圾，丟掉不影響任何看得見的內容——但必須講出來，
            # 而不是讓使用者自己發現檔案變小了。
            "normalizations": ({"dropped_unreferenced_shared_strings": orphaned} if orphaned else {}),
        },
    )
    ir.validate_contract()
    return ir


def _collect_passthrough(
    worksheet, part: str
) -> tuple[list[dict[str, str]], list[UnsupportedFeature], list[str]]:
    """把 worksheet 裡未建模的頂層元素同時登記、逐字保留，並記下原始子元素順序。

    順序要記，是因為 renderer 若改用 schema 順序表輸出，順序表上沒有的元素會被丟掉；
    而且 ``conditionalFormatting`` 這種**可以重複出現**的元素，用「標籤 -> 區塊」的字典
    去組裝會只留下最後一個。兩種都是靜默遺失。
    """
    passthrough: list[dict[str, str]] = []
    registry: list[UnsupportedFeature] = []
    sequence: list[str] = []
    for child in worksheet:
        tag = local_name(child.tag)
        sequence.append(tag)
        if tag in MODELLED_WORKSHEET_ELEMENTS:
            continue
        passthrough.append({"tag": tag, "xml": serialize_element(child, default_namespace=MAIN_NS)})
        registry.append(
            UnsupportedFeature(
                part=part,
                element=tag,
                count=1,
                note="未建模，但已逐字保留；renderer 會原樣寫回",
            )
        )
    return passthrough, registry, sequence


def _merge_unsupported(items: list[UnsupportedFeature]) -> list[UnsupportedFeature]:
    """把同 part 同元素的登記合併計數，讓報告不會被幾十行重複塞滿。"""
    merged: dict[tuple[str, str], UnsupportedFeature] = {}
    for item in items:
        key = (item.part, item.element)
        if key in merged:
            merged[key].count += item.count
        else:
            merged[key] = item.model_copy(deep=True)
    return sorted(merged.values(), key=lambda u: (u.part, u.element))


__all__ = ["parse_xlsx", "MODELLED_WORKSHEET_ELEMENTS"]
