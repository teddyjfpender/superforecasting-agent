"""The WARNINGS job type: a background sweep of the open ``alert_events`` backlog.

``execute`` is a faithful lift of the gateway's old ``_run`` body — it wires
:func:`forecasting.cron_runner.run_warning_resolution` with ``ctx.progress`` as
the streaming sink and ``ctx.should_cancel`` as the cooperative-cancel hook. The
per-warning throttle that used to live inline in the gateway is GONE: the
coalescing is now structural (in :class:`~forecasting.jobs.context.JobContext`),
so the 1,300-event storm is impossible by construction.
"""

from __future__ import annotations

from typing import Any

from forecasting.jobs.types import JobType, register


def _execute(spec: dict[str, Any], ctx: Any) -> dict[str, Any]:
    from forecasting.cron_runner import run_warning_resolution

    # Arc-9 approval gate. The warnings job is FREE-TIER by contract (spend_class=free):
    # the current wiring runs the deterministic backlog sweep with NO agent runner, so
    # it authorizes nothing and stays byte-identical. The SEAM is here for a future
    # PAID warnings job (an injected LLM reforecast/evidence runner) — such a spec would
    # carry a paid marker, and only then does the LLM-spend cell govern it.
    if spec.get("paid") or spec.get("agent") or spec.get("reforecast_runner"):
        from forecasting.jobs.policy import ActionClass

        ctx.authorize(ActionClass.LLM_SPEND, "paid warning-automode resolution tier")

    limit = spec.get("limit")
    return run_warning_resolution(
        now=spec.get("now"),
        limit=int(limit) if limit is not None else None,
        reason=spec.get("reason") or None,
        scope=spec.get("scope") or None,
        # Per-tier bulk filter: `tier` + `kinds` are validated downstream by the
        # dispatcher's resolve_kind_filter (a bad name fails the job loudly).
        kinds=spec.get("kinds") or None,
        tier=spec.get("tier") or None,
        dry_run=bool(spec.get("dry_run", False)),
        progress=ctx.progress,
        should_cancel=ctx.should_cancel,
    )


WARNINGS = JobType(
    name="warnings",
    execute=_execute,
    # Matches the old inline throttle: ~8 events/s for the noisy 'alert' phase.
    min_interval_s=0.125,
    # The legacy event prefix the aliased RPCs still emit ALONGSIDE jobs.* — so
    # the alerts view keeps working unchanged.
    alias_namespace="forecast.warnings.automode",
    spend_class="free",
)

register(WARNINGS)

__all__ = ["WARNINGS"]
