"""Document IR 正規化 diff｜定義「兩份 IR 相等」是什麼意思。

round-trip 驗證的核心。`ACCEPTANCE_AND_EVIDENCE.md` §3 要求比較必須明確宣告容差與未支援特徵，
所以容差是一個**要印在報告裡的具名物件**，不是藏在程式裡的幾個 if。

io: in=兩份 DocumentIR + Tolerance; out=IRDiff（可轉 JSON、可印成人看的報告）
依賴: docengine.core.document_ir.model
"""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from docengine.core.document_ir.model import DocumentIR, Node, canonical_json


class DiffKind(str, enum.Enum):
    NODE_ADDED = "node_added"
    NODE_REMOVED = "node_removed"
    NODE_CHANGED = "node_changed"
    STYLE_ADDED = "style_added"
    STYLE_REMOVED = "style_removed"
    RELATIONSHIP_ADDED = "relationship_added"
    RELATIONSHIP_REMOVED = "relationship_removed"
    UNSUPPORTED_ADDED = "unsupported_added"
    UNSUPPORTED_REMOVED = "unsupported_removed"
    HEADER_CHANGED = "header_changed"


class DiffEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DiffKind
    path: str
    left: Any = None
    right: Any = None
    note: str | None = None


class Tolerance(BaseModel):
    """明確宣告的比較容差。預設值就是 round-trip golden test 用的那一組。

    每一項都要能回答「為什麼忽略它不會讓測試變空心」。
    """

    model_config = ConfigDict(extra="forbid")

    #: 文件層欄位：來源檔名/雜湊/document_id 在 round-trip 兩側必然不同（來源是不同的檔案），
    #: 它們是出處資訊不是內容，忽略不會放過任何內容遺失。
    ignore_document_fields: tuple[str, ...] = ("document_id", "source", "metadata")

    #: source_ref 內忽略的子欄位。``original_index`` 是原始 styles.xml 的索引，AD-003 已說明
    #: 它在 render 後必然重排；``path`` 是 XML 元素路徑，會隨我們寫出的元素順序改變。
    #: part/sheet/cell 仍然比對——那三個才是「這個值在文件的哪裡」。
    ignore_source_ref_fields: tuple[str, ...] = ("original_index", "path")

    #: 浮點數比較的絕對容差。0 表示要求完全相等。
    float_abs_tol: float = 0.0

    #: 完全不參與比較的節點 attrs 鍵（格式層雜訊）。預設空的——要加就要寫理由。
    ignore_node_attrs: tuple[str, ...] = ()

    def describe(self) -> list[str]:
        lines = [
            f"忽略文件層欄位: {', '.join(self.ignore_document_fields) or '（無）'}",
            f"忽略 source_ref 子欄位: {', '.join(self.ignore_source_ref_fields) or '（無）'}",
            f"浮點絕對容差: {self.float_abs_tol}",
        ]
        if self.ignore_node_attrs:
            lines.append(f"忽略節點 attrs 鍵: {', '.join(self.ignore_node_attrs)}")
        return lines


class IRDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equal: bool
    entries: list[DiffEntry] = Field(default_factory=list)
    tolerance: Tolerance
    left_label: str = "A"
    right_label: str = "B"
    #: 兩側各自登記的未支援特徵。即使 diff 全綠，這一段也必須被讀——
    #: 它就是「這次 round-trip 沒有涵蓋到什麼」的答案。
    left_unsupported: list[dict[str, Any]] = Field(default_factory=list)
    right_unsupported: list[dict[str, Any]] = Field(default_factory=list)

    def render_text(self) -> str:
        out: list[str] = []
        verdict = "EQUAL" if self.equal else f"DIFFERENT ({len(self.entries)} 項)"
        out.append(f"Document IR diff: {self.left_label} vs {self.right_label} -> {verdict}")
        out.append("")
        out.append("宣告的容差:")
        out.extend(f"  - {line}" for line in self.tolerance.describe())
        out.append("")
        if self.entries:
            out.append("差異:")
            for e in self.entries[:200]:
                out.append(f"  [{e.kind.value}] {e.path}")
                if e.kind is DiffKind.NODE_CHANGED or e.kind is DiffKind.HEADER_CHANGED:
                    out.append(f"      {self.left_label}: {_short(e.left)}")
                    out.append(f"      {self.right_label}: {_short(e.right)}")
                elif e.left is not None:
                    out.append(f"      {self.left_label}: {_short(e.left)}")
                elif e.right is not None:
                    out.append(f"      {self.right_label}: {_short(e.right)}")
                if e.note:
                    out.append(f"      note: {e.note}")
            if len(self.entries) > 200:
                out.append(f"  ... 另有 {len(self.entries) - 200} 項未顯示")
            out.append("")
        out.append(f"未支援特徵（{self.left_label}）: {_fmt_unsupported(self.left_unsupported)}")
        out.append(f"未支援特徵（{self.right_label}）: {_fmt_unsupported(self.right_unsupported)}")
        return "\n".join(out)


def _fmt_unsupported(items: list[dict[str, Any]]) -> str:
    if not items:
        return "（無登記）"
    return "; ".join(f"{i['part']}::{i['element']}×{i.get('count', 1)}" for i in items)


def _short(value: Any, limit: int = 220) -> str:
    text = canonical_json(value) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[: limit - 3] + "..."


def diff_ir(
    left: DocumentIR,
    right: DocumentIR,
    tolerance: Tolerance | None = None,
    left_label: str = "A",
    right_label: str = "B",
) -> IRDiff:
    """比較兩份 IR。節點以 ``id`` 對齊——這是 ``make_node_id`` 用結構位置產生 id 的理由。"""
    tol = tolerance or Tolerance()
    entries: list[DiffEntry] = []

    left_doc = left.to_canonical_dict()
    right_doc = right.to_canonical_dict()
    for key in ("schema_version", "format"):
        if key in tol.ignore_document_fields:
            continue
        if left_doc.get(key) != right_doc.get(key):
            entries.append(
                DiffEntry(kind=DiffKind.HEADER_CHANGED, path=key, left=left_doc.get(key), right=right_doc.get(key))
            )

    left_nodes = {n.id: n for n in left.nodes}
    right_nodes = {n.id: n for n in right.nodes}
    for node_id in sorted(set(left_nodes) - set(right_nodes)):
        entries.append(DiffEntry(kind=DiffKind.NODE_REMOVED, path=node_id, left=_node_payload(left_nodes[node_id], tol)))
    for node_id in sorted(set(right_nodes) - set(left_nodes)):
        entries.append(DiffEntry(kind=DiffKind.NODE_ADDED, path=node_id, right=_node_payload(right_nodes[node_id], tol)))
    for node_id in sorted(set(left_nodes) & set(right_nodes)):
        a = _node_payload(left_nodes[node_id], tol)
        b = _node_payload(right_nodes[node_id], tol)
        for field in sorted(set(a) | set(b)):
            av, bv = a.get(field), b.get(field)
            if not _values_equal(av, bv, tol):
                entries.append(
                    DiffEntry(kind=DiffKind.NODE_CHANGED, path=f"{node_id}.{field}", left=av, right=bv)
                )

    left_styles = left.to_canonical_dict()["styles"]
    right_styles = right.to_canonical_dict()["styles"]
    # 樣式 id 就是內容雜湊（AD-003），所以「內容變了」必然表現成 id 出現/消失，不會有 CHANGED。
    for sid in sorted(set(left_styles) - set(right_styles)):
        entries.append(DiffEntry(kind=DiffKind.STYLE_REMOVED, path=sid, left=left_styles[sid]))
    for sid in sorted(set(right_styles) - set(left_styles)):
        entries.append(DiffEntry(kind=DiffKind.STYLE_ADDED, path=sid, right=right_styles[sid]))

    left_rels = {_rel_key(r): r for r in left.to_canonical_dict()["relationships"]}
    right_rels = {_rel_key(r): r for r in right.to_canonical_dict()["relationships"]}
    for key in sorted(set(left_rels) - set(right_rels)):
        entries.append(DiffEntry(kind=DiffKind.RELATIONSHIP_REMOVED, path=key, left=left_rels[key]))
    for key in sorted(set(right_rels) - set(left_rels)):
        entries.append(DiffEntry(kind=DiffKind.RELATIONSHIP_ADDED, path=key, right=right_rels[key]))

    left_unsup = {_unsup_key(u): u for u in left.to_canonical_dict()["unsupported"]}
    right_unsup = {_unsup_key(u): u for u in right.to_canonical_dict()["unsupported"]}
    for key in sorted(set(left_unsup) - set(right_unsup)):
        entries.append(DiffEntry(kind=DiffKind.UNSUPPORTED_REMOVED, path=key, left=left_unsup[key]))
    for key in sorted(set(right_unsup) - set(left_unsup)):
        entries.append(DiffEntry(kind=DiffKind.UNSUPPORTED_ADDED, path=key, right=right_unsup[key]))

    return IRDiff(
        equal=not entries,
        entries=entries,
        tolerance=tol,
        left_label=left_label,
        right_label=right_label,
        left_unsupported=left.to_canonical_dict()["unsupported"],
        right_unsupported=right.to_canonical_dict()["unsupported"],
    )


def _rel_key(rel: dict[str, Any]) -> str:
    return f"{rel['kind']}|{rel['source_id']}->{rel.get('target_id')}|{canonical_json(rel.get('attrs', {}))}"


def _unsup_key(item: dict[str, Any]) -> str:
    return f"{item['part']}::{item['element']}"


def _node_payload(node: Node, tol: Tolerance) -> dict[str, Any]:
    data = node.model_dump(mode="json")
    data.pop("id", None)
    if data.get("source_ref"):
        for field in tol.ignore_source_ref_fields:
            data["source_ref"].pop(field, None)
    if tol.ignore_node_attrs and data.get("attrs"):
        for key in tol.ignore_node_attrs:
            data["attrs"].pop(key, None)
    return data


def _values_equal(a: Any, b: Any, tol: Tolerance) -> bool:
    if tol.float_abs_tol > 0 and isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not isinstance(a, bool) and not isinstance(b, bool):
            return abs(float(a) - float(b)) <= tol.float_abs_tol
    return canonical_json(a) == canonical_json(b)


__all__ = ["DiffKind", "DiffEntry", "Tolerance", "IRDiff", "diff_ir"]
