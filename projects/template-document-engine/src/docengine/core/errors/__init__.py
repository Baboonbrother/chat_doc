"""錯誤分類法｜把失敗分成可判斷的族群，讓呼叫端能決定重試、降級還是送人審。

io: 無（純例外型別與分類列舉）
依賴: 無
"""

from __future__ import annotations

import enum
from typing import Any


class ErrorCategory(str, enum.Enum):
    """失敗的族群。分類的用途是決定「接下來能做什麼」，不是為了好看的錯誤碼。

    - ``INPUT``：輸入本身壞掉或不是我們支援的東西。重試沒用，要換輸入。
    - ``CONTRACT``：資料不符合 Document IR / Template Profile / Canonical Data 契約。
      這是我們自己的 bug 或版本不相容，重試沒用。
    - ``PARSE``：檔案是對的格式，但內容有我們處理不了的地方。
    - ``RENDER``：從 IR 寫回檔案時失敗。
    - ``TRANSPORT``：連不到本機模型、逾時、連線中斷。**可以重試**。
    - ``MODEL_OUTPUT``：模型有回應，但輸出不是合法 JSON 或不合 schema。**可以重試，且要換溫度**
      （見 `DECISIONS.md`／實測：temperature=0 重試會吐出位元組相同的壞 JSON）。
    - ``SEMANTIC``：輸出合法但語意站不住（引用了不存在的欄位、憑空發明事實）。
      重試通常沒用，要送 REVIEW。
    - ``GATE``：某道閘門判定不通過（必填欄位缺、驗證未過）。這是正常的拒絕，不是意外。
    - ``CONFIG``：設定缺漏或互相矛盾。
    """

    INPUT = "INPUT"
    CONTRACT = "CONTRACT"
    PARSE = "PARSE"
    RENDER = "RENDER"
    TRANSPORT = "TRANSPORT"
    MODEL_OUTPUT = "MODEL_OUTPUT"
    SEMANTIC = "SEMANTIC"
    GATE = "GATE"
    CONFIG = "CONFIG"


#: 哪些族群重試才有意義。其餘族群重試只是把同一個錯誤再犯一次。
RETRYABLE = frozenset({ErrorCategory.TRANSPORT, ErrorCategory.MODEL_OUTPUT})


class DocEngineError(Exception):
    """所有本專案例外的根。

    一律帶著足以定位問題的上下文：``category`` 決定呼叫端能怎麼反應，``context`` 保留現場。
    禁止空的 except；要吞錯就必須把 ``DocEngineError`` 轉成一筆明確的紀錄。
    """

    category: ErrorCategory = ErrorCategory.CONTRACT

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context

    @property
    def retryable(self) -> bool:
        return self.category in RETRYABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": type(self).__name__,
            "category": self.category.value,
            "message": self.message,
            "retryable": self.retryable,
            "context": self.context,
        }

    def __str__(self) -> str:  # pragma: no cover - 只是可讀性
        if not self.context:
            return self.message
        detail = ", ".join(f"{k}={v!r}" for k, v in sorted(self.context.items()))
        return f"{self.message} ({detail})"


class InputError(DocEngineError):
    """輸入檔案不存在、不是支援的格式、或大小/結構超出安全上限。"""

    category = ErrorCategory.INPUT


class ContractViolation(DocEngineError):
    """資料不符合核心契約。"""

    category = ErrorCategory.CONTRACT


class ParseError(DocEngineError):
    """OOXML 解析失敗。"""

    category = ErrorCategory.PARSE


class RenderError(DocEngineError):
    """從 Document IR 產生檔案失敗。"""

    category = ErrorCategory.RENDER


class TransportError(DocEngineError):
    """連不到模型端點 / 逾時 / 連線層失敗。可重試。"""

    category = ErrorCategory.TRANSPORT


class ModelOutputError(DocEngineError):
    """模型有回應但輸出不合法（非 JSON、不合 schema）。可重試，且要換溫度。"""

    category = ErrorCategory.MODEL_OUTPUT


class SemanticRejection(DocEngineError):
    """輸出合法但語意站不住：引用不存在的欄位、發明來源、與確定性證據矛盾。"""

    category = ErrorCategory.SEMANTIC


class GateFailure(DocEngineError):
    """閘門判定不通過。這是設計內的拒絕，不是程式壞掉。"""

    category = ErrorCategory.GATE


class ConfigError(DocEngineError):
    """設定缺漏或矛盾。"""

    category = ErrorCategory.CONFIG


__all__ = [
    "ErrorCategory",
    "RETRYABLE",
    "DocEngineError",
    "InputError",
    "ContractViolation",
    "ParseError",
    "RenderError",
    "TransportError",
    "ModelOutputError",
    "SemanticRejection",
    "GateFailure",
    "ConfigError",
]
