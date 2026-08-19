"""FND-008 CLI 骨架測試。

最重要的一條：還沒實作的子指令必須**非零退出**並說出卡在哪個節點。
一個印了友善訊息卻 exit 0 的 stub，會讓上層腳本把「還沒做」當成「做完了」。
"""

import pytest

from docengine.cli.main import PENDING_NODES, build_parser, main


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "docengine" in capsys.readouterr().out


@pytest.mark.parametrize("command", sorted(PENDING_NODES))
def test_unimplemented_commands_fail_loudly_with_the_blocking_node(command, capsys):
    assert main([command, "x"] if command == "learn" else [command]) == 2
    err = capsys.readouterr().err
    assert PENDING_NODES[command] in err
    assert "尚未可用" in err


def test_pending_nodes_reference_real_registry_nodes():
    """stub 訊息指向的節點必須真的存在，否則使用者拿著一個查不到的代號。"""
    from docengine.core.ledger import TaskRegistry
    from docengine.cli.main import DEFAULT_REGISTRY

    registry = TaskRegistry.from_file(DEFAULT_REGISTRY)
    for command, node_id in PENDING_NODES.items():
        assert node_id in registry.nodes, f"{command} 指向不存在的節點 {node_id}"


def test_ledger_ready_lists_actionable_nodes(capsys):
    """列出的每個節點，依賴都必須真的已經 DONE——否則 ready 這個字就沒有意義。"""
    from docengine.cli.main import DEFAULT_REGISTRY
    from docengine.core.ledger import TaskRegistry

    assert main(["ledger", "ready"]) == 0
    out = capsys.readouterr().out
    registry = TaskRegistry.from_file(DEFAULT_REGISTRY)
    expected = registry.ready()
    if not expected:
        assert "沒有 READY 節點" in out
        return
    for node in expected:
        assert node.id in out
        assert registry.unmet_deps(node.id) == []


def test_ledger_check_runs_and_reports(capsys):
    code = main(["ledger", "check"])
    out = capsys.readouterr().out
    assert code in (0, 1)
    assert "稽核" in out


def test_ledger_status_prints_every_status_bucket(capsys):
    main(["ledger", "status"])
    out = capsys.readouterr().out
    for status in ("TODO", "READY", "IN_PROGRESS", "BLOCKED", "DONE"):
        assert status in out


def test_parser_exposes_the_readme_command_surface():
    """README 承諾的五個指令必須都在 CLI 上，否則文件和程式對不上。"""
    parser = build_parser()
    actions = [a for a in parser._actions if hasattr(a, "choices") and a.choices]
    commands = set()
    for action in actions:
        commands.update(action.choices)
    for expected in ("inspect", "learn", "generate", "validate", "benchmark"):
        assert expected in commands


def test_unknown_command_is_rejected():
    with pytest.raises(SystemExit) as exc:
        main(["definitely-not-a-command"])
    assert exc.value.code != 0
