"""Canonical Data 契約｜描述「本次要填入的業務資料是什麼」，與輸入檔案的版面解耦。

關鍵設計：每一個值都同時保留 normalized 與 original。只留正規化值會讓「115/8/20 被解讀成
2026-08-20」這件事變成不可稽核的黑箱——出錯時沒有人查得出來是輸入錯還是解讀錯。

io: in=各種來源（JSON/CSV/XLSX/DOCX/純文字）抽出的值; out=可驗證、帶出處與狀態的 CanonicalData
依賴: pydantic, docengine.core.document_ir, docengine.core.evidence
"""

from __future__ import annotations

from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from docengine import CONTRACT_SCHEMA_VERSION
from docengine.core.document_ir.model import SourceRef
from docengine.core.errors import ContractViolation, GateFailure
from docengine.core.evidence import DecisionState
from docengine.core.template_profile import Cardinality, FieldDatatype, TemplateProfile


class CanonicalValue(BaseModel):
    """一個業務值。

    ``normalized`` 允許是純量、也允許是 list[dict]（例如一份人員名冊）。
    ``original`` 保留輸入端原樣，是稽核「解讀對不對」的唯一依據。
    """

    model_config = ConfigDict(extra="forbid")

    normalized: Any = None
    original: Any = None
    datatype: FieldDatatype = FieldDatatype.UNKNOWN
    source_refs: list[SourceRef] = Field(default_factory=list)
    confidence: float | None = None
    confidence_components: dict[str, float] = Field(default_factory=dict)
    state: DecisionState = DecisionState.CANDIDATE
    evidence_ids: list[str] = Field(default_factory=list)
    note: str | None = None

    @property
    def usable(self) -> bool:
        """能不能拿去生成。REVIEW/UNKNOWN/REJECTED 都不能，而且理由不同，不可合併處理。"""
        return self.state is DecisionState.ACCEPTED and self.normalized is not None


class Contradiction(BaseModel):
    """同一個欄位收到互相矛盾的值。保留兩邊，不自動挑一個。"""

    model_config = ConfigDict(extra="forbid")

    key: str
    values: list[Any]
    source_refs: list[SourceRef] = Field(default_factory=list)
    note: str | None = None


class CanonicalData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONTRACT_SCHEMA_VERSION
    data_id: str
    values: dict[str, CanonicalValue] = Field(default_factory=dict)
    contradictions: list[Contradiction] = Field(default_factory=list)
    #: 輸入裡有、但範本沒有對應欄位的東西。丟掉它們等於靜默漏資料，所以要登記。
    unmapped_inputs: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def get(self, key: str) -> CanonicalValue:
        try:
            return self.values[key]
        except KeyError as exc:
            raise ContractViolation("Canonical Data 沒有這個鍵", key=key, data_id=self.data_id) from exc

    def usable_keys(self) -> list[str]:
        return sorted(k for k, v in self.values.items() if v.usable)

    def needs_review(self) -> list[str]:
        return sorted(
            k for k, v in self.values.items() if v.state in (DecisionState.REVIEW, DecisionState.UNKNOWN)
        )

    # ------------------------------------------------------------ 契約驗證

    def validate_contract(self) -> None:
        for key, value in self.values.items():
            if value.state is DecisionState.ACCEPTED and value.normalized is None and value.datatype is not FieldDatatype.UNKNOWN:
                raise ContractViolation("值標成 ACCEPTED 卻沒有正規化結果", key=key)
            if value.confidence is not None and not 0.0 <= value.confidence <= 1.0:
                raise ContractViolation("confidence 必須在 0..1", key=key, confidence=value.confidence)
            if value.datatype is FieldDatatype.LIST and value.normalized is not None:
                if not isinstance(value.normalized, list):
                    raise ContractViolation("datatype=list 的值必須是 list", key=key)

    # ------------------------------------------------------- 與範本的對帳

    def missing_required(self, profile: TemplateProfile) -> list[str]:
        """對照範本，回傳「必填但拿不到可用值」的欄位名。

        這是生成閘的輸入。回傳的是**欄位名清單**而不是 bool，因為使用者需要知道缺哪一個，
        而不是只知道「不能生成」。
        """
        missing: list[str] = []
        for field in profile.required_fields():
            key = field.semantic_name or field.field_id
            value = self.values.get(key)
            if value is None or not value.usable:
                missing.append(key)
            elif field.cardinality is Cardinality.MANY and isinstance(value.normalized, list) and not value.normalized:
                missing.append(key)
        return missing

    def assert_ready_for_generation(self, profile: TemplateProfile) -> None:
        """生成前的閘。缺料就拒絕，並且說得出缺什麼——不填空白、不猜。"""
        missing = self.missing_required(profile)
        if missing:
            raise GateFailure(
                "必填欄位缺漏，拒絕生成",
                data_id=self.data_id,
                template_id=profile.template_id,
                missing=missing,
            )
        if self.contradictions:
            raise GateFailure(
                "輸入存在互相矛盾的值，拒絕生成",
                data_id=self.data_id,
                keys=[c.key for c in self.contradictions],
            )


def build_canonical_data(
    data_id: str,
    plain: dict[str, Any],
    source_refs: Iterable[SourceRef] = (),
    state: DecisionState = DecisionState.ACCEPTED,
) -> CanonicalData:
    """從一份已經確定的純資料 dict 建 Canonical Data（測試與 JSON 輸入用的捷徑）。

    刻意不做型別猜測以外的事：真正的抽取/正規化屬於 ING-* 節點，不該藏在建構子裡。
    """
    refs = list(source_refs)
    values: dict[str, CanonicalValue] = {}
    for key, raw in plain.items():
        values[key] = CanonicalValue(
            normalized=raw,
            original=raw,
            datatype=_infer_datatype(raw),
            source_refs=refs,
            state=state,
            confidence=1.0 if state is DecisionState.ACCEPTED else None,
        )
    return CanonicalData(data_id=data_id, values=values)


def _infer_datatype(value: Any) -> FieldDatatype:
    if isinstance(value, bool):
        return FieldDatatype.BOOLEAN
    if isinstance(value, (int, float)):
        return FieldDatatype.NUMBER
    if isinstance(value, list):
        return FieldDatatype.LIST
    if isinstance(value, str):
        return FieldDatatype.STRING
    return FieldDatatype.UNKNOWN


__all__ = [
    "CanonicalValue",
    "Contradiction",
    "CanonicalData",
    "build_canonical_data",
]
