"""Transactional application of reviewed ledger changesets."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any, Mapping

from forecasting.change_control.models import LedgerOperation, changeset_digest, content_digest
from forecasting.change_control.policy import evaluate_quorum
from forecasting.change_control.store import (
    current_revision,
    get_changeset,
    list_operations,
    list_reviews,
    transition_changeset,
)
from forecasting.ledger.gate import allow_ledger_writes
from forecasting.models import OutcomeSpace, ValidationError, utc_now_iso


_APPLYABLE_STATUSES = frozenset({"merge_ready", "merged_apply_pending", "apply_failed"})


def _public(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _target(operation: LedgerOperation, aliases: Mapping[str, str]) -> str:
    return aliases.get(operation.target_ref, operation.target_ref)


def _question_preconditions(ledger: Any, operation: LedgerOperation, target: str) -> list[str]:
    if operation.kind in {"forecast.create", "document.update", "lesson.activate"}:
        return []
    try:
        question = ledger.get_question(target)
    except Exception as exc:
        return [f"target question is unavailable: {type(exc).__name__}"]
    failures: list[str] = []
    expected_status = operation.preconditions.get("question_status")
    if expected_status is not None and question.status != expected_status:
        failures.append(f"question_status expected {expected_status!r}, found {question.status!r}")
    expected_snapshot = operation.preconditions.get("current_forecast_id")
    if expected_snapshot is not None and question.current_forecast_id != expected_snapshot:
        failures.append(
            f"current_forecast_id expected {expected_snapshot!r}, "
            f"found {question.current_forecast_id!r}"
        )
    if "prior_probability" in operation.preconditions:
        current = ledger.get_current_snapshot(target)
        actual = None if current is None else current.probability_or_distribution
        if content_digest(actual) != content_digest(operation.preconditions["prior_probability"]):
            failures.append("prior_probability no longer matches the current forecast")
    return failures


def validate_preconditions(
    ledger: Any,
    operation: LedgerOperation,
    *,
    aliases: Mapping[str, str] | None = None,
) -> list[str]:
    aliases = aliases or {}
    target = _target(operation, aliases)
    failures = _question_preconditions(ledger, operation, target)
    expected_revision = operation.preconditions.get("ledger_revision")
    if expected_revision is not None:
        actual_revision = current_revision(ledger)["revision"]
        if int(expected_revision) != actual_revision:
            failures.append(
                f"ledger_revision expected {int(expected_revision)}, found {actual_revision}"
            )
    return failures


def _snapshot_kwargs(payload: Mapping[str, Any], *, provenance: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "probability_or_distribution",
        "rationale",
        "as_of",
        "confidence",
        "method",
        "ensemble_components",
        "key_assumptions",
        "assumption_refs",
        "reference_class_refs",
        "evidence_refs",
        "model_run_refs",
        "forecast_origin",
        "agent_model",
        "prompt_version",
        "forecasting_protocol_version",
        "toolset_version",
        "source_snapshot_refs",
        "evidence_cutoff",
        "calibration_lesson_refs",
        "calibration_adjustment",
        "reasons_up",
        "reasons_down",
        "change_my_mind",
        "outcome_paths",
        "stale_evidence_days",
        "acknowledge_stale_evidence",
        "stale_evidence_reason",
        "require_citations",
        "require_decision_readiness",
        "require_structured_reasoning",
        "require_components",
        "require_fresh_evidence",
        "require_panel",
        "panel_run_ref",
        "panel_skipped_reason",
        "require_outcome_paths",
        "style_autofix",
        "require_style",
        "reasoning_methods",
        "require_output_structure",
        "distribution_autofix",
        "enforce_resolved_hooks",
    }
    result = {key: payload[key] for key in allowed if key in payload}
    result["metadata"] = {**dict(payload.get("metadata") or {}), **provenance}
    return result


def _question_kwargs(payload: Mapping[str, Any], *, provenance: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "title",
        "resolution_criteria",
        "description",
        "resolution_source",
        "close_time",
        "resolution_time",
        "tags",
        "domain",
        "topics",
        "owner",
        "impact",
        "review_cadence",
        "next_review_at",
        "decision_owner",
        "decision_deadline",
        "action_threshold",
        "update_triggers",
    }
    result = {key: payload[key] for key in allowed if key in payload}
    result["outcome_space"] = OutcomeSpace.from_dict(payload.get("outcome_space"))
    result["metadata"] = {**dict(payload.get("metadata") or {}), **provenance}
    return result


def _preview_snapshot(ledger: Any, question_id: str, kwargs: Mapping[str, Any]) -> dict[str, Any]:
    result = ledger.create_snapshot(question_id=question_id, preview=True, **dict(kwargs))
    if not result.get("would_commit"):
        raise ValidationError("; ".join(result.get("blockers") or ["forecast hooks failed"]))
    return result


def apply_operation(
    ledger: Any,
    operation: LedgerOperation,
    *,
    changeset_id: str,
    changeset_digest_value: str,
    aliases: dict[str, str],
) -> dict[str, Any]:
    """Apply one validated operation through ledger APIs inside an outer transaction."""

    failures = validate_preconditions(ledger, operation, aliases=aliases)
    if failures:
        raise ValidationError("; ".join(failures))
    payload = operation.payload
    target = _target(operation, aliases)
    provenance = {
        "changeset_id": changeset_id,
        "changeset_digest": changeset_digest_value,
        "operation_id": operation.id,
    }
    hook_result: dict[str, Any] | None = None

    if operation.kind == "forecast.create":
        question = ledger.create_question(**_question_kwargs(payload, provenance=provenance))
        aliases[operation.target_ref] = question.id
        snapshot_kwargs = _snapshot_kwargs(payload, provenance=provenance)
        hook_result = _preview_snapshot(ledger, question.id, snapshot_kwargs)
        snapshot = ledger.create_snapshot(question_id=question.id, **snapshot_kwargs)
        return {
            "operation_id": operation.id,
            "question_id": question.id,
            "forecast_id": snapshot.forecast_id,
            "hook_result": hook_result,
        }
    if operation.kind == "forecast.update":
        snapshot_kwargs = _snapshot_kwargs(payload, provenance=provenance)
        hook_result = _preview_snapshot(ledger, target, snapshot_kwargs)
        snapshot = ledger.create_snapshot(question_id=target, **snapshot_kwargs)
        return {
            "operation_id": operation.id,
            "question_id": target,
            "forecast_id": snapshot.forecast_id,
            "hook_result": hook_result,
        }
    if operation.kind == "evidence.attach":
        allowed = {
            "claim",
            "summary",
            "source_url",
            "source_name",
            "source_type",
            "published_at",
            "available_at",
            "reliability_rating",
            "relevance_rating",
            "stance",
            "claim_type",
            "admissible_for_backtests",
        }
        kwargs = {key: payload[key] for key in allowed if key in payload}
        kwargs["source_or_note"] = str(
            payload.get("source_or_note")
            or payload.get("source_url")
            or payload.get("source_name")
            or payload["claim"]
        )
        kwargs["metadata"] = {**dict(payload.get("metadata") or {}), **provenance}
        item = ledger.add_evidence(question_id=target, **kwargs)
        return {"operation_id": operation.id, "question_id": target, "evidence_id": item.id}
    if operation.kind == "assumption.upsert":
        assumption_id = payload.get("assumption_id")
        if assumption_id:
            ledger.get_assumption(str(assumption_id))
            with ledger._connect() as conn:
                conn.execute(
                    "UPDATE assumptions SET text = ? WHERE id = ?",
                    (str(payload["text"]).strip(), assumption_id),
                )
            item = ledger.update_assumption(
                str(assumption_id),
                **{
                    key: payload[key]
                    for key in ("status", "last_checked_at", "invalidated_at", "notes")
                    if key in payload
                },
            )
        else:
            item = ledger.add_assumption(
                question_id=target,
                **{
                    key: payload[key]
                    for key in ("text", "status", "check_cadence", "evidence_refs", "notes")
                    if key in payload
                },
            )
        return {"operation_id": operation.id, "question_id": target, "assumption_id": item["id"]}
    if operation.kind == "reference_class.upsert":
        reference_id = payload.get("reference_class_id")
        if reference_id:
            ledger.get_reference_class(str(reference_id))
            mutable = {
                key: payload[key]
                for key in (
                    "name",
                    "inclusion_criteria",
                    "exclusion_criteria",
                    "base_rate",
                    "base_rate_uncertainty",
                    "sample_size",
                )
                if key in payload
            }
            if mutable:
                assignments = ", ".join(f"{key} = ?" for key in mutable)
                with ledger._connect() as conn:
                    conn.execute(
                        f"UPDATE reference_classes SET {assignments} WHERE id = ?",
                        [*mutable.values(), reference_id],
                    )
            item = ledger.update_reference_class(
                str(reference_id),
                **{
                    key: payload[key]
                    for key in ("status", "last_checked_at", "invalidated_at", "check_cadence", "notes")
                    if key in payload
                },
            )
        else:
            item = ledger.add_reference_class(
                question_id=target,
                **{
                    key: payload[key]
                    for key in (
                        "name",
                        "inclusion_criteria",
                        "exclusion_criteria",
                        "base_rate",
                        "base_rate_uncertainty",
                        "source_refs",
                        "check_cadence",
                        "notes",
                        "sample_size",
                    )
                    if key in payload
                },
            )
        return {
            "operation_id": operation.id,
            "question_id": target,
            "reference_class_id": item["id"],
        }
    if operation.kind == "question.criteria.update":
        with ledger._connect() as conn:
            conn.execute(
                "UPDATE forecast_questions SET resolution_criteria = ? WHERE id = ?",
                (str(payload["resolution_criteria"]).strip(), target),
            )
        return {"operation_id": operation.id, "question_id": target}
    if operation.kind == "resolution.create":
        allowed = {
            "outcome",
            "resolution_source",
            "resolution_source_snapshot_ref",
            "resolver_type",
            "resolution_status",
            "criteria_satisfied",
            "confidence",
            "confirmed_by",
            "resolver_notes",
            "correction_ref",
            "trusted_policy_id",
            "scoreable",
            "auto_score",
        }
        resolution = ledger.resolve_question(
            question_id=target,
            **{key: payload[key] for key in allowed if key in payload},
        )
        return {
            "operation_id": operation.id,
            "question_id": target,
            "resolution_id": resolution.id,
        }
    if operation.kind == "thesis.update":
        question = ledger.get_question(target)
        if not ledger.is_thesis(question):
            raise ValidationError(f"question {target} is not a thesis")
        fields = {key: payload[key] for key in ("title", "description") if key in payload}
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with ledger._connect() as conn:
            conn.execute(
                f"UPDATE forecast_questions SET {assignments} WHERE id = ?",
                [*fields.values(), target],
            )
        return {"operation_id": operation.id, "question_id": target}
    if operation.kind == "document.update":
        return {
            "operation_id": operation.id,
            "document_path": str(payload["path"]),
            "document_digest": content_digest(str(payload["content"])),
        }
    if operation.kind == "lesson.activate":
        lesson = ledger.update_calibration_lesson(str(payload["lesson_id"]), status="active")
        return {"operation_id": operation.id, "lesson_id": lesson["id"]}
    raise ValidationError(f"unsupported operation kind: {operation.kind}")


def _attempt(ledger: Any, changeset_id: str, *, merge_sha: str | None) -> str:
    attempt_id = f"apply_{uuid.uuid4().hex[:16]}"
    with ledger._connect() as conn:
        conn.execute(
            """INSERT INTO ledger_apply_attempts
               (id, changeset_id, merge_sha, state, started_at)
               VALUES (?, ?, ?, 'running', ?)""",
            (attempt_id, changeset_id, merge_sha, utc_now_iso()),
        )
    return attempt_id


def _failed(ledger: Any, changeset_id: str, attempt_id: str, exc: BaseException) -> None:
    now = utc_now_iso()
    diagnostic = f"{type(exc).__name__}: changeset application failed"
    with ledger._connect() as conn:
        conn.execute(
            """UPDATE ledger_apply_attempts
               SET state = 'failed', diagnostic = ?, finished_at = ? WHERE id = ?""",
            (diagnostic, now, attempt_id),
        )
        conn.execute(
            """UPDATE ledger_changesets SET status = 'apply_failed', updated_at = ?
               WHERE id = ? AND status != 'applied'""",
            (now, changeset_id),
        )


def apply_changeset(ledger: Any, changeset_id: str) -> dict[str, Any]:
    """Apply a checks-passing, quorum-approved changeset exactly once."""

    initial = get_changeset(ledger, changeset_id)
    if initial["status"] == "applied":
        return dict(initial["metadata"].get("apply_result") or {})
    if initial["status"] not in _APPLYABLE_STATUSES:
        raise ValidationError(
            f"changeset {changeset_id} is {initial['status']}; expected an applyable status"
        )
    attempt_id = _attempt(ledger, changeset_id, merge_sha=initial.get("merge_sha"))
    try:
        with allow_ledger_writes(f"apply_changeset:{changeset_id}"), ledger.transaction(
            immediate=True
        ) as conn:
            changeset = get_changeset(ledger, changeset_id)
            if changeset["status"] == "applied":
                result = dict(changeset["metadata"].get("apply_result") or {})
                conn.execute(
                    """UPDATE ledger_apply_attempts
                       SET state = 'duplicate', finished_at = ? WHERE id = ?""",
                    (utc_now_iso(), attempt_id),
                )
                return result
            operations = list_operations(ledger, changeset_id)
            if not operations:
                raise ValidationError("changeset has no operations")
            actual_digest = changeset_digest(
                workspace_id=changeset["workspace_id"],
                base_revision=changeset["base_revision"],
                operations=operations,
            )
            if actual_digest != changeset["digest"]:
                raise ValidationError("changeset digest does not match its operations")
            revision = current_revision(ledger)
            if changeset["base_revision"] != revision["revision"]:
                raise ValidationError(
                    f"base revision is stale: {changeset['base_revision']} != {revision['revision']}"
                )
            if changeset["metadata"].get("checks_passed") is not True:
                raise ValidationError("required changeset checks have not passed")
            quorum = evaluate_quorum(
                risk_tier=changeset["risk_tier"],
                reviews=list_reviews(ledger, changeset_id),
                changeset_digest=changeset["digest"],
                head_sha=changeset.get("head_sha"),
                author_owner_ids=changeset["author_owner_ids"],
            )
            if not quorum.satisfied:
                raise ValidationError("review quorum is not satisfied: " + "; ".join(quorum.reasons))
            if quorum.required_humans and not changeset.get("head_sha"):
                raise ValidationError("human approvals require a bound Git head SHA")

            if changeset["status"] == "merge_ready":
                transition_changeset(
                    ledger,
                    changeset_id,
                    "merged_apply_pending",
                    expected_status="merge_ready",
                )
                changeset = get_changeset(ledger, changeset_id)
            transition_changeset(
                ledger,
                changeset_id,
                "applying",
                expected_status=changeset["status"],
            )

            aliases: dict[str, str] = {}
            results = [
                apply_operation(
                    ledger,
                    operation,
                    changeset_id=changeset_id,
                    changeset_digest_value=changeset["digest"],
                    aliases=aliases,
                )
                for operation in operations
            ]
            if changeset["metadata"].get("legacy_proposal_id"):
                from forecasting.change_control.compatibility import sync_legacy_proposal

                forecast_id = next(
                    (item.get("forecast_id") for item in results if item.get("forecast_id")),
                    None,
                )
                sync_legacy_proposal(
                    ledger,
                    changeset_id,
                    decision="approved",
                    reviewed_by="changeset-apply",
                    forecast_snapshot_id=forecast_id,
                )
            next_revision = int(revision["revision"]) + 1
            ledger_digest = content_digest(
                {
                    "revision": next_revision,
                    "parent_digest": revision["digest"],
                    "changeset_digest": changeset["digest"],
                }
            )
            result = {
                "changeset_id": changeset_id,
                "changeset_digest": changeset["digest"],
                "revision": next_revision,
                "ledger_digest": ledger_digest,
                "objects": results,
            }
            now = utc_now_iso()
            conn.execute(
                """INSERT INTO ledger_revisions
                   (revision, parent_revision, changeset_id, digest, applied_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (next_revision, revision["revision"], changeset_id, ledger_digest, now),
            )
            metadata = {**changeset["metadata"], "apply_result": result}
            conn.execute(
                """UPDATE ledger_changesets
                   SET status = 'applied', applied_revision = ?, applied_at = ?,
                       metadata = ?, updated_at = ?
                   WHERE id = ? AND status = 'applying'""",
                (next_revision, now, json.dumps(metadata, sort_keys=True), now, changeset_id),
            )
            conn.execute(
                """UPDATE ledger_apply_attempts
                   SET state = 'succeeded', finished_at = ? WHERE id = ?""",
                (now, attempt_id),
            )
            for item in results:
                for key, value in item.items():
                    if key.endswith("_id") and key != "operation_id":
                        conn.execute(
                            """INSERT OR IGNORE INTO ledger_artifact_links
                               (changeset_id, artifact_type, artifact_ref, digest, created_at)
                               VALUES (?, ?, ?, ?, ?)""",
                            (changeset_id, key, str(value), content_digest(value), now),
                        )
        return result
    except BaseException as exc:
        _failed(ledger, changeset_id, attempt_id, exc)
        raise


__all__ = ["apply_changeset", "apply_operation", "validate_preconditions"]
