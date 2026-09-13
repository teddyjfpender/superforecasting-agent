"""The shared gate rejects warning-level type errors in newly added files."""

import subprocess
from pathlib import Path

import pytest

from scripts import dev


def test_new_file_type_warning_blocks_remaining_gates(tmp_path, monkeypatch):
    strict_dir = tmp_path / 'application'
    strict_dir.mkdir()
    source = strict_dir / 'new_operation.py'
    source.write_text('def operation(*, count: int) -> int:\n    return count\n\noperation(count=1, unexpected=2)\n', encoding='utf-8')
    monkeypatch.setattr(dev, 'STRICT_PYTHON', (str(strict_dir),))
    executable = dev.venv_tool('ty')
    commands = []

    def run(*command, **kwargs):
        commands.append(command)
        if command[0] == executable:
            result = subprocess.run(
                (*command, '--project', str(dev.ROOT)),
                cwd=dev.ROOT, capture_output=True, text=True, check=False,
            )
            if result.returncode:
                assert 'unknown-argument' in result.stdout + result.stderr
                raise subprocess.CalledProcessError(result.returncode, command)

    monkeypatch.setattr(dev, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        dev.check(python_only=True)
    assert not any(Path(command[0]).name == 'lint-imports' for command in commands)

    # Repair the newly added module and prove the same gate proceeds normally.
    source.write_text('def operation(*, count: int) -> int:\n    return count\n\noperation(count=1)\n', encoding='utf-8')
    commands.clear()
    dev.check(python_only=True)
    assert any(Path(command[0]).name == 'lint-imports' for command in commands)
