"""Round-trip 驗證｜`parse -> IR -> render -> parse -> normalized diff` 的可執行版本。

`ACCEPTANCE_AND_EVIDENCE.md` §3 要求這條鏈，而且要求比較時**明確宣告容差與未支援特徵**。
所以報告不是一個 bool：它同時給出差異、容差、以及兩側各自登記了哪些沒建模的東西。
diff 全綠但未支援清單很長，代表「我們能重現的部分沒問題，但我們能重現的部分不多」——
這兩件事必須分開講，合成一個「通過」就是把限制藏起來。

io: in=來源文件路徑; out=RoundTripReport（可印、可轉 JSON）+ 產出的重建檔案
依賴: docengine.parsers, docengine.renderers, docengine.core.document_ir.diff
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from docengine.core.document_ir.diff import IRDiff, Tolerance, diff_ir
from docengine.core.document_ir.model import DocumentIR
from docengine.core.errors import InputError

DEFAULT_OUT_DIR = Path("artifacts") / "roundtrip"


class RoundTripReport(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    source_path: str
    rebuilt_path: str
    #: 排除出處後的結構雜湊。用它而不是 content_hash：兩份檔案的檔名與 sha256 必然不同，
    #: 拿含出處的雜湊來比對，永遠不會相等。這兩個值相等，是獨立於 diff 實作的第二個證據。
    source_hash: str
    rebuilt_hash: str
    diff: IRDiff
    source_bytes: int
    rebuilt_bytes: int
    carried_over_parts: list[str]
    #: 已宣告的正規化：重建時刻意做的、不影響可見內容的改變。
    #: 它們不參與 diff，但必須印出來——不講就等於偷偷改了使用者的檔案。
    normalizations: dict[str, Any] = {}

    @property
    def passed(self) -> bool:
        """diff 相等**且**結構雜湊相同。

        兩個條件都要，是為了不把驗證全押在 diff 的實作上：如果 diff 因為某個 bug 而
        永遠回傳 equal，結構雜湊仍然會抓到不一致。
        """
        return self.diff.equal and self.source_hash == self.rebuilt_hash

    def render_text(self) -> str:
        lines = [
            "Round-trip 驗證: parse -> IR -> render -> parse -> diff",
            f"  來源      : {self.source_path}  ({self.source_bytes} bytes)",
            f"  重建      : {self.rebuilt_path}  ({self.rebuilt_bytes} bytes)",
            f"  結構雜湊  : 來源={self.source_hash[:16]}  重建={self.rebuilt_hash[:16]}"
            + ("  (相同)" if self.source_hash == self.rebuilt_hash else "  (不同)"),
            f"  判定      : {'PASS' if self.passed else 'FAIL'}",
            "",
        ]
        if self.normalizations:
            lines.append("已宣告的正規化（刻意的改變，不影響可見內容）：")
            lines.extend(f"  - {k}: {v}" for k, v in sorted(self.normalizations.items()))
            lines.append("")
        if self.carried_over_parts:
            lines.append(
                "由來源封裝原樣帶過的 part（IR 未建模，因此無法從 IR 產生）："
            )
            lines.extend(f"  - {p}" for p in self.carried_over_parts)
            lines.append("")
        lines.append(self.diff.render_text())
        return "\n".join(lines)

    def to_json(self) -> str:
        payload: dict[str, Any] = json.loads(self.model_dump_json())
        payload["passed"] = self.passed
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def roundtrip_report(
    source: str | Path,
    out_dir: str | Path | None = None,
    tolerance: Tolerance | None = None,
) -> RoundTripReport:
    from docengine.parsers import parse_document
    from docengine.parsers.ooxml import load_package

    src = Path(source)
    suffix = src.suffix.lower()
    if suffix not in (".xlsx", ".docx"):
        raise InputError("round-trip 目前只支援 .xlsx / .docx", path=str(src), suffix=suffix)

    out = Path(out_dir) if out_dir else DEFAULT_OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    rebuilt = out / f"{src.stem}_roundtrip{suffix}"

    ir_a: DocumentIR = parse_document(src)

    # IR 沒建模的 part 由來源封裝原樣帶過。這不是作弊：它們不在 IR 裡，
    # 所以不參與 diff；帶過去只是為了讓輸出檔案本身是完整的。
    package = load_package(src)
    carried = {
        name: blob
        for name, blob in package.parts.items()
        if any(u.part == name and u.element == "(整個 part)" for u in ir_a.unsupported)
    }

    if suffix == ".xlsx":
        from docengine.renderers.xlsx.writer import render_xlsx

        render_xlsx(ir_a, rebuilt, carry_over_parts=carried)
    else:
        from docengine.renderers.docx.writer import render_docx

        render_docx(ir_a, rebuilt, carry_over_parts=carried)

    ir_b: DocumentIR = parse_document(rebuilt)

    return RoundTripReport(
        source_path=str(src),
        rebuilt_path=str(rebuilt),
        source_hash=ir_a.structural_hash(),
        rebuilt_hash=ir_b.structural_hash(),
        diff=diff_ir(ir_a, ir_b, tolerance, left_label="來源", right_label="重建"),
        source_bytes=src.stat().st_size,
        rebuilt_bytes=rebuilt.stat().st_size,
        carried_over_parts=sorted(carried),
        normalizations=dict(ir_a.metadata.get("normalizations") or {}),
    )


__all__ = ["RoundTripReport", "roundtrip_report", "DEFAULT_OUT_DIR"]
