"""The contributor command must fail closed before claiming a clean checkout."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts" / "dev.py"


def test_missing_tool_is_a_failed_check_not_a_clean_report(tmp_path):
    script = tmp_path / "scripts" / "dev.py"
    script.parent.mkdir()
    shutil.copyfile(SOURCE, script)
    result = subprocess.run([sys.executable, str(script), "check", "--python-only"],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "bootstrap" in result.stderr
    assert "Development gate failed" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixture; Windows missing-tool path is covered above")
def test_linter_process_failure_stops_the_quality_pipeline(tmp_path):
    script = tmp_path / "scripts" / "dev.py"
    script.parent.mkdir()
    shutil.copyfile(SOURCE, script)
    tool = tmp_path / ".venv" / "bin" / "ruff"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\necho 'fixture lint rejection' >&2\nexit 17\n", encoding="utf-8")
    tool.chmod(0o755)
    result = subprocess.run([sys.executable, str(script), "check", "--python-only"],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "fixture lint rejection" in result.stderr
    assert "17" in result.stderr
    assert "protocol.codegen" not in result.stdout
