from __future__ import annotations

from scripts import tester_handoff_check


def test_tester_handoff_dry_run_lists_product_gates(capsys):
    rc = tester_handoff_check.main(["--dry-run", "--include-website-build"])

    output = capsys.readouterr().out
    assert rc == 0
    assert "[tester-handoff] snapshot:" in output
    assert "not live forecasting superiority" in output
    assert "identity help:" in output
    assert "python" in output
    assert "-m superforecasting_agent --help" in output
    assert "compile packages:" in output
    assert "python" in output
    assert "-m compileall -q forecasting superforecasting_agent" in output
    assert "compile files:" in output
    assert "-m py_compile tools/forecasting_tool.py" in output
    assert "scripts/run_tests.sh" in output
    assert "tests/forecasting/test_smoke_script.py" in output
    assert "tests/test_project_metadata.py" in output
    assert "forecast smoke:" in output
    assert "scripts/forecast_smoke_test.py" in output
    assert "diff whitespace:" in output
    assert "website build:" in output
    assert "npm run build" in output
    assert "handoff gate passed" in output


def test_tester_handoff_gate_covers_fork_identity_and_smoke():
    assert "tests/forecasting/test_package_identity.py" in tester_handoff_check.HANDOFF_TESTS
    assert "tests/test_superforecasting_agent_cli.py" in tester_handoff_check.HANDOFF_TESTS
    assert "tests/forecasting/test_smoke_script.py" in tester_handoff_check.HANDOFF_TESTS
    assert "forecasting" in tester_handoff_check.COMPILE_DIRS
    assert "superforecasting_agent" in tester_handoff_check.COMPILE_DIRS
    assert "scripts/forecast_smoke_test.py" in tester_handoff_check.COMPILE_FILES
    assert "scripts/tester_handoff_check.py" in tester_handoff_check.COMPILE_FILES
