"""FND-006 節點履歷測試。

最重要的一條：把 status 改成 DONE 這件事，必須擋得住沒有證據 / 測試沒過的情況。
如果這道閘是空的，整份 TASK_REGISTRY 就只是一張會自我恭賀的清單。
"""

from pathlib import Path

import pytest

from docengine.core.errors import ContractViolation, GateFailure
from docengine.core.ledger import (
    LedgerEntry,
    NodeLedger,
    NodeStatus,
    TaskRegistry,
    TestResult,
    mark_blocked,
    mark_done,
    run_tests,
)

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "TASK_REGISTRY.yaml"

MINI_REGISTRY = """\
project: mini
status_values: [TODO, READY, IN_PROGRESS, BLOCKED, DONE]
done_requires: [implementation_files, tests, test_result, commit_sha_or_worktree_diff, evidence_notes]
nodes:
  - {id: A-001, kind: DETERMINISTIC, status: TODO, deps: [], title: "root"}
  - {id: A-002, kind: DETERMINISTIC, status: TODO, deps: [A-001], title: "child"}
  - {id: A-003, kind: LLM, status: TODO, deps: [A-002], title: "grandchild"}
"""


@pytest.fixture()
def mini(tmp_path: Path) -> TaskRegistry:
    p = tmp_path / "TASK_REGISTRY.yaml"
    p.write_text(MINI_REGISTRY, encoding="utf-8")
    return TaskRegistry.from_file(p)


# ------------------------------------------------------------------ DAG 求解


def test_ready_returns_only_nodes_whose_deps_are_done(mini: TaskRegistry):
    assert [n.id for n in mini.ready()] == ["A-001"]
    mini.set_status("A-001", NodeStatus.DONE)
    assert [n.id for n in mini.ready()] == ["A-002"]


def test_set_status_preserves_the_compact_registry_format(mini: TaskRegistry):
    """registry 是人要讀的。改一個 status 不該把整份 YAML 重排。"""
    before = mini.path.read_text(encoding="utf-8")
    mini.set_status("A-002", NodeStatus.IN_PROGRESS)
    after = mini.path.read_text(encoding="utf-8")
    assert after.count("\n") == before.count("\n")
    assert "- {id: A-002, kind: DETERMINISTIC, status: IN_PROGRESS, deps: [A-001], title: \"child\"}" in after
    assert TaskRegistry.from_file(mini.path).nodes["A-002"].status is NodeStatus.IN_PROGRESS


def test_registry_rejects_dependency_cycles(tmp_path: Path):
    p = tmp_path / "r.yaml"
    p.write_text(
        MINI_REGISTRY.replace('- {id: A-001, kind: DETERMINISTIC, status: TODO, deps: [], title: "root"}',
                              '- {id: A-001, kind: DETERMINISTIC, status: TODO, deps: [A-003], title: "root"}'),
        encoding="utf-8",
    )
    with pytest.raises(ContractViolation, match="循環"):
        TaskRegistry.from_file(p).validate()


def test_registry_rejects_missing_dependency(tmp_path: Path):
    p = tmp_path / "r.yaml"
    p.write_text(MINI_REGISTRY.replace("deps: [A-001]", "deps: [GHOST-999]"), encoding="utf-8")
    with pytest.raises(ContractViolation, match="不存在的節點"):
        TaskRegistry.from_file(p).validate()


def test_done_node_with_unfinished_dependency_is_an_integrity_problem(mini: TaskRegistry):
    mini.set_status("A-002", NodeStatus.DONE)
    assert any("A-002" in p for p in mini.integrity_problems())


# --------------------------------------------------- 真正的測試結果，不是宣稱


def test_run_tests_actually_runs_pytest_and_reports_green(tmp_path: Path):
    t = tmp_path / "test_ok.py"
    t.write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")
    result = run_tests([str(t)])
    assert result.passed == 1 and result.failed == 0 and result.exit_code == 0
    assert result.green


def test_run_tests_reports_red_for_failing_tests(tmp_path: Path):
    t = tmp_path / "test_bad.py"
    t.write_text("def test_bad():\n    assert 1 == 2\n", encoding="utf-8")
    result = run_tests([str(t)])
    assert result.failed == 1 and result.exit_code != 0
    assert not result.green


def test_zero_tests_is_not_green(tmp_path: Path):
    """『沒有測試』不得被當成『測試通過』。"""
    t = tmp_path / "test_empty.py"
    t.write_text("# 沒有任何測試\n", encoding="utf-8")
    assert not run_tests([str(t)]).green


# --------------------------------------------------------------- 假完成防線


def test_mark_done_refuses_when_tests_fail(tmp_path: Path, mini: TaskRegistry):
    t = tmp_path / "test_bad.py"
    t.write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    ledger = NodeLedger(tmp_path / "ledger.jsonl")
    with pytest.raises(GateFailure, match="證據不完整"):
        mark_done(mini, ledger, "A-001", ["impl.py"], [str(t)], ["寫了東西"], "abc123")
    assert TaskRegistry.from_file(mini.path).nodes["A-001"].status is NodeStatus.TODO


def test_mark_done_refuses_when_dependencies_are_not_done(tmp_path: Path, mini: TaskRegistry):
    t = tmp_path / "test_ok.py"
    t.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    ledger = NodeLedger(tmp_path / "ledger.jsonl")
    with pytest.raises(GateFailure, match="依賴尚未 DONE"):
        mark_done(mini, ledger, "A-002", ["impl.py"], [str(t)], ["note"], "abc123")


def test_mark_done_refuses_without_evidence_notes(tmp_path: Path, mini: TaskRegistry):
    t = tmp_path / "test_ok.py"
    t.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    ledger = NodeLedger(tmp_path / "ledger.jsonl")
    with pytest.raises(GateFailure, match="evidence_notes"):
        mark_done(mini, ledger, "A-001", ["impl.py"], [str(t)], [], "abc123")


def test_mark_done_succeeds_with_real_green_tests(tmp_path: Path, mini: TaskRegistry):
    t = tmp_path / "test_ok.py"
    t.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    ledger = NodeLedger(tmp_path / "ledger.jsonl")
    entry = mark_done(mini, ledger, "A-001", ["impl.py"], [str(t)], ["真的跑過"], "abc123")
    assert entry.test_result is not None and entry.test_result.passed == 1
    assert TaskRegistry.from_file(mini.path).nodes["A-001"].status is NodeStatus.DONE
    assert ledger.check(TaskRegistry.from_file(mini.path)) == []


def test_check_catches_status_edited_by_hand_without_evidence(tmp_path: Path, mini: TaskRegistry):
    """有人直接把 YAML 的 TODO 改成 DONE——這是最容易發生的假完成，必須被抓到。"""
    ledger = NodeLedger(tmp_path / "ledger.jsonl")
    mini.set_status("A-001", NodeStatus.DONE)
    problems = ledger.check(TaskRegistry.from_file(mini.path))
    assert any("沒有任何紀錄" in p for p in problems)


def test_check_catches_ledger_entry_with_hollow_evidence(tmp_path: Path, mini: TaskRegistry):
    ledger = NodeLedger(tmp_path / "ledger.jsonl")
    ledger.append(
        LedgerEntry(
            node_id="A-001",
            status=NodeStatus.DONE,
            implementation_files=["impl.py"],
            tests=["tests/test_x.py"],
            test_result=TestResult(command="fake", passed=0, failed=0, exit_code=0),
            commit_sha_or_worktree_diff="abc",
            evidence_notes=["看起來很好"],
        )
    )
    mini.set_status("A-001", NodeStatus.DONE)
    problems = ledger.check(TaskRegistry.from_file(mini.path))
    assert any("test_result" in p for p in problems)


def test_blocked_must_say_what_blocks_it(tmp_path: Path, mini: TaskRegistry):
    ledger = NodeLedger(tmp_path / "ledger.jsonl")
    with pytest.raises(GateFailure):
        mark_blocked(mini, ledger, "A-001", "   ")
    mark_blocked(mini, ledger, "A-001", "本機模型端點連不上", unblock_command="ollama serve")
    assert ledger.check(TaskRegistry.from_file(mini.path)) == []
    assert TaskRegistry.from_file(mini.path).nodes["A-001"].status is NodeStatus.BLOCKED


def test_blocked_node_without_reason_is_caught(tmp_path: Path, mini: TaskRegistry):
    ledger = NodeLedger(tmp_path / "ledger.jsonl")
    mini.set_status("A-003", NodeStatus.BLOCKED)
    assert any("A-003" in p and "卡住" in p for p in ledger.check(TaskRegistry.from_file(mini.path)))


# --------------------------------------------------------- 真正的 registry


def test_real_task_registry_is_a_valid_dag():
    reg = TaskRegistry.from_file(REGISTRY_PATH)
    reg.validate()
    assert len(reg.nodes) == 92, "藍圖宣稱 92 個節點"
    assert reg.integrity_problems() == []


def test_real_registry_roots_match_the_blueprint_priority():
    """藍圖說先蓋 FND 依賴根。第一批 READY 應該只有 FND-001。"""
    reg = TaskRegistry.from_file(REGISTRY_PATH)
    fresh = {nid: n for nid, n in reg.nodes.items() if not n.deps}
    assert set(fresh) == {"FND-001"}
