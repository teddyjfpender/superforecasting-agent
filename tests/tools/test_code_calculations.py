"""Archive validation and real replay consume frozen data without live tools."""

import json
import sys
from pathlib import Path

import pytest

from tools.code_calculations import replay, sealed, verified_cells
from tools.code_kernel import KernelOwner


@pytest.fixture
def archive(tmp_path, monkeypatch):
    from tools import code_execution_rpc, code_execution_tool

    monkeypatch.setattr(
        code_execution_tool, "_resolve_child_python", lambda mode: sys.executable
    )
    calls = []

    def live(name, args):
        calls.append((name, args))
        return json.dumps({"values": [2, 4, 6]})

    monkeypatch.setattr(code_execution_rpc, "_dispatcher", lambda *args: live)
    owner = KernelOwner(tmp_path / "source")
    try:
        first = owner.run(
            'from forecast_tools import read_file\nvalues = read_file(path="dataset")["values"]\nprint(sum(values))',
            "source",
            frozenset({"read_file"}),
            "proposal_only",
            "strict",
            5,
            2,
            False,
        )
        owner.run(
            "print(sum(values) / len(values))",
            "source",
            frozenset({"read_file"}),
            "proposal_only",
            "strict",
            5,
            2,
            False,
        )
        directory = Path(first["calculation_record"]).parent
    finally:
        owner.close()
    return directory, calls


def test_real_replay_uses_frozen_observations_and_preserves_source(archive, tmp_path):
    directory, calls = archive
    before = {
        path.relative_to(directory): path.read_bytes()
        for path in directory.rglob("*.json")
    }
    cells = verified_cells(directory)
    assert len(cells) == 2 and len(cells[0][1]) == 1
    report = replay(directory, tmp_path / "replay")
    assert report["matched"] and report["environment_matched"]
    assert report["live_tool_dispatch"] is False
    assert len(calls) == 1
    assert before == {
        path.relative_to(directory): path.read_bytes()
        for path in directory.rglob("*.json")
    }
    assert (tmp_path / "replay" / "replay-report.json").is_file()


def test_missing_input_or_changed_code_fails_before_replay(archive, tmp_path):
    directory, calls = archive
    path = next(directory.glob("*.inputs/*.json"))
    path.unlink()
    with pytest.raises(FileNotFoundError):
        replay(directory, tmp_path / "replay")
    assert len(calls) == 1 and not (tmp_path / "replay").exists()


def test_corruption_and_missing_cell_break_verified_chain(archive):
    directory, _ = archive
    cells = verified_cells(directory)
    second_path = directory / f"{cells[1][0]['cell_id']}.json"
    value = json.loads(second_path.read_text())
    value["code"] = "print(999)"
    second_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="checksum"):
        verified_cells(directory)
    second_path.write_text(json.dumps(sealed(value)))
    with pytest.raises(ValueError, match="code is unavailable or changed"):
        verified_cells(directory)
    (directory / f"{cells[0][0]['cell_id']}.json").unlink()
    with pytest.raises(ValueError, match="gap or invalid chain"):
        verified_cells(directory)


def test_redacted_input_is_retained_but_not_claimed_replayable(tmp_path, monkeypatch):
    from tools import code_execution_rpc, code_execution_tool

    monkeypatch.setattr(
        code_execution_tool, "_resolve_child_python", lambda mode: sys.executable
    )
    monkeypatch.setattr(
        code_execution_rpc,
        "_dispatcher",
        lambda *args: (
            lambda *args: "Authorization: Bearer abcdefghijklmnopqrstuvwxyz1234567890"
        ),
    )
    owner = KernelOwner(tmp_path / "source")
    try:
        result = owner.run(
            'from forecast_tools import read_file\nread_file(path="source")\nprint("done")',
            "source",
            frozenset({"read_file"}),
            "proposal_only",
            "strict",
            5,
            2,
            False,
        )
    finally:
        owner.close()
    directory = Path(result["calculation_record"]).parent
    text = next(directory.glob("*.inputs/*.json")).read_text()
    assert "abcdefghijklmnopqrstuvwxyz1234567890" not in text
    with pytest.raises(ValueError, match="observation is unavailable"):
        verified_cells(directory)


def test_runtime_difference_is_reported_separately_from_matching_outputs(
    archive, tmp_path
):
    directory, _ = archive
    cells = verified_cells(directory)
    previous = ""
    for record, _ in cells:
        record["runtime"]["python"] = "an older interpreter"
        record["previous_record_sha256"] = previous
        updated = sealed(record)
        previous = updated["record_sha256"]
        (directory / f"{record['cell_id']}.json").write_text(json.dumps(updated))
    report = replay(directory, tmp_path / "replay")
    assert report["matched"]
    assert not report["environment_matched"]


def test_frozen_replay_refuses_additional_calls():
    from tools.code_calculations import FrozenInputs

    frozen = FrozenInputs([])
    with pytest.raises(ValueError, match="additional"):
        frozen("read_file", {"path": "unrecorded"})
    with pytest.raises(ValueError, match="additional"):
        frozen.require_consumed()


def test_input_record_write_failure_cannot_become_replay_evidence(
    tmp_path, monkeypatch
):
    from tools import code_calculations, code_execution_rpc, code_execution_tool

    monkeypatch.setattr(
        code_execution_tool, "_resolve_child_python", lambda mode: sys.executable
    )
    calls = []
    monkeypatch.setattr(
        code_execution_rpc,
        "_dispatcher",
        lambda *args: lambda *args: calls.append("effect") or "{}",
    )
    write = code_calculations.atomic_json_write

    def failing_write(path, value, **kwargs):
        if value.get("status") == "completed":
            raise OSError("receipt disk full")
        return write(path, value, **kwargs)

    monkeypatch.setattr(code_calculations, "atomic_json_write", failing_write)
    owner = KernelOwner(tmp_path / "source")
    try:
        result = owner.run(
            'from forecast_tools import read_file\nprint(read_file(path="source"))',
            "source",
            frozenset({"read_file"}),
            "proposal_only",
            "strict",
            5,
            2,
            False,
        )
    finally:
        owner.close()
    assert calls == ["effect"]
    record = json.loads(Path(result["calculation_record"]).read_text())
    assert not record["inputs_complete"]
    with pytest.raises(ValueError, match="recording was interrupted"):
        verified_cells(Path(result["calculation_record"]).parent)


def test_module_cli_replays_archive_without_live_provider(archive, tmp_path):
    import subprocess

    directory, calls = archive
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.code_calculations",
            "replay",
            str(directory),
            "--output-directory",
            str(tmp_path / "command-replay"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["matched"] and report["live_tool_dispatch"] is False
    assert len(calls) == 1


def test_replay_compares_complete_output_not_short_interactive_preview(
    tmp_path, monkeypatch
):
    from tools import code_execution_tool

    monkeypatch.setattr(
        code_execution_tool, "_resolve_child_python", lambda mode: sys.executable
    )
    owner = KernelOwner(tmp_path / "source")
    try:
        result = owner.run(
            'print("é" * 40000)',
            "source",
            frozenset(),
            "proposal_only",
            "strict",
            5,
            0,
            False,
        )
    finally:
        owner.close()
    assert len(result["stdout"].encode()) <= 50000
    assert result["display_stdout_omitted_bytes"] > 0
    directory = Path(result["calculation_record"]).parent
    assert len(verified_cells(directory)[0][0]["result"]["stdout"]) == 40001
    assert replay(directory, tmp_path / "replay")["matched"]


def test_error_replay_keeps_partial_state_and_comparable_diagnostics(
    tmp_path, monkeypatch
):
    from tools import code_execution_tool

    monkeypatch.setattr(
        code_execution_tool, "_resolve_child_python", lambda mode: sys.executable
    )
    owner = KernelOwner(tmp_path / "source")
    try:
        result = owner.run(
            'value = 5\nraise ValueError("missing measurement")',
            "source",
            frozenset(),
            "proposal_only",
            "strict",
            5,
            0,
            False,
        )
        owner.run(
            "print(value)",
            "source",
            frozenset(),
            "proposal_only",
            "strict",
            5,
            0,
            False,
        )
    finally:
        owner.close()
    assert replay(Path(result["calculation_record"]).parent, tmp_path / "replay")[
        "matched"
    ]


def test_cli_output_mismatch_has_nonzero_status(tmp_path, monkeypatch):
    import subprocess
    from tools import code_execution_tool

    monkeypatch.setattr(
        code_execution_tool, "_resolve_child_python", lambda mode: sys.executable
    )
    owner = KernelOwner(tmp_path / "source")
    try:
        result = owner.run(
            "import os\nprint(os.getcwd())",
            "source",
            frozenset(),
            "proposal_only",
            "strict",
            5,
            0,
            False,
        )
    finally:
        owner.close()
    command = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.code_calculations",
            "replay",
            str(Path(result["calculation_record"]).parent),
            "--output-directory",
            str(tmp_path / "replay"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert command.returncode == 1, command.stderr
    assert json.loads(command.stdout)["matched"] is False
