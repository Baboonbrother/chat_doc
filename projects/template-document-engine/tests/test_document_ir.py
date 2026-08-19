"""FND-002 Document IR 契約測試。

這裡驗的是 round-trip 之所以能成立的三個前提：
1. 序列化是確定性的（同樣的內容，不論建構順序，雜湊一樣）。
2. 樣式 id 由內容決定，不受原始索引影響。
3. 契約違反會被擋下來，不會靜默通過。
"""

import math

import pytest

from docengine.core.document_ir import (
    DocumentIR,
    FormatInfo,
    Node,
    NodeKind,
    Relationship,
    SourceInfo,
    SourceKind,
    SourceRef,
    Style,
    Tolerance,
    UnsupportedFeature,
    ValueType,
    build_style_table,
    canonical_json,
    diff_ir,
    make_node_id,
    normalize_number,
)
from docengine.core.errors import ContractViolation


def _style(bold: bool = True, number_format: str | None = None) -> Style:
    return Style(font={"bold": bold, "name": "Calibri", "size": 11}, number_format=number_format)


def _ir(nodes: list[Node], styles: dict[str, Style] | None = None, **kw) -> DocumentIR:
    return DocumentIR(
        document_id="doc-test",
        source=SourceInfo(kind=SourceKind.XLSX, sha256="a" * 64, filename="t.xlsx"),
        format=FormatInfo(type="xlsx"),
        nodes=nodes,
        styles=styles or {},
        **kw,
    )


def _small_doc() -> DocumentIR:
    style = _style()
    sid = style.fingerprint()
    sheet = Node(id="sheet:0", kind=NodeKind.SHEET, order=0, attrs={"name": "工作表1"})
    row = Node(id="sheet:0:row:1", kind=NodeKind.ROW, parent_id="sheet:0", order=1)
    cell = Node(
        id="sheet:0:cell:B7",
        kind=NodeKind.CELL,
        parent_id="sheet:0:row:1",
        order=2,
        value="石牌",
        value_type=ValueType.STRING,
        style_ref=sid,
        source_ref=SourceRef(part="xl/worksheets/sheet1.xml", sheet="工作表1", cell="B7", original_index=12),
    )
    return _ir([sheet, row, cell], {sid: style})


# ------------------------------------------------------------ 確定性序列化


def test_canonical_json_is_order_independent():
    """節點在 list 裡的先後不該改變正規化結果——否則 diff 會被建構順序污染。"""
    a = _small_doc()
    b = _small_doc()
    b.nodes = list(reversed(b.nodes))
    assert a.canonical_json() == b.canonical_json()
    assert a.content_hash() == b.content_hash()


def test_canonical_json_sorts_dict_keys():
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_content_hash_changes_when_a_value_changes():
    """雜湊要真的對內容敏感，否則它是個假的完整性檢查。"""
    a = _small_doc()
    b = _small_doc()
    before = b.content_hash()
    for node in b.nodes:
        if node.id == "sheet:0:cell:B7":
            node.value = "明德"
    assert a.content_hash() == before
    assert b.content_hash() != before


def test_walk_is_depth_first_and_deterministic():
    doc = _small_doc()
    assert [n.id for n in doc.walk()] == ["sheet:0", "sheet:0:row:1", "sheet:0:cell:B7"]


# ------------------------------------------------------------------ 數值正規化


@pytest.mark.parametrize(
    "raw,expected",
    [(8.0, 8), (8, 8), (8.5, 8.5), (-3.0, -3), (0.0, 0), (1e20, 1e20)],
)
def test_normalize_number(raw, expected):
    got = normalize_number(raw)
    assert got == expected
    if isinstance(expected, int) and not isinstance(expected, bool):
        assert isinstance(got, int)


def test_normalize_number_rejects_nan_and_inf():
    """NaN/Inf 進了 IR，JSON 會變成非法的 NaN 字面值，round-trip 會在最不明顯的地方壞掉。"""
    for bad in (float("nan"), math.inf, -math.inf):
        with pytest.raises(ContractViolation):
            normalize_number(bad)


def test_float_and_int_of_same_value_serialize_identically():
    assert canonical_json({"v": 8.0}) == canonical_json({"v": 8})


# ------------------------------------------------------------------- 樣式指紋


def test_style_fingerprint_is_content_addressed():
    assert _style(bold=True).fingerprint() == _style(bold=True).fingerprint()
    assert _style(bold=True).fingerprint() != _style(bold=False).fingerprint()


def test_style_fingerprint_ignores_original_position():
    """AD-003：同樣的樣式在兩份文件裡排第幾個都無所謂，id 必須一樣。"""
    table_a = build_style_table([_style(True), _style(False)])
    table_b = build_style_table([_style(False), _style(True)])
    assert set(table_a) == set(table_b)
    assert len(table_a) == 2


def test_build_style_table_deduplicates():
    table = build_style_table([_style(True), _style(True), _style(True)])
    assert len(table) == 1


# ------------------------------------------------------------------- 契約驗證


def test_valid_document_passes():
    _small_doc().validate_contract()


def test_duplicate_node_id_is_rejected():
    doc = _small_doc()
    doc.nodes.append(Node(id="sheet:0", kind=NodeKind.SHEET))
    with pytest.raises(ContractViolation, match="重複的 node id"):
        doc.validate_contract()


def test_dangling_parent_is_rejected():
    doc = _ir([Node(id="a", kind=NodeKind.CELL, parent_id="ghost")])
    with pytest.raises(ContractViolation, match="parent_id"):
        doc.validate_contract()


def test_dangling_style_ref_is_rejected():
    doc = _ir([Node(id="a", kind=NodeKind.CELL, style_ref="style:deadbeef")])
    with pytest.raises(ContractViolation, match="style_ref"):
        doc.validate_contract()


def test_style_id_must_match_its_content_hash():
    """如果允許 id 和內容脫鉤，AD-003 的保證就沒了。"""
    doc = _ir([], {"style:not-a-real-hash": _style()})
    with pytest.raises(ContractViolation, match="樣式 id"):
        doc.validate_contract()


def test_cycle_is_rejected():
    doc = _ir(
        [
            Node(id="a", kind=NodeKind.SHEET, parent_id="b"),
            Node(id="b", kind=NodeKind.SHEET, parent_id="a"),
        ]
    )
    with pytest.raises(ContractViolation, match="循環"):
        doc.validate_contract()


def test_dangling_relationship_is_rejected():
    doc = _small_doc()
    doc.relationships.append(Relationship(id="r1", kind="formula_dep", source_id="sheet:0:cell:B7", target_id="ghost"))
    with pytest.raises(ContractViolation, match="target_id"):
        doc.validate_contract()


def test_node_value_must_be_scalar():
    with pytest.raises(ValueError):
        Node(id="a", kind=NodeKind.CELL, value={"nested": "dict"})


def test_orphan_nodes_are_not_silently_dropped_from_serialization():
    """契約違反要靠 validate 擋，但序列化不能把證據吃掉——否則 diff 看不到節點不見了。"""
    doc = _ir([Node(id="a", kind=NodeKind.CELL, parent_id="ghost")])
    assert len(doc.to_canonical_dict()["nodes"]) == 1


# --------------------------------------------------------------------- ID 生成


def test_make_node_id_is_stable_and_sanitized():
    assert make_node_id("sheet", 0, "cell", "B7") == "sheet:0:cell:B7"
    assert make_node_id("a", 1) == make_node_id("a", 1)
    # 只清掉會破壞結構的字元（分隔符與空白）
    assert make_node_id("sheet", "工作表 #1") == "sheet:工作表_#1"


def test_make_node_id_does_not_collapse_distinct_cjk_names():
    """把非 ASCII 一律換底線會讓不同的中文名字撞成同一個 id，那是靜默的資料毀損。"""
    assert make_node_id("sheet", "工作表1") != make_node_id("sheet", "資料表1")


# ------------------------------------------------------------------------ diff


def test_diff_of_identical_documents_is_equal():
    d = diff_ir(_small_doc(), _small_doc())
    assert d.equal
    assert d.entries == []


def test_diff_detects_changed_value():
    a, b = _small_doc(), _small_doc()
    for n in b.nodes:
        if n.kind is NodeKind.CELL:
            n.value = "明德"
    d = diff_ir(a, b)
    assert not d.equal
    assert [e.path for e in d.entries] == ["sheet:0:cell:B7.value"]
    assert d.entries[0].left == "石牌" and d.entries[0].right == "明德"


def test_diff_detects_missing_node():
    a, b = _small_doc(), _small_doc()
    b.nodes = [n for n in b.nodes if n.kind is not NodeKind.CELL]
    d = diff_ir(a, b)
    assert [e.kind.value for e in d.entries] == ["node_removed"]


def test_diff_tolerates_style_index_churn_but_not_style_content_change():
    """render 後樣式索引重排是預期的；樣式內容變了則必須被抓到。"""
    a, b = _small_doc(), _small_doc()
    for n in b.nodes:
        if n.source_ref:
            n.source_ref.original_index = 99
    assert diff_ir(a, b).equal

    c = _small_doc()
    new_style = _style(bold=False)
    c.styles = {new_style.fingerprint(): new_style}
    for n in c.nodes:
        if n.style_ref:
            n.style_ref = new_style.fingerprint()
    d = diff_ir(a, c)
    assert not d.equal
    kinds = {e.kind.value for e in d.entries}
    assert "style_added" in kinds and "style_removed" in kinds


def test_diff_reports_unsupported_features_on_both_sides():
    """就算 diff 全綠，未支援特徵也必須出現在報告裡——那是『這次沒涵蓋到什麼』的答案。"""
    a = _small_doc()
    a.unsupported.append(UnsupportedFeature(part="xl/worksheets/sheet1.xml", element="conditionalFormatting", count=2))
    b = _small_doc()
    d = diff_ir(a, b)
    assert not d.equal
    assert any(e.kind.value == "unsupported_removed" for e in d.entries)
    text = d.render_text()
    assert "conditionalFormatting" in text
    assert "宣告的容差" in text


def test_tolerance_is_printed_in_the_report():
    """ACCEPTANCE §3 要求比較必須明確宣告容差。它必須看得見，不能只存在程式碼裡。"""
    text = diff_ir(_small_doc(), _small_doc()).render_text()
    for line in Tolerance().describe():
        assert line in text


def test_float_tolerance_can_be_declared():
    a, b = _small_doc(), _small_doc()
    a.nodes[-1].value, a.nodes[-1].value_type = 1.0000001, ValueType.NUMBER
    b.nodes[-1].value, b.nodes[-1].value_type = 1.0000002, ValueType.NUMBER
    assert not diff_ir(a, b).equal
    assert diff_ir(a, b, Tolerance(float_abs_tol=1e-6)).equal
