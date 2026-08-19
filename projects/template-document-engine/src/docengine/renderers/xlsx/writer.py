"""XLSX-009 渲染器｜從 Document IR 寫出 .xlsx。

設計原則：**只從 IR 產生**。渲染器不偷看來源檔案來補值——那會讓 round-trip 變成一場
「來源檔幫忙作弊」的表演，而生成新文件時根本沒有來源檔可看。

唯一的例外是 ``carry_over_parts``：我們**完全沒讀過**的 part（theme、docProps、drawings…）。
它們不在 IR 裡，所以 IR 無從產生；呼叫端可以把來源封裝的這些 part 交過來原樣打包。
不交也能產出合法檔案，只是那些 part 會缺席——而它們已經在未支援登記簿裡被列出來了。

io: in=DocumentIR (+ 選配的未讀取 part); out=.xlsx 檔案
依賴: docengine.core.document_ir, docengine.parsers.xlsx.dates
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from docengine.core.document_ir.model import DocumentIR, Node, NodeKind, Style, ValueType, canonical_json
from docengine.core.errors import RenderError
from docengine.parsers.ooxml import MAIN_NS, PKG_REL_NS, REL_NS
from docengine.parsers.xlsx.dates import iso_to_serial

#: CT_Worksheet 的元素順序。OOXML 的 schema 是 sequence，順序錯了 Excel 會拒絕開檔。
#: 逐字保留的元素要依這張表插回正確位置，不能一律附在最後。
WORKSHEET_ELEMENT_ORDER = [
    "sheetPr",
    "dimension",
    "sheetViews",
    "sheetFormatPr",
    "cols",
    "sheetData",
    "sheetCalcPr",
    "sheetProtection",
    "protectedRanges",
    "scenarios",
    "autoFilter",
    "sortState",
    "dataConsolidate",
    "customSheetViews",
    "mergeCells",
    "phoneticPr",
    "conditionalFormatting",
    "dataValidations",
    "hyperlinks",
    "printOptions",
    "pageMargins",
    "pageSetup",
    "headerFooter",
    "rowBreaks",
    "colBreaks",
    "customProperties",
    "cellWatches",
    "ignoredErrors",
    "smartTags",
    "drawing",
    "drawingHF",
    "picture",
    "oleObjects",
    "controls",
    "webPublishItems",
    "tableParts",
    "extLst",
]

#: CT_Workbook 的元素順序，理由同上。
WORKBOOK_ELEMENT_ORDER = [
    "fileVersion",
    "fileSharing",
    "workbookPr",
    "workbookProtection",
    "bookViews",
    "sheets",
    "functionGroups",
    "externalReferences",
    "definedNames",
    "calcPr",
    "oleSize",
    "customWorkbookViews",
    "pivotCaches",
    "smartTagPr",
    "smartTagTypes",
    "webPublishing",
    "fileRecoveryPr",
    "webPublishObjects",
    "extLst",
]

#: CT_Stylesheet 的元素順序。
STYLES_ELEMENT_ORDER = [
    "numFmts",
    "fonts",
    "fills",
    "borders",
    "cellStyleXfs",
    "cellXfs",
    "cellStyles",
    "dxfs",
    "tableStyles",
    "colors",
    "extLst",
]

XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _assemble(
    modelled: dict[str, str],
    passthrough: list[dict[str, str]],
    child_sequence: list[str],
    schema_order: list[str],
) -> str:
    """把已建模區塊與逐字保留片段組回一份 XML body。

    有原始順序（``child_sequence``）就照原始順序走，沒有才退回 schema 順序。
    照原始順序有兩個非走不可的理由：

    1. schema 順序表上沒有的元素（例如 ``mc:AlternateContent``）會被丟掉。
       實測 40 份真實 Excel 檔時，這讓 33 份重建後少了東西。
    2. ``conditionalFormatting`` 這類可重複出現的元素，用「標籤 -> 區塊」的字典組裝
       只會留下最後一個。

    最後還有一道兜底：走完之後任何沒被輸出的片段都會被補在尾端，
    寧可順序不完美，也不要靜默少東西。
    """
    pending: dict[str, list[str]] = {}
    for item in passthrough:
        pending.setdefault(item["tag"], []).append(item["xml"])

    out: list[str] = []
    emitted_modelled: set[str] = set()
    for tag in child_sequence:
        if tag in modelled and tag not in emitted_modelled:
            out.append(modelled[tag])
            emitted_modelled.add(tag)
        elif pending.get(tag):
            out.append(pending[tag].pop(0))

    # child_sequence 沒涵蓋到的已建模區塊（新合成的文件、或我們自己加的區塊）依 schema 順序補上。
    leftover_modelled = [t for t in schema_order if t in modelled and t not in emitted_modelled]
    leftover_modelled += [t for t in modelled if t not in emitted_modelled and t not in schema_order]
    if leftover_modelled and not out:
        out = [modelled[t] for t in leftover_modelled]
    else:
        for tag in leftover_modelled:
            out.append(modelled[tag])

    for tag in sorted(pending):
        out.extend(pending[tag])
    return "".join(out)


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _num(value: Any) -> str:
    """數值轉字串。整數不加 ``.0``——加了之後再解析會變回 float，round-trip 就對不上。"""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


class _StyleIndexer:
    """把 IR 的內容定址樣式攤回 XLSX 的索引式 styles.xml。"""

    def __init__(self, styles: dict[str, Style]) -> None:
        # 依 style id 排序，讓同一份 IR 每次 render 出來的索引都一樣。
        self.order = sorted(styles)
        self.styles = styles
        self.fonts: list[dict[str, Any]] = []
        self.fills: list[dict[str, Any]] = []
        self.borders: list[dict[str, Any]] = []
        self.num_fmts: dict[int, str] = {}
        self.xfs: list[tuple[Style, int, int, int, int]] = []
        self.index_of: dict[str, int] = {}
        self._build()

    def _build(self) -> None:
        # Excel 期待 fills 至少有 none 與 gray125 兩個保留項；先種進去再去重。
        self._intern(self.fills, {"pattern_type": "none"})
        self._intern(self.fills, {"pattern_type": "gray125"})
        for style_id in self.order:
            style = self.styles[style_id]
            font_id = self._intern(self.fonts, style.font)
            fill_id = self._intern(self.fills, style.fill)
            border_id = self._intern(self.borders, style.border)
            num_fmt_id = self._num_fmt_id(style)
            self.index_of[style_id] = len(self.xfs)
            self.xfs.append((style, num_fmt_id, font_id, fill_id, border_id))
        if not self.fonts:
            self.fonts.append({})
        if not self.borders:
            self.borders.append({})

    @staticmethod
    def _intern(pool: list[dict[str, Any]], item: dict[str, Any]) -> int:
        key = canonical_json(item)
        for i, existing in enumerate(pool):
            if canonical_json(existing) == key:
                return i
        pool.append(item)
        return len(pool) - 1

    def _num_fmt_id(self, style: Style) -> int:
        """還原數值格式 id。

        parser 有把原始 ``num_fmt_id`` 存進 extras，所以這裡能還原成同一個 id——
        包含 164 以上的自訂格式。沒有 extras（例如 IR 是程式合成的）才退回自行配號。
        """
        stored = style.extras.get("num_fmt_id")
        if isinstance(stored, int):
            if stored >= 164 and style.number_format:
                self.num_fmts[stored] = style.number_format
            return stored
        if not style.number_format or style.number_format == "General":
            return 0
        for fmt_id, code in self.num_fmts.items():
            if code == style.number_format:
                return fmt_id
        new_id = 164 + len(self.num_fmts)
        self.num_fmts[new_id] = style.number_format
        return new_id

    def to_xml(self, passthrough: list[dict[str, str]], child_sequence: list[str] | None = None) -> str:
        blocks: dict[str, str] = {}
        if self.num_fmts:
            items = "".join(
                f'<numFmt numFmtId="{i}" formatCode="{_esc(self.num_fmts[i])}"/>' for i in sorted(self.num_fmts)
            )
            blocks["numFmts"] = f'<numFmts count="{len(self.num_fmts)}">{items}</numFmts>'
        blocks["fonts"] = f'<fonts count="{len(self.fonts)}">{"".join(_font_xml(f) for f in self.fonts)}</fonts>'
        blocks["fills"] = f'<fills count="{len(self.fills)}">{"".join(_fill_xml(f) for f in self.fills)}</fills>'
        blocks["borders"] = f'<borders count="{len(self.borders)}">{"".join(_border_xml(b) for b in self.borders)}</borders>'
        blocks["cellXfs"] = f'<cellXfs count="{len(self.xfs)}">{"".join(_xf_xml(*x) for x in self.xfs)}</cellXfs>'
        if not any(i["tag"] == "cellStyleXfs" for i in passthrough):
            blocks["cellStyleXfs"] = '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        body = _assemble(blocks, passthrough, child_sequence or [], STYLES_ELEMENT_ORDER)
        return f'{XML_DECL}<styleSheet xmlns="{MAIN_NS}">{body}</styleSheet>'


def _font_xml(font: dict[str, Any]) -> str:
    parts = []
    for key, tag in (("bold", "b"), ("italic", "i"), ("underline", "u"), ("strike", "strike"), ("outline", "outline"), ("shadow", "shadow")):
        if font.get(key):
            parts.append(f"<{tag}/>")
    if "size" in font:
        parts.append(f'<sz val="{_num(font["size"])}"/>')
    if "color" in font:
        parts.append(_color_xml("color", font["color"]))
    if "name" in font:
        parts.append(f'<name val="{_esc(font["name"])}"/>')
    for key, tag in (("family", "family"), ("scheme", "scheme"), ("charset", "charset")):
        if key in font:
            parts.append(f'<{tag} val="{_num(font[key])}"/>')
    return f"<font>{''.join(parts)}</font>"


def _fill_xml(fill: dict[str, Any]) -> str:
    if not fill:
        return "<fill><patternFill/></fill>"
    if fill.get("gradient"):
        return "<fill><gradientFill/></fill>"
    pattern = fill.get("pattern_type", "none")
    inner = []
    if "fg_color" in fill:
        inner.append(_color_xml("fgColor", fill["fg_color"]))
    if "bg_color" in fill:
        inner.append(_color_xml("bgColor", fill["bg_color"]))
    if inner:
        return f'<fill><patternFill patternType="{_esc(pattern)}">{"".join(inner)}</patternFill></fill>'
    return f'<fill><patternFill patternType="{_esc(pattern)}"/></fill>'


def _border_xml(border: dict[str, Any]) -> str:
    parts = []
    for side in ("left", "right", "top", "bottom", "diagonal"):
        entry = border.get(side)
        if not entry:
            parts.append(f"<{side}/>")
            continue
        color = _color_xml("color", entry["color"]) if "color" in entry else ""
        parts.append(f'<{side} style="{_esc(entry["style"])}">{color}</{side}>')
    attrs = "".join(f' {k}="1"' for k in ("diagonalUp", "diagonalDown") if border.get(k))
    return f"<border{attrs}>{''.join(parts)}</border>"


def _color_xml(tag: str, color: dict[str, Any]) -> str:
    if not color:
        return f"<{tag}/>"
    attrs = "".join(f' {k}="{_num(v) if not isinstance(v, str) else _esc(v)}"' for k, v in sorted(color.items()))
    return f"<{tag}{attrs}/>"


def _xf_xml(style: Style, num_fmt_id: int, font_id: int, fill_id: int, border_id: int) -> str:
    attrs = f'numFmtId="{num_fmt_id}" fontId="{font_id}" fillId="{fill_id}" borderId="{border_id}"'
    xf_id = style.extras.get("xf_id")
    if isinstance(xf_id, int):
        attrs += f' xfId="{xf_id}"'
    for flag in ("applyNumberFormat", "applyFont", "applyFill", "applyBorder", "applyAlignment", "applyProtection", "quotePrefix", "pivotButton"):
        if style.extras.get(flag):
            attrs += f' {flag}="1"'
    inner = ""
    if style.alignment:
        align_attrs = "".join(f' {_camel(k)}="{_attr_value(v)}"' for k, v in sorted(style.alignment.items()))
        inner += f"<alignment{align_attrs}/>"
    if style.protection:
        prot_attrs = "".join(f' {k}="{_attr_value(v)}"' for k, v in sorted(style.protection.items()))
        inner += f"<protection{prot_attrs}/>"
    return f"<xf {attrs}>{inner}</xf>" if inner else f"<xf {attrs}/>"


_CAMEL = {
    "wrap_text": "wrapText",
    "text_rotation": "textRotation",
    "shrink_to_fit": "shrinkToFit",
    "reading_order": "readingOrder",
}


def _camel(key: str) -> str:
    return _CAMEL.get(key, key)


def _attr_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return _esc(_num(value)) if not isinstance(value, str) else _esc(value)


class XlsxRenderer:
    def __init__(self, ir: DocumentIR, carry_over_parts: dict[str, bytes] | None = None) -> None:
        if ir.format.type != "xlsx":
            raise RenderError("這份 IR 不是 xlsx", format=ir.format.type)
        self.ir = ir
        self.carry_over = carry_over_parts or {}
        self.date1904 = bool(ir.format.flags.get("date1904", False))
        self.styles = _StyleIndexer(ir.styles)
        self.shared: list[tuple[str, str]] = []
        self._shared_lookup: dict[tuple[str, str], int] = {}
        self._shared_refs = 0

    # ------------------------------------------------------------------ 主流程

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        sheets = self.ir.by_kind(NodeKind.SHEET)
        if not sheets:
            raise RenderError("IR 裡沒有工作表，無法產生 xlsx")
        sheets = sorted(sheets, key=lambda n: n.order)

        # 先產生工作表（過程中會填字串池），最後才寫 sharedStrings。
        worksheets = [(i, self._worksheet_xml(node)) for i, node in enumerate(sheets, start=1)]

        parts: dict[str, str | bytes] = {}
        parts["[Content_Types].xml"] = self._content_types(len(sheets))
        parts["_rels/.rels"] = self._root_rels()
        parts["xl/workbook.xml"] = self._workbook_xml(sheets)
        parts["xl/_rels/workbook.xml.rels"] = self._workbook_rels(len(sheets))
        parts["xl/styles.xml"] = self.styles.to_xml(
            self._root_attr("styles_passthrough_xml"), self._root_list("styles_child_sequence")
        )
        parts["xl/sharedStrings.xml"] = self._shared_strings_xml()
        for index, xml in worksheets:
            parts[f"xl/worksheets/sheet{index}.xml"] = xml

        for name, blob in self.carry_over.items():
            if name not in parts:
                parts[name] = blob

        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for name in sorted(parts):
                data = parts[name]
                z.writestr(name, data if isinstance(data, bytes) else data.encode("utf-8"))
        return target

    # ------------------------------------------------------------------ 各部件

    def _root_list(self, key: str) -> list[str]:
        for node in self.ir.by_kind(NodeKind.DOCUMENT):
            value = node.attrs.get(key)
            if isinstance(value, list):
                return [str(v) for v in value]
        return []

    def _root_attr(self, key: str) -> list[dict[str, str]]:
        for node in self.ir.by_kind(NodeKind.DOCUMENT):
            value = node.attrs.get(key)
            if isinstance(value, list):
                return value
        return []

    def _content_types(self, sheet_count: int) -> str:
        overrides = [
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
            '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>',
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        ]
        for i in range(1, sheet_count + 1):
            overrides.append(
                f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
        return (
            f"{XML_DECL}"
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f"{''.join(overrides)}</Types>"
        )

    def _root_rels(self) -> str:
        return (
            f"{XML_DECL}"
            f'<Relationships xmlns="{PKG_REL_NS}">'
            f'<Relationship Id="rId1" Type="{REL_NS}/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        )

    def _workbook_rels(self, sheet_count: int) -> str:
        rels = [
            f'<Relationship Id="rId{i}" Type="{REL_NS}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, sheet_count + 1)
        ]
        rels.append(
            f'<Relationship Id="rId{sheet_count + 1}" Type="{REL_NS}/sharedStrings" Target="sharedStrings.xml"/>'
        )
        rels.append(f'<Relationship Id="rId{sheet_count + 2}" Type="{REL_NS}/styles" Target="styles.xml"/>')
        return f'{XML_DECL}<Relationships xmlns="{PKG_REL_NS}">{"".join(rels)}</Relationships>'

    def _workbook_xml(self, sheets: list[Node]) -> str:
        blocks: dict[str, str] = {}
        passthrough = self._root_attr("workbook_passthrough_xml")
        # 來源有 workbookPr 就用它的逐字保留版本（它可能帶著我們不理解的屬性）；
        # 只有在完全沒有、且確實是 1904 制時，才自己生一個。
        if self.date1904 and not any(i["tag"] == "workbookPr" for i in passthrough):
            blocks["workbookPr"] = '<workbookPr date1904="1"/>'

        entries = []
        for i, node in enumerate(sheets, start=1):
            name = _esc(str(node.attrs.get("name", f"Sheet{i}")))
            sheet_id = _esc(str(node.attrs.get("sheet_id", i)))
            state = str(node.attrs.get("state", "visible"))
            state_attr = f' state="{_esc(state)}"' if state != "visible" else ""
            entries.append(f'<sheet name="{name}" sheetId="{sheet_id}"{state_attr} r:id="rId{i}"/>')
        blocks["sheets"] = f"<sheets>{''.join(entries)}</sheets>"

        body = _assemble(blocks, passthrough, self._root_list("workbook_child_sequence"), WORKBOOK_ELEMENT_ORDER)
        return f'{XML_DECL}<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">{body}</workbook>'

    def _shared_index(self, text: str, rich_xml: str | None = None) -> int:
        """取得字串池索引。

        鍵包含富文字 XML：同樣的純文字，一個帶段內格式一個不帶，是兩個不同的 ``<si>``，
        合併成一個會讓其中一邊的格式被另一邊覆蓋掉。
        """
        self._shared_refs += 1
        key = (text, rich_xml or "")
        if key not in self._shared_lookup:
            self._shared_lookup[key] = len(self.shared)
            self.shared.append(key)
        return self._shared_lookup[key]

    def _shared_strings_xml(self) -> str:
        items = "".join(rich if rich else f"<si>{_t_xml(text)}</si>" for text, rich in self.shared)
        return (
            f"{XML_DECL}"
            f'<sst xmlns="{MAIN_NS}" count="{self._shared_refs}" uniqueCount="{len(self.shared)}">{items}</sst>'
        )

    def _worksheet_xml(self, sheet: Node) -> str:
        children = self.ir.children_of(sheet.id)
        columns = [n for n in children if n.kind is NodeKind.COLUMN]
        merges = [n for n in children if n.kind is NodeKind.MERGED_REGION]
        rows = [n for n in children if n.kind is NodeKind.ROW]

        child_sequence = [str(t) for t in sheet.attrs.get("child_sequence", []) or []]
        blocks: dict[str, str] = {}
        # dimension 是選配元素。來源沒有就不要生一個出來——多生等於改寫了原檔的形狀，
        # 而且會讓 round-trip 因為「我們自己加的東西」而轉紅。
        if "dimension" in child_sequence or not child_sequence:
            blocks["dimension"] = self._dimension_xml(rows)

        view = self._sheet_views_xml(sheet)
        if view:
            blocks["sheetViews"] = view
        fmt = self._sheet_format_xml(sheet)
        if fmt:
            blocks["sheetFormatPr"] = fmt
        if columns:
            blocks["cols"] = "<cols>" + "".join(self._col_xml(c) for c in columns) + "</cols>"

        row_xml = "".join(self._row_xml(r) for r in rows)
        blocks["sheetData"] = f"<sheetData>{row_xml}</sheetData>"

        if merges:
            refs = "".join(f'<mergeCell ref="{_esc(str(m.attrs["ref"]))}"/>' for m in merges)
            blocks["mergeCells"] = f'<mergeCells count="{len(merges)}">{refs}</mergeCells>'

        body = _assemble(blocks, sheet.attrs.get("passthrough_xml", []) or [], child_sequence, WORKSHEET_ELEMENT_ORDER)
        return f'{XML_DECL}<worksheet xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">{body}</worksheet>'

    def _dimension_xml(self, rows: list[Node]) -> str:
        """``<dimension>`` 由 sheetData 重算，不從 IR 保留。

        它是純衍生資訊（涵蓋範圍），保留原值反而可能與重寫後的內容不一致。
        """
        bounds: list[tuple[int, int]] = []
        for row in rows:
            for cell in self.ir.children_of(row.id):
                bounds.append((int(cell.attrs["row"]), int(cell.attrs["col"])))
        if not bounds:
            return '<dimension ref="A1"/>'
        min_r = min(b[0] for b in bounds)
        max_r = max(b[0] for b in bounds)
        min_c = min(b[1] for b in bounds)
        max_c = max(b[1] for b in bounds)
        start = f"{_col_letters(min_c)}{min_r}"
        end = f"{_col_letters(max_c)}{max_r}"
        return f'<dimension ref="{start}"/>' if start == end else f'<dimension ref="{start}:{end}"/>'

    def _sheet_views_xml(self, sheet: Node) -> str:
        geo = sheet.geometry
        pane = geo.get("pane") or {}
        attrs = ""
        if geo.get("tab_selected"):
            attrs += ' tabSelected="1"'
        if geo.get("show_grid_lines") is False:
            attrs += ' showGridLines="0"'
        if geo.get("zoom_scale"):
            attrs += f' zoomScale="{_num(geo["zoom_scale"])}"'
        attrs += ' workbookViewId="0"'
        inner = ""
        if pane:
            pane_attrs = ""
            for key, attr in (("x_split", "xSplit"), ("y_split", "ySplit"), ("top_left_cell", "topLeftCell"), ("active_pane", "activePane"), ("state", "state")):
                if key in pane:
                    value = pane[key]
                    pane_attrs += f' {attr}="{_esc(value) if isinstance(value, str) else _num(value)}"'
            inner = f"<pane{pane_attrs}/>"
        return f"<sheetViews><sheetView{attrs}>{inner}</sheetView></sheetViews>" if inner else f"<sheetViews><sheetView{attrs}/></sheetViews>"

    def _sheet_format_xml(self, sheet: Node) -> str:
        geo = sheet.geometry
        attrs = ""
        if geo.get("default_col_width") is not None:
            attrs += f' defaultColWidth="{_num(geo["default_col_width"])}"'
        if geo.get("default_row_height") is not None:
            attrs += f' defaultRowHeight="{_num(geo["default_row_height"])}"'
        return f"<sheetFormatPr{attrs}/>" if attrs else ""

    def _col_xml(self, node: Node) -> str:
        geo = node.geometry
        attrs = f'min="{_num(geo.get("min", 1))}" max="{_num(geo.get("max", 1))}"'
        if geo.get("width") is not None:
            attrs += f' width="{_num(geo["width"])}"'
        for key, attr in (("custom_width", "customWidth"), ("hidden", "hidden"), ("best_fit", "bestFit"), ("collapsed", "collapsed")):
            if geo.get(key):
                attrs += f' {attr}="1"'
        if geo.get("outline_level"):
            attrs += f' outlineLevel="{_num(geo["outline_level"])}"'
        if node.style_ref:
            attrs += f' style="{self.styles.index_of[node.style_ref]}"'
        return f"<col {attrs}/>"

    def _row_xml(self, node: Node) -> str:
        geo = node.geometry
        attrs = f'r="{_num(node.attrs["index"])}"'
        if geo.get("spans"):
            attrs += f' spans="{_esc(geo["spans"])}"'
        if node.style_ref:
            attrs += f' s="{self.styles.index_of[node.style_ref]}"'
        if geo.get("custom_format"):
            attrs += ' customFormat="1"'
        if geo.get("height") is not None:
            attrs += f' ht="{_num(geo["height"])}"'
        if geo.get("hidden"):
            attrs += ' hidden="1"'
        if geo.get("custom_height"):
            attrs += ' customHeight="1"'
        if geo.get("outline_level"):
            attrs += f' outlineLevel="{_num(geo["outline_level"])}"'
        if geo.get("collapsed"):
            attrs += ' collapsed="1"'
        cells = "".join(self._cell_xml(c) for c in self.ir.children_of(node.id))
        return f"<row {attrs}>{cells}</row>" if cells else f"<row {attrs}/>"

    def _cell_xml(self, node: Node) -> str:
        ref = _esc(str(node.attrs["ref"]))
        attrs = f'r="{ref}"'
        if node.style_ref:
            attrs += f' s="{self.styles.index_of[node.style_ref]}"'

        if node.attrs.get("is_formula"):
            cached_type = node.attrs.get("cached_type")
            if cached_type:
                attrs += f' t="{_esc(str(cached_type))}"'
            f_attrs = "".join(
                f' {k}="{_esc(str(v))}"' for k, v in sorted((node.attrs.get("formula_attrs") or {}).items())
            )
            formula = node.attrs.get("formula")
            # 共用公式的後續格沒有公式文字：``<f t="shared" si="0"/>``。
            body = f"<f{f_attrs}>{_esc(str(formula))}</f>" if formula is not None else f"<f{f_attrs}/>"
            if node.value is not None:
                body += f"<v>{self._value_text(node)}</v>"
            return f"<c {attrs}>{body}</c>"

        if node.value is None:
            return f"<c {attrs}/>"

        if node.value_type is ValueType.STRING:
            encoding = node.attrs.get("string_encoding", "shared")
            if encoding == "inline":
                return f'<c {attrs} t="inlineStr"><is>{_t_xml(str(node.value))}</is></c>'
            if encoding == "formula_result":
                return f'<c {attrs} t="str"><v>{_esc(str(node.value))}</v></c>'
            return f'<c {attrs} t="s"><v>{self._shared_index(str(node.value), node.attrs.get("rich_text_xml"))}</v></c>'
        if node.value_type is ValueType.DATE and node.attrs.get("date_encoding") == "iso":
            return f'<c {attrs} t="d"><v>{_esc(str(node.value))}</v></c>'
        if node.value_type is ValueType.BOOLEAN:
            return f'<c {attrs} t="b"><v>{1 if node.value else 0}</v></c>'
        if node.value_type is ValueType.ERROR:
            return f'<c {attrs} t="e"><v>{_esc(str(node.value))}</v></c>'
        return f"<c {attrs}><v>{self._value_text(node)}</v></c>"

    def _value_text(self, node: Node) -> str:
        # 先看日期編碼再看型別：公式格的 value_type 是 FORMULA，但它的快取值可能是日期
        # （``<c s="2"><f>$H$6</f><v>46209</v></c>`` 配上日期數值格式）。
        # 漏掉這一步就會把 ISO 字串當成數字寫進 <v>，重新解析時整份檔案炸掉。
        encoding = node.attrs.get("date_encoding")
        if encoding == "iso":
            return _esc(str(node.value))
        if encoding == "serial":
            return _num(iso_to_serial(str(node.value), self.date1904))
        if node.value_type is ValueType.FORMULA:
            cached_type = node.attrs.get("cached_type")
            if cached_type == "s":
                return str(self._shared_index(str(node.value)))
            if cached_type == "b":
                return "1" if node.value else "0"
            if cached_type in ("e", "str"):
                return _esc(str(node.value))
        if isinstance(node.value, str):
            return _esc(node.value)
        return _num(node.value)


def _col_letters(index: int) -> str:
    from docengine.parsers.xlsx.refs import index_to_column

    return index_to_column(index)


def _t_xml(text: str) -> str:
    """``<t>`` 元素。前後有空白時要加 ``xml:space="preserve"``，否則 Excel 會把它吃掉。"""
    space = ' xml:space="preserve"' if text != text.strip() else ""
    return f"<t{space}>{_esc(text)}</t>"


def render_xlsx(ir: DocumentIR, path: str | Path, carry_over_parts: dict[str, bytes] | None = None) -> Path:
    return XlsxRenderer(ir, carry_over_parts).write(path)


__all__ = ["XlsxRenderer", "render_xlsx", "WORKSHEET_ELEMENT_ORDER", "WORKBOOK_ELEMENT_ORDER", "STYLES_ELEMENT_ORDER"]
