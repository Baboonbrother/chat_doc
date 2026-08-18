"""XLSX-001..010 測試。

檔案分兩半：前半驗各個抽取器讀到的東西對不對，後半是 round-trip。

後半最重要的是**突變矩陣**。「round-trip 全綠」本身證明不了什麼——一個什麼都不比較的 diff
也會全綠。所以每一種我們宣稱有守住的東西（值、樣式、合併、隱藏、凍結、欄寬、公式、日期、
逐字保留的未建模元素），都要故意弄壞一次，看 diff 會不會轉紅。轉不紅就代表那一項其實沒在守。
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Callable

import pytest

from docengine.core.document_ir import DocumentIR, NodeKind, ValueType, diff_ir
from docengine.core.errors import InputError, ParseError
from docengine.parsers.ooxml import load_package
from docengine.parsers.xlsx.compiler import parse_xlsx
from docengine.parsers.xlsx.dates import PHANTOM_SERIAL, iso_to_serial, serial_to_iso
from docengine.parsers.xlsx.formulas import extract_references
from docengine.parsers.xlsx.loader import load_workbook
from docengine.parsers.xlsx.merges import MergedRegion, _assert_no_overlap
from docengine.parsers.xlsx.refs import column_to_index, index_to_column, make_cell_ref, parse_cell_ref, parse_range_ref
from docengine.parsers.xlsx.styles import extract_styles, is_date_format_code
from docengine.renderers.xlsx.writer import render_xlsx
from docengine.validation.roundtrip import roundtrip_report

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "xlsx"
SAMPLES = sorted(FIXTURES.glob("duty_roster_sample_*.xlsx"))


@pytest.fixture(scope="module")
def ir() -> DocumentIR:
    return parse_xlsx(SAMPLES[0])


def _cell(ir: DocumentIR, ref: str):
    for node in ir.by_kind(NodeKind.CELL):
        if node.attrs.get("ref") == ref and node.source_ref and node.source_ref.sheet == "勤務表":
            return node
    raise AssertionError(f"找不到 {ref}")


def test_fixtures_exist():
    assert len(SAMPLES) == 3, "需要三份同型樣本才驗得到『重複列區筆數會變』"


# ============================================================ XLSX-001 載入與安全


def test_load_workbook_reads_topology():
    wb = load_workbook(SAMPLES[0])
    assert [s.name for s in wb.sheets] == ["勤務表", "統計", "設定"]
    assert wb.date1904 is False


def test_rejects_non_zip(tmp_path: Path):
    bad = tmp_path / "fake.xlsx"
    bad.write_text("這不是 zip", encoding="utf-8")
    with pytest.raises(InputError, match="不是有效的 OOXML"):
        load_workbook(bad)


def test_rejects_empty_file(tmp_path: Path):
    bad = tmp_path / "empty.xlsx"
    bad.write_bytes(b"")
    with pytest.raises(InputError, match="空的"):
        load_workbook(bad)


def test_rejects_zip_without_content_types(tmp_path: Path):
    bad = tmp_path / "nozip.xlsx"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(InputError, match="Content_Types"):
        load_workbook(bad)


def test_rejects_docx_shaped_package(tmp_path: Path):
    """把 .docx 改名成 .xlsx 要在入口就被擋下，而不是在 compiler 丟出難懂的錯。"""
    bad = tmp_path / "actually_a_doc.xlsx"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<document/>")
    with pytest.raises(InputError, match="不是試算表"):
        load_workbook(bad)


def test_rejects_path_traversal_in_package(tmp_path: Path):
    bad = tmp_path / "traversal.xlsx"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("../../etc/passwd", "root:x:0:0")
    with pytest.raises(InputError, match="路徑穿越"):
        load_workbook(bad)


def test_rejects_zip_bomb_ratio(tmp_path: Path):
    bad = tmp_path / "bomb.xlsx"
    with zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "A" * (20 * 1024 * 1024))
    with pytest.raises(InputError, match="壓縮比異常"):
        load_workbook(bad)


def test_rejects_dtd_in_part(tmp_path: Path):
    """billion laughs 防線。正常 OOXML 不含 DOCTYPE，所以直接拒絕。"""
    bad = tmp_path / "dtd.xlsx"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", '<!DOCTYPE lolz [<!ENTITY lol "lol">]><workbook/>')
    with pytest.raises(InputError, match="DTD"):
        load_workbook(bad)


# ============================================================ XLSX-002 拓撲


def test_sheet_nodes_carry_state_and_order(ir: DocumentIR):
    sheets = sorted(ir.by_kind(NodeKind.SHEET), key=lambda n: n.order)
    assert [s.attrs["name"] for s in sheets] == ["勤務表", "統計", "設定"]
    assert [s.attrs["state"] for s in sheets] == ["visible", "visible", "hidden"]


def test_hidden_sheet_content_is_still_parsed(ir: DocumentIR):
    """隱藏不等於不存在。隱藏表裡的設定值之後是範本學習的線索。"""
    hidden = [n for n in ir.by_kind(NodeKind.SHEET) if n.attrs["state"] == "hidden"][0]
    values = [c.value for c in ir.by_kind(NodeKind.CELL) if c.source_ref and c.source_ref.sheet == hidden.attrs["name"]]
    assert "template_version" in values


def test_duplicate_sheet_names_are_rejected(tmp_path: Path):
    src = load_package(SAMPLES[0])
    bad = tmp_path / "dup.xlsx"
    with zipfile.ZipFile(bad, "w") as z:
        for name, blob in src.parts.items():
            if name == "xl/workbook.xml":
                blob = blob.replace('name="統計"'.encode(), 'name="勤務表"'.encode())
            z.writestr(name, blob)
    with pytest.raises(ParseError, match="重複的工作表名稱"):
        load_workbook(bad)


# ============================================================ XLSX-003 值與型別


def test_cell_types_are_determined_deterministically(ir: DocumentIR):
    assert _cell(ir, "A2").value == "報表日期"
    assert _cell(ir, "B2").value_type is ValueType.DATE
    assert _cell(ir, "B2").value == "2026-08-20"
    assert _cell(ir, "C3").value_type is ValueType.BOOLEAN and _cell(ir, "C3").value is True
    assert _cell(ir, "D3").value_type is ValueType.ERROR and _cell(ir, "D3").value == "#N/A"
    assert _cell(ir, "C5").value_type is ValueType.NUMBER and _cell(ir, "C5").value == 8
    assert _cell(ir, "C8").value_type is ValueType.FORMULA


def test_both_string_encodings_are_read_and_labelled(ir: DocumentIR):
    """sharedStrings 與 inlineStr 兩種編碼都要認得，而且要記得用了哪一種。"""
    assert _cell(ir, "A2").attrs["string_encoding"] == "shared"
    assert _cell(ir, "D2").attrs["string_encoding"] == "inline"
    assert _cell(ir, "D2").value == "internal-1"


def test_percentage_stays_a_number_not_a_string(ir: DocumentIR):
    assert _cell(ir, "D5").value_type is ValueType.NUMBER
    assert _cell(ir, "D5").value == 0.925


def test_sparse_row_does_not_invent_empty_cells(ir: DocumentIR):
    """來源第 6、7 列的 A 欄沒有 <c>（被合併覆蓋）。parser 不該幫它生一格出來。"""
    refs = {c.attrs["ref"] for c in ir.by_kind(NodeKind.CELL) if c.source_ref and c.source_ref.sheet == "勤務表"}
    assert "A6" not in refs and "A7" not in refs
    assert "B6" in refs


def test_bad_shared_string_index_is_rejected(tmp_path: Path):
    src = load_package(SAMPLES[0])
    bad = tmp_path / "badsst.xlsx"
    with zipfile.ZipFile(bad, "w") as z:
        for name, blob in src.parts.items():
            if name == "xl/worksheets/sheet1.xml":
                blob = blob.replace(b'<c r="A2" s="5" t="s"><v>', b'<c r="A2" s="5" t="s"><v>9999', 1)
            z.writestr(name, blob)
    with pytest.raises(ParseError, match="索引超出範圍"):
        parse_xlsx(bad)


# ============================================================ 日期轉換


@pytest.mark.parametrize("iso", ["2026-08-20", "1900-01-01", "1900-03-01", "1999-12-31", "2000-02-29"])
def test_date_serial_round_trips(iso):
    assert serial_to_iso(iso_to_serial(iso)) == iso


def test_phantom_1900_02_29_is_rejected_not_silently_wrong():
    """1900 制有一天不存在。給一個看似合理但錯誤的日期，比報錯更糟。"""
    with pytest.raises(ParseError, match="不存在"):
        serial_to_iso(PHANTOM_SERIAL)


def test_1904_system_differs_from_1900_by_1462_days():
    assert iso_to_serial("2026-08-20", date1904=False) - iso_to_serial("2026-08-20", date1904=True) == 1462


def test_datetime_with_time_component_round_trips():
    assert serial_to_iso(iso_to_serial("2026-08-20T13:45:00")) == "2026-08-20T13:45:00"


# ============================================================ XLSX-004 合併區


def test_merges_cover_both_orientations(ir: DocumentIR):
    merges = {n.attrs["ref"]: n.attrs for n in ir.by_kind(NodeKind.MERGED_REGION)}
    assert merges["A1:D1"]["orientation"] == "horizontal"
    assert merges["A5:A7"]["orientation"] == "vertical"
    assert merges["A5:A7"]["anchor"] == "A5"


def test_overlapping_merges_are_rejected():
    """交疊的合併區會讓『值該寫進哪一格』沒有答案，必須在解析時就擋下。"""
    with pytest.raises(ParseError, match="重疊"):
        _assert_no_overlap(
            [
                MergedRegion(ref="A1:C3", start_row=1, start_col=1, end_row=3, end_col=3),
                MergedRegion(ref="B2:D4", start_row=2, start_col=2, end_row=4, end_col=4),
            ]
        )


def test_merge_count_differs_across_samples():
    """三份樣本的重複列區筆數不同（3/4/2），縱向合併範圍也要跟著不同。"""
    spans = []
    for sample in SAMPLES:
        merges = [n.attrs for n in parse_xlsx(sample).by_kind(NodeKind.MERGED_REGION)]
        vertical = [m for m in merges if m["orientation"] == "vertical"][0]
        spans.append(vertical["end_row"] - vertical["start_row"] + 1)
    assert sorted(spans) == [2, 3, 4]


# ============================================================ XLSX-005 樣式


def test_style_fingerprints_are_shared_across_identical_cells(ir: DocumentIR):
    """表頭四格用同一個樣式，指紋必須相同——否則樣式表會爆炸成每格一個。"""
    header = [_cell(ir, f"{c}4").style_ref for c in "ABCD"]
    assert len(set(header)) == 1 and header[0] is not None


def test_styles_capture_font_fill_border_and_number_format(ir: DocumentIR):
    title = ir.styles[_cell(ir, "A1").style_ref]
    assert title.font.get("bold") is True and title.font.get("size") == 16
    assert title.fill.get("fg_color", {}).get("rgb") == "FFDBE5F1"
    assert title.border.get("left", {}).get("style") == "medium"
    assert title.alignment.get("horizontal") == "center"

    pct = ir.styles[_cell(ir, "D5").style_ref]
    assert pct.number_format == "0.0%"


def test_border_variants_are_distinguished(ir: DocumentIR):
    label = ir.styles[_cell(ir, "A2").style_ref]
    assert label.border["left"]["style"] == "dashed"
    assert label.border["bottom"]["style"] == "double"


@pytest.mark.parametrize(
    "code,expected",
    [
        ("yyyy-mm-dd", True),
        ('yyyy"年"m"月"d"日"', True),
        ("General", False),
        ("0.0%", False),
        ("#,##0.00", False),
        ("[Red]0.00", False),
        ('"日期"0', False),
        ("h:mm:ss", True),
    ],
)
def test_date_format_detection_ignores_literals_and_brackets(code, expected):
    """``"年"`` 這種中文字面值、``[Red]`` 這種區段，都不該被誤判成日期 token。"""
    assert is_date_format_code(code) is expected


def test_style_table_is_smaller_than_cell_count(ir: DocumentIR):
    assert len(ir.styles) < len(ir.by_kind(NodeKind.CELL))


def test_styles_passthrough_preserves_cell_style_xfs():
    """cellXfs 的 xfId 指向 cellStyleXfs。丟掉它，樣式繼承鏈就斷了。"""
    table = extract_styles(load_package(SAMPLES[0]))
    assert any(item["tag"] == "cellStyleXfs" for item in table.passthrough)


# ============================================================ XLSX-006 幾何


def test_column_geometry(ir: DocumentIR):
    cols = {n.geometry["min"]: n.geometry for n in ir.by_kind(NodeKind.COLUMN) if n.source_ref.sheet == "勤務表"}
    assert cols[1]["width"] == 18.5 and cols[1]["custom_width"] is True
    assert cols[4]["hidden"] is True


def test_row_geometry(ir: DocumentIR):
    rows = {n.attrs["index"]: n.geometry for n in ir.by_kind(NodeKind.ROW) if n.source_ref.sheet == "勤務表"}
    assert rows[1]["height"] == 33 and rows[1]["custom_height"] is True
    assert rows[3]["hidden"] is True
    assert "hidden" not in rows[4]


def test_freeze_pane_is_captured(ir: DocumentIR):
    sheet = [n for n in ir.by_kind(NodeKind.SHEET) if n.attrs["name"] == "勤務表"][0]
    assert sheet.geometry["pane"] == {
        "x_split": 1,
        "y_split": 4,
        "top_left_cell": "B5",
        "active_pane": "bottomRight",
        "state": "frozen",
    }


# ============================================================ XLSX-007 公式依賴


def test_in_sheet_and_cross_sheet_dependencies(ir: DocumentIR):
    deps = [r for r in ir.relationships if r.kind == "formula_dependency"]
    in_sheet = [r for r in deps if not r.attrs["cross_sheet"]]
    cross = [r for r in deps if r.attrs["cross_sheet"]]
    assert {r.attrs["ref"] for r in in_sheet} == {"C5", "C6", "C7"}
    assert [r.attrs["sheet"] for r in cross] == ["勤務表"]
    assert all(r.attrs["resolved"] for r in deps)


@pytest.mark.parametrize(
    "formula,expected",
    [
        ("SUM(C5:C7)", ["C5", "C6", "C7"]),
        ("勤務表!C8", ["C8"]),
        ("'我的 表'!B2", ["B2"]),
        ("A1+B2*2", ["A1", "B2"]),
        ("$A$1", ["A1"]),
        ('IF(A1>0,"看 B7 欄",B7)', ["A1", "B7"]),
        ("LOG10(A1)", ["A1"]),
        ("MyNamedRange", []),
        ("", []),
    ],
)
def test_reference_extraction_edge_cases(formula, expected):
    """字串字面值裡的 B7、函式名裡的 LOG10、具名範圍——三個最容易誤抓的形狀。"""
    got = [c for ref in extract_references(formula) for c in ref.cells()]
    assert got == expected


def test_huge_range_is_not_expanded():
    """整欄參照展開成一百萬筆會讓 IR 爆掉。只留端點。"""
    assert extract_references("SUM(A1:A100000)")[0].cells() == ["A1", "A100000"]


# ============================================================ 參照工具


@pytest.mark.parametrize("letters,index", [("A", 1), ("Z", 26), ("AA", 27), ("AZ", 52), ("BA", 53), ("XFD", 16384)])
def test_column_conversion(letters, index):
    assert column_to_index(letters) == index
    assert index_to_column(index) == letters


def test_cell_ref_round_trip():
    assert make_cell_ref(*parse_cell_ref("$B$7")) == "B7"


def test_range_normalizes_reversed_corners():
    assert parse_range_ref("D3:A1") == (1, 1, 3, 4)


def test_single_cell_is_a_1x1_range():
    assert parse_range_ref("B7") == (7, 2, 7, 2)


# ============================================================ XLSX-008 編譯


def test_ir_validates_and_has_a_document_root(ir: DocumentIR):
    ir.validate_contract()
    roots = ir.roots()
    assert len(roots) == 1 and roots[0].kind is NodeKind.DOCUMENT


def test_unsupported_registry_actually_fires(ir: DocumentIR):
    """登記簿如果從沒被觸發過，它就是一個沒被驗證過的空 list。

    fixture 刻意放了 definedNames 與 conditionalFormatting 兩個我們不建模的元素。
    """
    registered = {(u.part, u.element) for u in ir.unsupported}
    assert ("xl/workbook.xml", "definedNames") in registered
    assert ("xl/worksheets/sheet1.xml", "conditionalFormatting") in registered


def test_unmodelled_elements_are_preserved_verbatim(ir: DocumentIR):
    """光是登記還不夠：重寫 worksheet 時它們會消失，所以必須同時逐字保留。"""
    sheet = [n for n in ir.by_kind(NodeKind.SHEET) if n.attrs["name"] == "勤務表"][0]
    tags = {item["tag"] for item in sheet.attrs["passthrough_xml"]}
    assert "conditionalFormatting" in tags
    root = ir.roots()[0]
    assert any(i["tag"] == "definedNames" for i in root.attrs["workbook_passthrough_xml"])


def test_parsing_is_reproducible():
    """同一份檔案解析兩次必須得到位元組相同的 IR，否則 diff 會被雜訊淹沒。"""
    assert parse_xlsx(SAMPLES[0]).canonical_json() == parse_xlsx(SAMPLES[0]).canonical_json()


# ============================================================ XLSX-009/010 round-trip


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: p.stem)
def test_round_trip_is_equal(sample: Path, tmp_path: Path):
    report = roundtrip_report(sample, out_dir=tmp_path)
    assert report.passed, report.render_text()
    assert report.source_hash == report.rebuilt_hash


def test_round_trip_report_declares_tolerances_and_unsupported(tmp_path: Path):
    """ACCEPTANCE §3：比較必須明確宣告容差與未支援特徵。它們要出現在報告裡。"""
    text = roundtrip_report(SAMPLES[0], out_dir=tmp_path).render_text()
    assert "宣告的容差" in text
    assert "definedNames" in text


def test_rebuilt_file_is_a_wellformed_package(tmp_path: Path):
    from xml.etree import ElementTree as ET

    report = roundtrip_report(SAMPLES[0], out_dir=tmp_path)
    with zipfile.ZipFile(report.rebuilt_path) as z:
        names = z.namelist()
        for name in names:
            ET.fromstring(z.read(name))
    assert "[Content_Types].xml" in names
    assert "xl/workbook.xml" in names
    assert sum(1 for n in names if n.startswith("xl/worksheets/")) == 3


# ------------------------------------------------------------------ 突變矩陣


def _mutate_and_diff(sample: Path, out_dir: Path, mutate: Callable[[DocumentIR], None]):
    original = parse_xlsx(sample)
    mutated = parse_xlsx(sample)
    mutate(mutated)
    target = out_dir / "mutated.xlsx"
    render_xlsx(mutated, target)
    return diff_ir(original, parse_xlsx(target))


def _first(ir: DocumentIR, kind: NodeKind, **match):
    for node in ir.by_kind(kind):
        if all(node.attrs.get(k) == v for k, v in match.items()):
            return node
    raise AssertionError(f"找不到 {kind} {match}")


def _mut_cell_value(ir: DocumentIR) -> None:
    _first(ir, NodeKind.CELL, ref="B5").value = "另一個人"


def _mut_date(ir: DocumentIR) -> None:
    _first(ir, NodeKind.CELL, ref="B2").value = "2026-12-31"


def _mut_formula(ir: DocumentIR) -> None:
    _first(ir, NodeKind.CELL, ref="C8").attrs["formula"] = "SUM(C5:C6)"


def _mut_style(ir: DocumentIR) -> None:
    node = _first(ir, NodeKind.CELL, ref="A1")
    style = ir.styles[node.style_ref].model_copy(deep=True)
    style.font["bold"] = False
    new_id = style.fingerprint()
    ir.styles[new_id] = style
    node.style_ref = new_id


def _mut_drop_merge(ir: DocumentIR) -> None:
    target = _first(ir, NodeKind.MERGED_REGION, ref="A5:A7")
    ir.nodes = [n for n in ir.nodes if n.id != target.id]


def _mut_unhide_row(ir: DocumentIR) -> None:
    for node in ir.by_kind(NodeKind.ROW):
        if node.geometry.get("hidden"):
            node.geometry.pop("hidden")
            return
    raise AssertionError("樣本裡沒有隱藏列")


def _mut_column_width(ir: DocumentIR) -> None:
    for node in ir.by_kind(NodeKind.COLUMN):
        if node.geometry.get("width") == 18.5:
            node.geometry["width"] = 40.0
            return
    raise AssertionError("樣本裡沒有寬度 18.5 的欄")


def _mut_drop_freeze(ir: DocumentIR) -> None:
    for node in ir.by_kind(NodeKind.SHEET):
        if node.geometry.get("pane"):
            node.geometry.pop("pane")
            return
    raise AssertionError("樣本裡沒有凍結窗格")


def _mut_unhide_sheet(ir: DocumentIR) -> None:
    _first(ir, NodeKind.SHEET, name="設定").attrs["state"] = "visible"


def _mut_drop_passthrough(ir: DocumentIR) -> None:
    """把逐字保留的條件格式拿掉——這正是「只登記不保留」會造成的靜默遺失。"""
    node = _first(ir, NodeKind.SHEET, name="勤務表")
    node.attrs["passthrough_xml"] = [i for i in node.attrs["passthrough_xml"] if i["tag"] != "conditionalFormatting"]


def _mut_string_encoding(ir: DocumentIR) -> None:
    _first(ir, NodeKind.CELL, ref="D2").attrs["string_encoding"] = "shared"


MUTATIONS: list[tuple[str, Callable[[DocumentIR], None]]] = [
    ("儲存格文字", _mut_cell_value),
    ("日期", _mut_date),
    ("公式", _mut_formula),
    ("字型粗體", _mut_style),
    ("移除縱向合併", _mut_drop_merge),
    ("取消隱藏列", _mut_unhide_row),
    ("欄寬", _mut_column_width),
    ("移除凍結窗格", _mut_drop_freeze),
    ("取消隱藏工作表", _mut_unhide_sheet),
    ("移除逐字保留的條件格式", _mut_drop_passthrough),
    ("改寫字串儲存編碼", _mut_string_encoding),
]


@pytest.mark.parametrize("label,mutate", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_round_trip_detects_each_mutation(label, mutate, tmp_path: Path):
    """突變證明：每一項我們宣稱守住的東西，弄壞它 diff 都必須轉紅。

    這才是 round-trip 有在守東西的證據。少了這個矩陣，一個永遠回傳 equal 的 diff
    也能讓所有 round-trip 測試全綠。
    """
    result = _mutate_and_diff(SAMPLES[0], tmp_path, mutate)
    assert not result.equal, f"突變「{label}」沒有被 diff 抓到——這一項其實沒有被守住"


def test_mutation_harness_itself_is_not_vacuous(tmp_path: Path):
    """反面對照：不做任何突變時，同一套流程必須是綠的。

    沒有這一條，上面的矩陣可能只是因為 render->parse 本來就對不上而全紅，
    那樣它證明的是「流程壞掉」而不是「守衛有效」。
    """
    assert _mutate_and_diff(SAMPLES[0], tmp_path, lambda ir: None).equal
