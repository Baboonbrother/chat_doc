"""FND-003 Template Profile 與 FND-004 Canonical Data 契約測試。

重點在兩個不變式：ACCEPTED 必須有證據；單一樣本不得宣稱學到固定/變動規則。
以及生成閘必須說得出「缺哪一個欄位」，而不是只吐一個 False。
"""

import pytest

from docengine.core.canonical_data import (
    CanonicalData,
    CanonicalValue,
    Contradiction,
    build_canonical_data,
)
from docengine.core.errors import ContractViolation, GateFailure
from docengine.core.evidence import DecisionState
from docengine.core.template_profile import (
    Cardinality,
    FieldDatatype,
    HumanPatch,
    LearnedFrom,
    Rule,
    TemplateField,
    TemplateProfile,
)


def _profile(**kw) -> TemplateProfile:
    base = dict(
        template_id="duty-roster",
        learned_from=LearnedFrom(sample_ids=["s1", "s2", "s3"], source_hashes=["h1", "h2", "h3"]),
        fields=[
            TemplateField(
                field_id="f_date",
                semantic_name="report_date",
                datatype=FieldDatatype.DATE,
                required=True,
                state=DecisionState.ACCEPTED,
                evidence_ids=["ev-1"],
            ),
            TemplateField(
                field_id="f_loc",
                semantic_name="duty_location",
                datatype=FieldDatatype.STRING,
                required=False,
                state=DecisionState.REVIEW,
                evidence_ids=["ev-2"],
            ),
        ],
    )
    base.update(kw)
    return TemplateProfile(**base)


# ------------------------------------------------------------ Template Profile


def test_profile_validates():
    _profile().validate_contract()


def test_accepted_field_without_evidence_is_rejected():
    """『每個推論出來的語意欄位都必須有證據』。"""
    p = _profile()
    p.fields[0].evidence_ids = []
    with pytest.raises(ContractViolation, match="沒有證據"):
        p.validate_contract()


def test_single_sample_cannot_claim_variable_token_rules():
    """藍圖明列的錯誤實作：只有一份樣本卻假裝學到了固定 vs 變動。"""
    p = _profile(
        learned_from=LearnedFrom(sample_ids=["only-one"], source_hashes=["h1"]),
        structure_rules=[Rule(rule_id="r1", kind="variable_token", evidence_ids=["ev-1"])],
    )
    with pytest.raises(ContractViolation, match="只有一份樣本"):
        p.validate_contract()


def test_three_samples_may_claim_variable_token_rules():
    p = _profile(structure_rules=[Rule(rule_id="r1", kind="variable_token", evidence_ids=["ev-1"])])
    p.validate_contract()


def test_duplicate_field_id_is_rejected():
    p = _profile()
    p.fields.append(TemplateField(field_id="f_date"))
    with pytest.raises(ContractViolation, match="重複的 field_id"):
        p.validate_contract()


def test_unresolved_fields_are_listed_not_hidden():
    """REVIEW/UNKNOWN 的欄位必須列得出來，否則使用者不知道範本哪裡還沒學會。"""
    assert [f.field_id for f in _profile().unresolved()] == ["f_loc"]


def test_offline_capability_is_derivable_from_rules():
    """『這個範本能不能完全離線生成』要能從 profile 直接答出來（INT-004 靠它）。"""
    p = _profile(language_rules=[Rule(rule_id="lr1", kind="sentence_pattern", deterministic=True)])
    assert p.needs_llm_at_runtime() == []
    p.language_rules.append(Rule(rule_id="lr2", kind="free_text", deterministic=False))
    assert [r.rule_id for r in p.needs_llm_at_runtime()] == ["lr2"]


def test_human_patch_creates_new_version_and_does_not_mutate_history():
    """人工修正建立新版本，不改寫歷史。"""
    p = _profile()
    patch = HumanPatch(
        patch_id="patch-1",
        author="owner",
        target="f_loc",
        operation="set_semantic_name",
        payload={"semantic_name": "duty_zone"},
        reason="勤區的正式英文名是 duty_zone",
    )
    p2 = p.with_patch(patch)
    assert p.template_version == "1" and p2.template_version == "2"
    assert p.field("f_loc").semantic_name == "duty_location"  # 原件沒被改
    assert p2.field("f_loc").semantic_name == "duty_zone"
    assert "patch-1" in p2.field("f_loc").evidence_ids
    assert p2.human_patches[0].reason


def test_patch_on_unknown_target_is_rejected():
    p = _profile()
    with pytest.raises(ContractViolation, match="不存在"):
        p.with_patch(HumanPatch(patch_id="x", author="o", target="ghost", operation="set_required", payload={}, reason="r"))


def test_profile_content_hash_ignores_version_but_not_content():
    p = _profile()
    p2 = p.model_copy(deep=True)
    p2.template_version = "99"
    assert p.content_hash() == p2.content_hash()
    p2.fields[0].required = False
    assert p.content_hash() != p2.content_hash()


# -------------------------------------------------------------- Canonical Data


def test_build_canonical_data_keeps_original_alongside_normalized():
    d = build_canonical_data("d1", {"report_date": "2026-08-20", "count": 3})
    assert d.get("report_date").original == "2026-08-20"
    assert d.get("count").datatype is FieldDatatype.NUMBER
    d.validate_contract()


def test_missing_required_field_is_named_not_just_flagged():
    """使用者需要知道缺哪一個，不是只知道『不能生成』。"""
    profile = _profile()
    data = build_canonical_data("d1", {"duty_location": "石牌"})
    assert data.missing_required(profile) == ["report_date"]
    with pytest.raises(GateFailure) as exc:
        data.assert_ready_for_generation(profile)
    assert exc.value.context["missing"] == ["report_date"]


def test_review_state_value_does_not_satisfy_a_required_field():
    """REVIEW 不等於可用。讓 REVIEW 悄悄通過就是把不確定性吞掉。"""
    profile = _profile()
    data = CanonicalData(
        data_id="d1",
        values={"report_date": CanonicalValue(normalized="2026-08-20", state=DecisionState.REVIEW)},
    )
    assert data.missing_required(profile) == ["report_date"]
    assert data.needs_review() == ["report_date"]


def test_empty_list_fails_a_required_many_field():
    profile = _profile()
    profile.fields.append(
        TemplateField(
            field_id="f_staff",
            semantic_name="staff",
            datatype=FieldDatatype.LIST,
            cardinality=Cardinality.MANY,
            required=True,
            state=DecisionState.ACCEPTED,
            evidence_ids=["ev-3"],
        )
    )
    data = build_canonical_data("d1", {"report_date": "2026-08-20", "staff": []})
    assert data.missing_required(profile) == ["staff"]


def test_contradictions_block_generation_and_keep_both_values():
    """矛盾不自動挑一個。挑了就是在使用者不知情的狀況下替他做決定。"""
    profile = _profile()
    data = build_canonical_data("d1", {"report_date": "2026-08-20"})
    data.contradictions.append(Contradiction(key="report_date", values=["2026-08-20", "2026-08-21"]))
    with pytest.raises(GateFailure, match="矛盾"):
        data.assert_ready_for_generation(profile)
    assert len(data.contradictions[0].values) == 2


def test_ready_data_passes_the_gate():
    data = build_canonical_data("d1", {"report_date": "2026-08-20"})
    data.assert_ready_for_generation(_profile())


def test_unmapped_inputs_are_registered_not_dropped():
    """輸入有、範本沒有的東西必須看得見，否則就是靜默漏資料。"""
    data = build_canonical_data("d1", {"report_date": "2026-08-20"})
    data.unmapped_inputs["承辦人手機"] = "0912345678"
    data.validate_contract()
    assert "承辦人手機" in data.unmapped_inputs


def test_list_datatype_must_hold_a_list():
    data = CanonicalData(
        data_id="d1",
        values={"staff": CanonicalValue(normalized="不是清單", datatype=FieldDatatype.LIST)},
    )
    with pytest.raises(ContractViolation, match="必須是 list"):
        data.validate_contract()
