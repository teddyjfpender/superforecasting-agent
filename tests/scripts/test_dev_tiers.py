"""Validation tier planning must never widen a focused request into the full suite."""

from pathlib import Path
import subprocess

import pytest

from scripts import dev


@pytest.fixture
def plan(tmp_path, monkeypatch):
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    for name in (*dev.INTEGRATION_PYTHON, "tests/test_small.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    for name in (*dev.INTEGRATION_TUI, "src/__tests__/small.test.ts"):
        path = tmp_path / "ui-tui" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    calls = []
    monkeypatch.setattr(dev, "check", lambda **kw: calls.append(("check", kw)))
    monkeypatch.setattr(dev, "executable", lambda name: name)
    monkeypatch.setattr(dev, "run", lambda *args, **kw: calls.append((args, kw)))
    return tmp_path, calls


def test_fast_preserves_explicit_nodes_and_deduplicates(plan, capsys):
    root, calls = plan
    dev.verify(
        "fast", ["tests/test_small.py::test_one"] * 2, ["src/__tests__/small.test.ts"]
    )
    assert calls == [
        ("check", {"python_only": False}),
        (
            (
                "bash",
                str(root / "scripts/run_tests.sh"),
                "tests/test_small.py::test_one",
            ),
            {},
        ),
        (
            ("npm", "test", "--", "src/__tests__/small.test.ts"),
            {"cwd": root / "ui-tui"},
        ),
    ]
    assert "Tier elapsed:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "selector",
    ["tests", "tests/missing.py", "../escape.py", "--help", "tests/test_small.py::"],
)
def test_fast_rejects_missing_or_unbounded_selection_before_checks(plan, selector):
    _, calls = plan
    with pytest.raises(RuntimeError):
        dev.verify("fast", [selector], [])
    assert calls == []


def test_empty_fast_never_runs_full_suite(plan):
    _, calls = plan
    with pytest.raises(RuntimeError, match="needs"):
        dev.verify("fast", [], [])
    assert calls == []


def test_python_only_uses_no_node_tools(plan):
    root, calls = plan
    dev.verify("fast", ["tests/test_small.py"], [], python_only=True)
    assert calls == [
        ("check", {"python_only": True}),
        (("bash", str(root / "scripts/run_tests.sh"), "tests/test_small.py"), {}),
    ]


def test_integration_builds_and_runs_only_declared_controlled_scenarios(plan):
    root, calls = plan
    dev.verify("integration", [], [])
    assert calls == [
        ("check", {"python_only": False}),
        (("npm", "run", "build"), {"cwd": root / "ui-tui"}),
        (("bash", str(root / "scripts/run_tests.sh"), *dev.INTEGRATION_PYTHON), {}),
        (("npm", "test", "--", *dev.INTEGRATION_TUI), {"cwd": root / "ui-tui"}),
    ]


def test_only_explicit_qualification_plans_full_suites(plan):
    root, calls = plan
    dev.verify("qualification", [], [])
    assert calls[-2:] == [
        (("bash", str(root / "scripts/run_tests.sh")), {}),
        (("npm", "test", "--"), {"cwd": root / "ui-tui"}),
    ]


@pytest.mark.parametrize("tier", ["integration", "qualification"])
def test_partial_selections_cannot_claim_a_broader_tier(plan, tier):
    _, calls = plan
    with pytest.raises(RuntimeError, match="fast tier only"):
        dev.verify(tier, ["tests/test_small.py"], [])
    assert calls == []


def test_failed_checks_stop_tests_and_do_not_print_success(plan, monkeypatch, capsys):
    _, calls = plan

    def fail(**kwargs):
        raise subprocess.CalledProcessError(7, ["fixture-check"])

    monkeypatch.setattr(dev, "check", fail)
    with pytest.raises(subprocess.CalledProcessError):
        dev.verify("fast", ["tests/test_small.py"], [])
    assert calls == []
    output = capsys.readouterr().out
    assert "Tier elapsed:" in output
    assert "Local tier passed" not in output


def test_tui_cannot_escape_selected_test_root(plan):
    root, calls = plan
    (root / "ui-tui/src/product.ts").touch()
    with pytest.raises(RuntimeError):
        dev.verify("fast", [], ["src/product.ts"])
    assert calls == []
