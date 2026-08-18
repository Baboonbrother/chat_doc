"""FND-005 證據與語意決策契約測試。

驗的是 SCHEMAS_AND_CONTRACTS.md 的不變式真的擋得住事，而不是型別存在。
"""

import pytest

from docengine.core.document_ir import SourceRef
from docengine.core.errors import ContractViolation
from docengine.core.evidence import (
    DecisionState,
    EvidenceKind,
    EvidenceRecord,
    EvidenceStore,
    SemanticDecision,
    ValidatorResult,
)


def _ev(claim: str = "B7 在三份樣本裡的值都不同", kind: EvidenceKind = EvidenceKind.SAMPLE) -> EvidenceRecord:
    return EvidenceRecord(
        kind=kind,
        claim=claim,
        source_refs=[SourceRef(part="xl/worksheets/sheet1.xml", sheet="工作表1", cell="B7")],
    )


def test_evidence_id_is_content_addressed_and_stable():
    assert _ev().evidence_id == _ev().evidence_id
    assert _ev().evidence_id != _ev("完全不同的主張").evidence_id
    assert _ev().evidence_id.startswith("ev-")


def test_evidence_is_append_only_and_cannot_be_rewritten():
    """人工修正要產生新證據，不得改寫歷史證據。"""
    store = EvidenceStore()
    rec = _ev()
    store.add(rec)
    store.add(_ev())  # 同內容重加 = 冪等，不算改寫
    assert len(store) == 1

    tampered = rec.model_copy(update={"claim": "被偷改的主張"})
    with pytest.raises(ContractViolation, match="不可被改寫"):
        store.add(tampered)


def test_decision_cannot_be_accepted_without_evidence():
    """『每個推論出來的語意欄位都必須有證據』——這裡是它可執行的版本。"""
    store = EvidenceStore()
    decision = SemanticDecision(
        decision_id="dec-1",
        subject_id="sheet:0:cell:B7",
        decision_type="field_semantic",
        proposal={"semantic_name": "duty_location"},
        state=DecisionState.ACCEPTED,
        evidence_ids=[],
    )
    with pytest.raises(ContractViolation, match="沒有證據"):
        store.record_decision(decision)


def test_decision_cannot_reference_nonexistent_evidence():
    store = EvidenceStore()
    decision = SemanticDecision(
        decision_id="dec-1",
        subject_id="x",
        decision_type="field_semantic",
        evidence_ids=["ev-does-not-exist"],
    )
    with pytest.raises(ContractViolation, match="不存在的證據"):
        store.record_decision(decision)


def test_failed_validator_blocks_acceptance():
    """HYBRID 的『deterministic validation』那一半必須真的有否決權。"""
    store = EvidenceStore()
    eid = store.add(_ev())
    decision = SemanticDecision(
        decision_id="dec-1",
        subject_id="x",
        decision_type="field_mapping",
        state=DecisionState.ACCEPTED,
        evidence_ids=[eid],
        validator_results=[
            ValidatorResult(validator="target_field_exists", passed=False, detail="duty_locatoin 不在 schema 裡"),
        ],
    )
    with pytest.raises(ContractViolation, match="驗證器判定失敗"):
        store.record_decision(decision)


def test_review_and_unknown_survive_as_first_class_states():
    """UNKNOWN 不是『當作沒有』，它必須能被列出來送人審。"""
    store = EvidenceStore()
    eid = store.add(_ev())
    for did, state in [("d1", DecisionState.REVIEW), ("d2", DecisionState.UNKNOWN), ("d3", DecisionState.ACCEPTED)]:
        store.record_decision(
            SemanticDecision(decision_id=did, subject_id="x", decision_type="field_semantic", state=state, evidence_ids=[eid])
        )
    assert {d.decision_id for d in store.needs_human_review()} == {"d1", "d2"}


def test_confidence_components_are_kept_separate():
    """合成後就無法回答『這個 0.9 是跨樣本一致還是模型自稱』。成分必須分開存。"""
    rec = EvidenceRecord(
        kind=EvidenceKind.MODEL,
        claim="B7 是 duty_location",
        model_id="orinth9b",
        prompt_version="1.0.0",
        confidence_components={"model_self_report": 0.91, "cross_sample_consistency": 0.4},
    )
    assert set(rec.confidence_components) == {"model_self_report", "cross_sample_consistency"}
    assert rec.is_model_claim


def test_model_provenance_changes_evidence_identity():
    """同一句主張由不同模型講出來，是兩筆證據，不是一筆。"""
    a = EvidenceRecord(kind=EvidenceKind.MODEL, claim="同一句話", model_id="qwen27b")
    b = EvidenceRecord(kind=EvidenceKind.MODEL, claim="同一句話", model_id="orinth9b")
    assert a.evidence_id != b.evidence_id
