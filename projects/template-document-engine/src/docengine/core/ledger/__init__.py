"""節點執行履歷｜TASK_REGISTRY 的 DAG 求解 + 防止「假完成」的證據閘。

`CLAUDE_CODE_EXECUTION.md` 說 registry 是任務狀態的唯一真相源，`ACCEPTANCE_AND_EVIDENCE.md` 說
沒有證據不得標 DONE。這個模組讓那兩句話變成程式會擋的事：

- registry 只存 ``status``（維持它原本好讀的緊湊格式，人可以直接看）。
- 證據存在 append-only 的 ``artifacts/node_ledger.jsonl``。
- ``check()`` 比對兩者：registry 說 DONE 但履歷沒有完整證據 = 問題，非零退出。
- ``mark_done()`` **自己去跑 pytest** 取真實數字，所以「測試通過」不可能用打字宣稱出來。

io: in=TASK_REGISTRY.yaml + artifacts/node_ledger.jsonl; out=READY 節點清單、稽核問題清單
依賴: pyyaml, pydantic
"""

from __future__ import annotations

import enum
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml
from pydantic import BaseModel, ConfigDict, Field

from docengine.core.errors import ContractViolation, GateFailure, InputError


class NodeStatus(str, enum.Enum):
    TODO = "TODO"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    DONE = "DONE"


class NodeKindTag(str, enum.Enum):
    DETERMINISTIC = "DETERMINISTIC"
    LLM = "LLM"
    HYBRID = "HYBRID"


class TaskNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    kind: NodeKindTag
    status: NodeStatus
    deps: list[str] = Field(default_factory=list)
    title: str = ""


class TestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: 告訴 pytest 別把這個類別當成測試類別收集（名字剛好以 Test 開頭）。
    __test__ = False

    command: str
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    exit_code: int = 0
    summary_line: str = ""

    @property
    def green(self) -> bool:
        return self.exit_code == 0 and self.failed == 0 and self.errors == 0 and self.passed > 0


class LedgerEntry(BaseModel):
    """一次節點狀態變更的完整證據。欄位對應 registry 的 ``done_requires``。"""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    status: NodeStatus
    implementation_files: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    test_result: TestResult | None = None
    commit_sha_or_worktree_diff: str = ""
    evidence_notes: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    recorded_at: str = ""

    def missing_done_requirements(self) -> list[str]:
        """回傳這筆證據距離「可以標 DONE」還缺什麼。空 list 才算完整。"""
        missing: list[str] = []
        if not self.implementation_files:
            missing.append("implementation_files")
        if not self.tests:
            missing.append("tests")
        if self.test_result is None:
            missing.append("test_result")
        elif not self.test_result.green:
            missing.append(
                f"test_result（測試不是全綠：exit={self.test_result.exit_code} "
                f"passed={self.test_result.passed} failed={self.test_result.failed} errors={self.test_result.errors}）"
            )
        if not self.commit_sha_or_worktree_diff:
            missing.append("commit_sha_or_worktree_diff")
        if not self.evidence_notes:
            missing.append("evidence_notes")
        return missing


_NODE_LINE = r"^(\s*-\s*\{{id:\s*{node_id},.*?status:\s*)(\w+)(.*)$"


class TaskRegistry:
    """TASK_REGISTRY.yaml 的讀取、DAG 求解與就地狀態更新。"""

    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self.path = path
        self.raw = data
        self.nodes: dict[str, TaskNode] = {}
        for item in data.get("nodes", []):
            node = TaskNode(**item)
            if node.id in self.nodes:
                raise ContractViolation("TASK_REGISTRY 出現重複的節點 id", node_id=node.id)
            self.nodes[node.id] = node

    @classmethod
    def from_file(cls, path: str | Path) -> "TaskRegistry":
        p = Path(path)
        if not p.exists():
            raise InputError("找不到 TASK_REGISTRY.yaml", path=str(p))
        return cls(p, yaml.safe_load(p.read_text(encoding="utf-8")))

    # ------------------------------------------------------------- DAG 查詢

    def validate(self) -> None:
        for node in self.nodes.values():
            for dep in node.deps:
                if dep not in self.nodes:
                    raise ContractViolation("節點依賴了不存在的節點", node_id=node.id, dep=dep)
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        WHITE, GREY, BLACK = 0, 1, 2
        colour = {nid: WHITE for nid in self.nodes}

        def visit(nid: str, trail: list[str]) -> None:
            if colour[nid] == GREY:
                raise ContractViolation("TASK_REGISTRY 的依賴圖有循環", cycle=" -> ".join(trail + [nid]))
            if colour[nid] == BLACK:
                return
            colour[nid] = GREY
            for dep in self.nodes[nid].deps:
                visit(dep, trail + [nid])
            colour[nid] = BLACK

        for nid in sorted(self.nodes):
            visit(nid, [])

    def unmet_deps(self, node_id: str) -> list[str]:
        node = self.nodes[node_id]
        return [d for d in node.deps if self.nodes[d].status is not NodeStatus.DONE]

    def ready(self) -> list[TaskNode]:
        """依賴全 DONE、自己還沒 DONE/BLOCKED 的節點，依 id 排序。"""
        out = []
        for nid in sorted(self.nodes):
            node = self.nodes[nid]
            if node.status in (NodeStatus.DONE, NodeStatus.BLOCKED):
                continue
            if not self.unmet_deps(nid):
                out.append(node)
        return out

    def by_status(self, status: NodeStatus) -> list[TaskNode]:
        return [self.nodes[n] for n in sorted(self.nodes) if self.nodes[n].status is status]

    def counts(self) -> dict[str, int]:
        result = {s.value: 0 for s in NodeStatus}
        for node in self.nodes.values():
            result[node.status.value] += 1
        return result

    def integrity_problems(self) -> list[str]:
        """registry 自身的矛盾：DONE 的節點卻依賴著沒 DONE 的節點。"""
        problems = []
        for nid in sorted(self.nodes):
            node = self.nodes[nid]
            if node.status is NodeStatus.DONE:
                unmet = self.unmet_deps(nid)
                if unmet:
                    problems.append(f"{nid} 標為 DONE，但依賴 {unmet} 尚未 DONE")
        return problems

    # --------------------------------------------------------- 就地狀態更新

    def set_status(self, node_id: str, status: NodeStatus) -> None:
        """只改那一行的 status 字串，保留 registry 原本的緊湊格式與註解。"""
        if node_id not in self.nodes:
            raise ContractViolation("要更新的節點不存在", node_id=node_id)
        text = self.path.read_text(encoding="utf-8")
        pattern = re.compile(_NODE_LINE.format(node_id=re.escape(node_id)), re.MULTILINE)
        new_text, count = pattern.subn(lambda m: f"{m.group(1)}{status.value}{m.group(3)}", text)
        if count != 1:
            raise ContractViolation(
                "無法在 registry 裡唯一定位該節點的 status 欄位",
                node_id=node_id,
                matches=count,
            )
        self.path.write_text(new_text, encoding="utf-8")
        self.nodes[node_id].status = status


class NodeLedger:
    """append-only 的節點證據履歷（JSONL）。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        if not entry.recorded_at:
            entry.recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n")
        return entry

    def entries(self) -> list[LedgerEntry]:
        if not self.path.exists():
            return []
        out = []
        for line_no, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(LedgerEntry(**json.loads(line)))
            except Exception as exc:
                raise ContractViolation("節點履歷有壞掉的一行", path=str(self.path), line=line_no, detail=str(exc)) from exc
        return out

    def latest(self, node_id: str) -> LedgerEntry | None:
        matches = [e for e in self.entries() if e.node_id == node_id]
        return matches[-1] if matches else None

    def check(self, registry: TaskRegistry) -> list[str]:
        """稽核：registry 宣稱的狀態，履歷撐得住嗎？

        這是整套流程唯一一道擋得住「把 status 改成 DONE 就當作做完」的閘。
        """
        problems = list(registry.integrity_problems())
        for nid in sorted(registry.nodes):
            node = registry.nodes[nid]
            entry = self.latest(nid)
            if node.status is NodeStatus.DONE:
                if entry is None:
                    problems.append(f"{nid} 標為 DONE，但節點履歷裡沒有任何紀錄")
                    continue
                if entry.status is not NodeStatus.DONE:
                    problems.append(f"{nid} 標為 DONE，但履歷最後一筆是 {entry.status.value}")
                    continue
                missing = entry.missing_done_requirements()
                if missing:
                    problems.append(f"{nid} 標為 DONE，但履歷缺少: {', '.join(missing)}")
            elif node.status is NodeStatus.BLOCKED:
                if entry is None or not entry.blocked_reason:
                    problems.append(f"{nid} 標為 BLOCKED，但履歷沒有寫下被什麼卡住")
        return problems


def run_tests(test_paths: Iterable[str], cwd: str | Path | None = None, extra_args: Iterable[str] = ()) -> TestResult:
    """實際執行 pytest 並解析真實結果。

    存在的理由：如果測試結果是呼叫端自己填的數字，那 ``done_requires`` 的 ``test_result`` 就是一句
    宣稱。這個函式讓「測試通過」只能來自真的跑過一次。
    """
    paths = list(test_paths)
    if not paths:
        raise GateFailure("沒有指定測試路徑，無法產生 test_result")
    cmd = ["python3", "-m", "pytest", *paths, "--tb=short", "-q", *extra_args]
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    summary_line = ""
    for line in reversed(output.splitlines()):
        if re.search(r"\b(passed|failed|error|errors|skipped|no tests ran)\b", line):
            summary_line = line.strip()
            break

    def count(word: str) -> int:
        m = re.search(rf"(\d+)\s+{word}\b", summary_line)
        return int(m.group(1)) if m else 0

    return TestResult(
        command=" ".join(cmd),
        passed=count("passed"),
        failed=count("failed"),
        errors=count("errors") or count("error"),
        skipped=count("skipped"),
        exit_code=proc.returncode,
        summary_line=summary_line,
    )


def mark_done(
    registry: TaskRegistry,
    ledger: NodeLedger,
    node_id: str,
    implementation_files: list[str],
    tests: list[str],
    evidence_notes: list[str],
    commit: str,
    artifacts: list[str] | None = None,
    cwd: str | Path | None = None,
) -> LedgerEntry:
    """把節點標成 DONE。跑不過測試就直接拒絕，不留下半綠的 DONE。"""
    unmet = registry.unmet_deps(node_id)
    if unmet:
        raise GateFailure("依賴尚未 DONE，不得標記完成", node_id=node_id, unmet_deps=unmet)
    result = run_tests(tests, cwd=cwd)
    entry = LedgerEntry(
        node_id=node_id,
        status=NodeStatus.DONE,
        implementation_files=implementation_files,
        tests=tests,
        test_result=result,
        commit_sha_or_worktree_diff=commit,
        evidence_notes=evidence_notes,
        artifacts=artifacts or [],
    )
    missing = entry.missing_done_requirements()
    if missing:
        raise GateFailure("證據不完整，不得標記完成", node_id=node_id, missing=missing)
    ledger.append(entry)
    registry.set_status(node_id, NodeStatus.DONE)
    return entry


def mark_blocked(
    registry: TaskRegistry,
    ledger: NodeLedger,
    node_id: str,
    reason: str,
    unblock_command: str | None = None,
) -> LedgerEntry:
    """把節點標成 BLOCKED，並且**必須**寫下被什麼卡住、怎麼解除。"""
    if not reason.strip():
        raise GateFailure("BLOCKED 必須寫下原因", node_id=node_id)
    entry = LedgerEntry(
        node_id=node_id,
        status=NodeStatus.BLOCKED,
        blocked_reason=reason,
        evidence_notes=[f"解除封鎖的指令: {unblock_command}"] if unblock_command else [],
    )
    ledger.append(entry)
    registry.set_status(node_id, NodeStatus.BLOCKED)
    return entry


__all__ = [
    "NodeStatus",
    "NodeKindTag",
    "TaskNode",
    "TestResult",
    "LedgerEntry",
    "TaskRegistry",
    "NodeLedger",
    "run_tests",
    "mark_done",
    "mark_blocked",
]
