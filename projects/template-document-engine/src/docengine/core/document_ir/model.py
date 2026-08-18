"""Document IR 契約｜描述「這一份文件現在長什麼樣」，與來源格式解耦。

io: in=parser 產出的節點/樣式資料; out=可正規化序列化、可雜湊、可 diff 的 DocumentIR
依賴: pydantic
"""

from __future__ import annotations

import enum
import hashlib
import json
import re
from typing import Any, Iterable, Iterator

from pydantic import BaseModel, ConfigDict, Field, field_validator

from docengine import CONTRACT_SCHEMA_VERSION
from docengine.core.errors import ContractViolation


class NodeKind(str, enum.Enum):
    """IR 節點種類。

    `SCHEMAS_AND_CONTRACTS.md` 列的是 sheet/section/paragraph/run/table/row/cell；
    這裡是刻意擴充後的唯一真相源，擴充理由見 `DECISIONS.md` AD-006。
    """

    DOCUMENT = "document"

    # --- XLSX ---
    SHEET = "sheet"
    COLUMN = "column"
    ROW = "row"
    CELL = "cell"
    MERGED_REGION = "merged_region"

    # --- DOCX ---
    SECTION = "section"
    PARAGRAPH = "paragraph"
    RUN = "run"
    TABLE = "table"
    TABLE_ROW = "table_row"
    TABLE_CELL = "table_cell"
    HEADER = "header"
    FOOTER = "footer"
    FIELD = "field"


class ValueType(str, enum.Enum):
    """節點值的語意型別。由確定性規則判定，不由 LLM 判定。"""

    STRING = "string"
    NUMBER = "number"
    DATE = "date"
    BOOLEAN = "boolean"
    FORMULA = "formula"
    ERROR = "error"
    NULL = "null"


class SourceKind(str, enum.Enum):
    XLSX = "xlsx"
    DOCX = "docx"
    GENERATED = "generated"


class SourceRef(BaseModel):
    """一個 IR 節點在原始 OOXML package 裡的座標。稽核與人工複核靠它。"""

    model_config = ConfigDict(extra="forbid")

    part: str = Field(description="OOXML package 內的 part 路徑，例如 xl/worksheets/sheet1.xml")
    path: str | None = Field(default=None, description="part 內的元素路徑，例如 worksheet/sheetData/row[3]/c[2]")
    sheet: str | None = Field(default=None, description="XLSX 專用：工作表名稱")
    cell: str | None = Field(default=None, description="XLSX 專用：A1 形式的儲存格參照")
    original_index: int | None = Field(default=None, description="原始檔案裡的索引（例如 cellXfs 的 s 值）")


class SourceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: SourceKind
    sha256: str | None = None
    filename: str | None = None


class FormatInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(description="xlsx 或 docx")
    #: 影響數值/日期解讀的全域旗標，例如 XLSX 的 date1904。
    flags: dict[str, Any] = Field(default_factory=dict)


class Style(BaseModel):
    """一個樣式指紋。ID 由內容算出（AD-003），與原始索引無關。"""

    model_config = ConfigDict(extra="forbid")

    font: dict[str, Any] = Field(default_factory=dict)
    fill: dict[str, Any] = Field(default_factory=dict)
    border: dict[str, Any] = Field(default_factory=dict)
    alignment: dict[str, Any] = Field(default_factory=dict)
    number_format: str | None = None
    protection: dict[str, Any] = Field(default_factory=dict)
    #: DOCX 的段落層屬性（pPr 衍生），XLSX 用不到就留空。
    paragraph: dict[str, Any] = Field(default_factory=dict)
    #: 格式特有、尚未歸類的已建模屬性。**不是**未支援特徵的垃圾桶——那個是 UnsupportedFeature。
    extras: dict[str, Any] = Field(default_factory=dict)

    def fingerprint(self) -> str:
        """回傳內容雜湊式的 style id：``style:<sha256 前 16 碼>``。"""
        payload = canonical_json(self.model_dump(mode="json"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return f"style:{digest}"


class Node(BaseModel):
    """IR 的一個節點。id 在單次 parse 內穩定且可重現。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: NodeKind
    parent_id: str | None = None
    order: int = 0
    value: Any = None
    value_type: ValueType = ValueType.NULL
    style_ref: str | None = None
    geometry: dict[str, Any] = Field(default_factory=dict)
    attrs: dict[str, Any] = Field(default_factory=dict)
    source_ref: SourceRef | None = None

    @field_validator("value")
    @classmethod
    def _value_must_be_scalar(cls, v: Any) -> Any:
        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        raise ValueError(f"node value 必須是 JSON 純量或 None，收到 {type(v).__name__}")


class Relationship(BaseModel):
    """節點之間的關係：公式依賴、合併錨點、超連結、編號參照等。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    source_id: str
    target_id: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)


class UnsupportedFeature(BaseModel):
    """未建模特徵登記簿的一筆（AD-004）。

    存在的理由：只模型化一部分 OOXML 的 parser 一定會遇到不認識的東西。靜默丟棄會讓 round-trip
    測試通過（兩邊都沒有它）卻讓使用者拿到少東西的檔案。登記它，讓「我們沒處理什麼」看得見。
    """

    model_config = ConfigDict(extra="forbid")

    part: str
    element: str
    path: str | None = None
    count: int = 1
    note: str | None = None


class DocumentIR(BaseModel):
    """一份文件的完整中介表示。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONTRACT_SCHEMA_VERSION
    document_id: str
    source: SourceInfo
    format: FormatInfo
    nodes: list[Node] = Field(default_factory=list)
    styles: dict[str, Style] = Field(default_factory=dict)
    relationships: list[Relationship] = Field(default_factory=list)
    unsupported: list[UnsupportedFeature] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # ------------------------------------------------------------------ 查詢

    def node_map(self) -> dict[str, Node]:
        return {n.id: n for n in self.nodes}

    def children_of(self, parent_id: str | None) -> list[Node]:
        """回傳某節點的子節點，依 ``order`` 排序（同 order 再依 id，確保確定性）。"""
        kids = [n for n in self.nodes if n.parent_id == parent_id]
        return sorted(kids, key=lambda n: (n.order, n.id))

    def roots(self) -> list[Node]:
        return self.children_of(None)

    def by_kind(self, kind: NodeKind) -> list[Node]:
        return [n for n in self.nodes if n.kind == kind]

    def walk(self, parent_id: str | None = None) -> Iterator[Node]:
        """深度優先走訪，順序確定。"""
        for node in self.children_of(parent_id):
            yield node
            yield from self.walk(node.id)

    # ------------------------------------------------------- 序列化 / 雜湊

    def to_canonical_dict(self) -> dict[str, Any]:
        """轉成正規化 dict：節點依 (parent 路徑, order, id) 排序、樣式表依 key 排序。"""
        data = self.model_dump(mode="json", exclude_none=False)
        data["nodes"] = [n.model_dump(mode="json") for n in self._sorted_nodes()]
        data["relationships"] = [
            r.model_dump(mode="json") for r in sorted(self.relationships, key=lambda r: (r.kind, r.source_id, r.target_id or "", r.id))
        ]
        data["unsupported"] = [
            u.model_dump(mode="json")
            for u in sorted(self.unsupported, key=lambda u: (u.part, u.element, u.path or ""))
        ]
        data["styles"] = {k: self.styles[k].model_dump(mode="json") for k in sorted(self.styles)}
        return data

    def _sorted_nodes(self) -> list[Node]:
        """依樹狀走訪順序排列節點；孤兒節點（parent 不存在）排在最後，並保持確定性。"""
        known = {n.id for n in self.nodes}
        ordered = list(self.walk(None))
        seen = {n.id for n in ordered}
        orphans = sorted(
            (n for n in self.nodes if n.id not in seen),
            key=lambda n: (n.parent_id or "", n.order, n.id),
        )
        if orphans:
            # 孤兒代表 parent_id 指向不存在的節點——這是契約違反，validate() 會擋下，
            # 但序列化不能把它們吃掉，否則 diff 會看不到問題。
            missing = {n.parent_id for n in orphans if n.parent_id not in known}
            if missing:
                pass  # 由 validate() 負責報錯；這裡只保證不丟失。
        return ordered + orphans

    def canonical_json(self) -> str:
        return canonical_json(self.to_canonical_dict())

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    # ------------------------------------------------------------ 契約驗證

    def validate_contract(self) -> None:
        """檢查 IR 自身的不變式。違反就丟 ContractViolation，不做靜默修補。"""
        ids: set[str] = set()
        for node in self.nodes:
            if node.id in ids:
                raise ContractViolation("Document IR 出現重複的 node id", node_id=node.id)
            ids.add(node.id)

        for node in self.nodes:
            if node.parent_id is not None and node.parent_id not in ids:
                raise ContractViolation(
                    "Document IR 的 parent_id 指向不存在的節點",
                    node_id=node.id,
                    parent_id=node.parent_id,
                )
            if node.style_ref is not None and node.style_ref not in self.styles:
                raise ContractViolation(
                    "Document IR 的 style_ref 指向不存在的樣式",
                    node_id=node.id,
                    style_ref=node.style_ref,
                )

        for rel in self.relationships:
            if rel.source_id not in ids:
                raise ContractViolation("relationship 的 source_id 不存在", relationship_id=rel.id, source_id=rel.source_id)
            if rel.target_id is not None and rel.target_id not in ids:
                raise ContractViolation("relationship 的 target_id 不存在", relationship_id=rel.id, target_id=rel.target_id)

        for style_id, style in self.styles.items():
            expected = style.fingerprint()
            if style_id != expected:
                raise ContractViolation(
                    "樣式 id 與內容雜湊不符（AD-003 要求 id 由內容算出）",
                    style_id=style_id,
                    expected=expected,
                )

        self._check_cycles()

    def _check_cycles(self) -> None:
        parent = {n.id: n.parent_id for n in self.nodes}
        for start in parent:
            slow = start
            seen: set[str] = set()
            while slow is not None:
                if slow in seen:
                    raise ContractViolation("Document IR 的節點樹出現循環", node_id=start)
                seen.add(slow)
                slow = parent.get(slow)


# --------------------------------------------------------------------- 工具


def canonical_json(data: Any) -> str:
    """確定性 JSON 序列化：key 排序、無多餘空白、不轉義非 ASCII、數值正規化。"""
    return json.dumps(
        _normalize(data),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return normalize_number(value)
    return value


def normalize_number(value: float | int) -> float | int:
    """數值正規化：整數值的浮點數收斂成 int。

    為什麼需要：XLSX 把 ``8`` 和 ``8.0`` 都存成數字文字。若不收斂，
    ``parse("8.0") -> 8.0 -> render "8.0" -> parse -> 8.0`` 沒問題，但
    ``parse("8.0") -> 8.0 -> render "8" -> parse -> 8``（int）就會讓 round-trip 假紅。
    統一在 parse 端收斂成同一個表示，兩邊才會相等。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        raise ContractViolation("IR 不接受 NaN 或 Inf 數值", value=str(value))
    if float(value).is_integer() and abs(value) < 2**53:
        return int(value)
    return float(value)


#: 只清掉會破壞 id 結構的字元：分隔符 ``:``、控制字元、以及各種空白。
#: 刻意**不**清掉中日韓文字——把非 ASCII 一律換成底線會讓「工作表1」和「資料表1」
#: 撞成同一個 id，那是一個很難查的靜默錯誤。canonical_json 用 ensure_ascii=False，
#: 非 ASCII 的 id 在序列化與 diff 都能正常運作。
_ID_UNSAFE = re.compile(r"[:\s\x00-\x1f\x7f]")


def make_node_id(*parts: Any) -> str:
    """組出穩定的節點 id。

    id 由結構位置決定（而非流水號），所以同一份檔案重複 parse、或 render 後再 parse，
    只要結構一樣就會得到一樣的 id——這是 round-trip diff 能逐節點對上的前提。
    """
    return ":".join(_ID_UNSAFE.sub("_", str(part)) for part in parts)


def build_style_table(styles: Iterable[Style]) -> dict[str, Style]:
    """把一堆樣式收斂成 ``id -> Style`` 表，重複的自動合併。"""
    table: dict[str, Style] = {}
    for style in styles:
        table[style.fingerprint()] = style
    return table


__all__ = [
    "NodeKind",
    "ValueType",
    "SourceKind",
    "SourceRef",
    "SourceInfo",
    "FormatInfo",
    "Style",
    "Node",
    "Relationship",
    "UnsupportedFeature",
    "DocumentIR",
    "canonical_json",
    "normalize_number",
    "make_node_id",
    "build_style_table",
]
