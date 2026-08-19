"""真實 Excel 檔案語料測試（本機專用，語料**不進版控**）。

存在的理由見 DECISIONS.md AD-002：進版控的 fixture 是我自己寫的產生器產出的，
它的「第三方性」有限——我可能無意識地只寫出自己 parser 看得懂的形狀。
真正的證據是拿真的 Microsoft Excel 檔案來跑。

本 repo 是公開的，而本機可用的真實檔案含公務與個人資料，所以語料只能留在本機：
用環境變數指路，沒設就 skip。

    DOCENGINE_REAL_XLSX_DIR=/path/to/dir python3 -m pytest tests/test_xlsx_real_corpus.py -v

判定標準刻意分兩層，不合併成一個「通過率」：
- **解析**：讀得進來、IR 通過契約驗證。讀不進來是硬失敗。
- **round-trip**：重建後 IR 相同。這一層允許有已知落差，但落差必須被印出來，
  不能靠調寬容差變綠。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from docengine.parsers.xlsx.compiler import parse_xlsx
from docengine.validation.roundtrip import roundtrip_report

CORPUS_DIR = os.environ.get("DOCENGINE_REAL_XLSX_DIR")
LIMIT = int(os.environ.get("DOCENGINE_REAL_XLSX_LIMIT", "40"))


def _corpus() -> list[Path]:
    if not CORPUS_DIR:
        return []
    root = Path(CORPUS_DIR)
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.xlsx") if not p.name.startswith("~$"))[:LIMIT]


CORPUS = _corpus()

pytestmark = pytest.mark.skipif(
    not CORPUS,
    reason="未設定 DOCENGINE_REAL_XLSX_DIR（或目錄裡沒有 .xlsx）；真實語料不進版控",
)


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: p.name)
def test_real_file_parses_and_validates(path: Path):
    ir = parse_xlsx(path)
    ir.validate_contract()
    assert ir.nodes, f"{path.name} 解析後沒有任何節點"


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: p.name)
def test_real_file_round_trips(path: Path, tmp_path: Path):
    report = roundtrip_report(path, out_dir=tmp_path)
    assert report.passed, report.render_text()
