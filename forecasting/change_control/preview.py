"""Deterministic, non-mutating changeset previews."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from forecasting.change_control.apply import apply_operation, validate_preconditions
from forecasting.change_control.models import LedgerOperation, content_digest
from forecasting.change_control.store import current_revision, get_changeset, list_operations
from forecasting.ledger.gate import allow_ledger_writes


def _probability(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        candidate = value.get("probability", value.get("yes"))
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            return float(candidate)
    return None


def _semantic_change(ledger: Any, operation: LedgerOperation) -> dict[str, Any]:
    change: dict[str, Any] = {
        "operation_id": operation.id,
        "kind": operation.kind,
        "target_ref": operation.target_ref,
    }
    if operation.kind == "forecast.create":
        change["question"] = {
            "before": None,
            "after": {
                "title": operation.payload["title"],
                "resolution_criteria": operation.payload["resolution_criteria"],
            },
        }
        change["probability"] = {
            "before": None,
            "after": operation.payload["probability_or_distribution"],
            "delta": None,
        }
    elif operation.kind == "forecast.update":
        current = ledger.get_current_snapshot(operation.target_ref)
        before = None if current is None else current.probability_or_distribution
        after = operation.payload["probability_or_distribution"]
        before_p, after_p = _probability(before), _probability(after)
        change["probability"] = {
            "before": before,
            "after": after,
            "delta": None if before_p is None or after_p is None else after_p - before_p,
        }
    elif operation.kind == "question.criteria.update":
        question = ledger.get_question(operation.target_ref)
        change["resolution_criteria"] = {
            "before": question.resolution_criteria,
            "after": operation.payload["resolution_criteria"],
        }
    elif operation.kind == "evidence.attach":
        change["new_evidence"] = {
            key: operation.payload.get(key)
            for key in ("source_type", "source_url", "source_name", "claim", "summary")
            if key in operation.payload
        }
    elif operation.kind == "document.update":
        content = str(operation.payload["content"])
        change["portable_file_diff"] = {
            "path": str(operation.payload["path"]),
            "content_digest": content_digest(content),
            "bytes": len(content.encode("utf-8")),
        }
    return change


def _hook_summary(result: dict[str, Any]) -> dict[str, Any] | None:
    hook = result.get("hook_result")
    if not hook:
        return None
    return {
        "operation_id": result["operation_id"],
        "would_commit": bool(hook.get("would_commit")),
        "blockers": list(hook.get("blockers") or ()),
        "saturation": hook.get("saturation"),
    }


def _copy_ledger(ledger: Any, destination: Path) -> None:
    source = sqlite3.connect(f"file:{ledger.db_path}?mode=ro", uri=True)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def preview_changeset(ledger: Any, changeset_id: str) -> dict[str, Any]:
    """Project a changeset on a disposable ledger and return stable JSON + Markdown."""

    changes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    hook_results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="forecast-preview-") as directory:
        preview_path = Path(directory) / "ledger.db"
        _copy_ledger(ledger, preview_path)
        from forecasting.ledger import ForecastLedger

        preview_ledger = ForecastLedger(preview_path)
        changeset = get_changeset(preview_ledger, changeset_id)
        operations = list_operations(preview_ledger, changeset_id)
        revision = current_revision(preview_ledger)["revision"]
        for operation in operations:
            try:
                changes.append(_semantic_change(preview_ledger, operation))
            except Exception as exc:
                failures.append(
                    {
                        "operation_id": operation.id,
                        "stage": "projection",
                        "error": str(exc),
                    }
                )
            for failure in validate_preconditions(preview_ledger, operation):
                failures.append(
                    {"operation_id": operation.id, "stage": "precondition", "error": failure}
                )
        if changeset["base_revision"] != revision:
            failures.append(
                {
                    "operation_id": None,
                    "stage": "base_revision",
                    "error": f"base revision is stale: {changeset['base_revision']} != {revision}",
                }
            )
        aliases: dict[str, str] = {}
        for operation in operations:
            previous_aliases = dict(aliases)
            try:
                with allow_ledger_writes("changeset_preview"), preview_ledger.transaction(
                    immediate=True
                ):
                    result = apply_operation(
                        preview_ledger,
                        operation,
                        changeset_id=changeset_id,
                        changeset_digest_value=changeset["digest"],
                        aliases=aliases,
                    )
                hook = _hook_summary(result)
                if hook:
                    hook_results.append(hook)
            except Exception as exc:
                aliases = previous_aliases
                failure = {
                    "operation_id": operation.id,
                    "stage": "validation_or_hook",
                    "error": str(exc),
                }
                if failure not in failures:
                    failures.append(failure)

    projection = {
        "version": 1,
        "changeset_id": changeset_id,
        "changeset_digest": changeset["digest"],
        "base_revision": changeset["base_revision"],
        "live_revision": revision,
        "changes": changes,
        "hook_results": hook_results,
        "failures": failures,
    }
    projection["projection_digest"] = content_digest(projection)
    projection["would_apply"] = not failures
    projection["markdown"] = render_preview_markdown(projection)
    return projection


def render_preview_markdown(preview: dict[str, Any]) -> str:
    lines = [
        f"# Changeset {preview['changeset_id']}",
        "",
        f"- Base revision: `{preview['base_revision']}`",
        f"- Changeset digest: `{preview['changeset_digest']}`",
        f"- Projection digest: `{preview.get('projection_digest', 'pending')}`",
        f"- Result: **{'ready' if not preview['failures'] else 'blocked'}**",
        "",
        "## Proposed operations",
        "",
    ]
    for change in preview["changes"]:
        lines.append(
            f"- `{change['operation_id']}` — `{change['kind']}` on `{change['target_ref']}`"
        )
        probability = change.get("probability")
        if probability and probability.get("delta") is not None:
            lines.append(f"  - Probability delta: `{probability['delta']:+.4f}`")
        if "portable_file_diff" in change:
            lines.append(f"  - File: `{change['portable_file_diff']['path']}`")
    if preview["hook_results"]:
        lines.extend(["", "## Hook results", ""])
        for hook in preview["hook_results"]:
            state = "pass" if hook["would_commit"] else "fail"
            lines.append(f"- `{hook['operation_id']}`: **{state}**")
    if preview["failures"]:
        lines.extend(["", "## Blocking findings", ""])
        for failure in preview["failures"]:
            lines.append(
                f"- `{failure.get('operation_id') or 'changeset'}` "
                f"({failure['stage']}): {failure['error']}"
            )
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["preview_changeset", "render_preview_markdown"]
