"""Document IR 契約與比較工具的公開介面。"""

from docengine.core.document_ir.diff import DiffEntry, DiffKind, IRDiff, Tolerance, diff_ir
from docengine.core.document_ir.model import (
    DocumentIR,
    FormatInfo,
    Node,
    NodeKind,
    Relationship,
    SourceInfo,
    SourceKind,
    SourceRef,
    Style,
    UnsupportedFeature,
    ValueType,
    build_style_table,
    canonical_json,
    make_node_id,
    normalize_number,
)

__all__ = [
    "DocumentIR",
    "FormatInfo",
    "Node",
    "NodeKind",
    "Relationship",
    "SourceInfo",
    "SourceKind",
    "SourceRef",
    "Style",
    "UnsupportedFeature",
    "ValueType",
    "build_style_table",
    "canonical_json",
    "make_node_id",
    "normalize_number",
    "DiffEntry",
    "DiffKind",
    "IRDiff",
    "Tolerance",
    "diff_ir",
]
