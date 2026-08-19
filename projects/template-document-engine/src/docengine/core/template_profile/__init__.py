"""Template Profile 契約｜描述「這一類文件應該怎麼生成」。

和 Document IR 的分工：IR 說「這一份現在長什麼樣」，Profile 說「這一類該怎麼長出來」。
Profile 是可版本化的生成規格，人工修正會生出新版本而不是就地改寫（`SCHEMAS_AND_CONTRACTS.md` 不變式）。

io: in=跨樣本推論的結果與證據 id; out=可序列化、可版本化、可驗證的 TemplateProfile
依賴: pydantic, docengine.core.document_ir, docengine.core.evidence
"""

from __future__ import annotations

import enum
import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from docengine import CONTRACT_SCHEMA_VERSION
from docengine.core.document_ir.model import SourceRef, canonical_json
from docengine.core.errors import ContractViolation
from docengine.core.evidence import DecisionState


class Cardinality(str, enum.Enum):
    ONE = "one"
    OPTIONAL = "optional"
    MANY = "many"


class FieldDatatype(str, enum.Enum):
    STRING = "string"
    NUMBER = "number"
    DATE = "date"
    BOOLEAN = "boolean"
    LIST = "list"
    UNKNOWN = "unknown"


class FieldLocation(BaseModel):
    """欄位在範本裡的落點。生成時 binding planner 就是往這些座標寫值。"""

    model_config = ConfigDict(extra="forbid")

    node_id: str | None = None
    source_ref: SourceRef | None = None
    #: 重複區塊內的相對位置（例如表格第 N 欄），用於 repeat-region 展開。
    repeat_group: str | None = None
    role: str = "value"  # value | label | derived


class TemplateField(BaseModel):
    """範本的一個欄位。

    ``state`` 是一等公民：能重現版面但還無法證明 B7 是日期還是案號，就是 UNKNOWN，
    不是硬猜一個。``evidence_ids`` 為空而 state 是 ACCEPTED 會被 validate 擋下。
    """

    model_config = ConfigDict(extra="forbid")

    field_id: str
    semantic_name: str | None = None
    datatype: FieldDatatype = FieldDatatype.UNKNOWN
    cardinality: Cardinality = Cardinality.ONE
    required: bool = False
    locations: list[FieldLocation] = Field(default_factory=list)
    confidence: float | None = None
    confidence_components: dict[str, float] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    state: DecisionState = DecisionState.CANDIDATE
    note: str | None = None


class Rule(BaseModel):
    """規則的共同外殼。

    刻意保留 ``kind`` + ``params`` 的開放形狀：規則的種類會隨 TPL-* 節點長出來，
    但每一條規則都必須說得出 ``evidence_ids``（憑什麼有這條規則）與 ``deterministic``
    （執行它需不需要模型）。這兩個欄位是後面「離線無 LLM 模式」能不能成立的關鍵。
    """

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    applies_to: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    deterministic: bool = True
    state: DecisionState = DecisionState.CANDIDATE
    note: str | None = None


class HumanPatch(BaseModel):
    """人工修正。它建立新版本，不改寫歷史證據。"""

    model_config = ConfigDict(extra="forbid")

    patch_id: str
    author: str
    target: str  # field_id 或 rule_id
    operation: str  # set_semantic_name | set_required | set_datatype | disable_rule | ...
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str
    created_at: str | None = None


class LearnedFrom(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_ids: list[str] = Field(default_factory=list)
    source_hashes: list[str] = Field(default_factory=list)

    @property
    def sample_count(self) -> int:
        return len(self.sample_ids)


class TemplateProfile(BaseModel):
    """可重複使用、可版本化的生成規格。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONTRACT_SCHEMA_VERSION
    template_id: str
    template_version: str = "1"
    format: str = "xlsx"
    learned_from: LearnedFrom = Field(default_factory=LearnedFrom)
    structure_rules: list[Rule] = Field(default_factory=list)
    style_rules: list[Rule] = Field(default_factory=list)
    fields: list[TemplateField] = Field(default_factory=list)
    language_rules: list[Rule] = Field(default_factory=list)
    mapping_rules: list[Rule] = Field(default_factory=list)
    calculation_rules: list[Rule] = Field(default_factory=list)
    validation_rules: list[Rule] = Field(default_factory=list)
    rendering_rules: list[Rule] = Field(default_factory=list)
    human_patches: list[HumanPatch] = Field(default_factory=list)
    #: 生成閘的政策：哪些欄位必須是 ACCEPTED 才准生成（`ARCHITECTURE.md` §6）。
    generation_policy: dict[str, Any] = Field(default_factory=lambda: {"required_fields_must_be": "ACCEPTED"})
    metadata: dict[str, Any] = Field(default_factory=dict)

    # ---------------------------------------------------------------- 查詢

    def field(self, field_id: str) -> TemplateField:
        for f in self.fields:
            if f.field_id == field_id:
                return f
        raise ContractViolation("Template Profile 沒有這個欄位", field_id=field_id, template_id=self.template_id)

    def required_fields(self) -> list[TemplateField]:
        return [f for f in self.fields if f.required]

    def all_rules(self) -> list[Rule]:
        return [
            *self.structure_rules,
            *self.style_rules,
            *self.language_rules,
            *self.mapping_rules,
            *self.calculation_rules,
            *self.validation_rules,
            *self.rendering_rules,
        ]

    def unresolved(self) -> list[TemplateField]:
        """還不能拿來生成的欄位：REVIEW / UNKNOWN / CANDIDATE。"""
        blocked = {DecisionState.REVIEW, DecisionState.UNKNOWN, DecisionState.CANDIDATE}
        return [f for f in self.fields if f.state in blocked]

    def needs_llm_at_runtime(self) -> list[Rule]:
        """執行時仍需要模型的規則。這張清單為空 = 這個範本可以完全離線生成。"""
        return [r for r in self.all_rules() if not r.deterministic]

    # ------------------------------------------------------------ 契約驗證

    def validate_contract(self) -> None:
        seen: set[str] = set()
        for f in self.fields:
            if f.field_id in seen:
                raise ContractViolation("Template Profile 出現重複的 field_id", field_id=f.field_id)
            seen.add(f.field_id)
            if f.state is DecisionState.ACCEPTED and not f.evidence_ids:
                raise ContractViolation(
                    "欄位標成 ACCEPTED 卻沒有證據（SCHEMAS_AND_CONTRACTS 不變式）",
                    field_id=f.field_id,
                )
            if f.confidence is not None and not 0.0 <= f.confidence <= 1.0:
                raise ContractViolation("confidence 必須在 0..1", field_id=f.field_id, confidence=f.confidence)

        rule_ids: set[str] = set()
        for r in self.all_rules():
            if r.rule_id in rule_ids:
                raise ContractViolation("Template Profile 出現重複的 rule_id", rule_id=r.rule_id)
            rule_ids.add(r.rule_id)

        if self.learned_from.sample_count == 1:
            # 藍圖明列的錯誤：只有單一樣本卻假裝學到了「固定 vs 變動」。
            varying = [r for r in self.structure_rules if r.kind in {"variable_token", "repeat_region"}]
            if varying:
                raise ContractViolation(
                    "只有一份樣本，不得宣稱學到固定/變動規則",
                    template_id=self.template_id,
                    rules=[r.rule_id for r in varying],
                )

    # ----------------------------------------------------------- 版本與修正

    def content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        payload.pop("template_version", None)
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def with_patch(self, patch: HumanPatch) -> "TemplateProfile":
        """套用人工修正並產生**新版本**。原 profile 不變。"""
        new = self.model_copy(deep=True)
        target_field = next((f for f in new.fields if f.field_id == patch.target), None)
        target_rule = next((r for r in new.all_rules() if r.rule_id == patch.target), None)
        if target_field is None and target_rule is None:
            raise ContractViolation("人工修正指向不存在的欄位或規則", patch_id=patch.patch_id, target=patch.target)

        if target_field is not None:
            if patch.operation == "set_semantic_name":
                target_field.semantic_name = patch.payload["semantic_name"]
            elif patch.operation == "set_required":
                target_field.required = bool(patch.payload["required"])
            elif patch.operation == "set_datatype":
                target_field.datatype = FieldDatatype(patch.payload["datatype"])
            elif patch.operation == "set_state":
                target_field.state = DecisionState(patch.payload["state"])
            else:
                raise ContractViolation("不支援的人工修正操作", operation=patch.operation)
            # 人工拍板本身就是證據，而且是最重的一種。
            if patch.patch_id not in target_field.evidence_ids:
                target_field.evidence_ids.append(patch.patch_id)
            target_field.confidence_components["human_patch"] = 1.0
        elif patch.operation == "disable_rule":
            target_rule.state = DecisionState.REJECTED
        else:
            raise ContractViolation("不支援的人工修正操作", operation=patch.operation)

        new.human_patches.append(patch)
        new.template_version = _bump(self.template_version)
        return new


def _bump(version: str) -> str:
    try:
        return str(int(version) + 1)
    except ValueError:
        return f"{version}+1"


__all__ = [
    "Cardinality",
    "FieldDatatype",
    "FieldLocation",
    "TemplateField",
    "Rule",
    "HumanPatch",
    "LearnedFrom",
    "TemplateProfile",
]
