"""docengine CLI｜v0.1 唯一的人機介面（藍圖規定 UI 不在 v0.1 範圍）。

設計原則：**還沒實作的子指令要明確說出「卡在哪個節點」並以非零碼退出**，
不得印一句友善的話然後 exit 0——那會讓上層腳本把「還沒做」當成「做完了」。

io: in=命令列參數; out=stdout 報告 / 非零退出碼
依賴: argparse, docengine.core.*
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from docengine import __version__
from docengine.core.errors import DocEngineError
from docengine.core.ledger import (
    NodeLedger,
    NodeStatus,
    TaskRegistry,
    mark_blocked,
    mark_done,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = PROJECT_ROOT / "TASK_REGISTRY.yaml"
DEFAULT_LEDGER = PROJECT_ROOT / "artifacts" / "node_ledger.jsonl"

#: 子指令 -> 讓它可用的 registry 節點。用來產生誠實的「還沒做」訊息。
PENDING_NODES = {
    "learn": "TPL-011",
    "generate": "GEN-010",
    "validate": "VAL-010",
    "benchmark": "LLM-010",
    "models": "LLM-002",
}


class NotImplementedYet(DocEngineError):
    """這個子指令的依賴節點還沒完成。這是設計內的拒絕，不是崩潰。"""

    def __init__(self, command: str, node_id: str) -> None:
        super().__init__(
            f"`docengine {command}` 尚未可用：它需要 TASK_REGISTRY 節點 {node_id} 完成",
            command=command,
            pending_node=node_id,
        )


# ------------------------------------------------------------------ 子指令


def cmd_inspect(args: argparse.Namespace) -> int:
    """把一份文件解析成 Document IR 並印出摘要。"""
    from docengine.parsers import parse_document  # 延後匯入：讓 CLI 在 parser 未就緒時仍可用

    ir = parse_document(args.path)
    ir.validate_contract()
    if args.json:
        print(ir.canonical_json())
        return 0
    print(f"檔案      : {args.path}")
    print(f"格式      : {ir.format.type}")
    print(f"內容雜湊  : {ir.content_hash()[:16]}")
    print(f"節點      : {len(ir.nodes)}（樣式 {len(ir.styles)}、關係 {len(ir.relationships)}）")
    kinds: dict[str, int] = {}
    for node in ir.nodes:
        kinds[node.kind.value] = kinds.get(node.kind.value, 0) + 1
    for kind in sorted(kinds):
        print(f"  - {kind}: {kinds[kind]}")
    if ir.unsupported:
        print("未支援特徵（已登記，不是靜默丟棄）:")
        for u in ir.unsupported:
            print(f"  - {u.part}::{u.element} ×{u.count}" + (f"  # {u.note}" if u.note else ""))
    else:
        print("未支援特徵: （無登記）")
    return 0


def cmd_roundtrip(args: argparse.Namespace) -> int:
    """parse -> IR -> render -> parse -> normalized diff。第一個里程碑的驗收指令。"""
    from docengine.validation.roundtrip import roundtrip_report

    report = roundtrip_report(args.path, out_dir=args.out_dir)
    print(report.render_text())
    if args.json_out:
        Path(args.json_out).write_text(report.to_json(), encoding="utf-8")
        print(f"\n機器可讀報告: {args.json_out}")
    return 0 if report.diff.equal else 1


def _pending(command: str) -> Callable[[argparse.Namespace], int]:
    def run(_args: argparse.Namespace) -> int:
        raise NotImplementedYet(command, PENDING_NODES[command])

    return run


def cmd_ledger(args: argparse.Namespace) -> int:
    registry = TaskRegistry.from_file(args.registry)
    registry.validate()
    ledger = NodeLedger(args.ledger)

    if args.ledger_command == "status":
        counts = registry.counts()
        total = len(registry.nodes)
        print(f"TASK_REGISTRY: {total} 個節點")
        for status in NodeStatus:
            print(f"  {status.value:<12} {counts[status.value]}")
        problems = ledger.check(registry)
        print(f"\n稽核: {'通過' if not problems else str(len(problems)) + ' 個問題'}")
        for p in problems:
            print(f"  ! {p}")
        return 0 if not problems else 1

    if args.ledger_command == "ready":
        ready = registry.ready()
        if not ready:
            print("沒有 READY 節點。")
            return 0
        for node in ready:
            print(f"{node.id:<10} {node.kind.value:<14} {node.title}")
        return 0

    if args.ledger_command == "check":
        problems = ledger.check(registry)
        if not problems:
            print("節點履歷稽核通過：沒有缺證據的 DONE，也沒有沒寫原因的 BLOCKED。")
            return 0
        print(f"節點履歷稽核發現 {len(problems)} 個問題：")
        for p in problems:
            print(f"  ! {p}")
        return 1

    if args.ledger_command == "done":
        entry = mark_done(
            registry,
            ledger,
            args.node_id,
            implementation_files=args.impl,
            tests=args.tests,
            evidence_notes=args.note,
            commit=args.commit,
            artifacts=args.artifact,
            cwd=PROJECT_ROOT,
        )
        assert entry.test_result is not None
        print(f"{args.node_id} -> DONE")
        print(f"  測試: {entry.test_result.summary_line}")
        print(f"  指令: {entry.test_result.command}")
        return 0

    if args.ledger_command == "blocked":
        mark_blocked(registry, ledger, args.node_id, args.reason, args.unblock)
        print(f"{args.node_id} -> BLOCKED：{args.reason}")
        if args.unblock:
            print(f"  解除指令: {args.unblock}")
        return 0

    raise DocEngineError("未知的 ledger 子指令", command=args.ledger_command)


def cmd_models(args: argparse.Namespace) -> int:
    """列出設定裡的模型別名與實際 model id，並選擇性地探測可用性。"""
    try:
        from docengine.llm.config import load_model_config
    except ModuleNotFoundError as exc:  # LLM 層尚未實作
        raise NotImplementedYet("models", PENDING_NODES["models"]) from exc

    config = load_model_config(args.config)
    print(f"設定檔: {config.source_path or '（內建預設）'}")
    for alias in sorted(config.models):
        m = config.models[alias]
        line = f"  {alias:<10} -> {m.model:<24} {m.provider:<18} {m.base_url}"
        if args.probe:
            ok, detail = config.probe(alias)
            line += f"  [{'可用' if ok else '不可用'}] {detail}"
        print(line)
    return 0


# --------------------------------------------------------------------- 進入點


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docengine",
        description="範本導向 Word/Excel 文件生成引擎（v0.1 CLI）",
    )
    parser.add_argument("--version", action="version", version=f"docengine {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="解析文件並印出 Document IR 摘要")
    p_inspect.add_argument("path")
    p_inspect.add_argument("--json", action="store_true", help="輸出完整正規化 IR JSON")
    p_inspect.set_defaults(func=cmd_inspect)

    p_rt = sub.add_parser("roundtrip", help="parse -> IR -> render -> parse -> diff")
    p_rt.add_argument("path")
    p_rt.add_argument("--out-dir", default=None, help="產出檔案的目錄（預設 artifacts/roundtrip）")
    p_rt.add_argument("--json-out", default=None, help="把機器可讀報告寫到這個路徑")
    p_rt.set_defaults(func=cmd_roundtrip)

    p_learn = sub.add_parser("learn", help="從多份同型樣本學出 Template Profile")
    p_learn.add_argument("samples")
    p_learn.add_argument("--out", required=False)
    p_learn.set_defaults(func=_pending("learn"))

    p_gen = sub.add_parser("generate", help="用 Template Profile + Canonical Data 生成文件")
    p_gen.add_argument("--template", required=False)
    p_gen.add_argument("--input", required=False)
    p_gen.add_argument("--output", required=False)
    p_gen.set_defaults(func=_pending("generate"))

    p_val = sub.add_parser("validate", help="驗證生成結果")
    p_val.add_argument("--template", required=False)
    p_val.add_argument("--document", required=False)
    p_val.set_defaults(func=_pending("validate"))

    p_bench = sub.add_parser("benchmark", help="在同一套 corpus 上比較多個本機模型")
    p_bench.add_argument("--models", default="qwen27b,orinth9b")
    p_bench.add_argument("--suite", default="semantic_v1")
    p_bench.set_defaults(func=_pending("benchmark"))

    p_models = sub.add_parser("models", help="列出模型別名對應，並可探測可用性")
    p_models.add_argument("--config", default=None)
    p_models.add_argument("--probe", action="store_true", help="實際連線探測每個端點")
    p_models.set_defaults(func=cmd_models)

    p_ledger = sub.add_parser("ledger", help="TASK_REGISTRY 的 DAG 求解與證據稽核")
    p_ledger.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    p_ledger.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    lsub = p_ledger.add_subparsers(dest="ledger_command", required=True)
    lsub.add_parser("status", help="各狀態節點數 + 稽核結果")
    lsub.add_parser("ready", help="列出依賴已滿足、可以動工的節點")
    lsub.add_parser("check", help="只跑證據稽核，有問題就非零退出")

    l_done = lsub.add_parser("done", help="標記節點完成（會實際執行測試）")
    l_done.add_argument("node_id")
    l_done.add_argument("--impl", action="append", required=True, help="實作檔案（可重複）")
    l_done.add_argument("--tests", action="append", required=True, help="測試路徑（可重複，會被實際執行）")
    l_done.add_argument("--note", action="append", required=True, help="證據說明（可重複）")
    l_done.add_argument("--commit", required=True)
    l_done.add_argument("--artifact", action="append", default=[])

    l_blocked = lsub.add_parser("blocked", help="標記節點被卡住（必須寫原因）")
    l_blocked.add_argument("node_id")
    l_blocked.add_argument("--reason", required=True)
    l_blocked.add_argument("--unblock", default=None, help="解除封鎖需要執行的指令")

    p_ledger.set_defaults(func=cmd_ledger)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except DocEngineError as exc:
        payload: dict[str, Any] = exc.to_dict()
        print(f"[{payload['category']}] {exc}", file=sys.stderr)
        if payload["retryable"]:
            print("（這個錯誤族群是可重試的）", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"[INPUT] 找不到檔案: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
