"""Versioned calculation inputs and explicit replay without live tool dispatch.

Hashes detect accidental corruption, not forgery by someone able to rewrite the
whole archive. Replay executes recorded Python; use only locally trusted code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent.redact import redact_sensitive_text
from superforecasting_agent.storage.files import atomic_json_write
from tools.registry import tool_error

MAX_OBSERVATION_BYTES = 2 * 1024 * 1024
MAX_RECORD_BYTES = 8 * 1024 * 1024


def display_output(text: str, limit: int) -> tuple[str, int]:
    """Keep the interactive result bounded; complete retained text stays on disk."""
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= limit:
        return text, 0
    marker = b"\n[Output shortened; see calculation record]\n"
    available = limit - len(marker)
    head = available * 2 // 3
    tail = available - head
    return (
        raw[:head].decode("utf-8", errors="ignore")
        + marker.decode()
        + raw[-tail:].decode("utf-8", errors="ignore"),
        len(raw) - available,
    )


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)


def sealed(value: dict[str, Any]) -> dict[str, Any]:
    payload = {key: item for key, item in value.items() if key != "record_sha256"}
    return {**payload, "record_sha256": digest(canonical(payload))}


def read_record(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError(f"Symlinked calculation record is not accepted: {path.name}")
    with path.open("rb") as stream:
        raw = stream.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError("Calculation record exceeds size limit")
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or value.get("record_sha256") != sealed(value)["record_sha256"]
    ):
        raise ValueError(
            f"Calculation record checksum is missing or invalid: {path.name}"
        )
    return value


def _retained(text: str) -> dict[str, Any]:
    redacted = redact_sensitive_text(text, force=True)
    omitted = len(canonical(redacted)) > MAX_OBSERVATION_BYTES
    return {
        "sha256": digest(text),
        "redacted": redacted != text,
        "omitted": omitted,
        "text": None if omitted else redacted,
    }


class InputRecorder:
    """Record admission before effects; preserve exact, bounded observations."""

    def __init__(self, directory: Path, dispatch: Callable[[str, dict], str]) -> None:
        self.directory, self.dispatch = directory, dispatch
        self.directory.mkdir(mode=0o700)
        self.count = 0
        self.complete = True

    def __call__(self, name: str, args: dict) -> str:
        self.count += 1
        path = self.directory / f"{self.count:06d}.json"
        entry: dict[str, Any] = {
            "version": 1,
            "sequence": self.count,
            "tool": name,
            "arguments": _retained(canonical(args)),
            "status": "running",
        }
        try:
            atomic_json_write(path, sealed(entry))
            try:
                result = self.dispatch(name, args)
                if not isinstance(result, str):
                    result = tool_error("Tool returned an invalid RPC response type")
            except Exception as exc:
                result = tool_error(redact_sensitive_text(str(exc), force=True))
            entry.update(status="completed", response=_retained(result))
            atomic_json_write(path, sealed(entry))
            return result
        except BaseException:
            self.complete = False
            raise

    def snapshot(self) -> dict[str, Any]:
        entries = []
        try:
            for number in range(1, self.count + 1):
                entries.append(read_record(self.directory / f"{number:06d}.json"))
        except (OSError, ValueError):
            self.complete = False
        return {
            "input_count": self.count,
            "inputs_complete": self.complete,
            "inputs_sha256": digest(canonical(entries)),
        }


class FrozenInputs:
    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self.entries = entries
        self.index = 0
        self.mismatch: str | None = None

    def __call__(self, name: str, args: dict) -> str:
        if self.index >= len(self.entries):
            self.mismatch = "Replay attempted an additional tool call"
            raise ValueError(self.mismatch)
        entry = self.entries[self.index]
        if entry["tool"] != name or entry["arguments"]["sha256"] != digest(
            canonical(args)
        ):
            self.mismatch = (
                "Replay tool identity or arguments differ from recorded input"
            )
            raise ValueError(self.mismatch)
        self.index += 1
        return entry["response"]["text"]

    def require_consumed(self) -> None:
        if self.mismatch or self.index != len(self.entries):
            raise ValueError(
                self.mismatch or "Replay did not consume every recorded tool input"
            )


def verified_cells(
    directory: Path,
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Validate the entire archive before any recorded code may execute."""
    if directory.is_symlink():
        raise ValueError("Symlinked calculation directories are not accepted")
    records = []
    retained_bytes = 0
    for path in directory.glob("*.json"):
        if len(records) >= 10000:
            raise ValueError("Too many calculation records")
        record = read_record(path)
        retained_bytes += len(canonical(record))
        if retained_bytes > 64 * 1024 * 1024:
            raise ValueError("Calculation archive exceeds verification memory limit")
        if record.get("version") != 2:
            raise ValueError(
                "Calculation version does not contain verifiable replay inputs"
            )
        records.append(record)
    if not records:
        raise ValueError("No calculation records found")
    try:
        records.sort(key=lambda item: item["sequence"])
        previous = ""
        kernel_id = records[0]["kernel_id"]
        checked = []
        for sequence, record in enumerate(records, 1):
            if (
                not isinstance(record.get("code"), str)
                or type(record.get("code_redacted")) is not bool
                or not isinstance(record.get("runtime"), dict)
                or not isinstance(record.get("tools"), list)
                or not all(isinstance(name, str) for name in record["tools"])
                or type(record.get("max_tool_calls")) is not int
                or record["max_tool_calls"] < 0
                or not isinstance(record.get("result"), dict)
            ):
                raise ValueError("Invalid calculation replay metadata")
            if (
                type(record["sequence"]) is not int
                or record["sequence"] != sequence
                or record["kernel_id"] != kernel_id
                or record["previous_record_sha256"] != previous
            ):
                raise ValueError("Calculation history has a gap or invalid chain")
            if record["status"] not in {"completed", "failed"}:
                raise ValueError(
                    "Unfinished calculation cannot be replayed as a complete history"
                )
            if (
                record["code_redacted"]
                or digest(record["code"]) != record["code_sha256"]
            ):
                raise ValueError("Original calculation code is unavailable or changed")
            if (
                record.get("result_redacted") is not False
                or record["result"].get("stdout_omitted_chars") != 0
                or record["result"].get("stderr_omitted_chars") != 0
            ):
                raise ValueError("Complete original calculation output is unavailable")
            if not record["inputs_complete"]:
                raise ValueError("Calculation input recording was interrupted")
            cell_id = record["cell_id"]
            if (
                not isinstance(cell_id, str)
                or len(cell_id) != 32
                or any(c not in "0123456789abcdef" for c in cell_id)
            ):
                raise ValueError("Invalid calculation identity")
            count = record["input_count"]
            if type(count) is not int or not 0 <= count <= 10000:
                raise ValueError("Invalid calculation input count")
            inputs_dir = directory / f"{cell_id}.inputs"
            if inputs_dir.is_symlink():
                raise ValueError("Symlinked input directory is not accepted")
            inputs = []
            for number in range(1, count + 1):
                entry = read_record(inputs_dir / f"{number:06d}.json")
                retained_bytes += len(canonical(entry))
                if retained_bytes > 64 * 1024 * 1024:
                    raise ValueError(
                        "Calculation archive exceeds verification memory limit"
                    )
                if entry["sequence"] != number or entry["status"] != "completed":
                    raise ValueError("Calculation input is incomplete")
                for field in ("arguments", "response"):
                    value = entry[field]
                    if (
                        value["redacted"]
                        or value["omitted"]
                        or not isinstance(value["text"], str)
                    ):
                        raise ValueError(
                            "Original tool observation is unavailable for exact replay"
                        )
                    if digest(value["text"]) != value["sha256"]:
                        raise ValueError("Tool observation checksum mismatch")
                inputs.append(entry)
            if digest(canonical(inputs)) != record["inputs_sha256"]:
                raise ValueError("Calculation input manifest mismatch")
            checked.append((record, inputs))
            previous = record["record_sha256"]
        return checked
    except (KeyError, TypeError) as exc:
        raise ValueError("Malformed calculation archive") from exc


def replay(directory: Path, output_directory: Path) -> dict[str, Any]:
    """Explicitly execute trusted recorded code with frozen RPC observations.

    Direct Python filesystem/network effects are not intercepted by this RPC
    boundary. This function must never be called automatically on imported data.
    """
    from tools.code_kernel import KernelOwner

    cells = verified_cells(directory)
    if output_directory.exists():
        raise ValueError("Replay output directory must be new")
    output_directory.mkdir(parents=True, mode=0o700)
    owner = KernelOwner(output_directory)
    outcomes = []
    try:
        for record, entries in cells:
            frozen = FrozenInputs(entries)
            result = owner.run(
                record["code"],
                "calculation-replay",
                frozenset(record["tools"]),
                record["forecast_commit_policy"],
                "strict",
                60,
                record["max_tool_calls"],
                False,
                dispatch_override=frozen,
            )
            frozen.require_consumed()
            # Compare the full retained observation, not the bounded TUI preview.
            replay_record_path = result["calculation_record"]
            result = read_record(Path(replay_record_path))
            actual = result["result"]
            expected = record["result"]
            assert owner.kernel is not None
            environment_matches = owner.kernel.runtime == record["runtime"]
            matches = all(
                actual[field] == expected[field]
                for field in (
                    "stdout",
                    "stderr",
                    "error",
                    "stdout_omitted_chars",
                    "stderr_omitted_chars",
                )
            )
            outcomes.append({
                "cell_id": record["cell_id"],
                "matches": matches,
                "environment_matches": environment_matches,
                "record": replay_record_path,
            })
    finally:
        owner.close()
    report = {
        "version": 1,
        "source": str(directory.resolve()),
        "matched": all(item["matches"] for item in outcomes),
        "environment_matched": all(item["environment_matches"] for item in outcomes),
        "cells": outcomes,
        "live_tool_dispatch": False,
        "input_coverage": "recorded RPC observations; direct Python I/O is not frozen",
    }
    atomic_json_write(output_directory / "replay-report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify or explicitly replay trusted Python calculation records."
    )
    parser.add_argument("action", choices=("verify", "replay"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output-directory", type=Path)
    args = parser.parse_args()
    if args.action == "verify":
        result = {"verified_cells": len(verified_cells(args.directory))}
    else:
        if args.output_directory is None:
            parser.error("replay requires --output-directory (must not exist)")
        result = replay(args.directory, args.output_directory)
    print(json.dumps(result, indent=2))
    if args.action == "replay" and not result["matched"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
