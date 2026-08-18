"""解析器分派｜依副檔名/內容決定用哪一支 parser。

io: in=檔案路徑; out=DocumentIR
依賴: docengine.parsers.xlsx（DOCX 待 DOCX-008）
"""

from __future__ import annotations

from pathlib import Path

from docengine.core.document_ir.model import DocumentIR
from docengine.core.errors import InputError


def parse_document(path: str | Path) -> DocumentIR:
    suffix = Path(path).suffix.lower()
    if suffix == ".xlsx":
        from docengine.parsers.xlsx.compiler import parse_xlsx

        return parse_xlsx(path)
    if suffix == ".docx":
        from docengine.parsers.docx.compiler import parse_docx

        return parse_docx(path)
    raise InputError("不支援的檔案格式", path=str(path), suffix=suffix, supported=[".xlsx", ".docx"])


__all__ = ["parse_document"]
