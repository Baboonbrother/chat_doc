"""FND-007 錯誤分類法的測試。

驗的是「分類真的能決定接下來能做什麼」，不是「例外類別存在」。
"""

import pytest

from docengine.core.errors import (
    RETRYABLE,
    ConfigError,
    ContractViolation,
    DocEngineError,
    ErrorCategory,
    GateFailure,
    InputError,
    ModelOutputError,
    ParseError,
    RenderError,
    SemanticRejection,
    TransportError,
)

ALL_ERRORS = [
    InputError,
    ContractViolation,
    ParseError,
    RenderError,
    TransportError,
    ModelOutputError,
    SemanticRejection,
    GateFailure,
    ConfigError,
]


def test_every_error_has_a_distinct_category():
    categories = [cls.category for cls in ALL_ERRORS]
    assert len(set(categories)) == len(categories)
    assert set(categories) == set(ErrorCategory)


@pytest.mark.parametrize("cls", ALL_ERRORS)
def test_all_errors_derive_from_root(cls):
    assert issubclass(cls, DocEngineError)


def test_only_transport_and_model_output_are_retryable():
    """重試策略的唯一真相源。改這條等於改重試行為，必須是刻意的。"""
    retryable = {cls.category for cls in ALL_ERRORS if cls("x").retryable}
    assert retryable == {ErrorCategory.TRANSPORT, ErrorCategory.MODEL_OUTPUT}
    assert RETRYABLE == retryable


def test_context_is_preserved_not_swallowed():
    err = ParseError("看不懂的元素", part="xl/worksheets/sheet1.xml", element="w:weird")
    assert err.context["part"] == "xl/worksheets/sheet1.xml"
    assert "w:weird" in str(err)
    payload = err.to_dict()
    assert payload["category"] == "PARSE"
    assert payload["retryable"] is False
    assert payload["context"]["element"] == "w:weird"


def test_gate_failure_is_a_designed_refusal_not_a_crash():
    """閘門不通過必須可以被分辨出來，否則呼叫端會把「被拒絕」當成「程式壞了」。"""
    err = GateFailure("必填欄位缺漏", missing=["report_date"])
    assert err.category is ErrorCategory.GATE
    assert err.retryable is False
