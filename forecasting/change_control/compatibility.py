"""Compatibility bridge for legacy forecast update proposals.

The adapter never calls the legacy approval method: generalized changeset apply
creates the sole forecast snapshot, then this module synchronizes only the old
row's review status and run reference.
"""

from __future__ import annotations

from typing import Any, Iterable

from forecasting.change_control.models import LedgerOperation
from forecasting.change_control.store import add_operation, create_changeset, get_changeset
from forecasting.models import ValidationError, utc_now_iso


def wrap_legacy_proposal(
    ledger: Any,
    proposal_id: str,
    *,
    workspace_id: str,
    author_owner_ids: Iterable[str],
    slack_thread_key: str | None = None,
) -> dict[str, Any]:
    """Create a changeset view of a pending proposal without changing it."""

    proposal = ledger.get_forecast_update_proposal(proposal_id)
    if proposal["status"] != "pending":
        raise ValidationError("only pending legacy proposals can be wrapped")
    prior = (
        ledger.get_snapshot(proposal["prior_forecast_id"])
        if proposal.get("prior_forecast_id")
        else ledger.get_current_snapshot(proposal["question_id"])
    )
    metadata = {
        "legacy_proposal_id": proposal_id,
        "legacy_adapter": "forecast_update_proposals/v1",
        "checks_passed": False,
    }
    changeset = create_changeset(
        ledger,
        workspace_id=workspace_id,
        author_owner_ids=author_owner_ids,
        affected_question_ids=[proposal["question_id"]],
        slack_thread_key=slack_thread_key,
        metadata=metadata,
    )
    operation = LedgerOperation(
        id=f"legacy_{proposal_id}",
        kind="forecast.update",
        target_ref=proposal["question_id"],
        preconditions={
            "current_forecast_id": proposal.get("prior_forecast_id"),
            "prior_probability": (
                None if prior is None else prior.probability_or_distribution
            ),
        },
        payload={
            "probability_or_distribution": proposal["proposed_probability_or_distribution"],
            "rationale": proposal["rationale"],
            "method": "autopilot",
            "evidence_refs": proposal["evidence_refs"],
            "source_snapshot_refs": proposal["source_snapshot_refs"],
            "model_run_refs": proposal["model_run_refs"],
            "assumption_refs": proposal["assumption_refs"],
            "reference_class_refs": proposal["reference_class_refs"],
            "metadata": {"autopilot_proposal_id": proposal_id},
            "style_autofix": True,
            "distribution_autofix": True,
            "require_citations": True,
        },
        provenance_refs=[value for value in (proposal.get("run_id"),) if value],
        author_attestation={"source": "legacy_autopilot", "proposal_id": proposal_id},
    )
    add_operation(ledger, changeset["id"], operation)
    return get_changeset(ledger, changeset["id"])


def sync_legacy_proposal(
    ledger: Any,
    changeset_id: str,
    *,
    decision: str,
    reviewed_by: str | None = None,
    forecast_snapshot_id: str | None = None,
) -> dict[str, Any] | None:
    """Synchronize a wrapped legacy row without creating a forecast snapshot."""

    if decision not in {"approved", "rejected"}:
        raise ValidationError("legacy synchronization decision must be approved or rejected")
    changeset = get_changeset(ledger, changeset_id)
    proposal_id = changeset["metadata"].get("legacy_proposal_id")
    if not proposal_id:
        return None
    proposal = ledger.get_forecast_update_proposal(proposal_id)
    if proposal["status"] == decision:
        return proposal
    if proposal["status"] != "pending":
        raise ValidationError(
            f"legacy proposal {proposal_id} is already {proposal['status']}, not pending"
        )
    if decision == "approved" and not forecast_snapshot_id:
        raise ValidationError("approved legacy synchronization requires forecast_snapshot_id")
    with ledger._connect() as conn:
        conn.execute(
            """UPDATE forecast_update_proposals
               SET status = ?, reviewed_at = ?, reviewed_by = ? WHERE id = ?""",
            (decision, utc_now_iso(), reviewed_by, proposal_id),
        )
        if decision == "approved" and proposal.get("run_id"):
            conn.execute(
                "UPDATE autopilot_runs SET forecast_snapshot_id = ? WHERE id = ?",
                (forecast_snapshot_id, proposal["run_id"]),
            )
    return ledger.get_forecast_update_proposal(proposal_id)


__all__ = ["sync_legacy_proposal", "wrap_legacy_proposal"]
