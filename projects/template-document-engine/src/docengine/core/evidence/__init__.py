"""證據與語意決策契約｜任何推論出來的結論都必須說得出「根據什麼」。

`SCHEMAS_AND_CONTRACTS.md` 的不變式：每個推論出來的語意欄位都必須有證據；UNKNOWN 與 REVIEW 是
一等狀態；人工修正產生新的 patch，不改寫歷史證據。這個模組是那些不變式的可執行版本。

io: in=推論過程產生的主張與來源座標; out=可雜湊、可稽核、可序列化的證據與決策紀錄
依賴: pydantic, docengine.core.document_ir
"""

from __future__ import annotations

import enum
import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from docengine.core.document_ir.model import SourceRef, canonical_json
from docengine.core.errors import ContractViolation


class EvidenceKind(str, enum.Enum):
    """證據來自哪裡。這決定它有多重——模型自述不等於觀察到的事實。"""

    DETERMINISTIC = "deterministic"  # 從檔案結構直接讀出來的事實
    SAMPLE = "sample"  # 跨樣本比對得到的觀察（例如「這格在 3 份樣本裡都不一樣」）
    MODEL = "model"  # 本機模型的判斷
    HUMAN = "human"  # 人工標註或修正


class DecisionState(str, enum.Enum):
    """語意決策的狀態機（`ARCHITECTURE.md` §6）。

    刻意不是 true/false。系統必須能說出「我能重現版面，但我還無法證明 B7 是日期還是案號」。
    """

    CANDIDATE = "CANDIDATE"
    ACCEPTED = "ACCEPTED"
    REVIEW = "REVIEW"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class EvidenceRecord(BaseModel):
    """一筆證據。

    ``evidence_id`` 由內容算出，所以同樣的觀察不會產生兩筆不同 id 的證據，
    而且任何人拿到 id 都能重算驗證它沒被改過。
    """

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = ""
    kind: EvidenceKind
    claim: str
    source_refs: list[SourceRef] = Field(default_factory=list)
    task_id: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    #: 各個信心成分分開存（`LLM_GATEWAY.md` §6）。**不得**先合成一個總分再丟掉成分——
    #: 合成後就無法回答「這個 0.9 是因為跨樣本一致，還是因為模型自己說它很有信心」。
    confidence_components: dict[str, float] = Field(default_factory=dict)
    created_at: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, _ctx: Any) -> None:
        if not self.evidence_id:
            object.__setattr__(self, "evidence_id", self.compute_id())

    def compute_id(self) -> str:
        payload = canonical_json(
            {
                "kind": self.kind.value,
                "claim": self.claim,
                "source_refs": [r.model_dump(mode="json") for r in self.source_refs],
                "task_id": self.task_id,
                "model_id": self.model_id,
                "prompt_version": self.prompt_version,
                "context": self.context,
            }
        )
        return "ev-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @property
    def is_model_claim(self) -> bool:
        return self.kind is EvidenceKind.MODEL


class ValidatorResult(BaseModel):
    """確定性驗證器對一個提案的判定。HYBRID 節點的「deterministic validation」那一半。"""

    model_config = ConfigDict(extra="forbid")

    validator: str
    passed: bool
    detail: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class SemanticDecision(BaseModel):
    """一個語意決策：主張了什麼、憑什麼、現在處於什麼狀態。"""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    subject_id: str
    decision_type: str
    proposal: dict[str, Any] = Field(default_factory=dict)
    state: DecisionState = DecisionState.CANDIDATE
    evidence_ids: list[str] = Field(default_factory=list)
    validator_results: list[ValidatorResult] = Field(default_factory=list)
    note: str | None = None

    @property
    def failed_validators(self) -> list[ValidatorResult]:
        return [v for v in self.validator_results if not v.passed]

    def assert_can_be_accepted(self) -> None:
        """ACCEPTED 的准入條件。想放寬就得改這裡，而且改動看得見。"""
        if not self.evidence_ids:
            raise ContractViolation(
                "決策不得在沒有證據的情況下被接受",
                decision_id=self.decision_id,
                subject_id=self.subject_id,
            )
        if self.failed_validators:
            raise ContractViolation(
                "有驗證器判定失敗，決策不得被接受",
                decision_id=self.decision_id,
                failed=[v.validator for v in self.failed_validators],
            )


class EvidenceStore:
    """證據的集合。刻意做成 append-only：人工修正產生新證據，不改寫舊的。"""

    def __init__(self) -> None:
        self._records: dict[str, EvidenceRecord] = {}
        self._decisions: dict[str, SemanticDecision] = {}

    # ---------------------------------------------------------------- 證據

    def add(self, record: EvidenceRecord) -> str:
        existing = self._records.get(record.evidence_id)
        if existing is not None and existing.model_dump() != record.model_dump():
            raise ContractViolation(
                "證據不可被改寫：同一個 evidence_id 出現不同內容",
                evidence_id=record.evidence_id,
            )
        self._records[record.evidence_id] = record
        return record.evidence_id

    def get(self, evidence_id: str) -> EvidenceRecord:
        try:
            return self._records[evidence_id]
        except KeyError as exc:
            raise ContractViolation("引用了不存在的證據", evidence_id=evidence_id) from exc

    def __len__(self) -> int:
        return len(self._records)

    @property
    def records(self) -> list[EvidenceRecord]:
        return [self._records[k] for k in sorted(self._records)]

    # ---------------------------------------------------------------- 決策

    def record_decision(self, decision: SemanticDecision) -> SemanticDecision:
        for eid in decision.evidence_ids:
            self.get(eid)  # 引用不存在的證據就地爆掉，不留到下游
        if decision.state is DecisionState.ACCEPTED:
            decision.assert_can_be_accepted()
        self._decisions[decision.decision_id] = decision
        return decision

    def decisions(self, state: DecisionState | None = None) -> list[SemanticDecision]:
        items = [self._decisions[k] for k in sorted(self._decisions)]
        return [d for d in items if state is None or d.state is state]

    def needs_human_review(self) -> list[SemanticDecision]:
        """要送人審的決策。REVIEW 與 UNKNOWN 都算——UNKNOWN 不是「當作沒有」。"""
        return [d for d in self.decisions() if d.state in (DecisionState.REVIEW, DecisionState.UNKNOWN)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": [r.model_dump(mode="json") for r in self.records],
            "decisions": [d.model_dump(mode="json") for d in self.decisions()],
        }


__all__ = [
    "EvidenceKind",
    "DecisionState",
    "EvidenceRecord",
    "ValidatorResult",
    "SemanticDecision",
    "EvidenceStore",
]
