"""The WIKI_PRUNE job type: the second brain's anti-rot pass on the runtime.

Runs :func:`plugins.obsidian.prune.build_prune_report` over the resolved vault
(lint + staleness + orphans + near-dupes + resolution-condensation candidates
+ ledger-truth contradictions + budgets) and surfaces the result as a PROPOSAL
on ``alert_events`` — the same seam resolution proposals ride, so the alerts
view and the doctor already show it.

**Dry-run is the default.** Pruning APPLIES (tombstones, never deletions) only
when the spec carries an explicit ``apply=true`` — an operator confirm on an
interactive run — and the apply is additionally authorized through the policy
matrix (``ctx.authorize(LEDGER_WRITES)``: the tombstone rewrite + the prune
alert ride the ledger-writes cell). A cron/cycle apply therefore obeys
``FORECAST_POLICY_<MODE>_LEDGER_WRITES``: ``ask`` parks the job on the standard
approval seam; ``auto`` is the policy-matrix grant.

The plugin import happens INSIDE ``execute`` (call time, not import time), so
the forecasting→plugins layer boundary holds for every consumer that merely
imports the jobs registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore
from forecasting.jobs.types import JobType, register

PROPOSAL_ALERT_REASON = "wiki_prune_proposal"


def validate_spec(spec: dict[str, Any]) -> None:
    """Validate the (all-optional) spec: ``vault``, ``db``, ``apply``,
    ``classes``, ``stale_days``, ``page_byte_budget``."""
    classes = spec.get("classes")
    if classes is not None:
        if not isinstance(classes, (list, tuple)) or not all(
            isinstance(c, str) for c in classes
        ):
            raise ValueError("classes must be a list of prune-class names")
        # Late import keeps the layer boundary at registry-import time.
        from plugins.obsidian.prune import APPLYABLE_CLASSES

        unknown = [c for c in classes if c not in APPLYABLE_CLASSES]
        if unknown:
            raise ValueError(
                f"classes {unknown} are not applyable; applyable: {list(APPLYABLE_CLASSES)}"
            )
    for field in ("stale_days", "page_byte_budget"):
        value = spec.get(field)
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field} must be an integer, got {value!r}") from None
        if parsed <= 0:
            raise ValueError(f"{field} must be > 0, got {parsed}")


def _resolve_vault(spec: dict[str, Any]) -> Path:
    from plugins.obsidian.vault import resolve_vault_path

    if spec.get("vault"):
        vault = Path(str(spec["vault"])).expanduser()
        if not vault.is_dir():
            raise ValueError(f"vault is not a directory: {vault}")
        return vault
    vault = resolve_vault_path()
    if vault is None:
        raise ValueError(
            "no vault: OBSIDIAN_VAULT_PATH points at a non-directory and the "
            "managed vault could not be created"
        )
    return vault


def execute(spec: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Scan → propose (alert) → optionally apply (policy-gated tombstones)."""
    from forecasting.ledger import ForecastLedger
    from plugins.obsidian.prune import (
        DEFAULT_APPLY_CLASSES,
        apply_prune,
        build_prune_report,
    )

    validate_spec(spec)
    vault = _resolve_vault(spec)
    apply_requested = bool(spec.get("apply"))
    total = 3 if apply_requested else 2

    if ctx.should_cancel():
        return {"cancelled": True, "vault": str(vault)}

    ledger = ForecastLedger(spec.get("db"))

    ctx.progress(phase="scan", done=0, total=total)
    report = build_prune_report(
        vault,
        ledger=ledger,
        stale_days=int(spec.get("stale_days") or 0) or 45,
        page_byte_budget=int(spec.get("page_byte_budget") or 0) or 16_000,
    )
    ctx.annotate(
        "prune_report",
        {"counts": report["counts"], "proposal_count": report["proposal_count"],
         "budget": report["budget"], "pages": report["pages"]},
    )

    ctx.progress(phase="propose", done=1, total=total)
    alert_id = None
    if report["proposal_count"] > 0 and not apply_requested:
        # Surface the proposal on alert_events (best-effort — the report is
        # the artifact; a surfacing hiccup never fails the job).
        try:
            counts_text = ", ".join(
                f"{k}={v}" for k, v in report["counts"].items() if v
            )
            alert = ledger.create_alert(
                severity="info",
                scope_type="global",
                scope_ref="vault",
                reason=PROPOSAL_ALERT_REASON,
                recommended_action=(
                    f"Wiki prune proposal ({counts_text}). Review the job result, "
                    "then confirm by re-running with apply=true "
                    "(tombstones + archive, never deletions)."
                ),
            )
            alert_id = alert.id
        except Exception:  # noqa: BLE001 — surfacing is best-effort
            alert_id = None

    applied = None
    if apply_requested:
        # The policy-matrix seam: operator confirm is the interactive default;
        # a cron/cycle apply obeys FORECAST_POLICY_<MODE>_LEDGER_WRITES.
        from forecasting.jobs.policy import ActionClass

        ctx.authorize(
            ActionClass.LEDGER_WRITES,
            "wiki prune apply: vault tombstones + archive rewrites",
        )
        classes = tuple(spec.get("classes") or DEFAULT_APPLY_CLASSES)
        ctx.progress(phase="apply", done=2, total=total)
        applied = apply_prune(vault, report, classes=classes)
        ctx.annotate("applied", {
            "tombstoned": len(applied["tombstoned"]),
            "skipped": len(applied["skipped"]),
            "classes": applied["classes"],
        })

    result = {
        "vault": str(vault),
        "dry_run": not apply_requested,
        "proposal_count": report["proposal_count"],
        "counts": report["counts"],
        "budget": report["budget"],
        "pages": report["pages"],
        "tombstones": report["tombstones"],
        "proposals": report["proposals"],
        "alert_id": alert_id,
        "applied": applied,
        "cancelled": False,
    }
    ctx.progress(phase="done", done=total, total=total)
    return result


# ── enqueue + thin read helpers (CLI / cron surface) ─────────────────────────


def start_job(spec: dict[str, Any], *, wait: bool = True) -> str:
    """Create a queued ``wiki_prune`` JobRecord and run it inline (a prune is
    seconds — the caller wants the proposal report synchronously)."""
    validate_spec(spec)
    store = JobStore()
    job_id = store.new_id()
    store.write(JobRecord(job_id=job_id, type="wiki_prune", spec=dict(spec)))
    if wait:
        from forecasting.jobs import runtime

        runtime.run(job_id, store=store)
    return job_id


def read_job(job_id: str) -> dict[str, Any]:
    return JobStore().read(job_id, include_legacy=False).to_dict()


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in JobStore().list(limit=max(limit * 4, 80), include_legacy=False):
        if record.type == "wiki_prune":
            rows.append(record.to_dict())
    return rows[:limit]


WIKI_PRUNE = JobType(
    name="wiki_prune",
    execute=execute,
    # Three phase-change events + terminal — a prune is seconds; every phase
    # change passes the coalescer regardless.
    min_interval_s=0.0,
    # Net-new capability: no legacy alias family, no LLM spend.
    alias_namespace=None,
    spend_class="free",
    validate_spec=validate_spec,
)

register(WIKI_PRUNE)

__all__ = [
    "WIKI_PRUNE",
    "PROPOSAL_ALERT_REASON",
    "execute",
    "validate_spec",
    "start_job",
    "read_job",
    "list_jobs",
]
