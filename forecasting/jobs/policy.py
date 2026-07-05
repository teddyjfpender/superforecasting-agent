"""The APPROVAL / SPEND POLICY MATRIX (architecture review item #9).

Every background job on the detached-job runtime (Arc B) has a PROVENANCE — the
:class:`RunMode` it was started under — and touches one or more :class:`ActionClass`
side effects (ledger writes, network, LLM spend, subprocess). This module maps each
``(run_mode, action_class)`` pair to a :class:`Decision`:

* ``auto``  — proceed, and LOG the decision into the JobRecord (auditability);
* ``ask``   — PARK the job (status ``awaiting_approval``), surface an approval
              request on ``alert_events`` (the same seam resolution PROPOSALS ride),
              and resume only once an operator approves;
* ``never`` — REFUSE with a teaching error that NAMES the config key to loosen it.

**The defaults FORMALIZE CURRENT PRACTICE.** Today the runtime just runs every job:
an interactive Desk run, a headless ``cycle`` sweep, and a ``cron`` tick all spend
and write without a prompt — the only brakes are the EXISTING hard caps (the
reforecast batch cap, ``cap_preset_by_calls`` on a quorum, the warning-automode
paid-tier budget + interval gate). So every default here is ``auto`` — the matrix is
**behaviour-neutral until an operator tightens a key**. Two ``(mode, class)`` pairs
are additionally flagged BOUNDED: ``cycle``/``cron`` LLM spend proceeds ``auto`` but
under one of those existing caps, and the audit log records that a cap governs it.
The matrix's value today is (a) making the current posture explicit and auditable,
and (b) giving an operator ONE place — the ``policy.<mode>.<class>`` config keys — to
tighten a specific mode (e.g. ``policy.cron.llm_spend = ask`` to require sign-off
before any unattended LLM spend) without touching code.

Config overlay: each cell is overridable by an appconfig key
``FORECAST_POLICY_<MODE>_<CLASS>`` (the ENV/registry spelling of the logical
``policy.<mode>.<class>`` knob) whose value is ``auto`` | ``ask`` | ``never``. An
unset key (the default) uses the matrix default; an unrecognised value falls SAFE to
the matrix default (a typo never crashes a running job).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger("forecasting.jobs.policy")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ActionClass(str, Enum):
    """The side-effect classes a job body authorizes at its real action points."""

    LEDGER_WRITES = "ledger_writes"
    NETWORK = "network"
    LLM_SPEND = "llm_spend"
    SUBPROCESS = "subprocess"


class Decision(str, Enum):
    AUTO = "auto"
    ASK = "ask"
    NEVER = "never"


class RunMode(str, Enum):
    """A job's provenance — how it was started, which selects the default row."""

    INTERACTIVE = "interactive"  # a human is at the Desk / CLI; work runs at once
    CYCLE = "cycle"  # the headless `forecast cycle --agent` autonomous sweep
    CRON = "cron"  # an unattended scheduled tick


# ── the default matrix ────────────────────────────────────────────────────────
#
# EVERY cell is AUTO — the matrix formalizes today's behaviour (the runtime runs
# every job regardless of mode; the only brakes are the existing hard caps). This
# is the ZERO-BEHAVIOUR-CHANGE contract: nothing parks or refuses until an operator
# sets a `policy.<mode>.<class>` key. Justification per mode:
#   * interactive — a human is present and watching; every side effect is auto, as
#     it is today (the Desk `A`/`T`/`U`/quorum actions all just go).
#   * cycle — the autonomous reforecast sweep; ledger_writes/network/subprocess are
#     auto (it re-pools + researches unattended today), and llm_spend is auto but
#     BOUNDED by the reforecast batch cap + `cap_preset_by_calls` on any auto-quorum.
#   * cron — an unattended tick; subprocess (detach), ledger_writes (the deterministic
#     re-pool + backup commit) and network are auto exactly as today, and llm_spend is
#     auto but BOUNDED by the warning-automode paid-tier budget + min-interval gate.
#     "ask-or-bounded": the honest default is BOUNDED (the caps already gate it); an
#     operator TIGHTENS to `ask` when they want explicit sign-off on unattended spend.
_A = Decision.AUTO
DEFAULTS: dict[RunMode, dict[ActionClass, Decision]] = {
    RunMode.INTERACTIVE: {c: _A for c in ActionClass},
    RunMode.CYCLE: {c: _A for c in ActionClass},
    RunMode.CRON: {c: _A for c in ActionClass},
}

# The `(mode, class)` cells that proceed AUTO but under an EXISTING hard cap. The
# decision stays `auto`; `authorize` stamps `bounded=True` on the audit entry so the
# JobRecord records that a cap — not an unbounded grant — governs the spend.
_BOUNDED: frozenset[tuple[RunMode, ActionClass]] = frozenset(
    {
        (RunMode.CYCLE, ActionClass.LLM_SPEND),
        (RunMode.CRON, ActionClass.LLM_SPEND),
    }
)

# triggered_by tokens that pin a non-interactive provenance when a job spec carries
# no explicit `run_mode`. Anything unrecognised defaults to INTERACTIVE — the
# all-auto row, so an unknown provenance can never accidentally park or refuse.
_TRIGGER_MODES: dict[str, RunMode] = {
    "cron": RunMode.CRON,
    "cron_backup": RunMode.CRON,
    "backup_cron": RunMode.CRON,
    "cycle": RunMode.CYCLE,
    "cycle_agent": RunMode.CYCLE,
    "autonomous": RunMode.CYCLE,
}


class PolicyRefused(Exception):
    """A ``never`` cell refused an action. The message NAMES the config key to loosen
    it — a teaching error, not a bare crash."""

    def __init__(self, run_mode: RunMode, action_class: ActionClass) -> None:
        self.run_mode = run_mode
        self.action_class = action_class
        key = config_key(run_mode, action_class)
        super().__init__(
            f"policy refused {action_class.value} in {run_mode.value} mode "
            f"(policy.{run_mode.value}.{action_class.value} = never). "
            f"Loosen it by setting {key}=auto (or =ask to require approval) in the "
            f"config.yaml env: section or the environment, then re-run the job."
        )


class ApprovalRequired(Exception):
    """An ``ask`` cell parked the job pending operator approval. Carries the
    surfaced alert id so the resume path can ack it."""

    def __init__(self, *, job_id: str, action_class: str, detail: str, alert_id: str | None) -> None:
        self.job_id = job_id
        self.action_class = action_class
        self.detail = detail
        self.alert_id = alert_id
        super().__init__(f"approval required: {action_class} for job {job_id}")


def config_key(run_mode: RunMode, action_class: ActionClass) -> str:
    """The appconfig/ENV name for the logical ``policy.<mode>.<class>`` cell."""

    return f"FORECAST_POLICY_{run_mode.value.upper()}_{action_class.value.upper()}"


def _coerce_action_class(value: Any) -> ActionClass:
    if isinstance(value, ActionClass):
        return value
    return ActionClass(str(value).strip().lower())


def _coerce_run_mode(value: Any) -> RunMode | None:
    try:
        return RunMode(str(value).strip().lower())
    except ValueError:
        return None


def resolve_run_mode(spec: dict[str, Any] | None) -> RunMode:
    """A job's provenance: an explicit ``spec['run_mode']`` wins; else derive it from
    ``spec['triggered_by']``; else INTERACTIVE (the all-auto row — the honest default,
    since a human enqueue is the common case and never changes behaviour)."""

    spec = spec or {}
    explicit = spec.get("run_mode")
    if explicit:
        mode = _coerce_run_mode(explicit)
        if mode is not None:
            return mode
    trig = str(spec.get("triggered_by") or "").strip().lower()
    return _TRIGGER_MODES.get(trig, RunMode.INTERACTIVE)


def is_bounded(run_mode: RunMode, action_class: ActionClass) -> bool:
    return (run_mode, action_class) in _BOUNDED


def resolve_decision(run_mode: RunMode, action_class: ActionClass) -> Decision:
    """The effective decision for a cell: the matrix default overlaid by the
    ``FORECAST_POLICY_<MODE>_<CLASS>`` appconfig key. An unrecognised override value
    falls SAFE to the default (logged once) so a config typo never crashes a job."""

    default = DEFAULTS[run_mode][action_class]
    try:
        from forecasting import appconfig

        raw = appconfig.get_str(config_key(run_mode, action_class), None)
    except Exception:  # noqa: BLE001 — config is best-effort; default governs
        return default
    if not raw or not str(raw).strip():
        return default
    token = str(raw).strip().lower()
    try:
        return Decision(token)
    except ValueError:
        logger.warning(
            "policy: %s=%r is not one of auto|ask|never; using the default %s",
            config_key(run_mode, action_class),
            raw,
            default.value,
        )
        return default


def resolve_policy(run_mode: RunMode) -> dict[str, Any]:
    """The full resolved matrix for a run — logged onto the JobRecord once (the
    ``resolved_policy`` audit field) so a status poll shows exactly what governed it."""

    return {
        "run_mode": run_mode.value,
        "decisions": {c.value: resolve_decision(run_mode, c).value for c in ActionClass},
        "bounded": [c.value for c in ActionClass if is_bounded(run_mode, c)],
    }


# ── the 'ask' surfacing + resume (rides alert_events like resolution proposals) ──


def _ledger_for(record: Any) -> Any:
    """A ForecastLedger bound to the job's ``spec['db']`` (lazily imported — the
    ledger is a heavy leaf and this keeps the jobs package import-cycle free)."""

    from forecasting.ledger import ForecastLedger

    return ForecastLedger((record.spec or {}).get("db"))


def request_approval(record: Any, action_class: ActionClass, detail: str) -> str | None:
    """Surface an approval request for a parked action on ``alert_events`` — the SAME
    seam a resolution PROPOSAL rides (there is no metadata column, so job_id/class/detail
    ride ``scope_ref`` + ``reason`` + ``recommended_action`` exactly as the proposal's
    outcome rides its reason). Deduped against an already-open request for the same
    ``(job, class)``. Returns the alert id (or None if the ledger is unavailable —
    surfacing is best-effort; the park still happens)."""

    run_mode = resolve_run_mode(record.spec or {})
    try:
        ledger = _ledger_for(record)
        alert = ledger.enqueue_approval_request(
            job_id=record.job_id,
            job_type=record.type,
            action_class=action_class.value,
            detail=detail,
            run_mode=run_mode.value,
        )
        return alert.id
    except Exception:  # noqa: BLE001 — never let a surfacing hiccup break the park
        logger.warning("policy: could not surface approval request for %s", record.job_id, exc_info=True)
        return None


def approve_job(
    job_id: str,
    *,
    action_class: Any | None = None,
    store: Any = None,
    resume: bool = True,
) -> Any:
    """Approve a parked job and (by default) RESUME it — the job-runtime analogue of
    confirming a resolution proposal through the existing resolve flow.

    Records a GRANT for the approved class(es) on the record (so the resumed run's
    ``authorize`` proceeds instead of re-parking), acks the surfaced alert(s), flips
    the status back to ``queued``, and re-runs the job to completion. A job parked
    BEFORE any spend (every type authorizes at the top, before its loop) re-runs from
    scratch with nothing wasted. Raises if the job is not awaiting approval."""

    from forecasting.jobs.store import JobStore

    store = store or JobStore()
    record = store.read(job_id)
    if record.status != "awaiting_approval":
        raise ValueError(
            f"job {job_id} is not awaiting approval (status={record.status})"
        )

    parked_classes = [
        d.get("class")
        for d in (record.policy_decisions or [])
        if d.get("outcome") == "awaiting_approval" and d.get("class")
    ]
    grants = set(record.policy_grants or [])
    if action_class is not None:
        grants.add(_coerce_action_class(action_class).value)
    else:
        grants.update(parked_classes)
    record.policy_grants = sorted(grants)

    _ack_approval_alerts(record)
    record.status = "queued"
    record.error = None
    store.write(record)

    if not resume:
        return record

    from forecasting.jobs import runtime

    return runtime.run(job_id, store=store)


def _ack_approval_alerts(record: Any) -> None:
    """Acknowledge the open approval alert(s) this parked run surfaced (best-effort)."""

    alert_ids = [
        d.get("alert_id")
        for d in (record.policy_decisions or [])
        if d.get("outcome") == "awaiting_approval" and d.get("alert_id")
    ]
    if not alert_ids:
        return
    try:
        ledger = _ledger_for(record)
    except Exception:  # noqa: BLE001
        return
    for alert_id in alert_ids:
        try:
            ledger.acknowledge_alert(alert_id)
        except Exception:  # noqa: BLE001 — a stale/gone alert never blocks the resume
            continue


# ── the COLLAB share/accept governed classes + counterparty allowlist (M3) ────
#
# Design pillar 5 ("Sharing is a governed action class"): cross-instance exchange
# grows its OWN axis on top of the (run_mode × action_class) matrix — a DIRECTION
# (share = this desk hands an artifact to peers; accept = this desk imports a
# peer's) × an ARTIFACT CLASS ({evidence, forecast, lesson, document}) → the same
# auto|ask|never Decision. It is a SEPARATE axis (not a RunMode row) because the
# governing question is "what artifact, to/from whom", not "how was the job
# started"; the outbound M2 share still rides the NETWORK cell of the base matrix
# (posting is a network side effect), while this axis governs WHICH artifact may
# cross the org boundary and — the hard gate — WHETHER the counterparty is
# authorised at all.
#
# The counterparty ALLOWLIST is closed by default: an instance_id absent from the
# allowlist is REFUSED before any auto/ask cell is consulted (an empty allowlist
# accepts NO one). Names are spoofable, so authorisation is by stable instance_id,
# never display name (the plan's "authorization" note).


class ShareClass(str, Enum):
    """The artifact classes that can cross the org boundary."""

    EVIDENCE = "evidence"
    FORECAST = "forecast"
    LESSON = "lesson"
    DOCUMENT = "document"


class ShareDirection(str, Enum):
    """The direction a governed collab action runs."""

    SHARE = "share"    # outbound — hand an artifact to peers
    ACCEPT = "accept"  # inbound — import a peer's artifact


# Per the plan (pillar 5 / "Trust, safety"): share.evidence auto, share.forecast
# auto, share.lesson ask; accept.* MIRROR share. ``document`` defaults to ``ask``
# (an opaque artifact the operator should eyeball before it lands). Every default
# here is behaviour-visible ONLY once an operator adds a counterparty to the
# allowlist — with an empty allowlist nothing is accepted regardless of the cell.
_COLLAB_SHARE_DEFAULTS: dict[ShareClass, Decision] = {
    ShareClass.EVIDENCE: Decision.AUTO,
    ShareClass.FORECAST: Decision.AUTO,
    ShareClass.LESSON: Decision.ASK,
    ShareClass.DOCUMENT: Decision.ASK,
}
COLLAB_DEFAULTS: dict[ShareDirection, dict[ShareClass, Decision]] = {
    ShareDirection.SHARE: dict(_COLLAB_SHARE_DEFAULTS),
    ShareDirection.ACCEPT: dict(_COLLAB_SHARE_DEFAULTS),  # accept mirrors share
}

# The sfp/1 message kind → the governed ShareClass it imports under.
_COLLAB_CLASS_BY_KIND: dict[str, ShareClass] = {
    "forecast.card": ShareClass.FORECAST,
    "evidence.share": ShareClass.EVIDENCE,
    "lesson.share": ShareClass.LESSON,
}

# The appconfig key holding the comma-separated counterparty allowlist (stable
# instance_ids). Empty / unset ⇒ closed (accept none). Lives here so the ONE
# authorisation gate names the ONE knob that opens it.
COLLAB_ALLOWLIST_CONFIG_KEY = "COLLAB_ALLOWED_INSTANCES"


class CollabPolicyRefused(Exception):
    """A collab share/accept was refused because the counterparty is not on the
    allowlist. A teaching error that NAMES the knob to authorise it — the closed-
    by-default org-boundary gate, distinct from a ``never`` cell (:class:`PolicyRefused`)."""

    def __init__(
        self,
        *,
        instance_id: str | None,
        direction: ShareDirection,
        share_class: ShareClass,
        reason: str = "not on the counterparty allowlist",
    ) -> None:
        self.instance_id = instance_id
        self.direction = direction
        self.share_class = share_class
        self.reason = reason
        super().__init__(
            f"collab {direction.value}.{share_class.value} refused: counterparty "
            f"{instance_id!r} {reason} — authorise it by adding its instance_id to "
            f"{COLLAB_ALLOWLIST_CONFIG_KEY} (comma-separated) in the config.yaml env: "
            f"section or the environment (empty = accept none)."
        )


def collab_config_key(direction: ShareDirection, share_class: ShareClass) -> str:
    """The appconfig/ENV name for a ``policy.<direction>.<class>`` collab cell."""

    return f"FORECAST_POLICY_{direction.value.upper()}_{share_class.value.upper()}"


def share_class_for_kind(kind: str) -> ShareClass | None:
    """Map an sfp/1 message ``kind`` to its governed :class:`ShareClass` (or None
    for a kind that is not a governed artifact import, e.g. ``ack``/``request``)."""

    return _COLLAB_CLASS_BY_KIND.get(str(kind or "").strip().lower())


def resolve_collab_decision(direction: ShareDirection, share_class: ShareClass) -> Decision:
    """The effective auto|ask|never for a collab cell: the matrix default overlaid
    by ``FORECAST_POLICY_<DIRECTION>_<CLASS>``. An unrecognised override falls SAFE
    to the default (logged once) — a config typo never crashes an import."""

    default = COLLAB_DEFAULTS[direction][share_class]
    try:
        from forecasting import appconfig

        raw = appconfig.get_str(collab_config_key(direction, share_class), None)
    except Exception:  # noqa: BLE001 — config is best-effort; default governs
        return default
    if not raw or not str(raw).strip():
        return default
    token = str(raw).strip().lower()
    try:
        return Decision(token)
    except ValueError:
        logger.warning(
            "policy: %s=%r is not one of auto|ask|never; using the default %s",
            collab_config_key(direction, share_class),
            raw,
            default.value,
        )
        return default


def resolve_collab_action(
    direction: ShareDirection,
    share_class: ShareClass,
    *,
    counterparty_instance_id: str | None,
    allowlist: Any,
) -> Decision:
    """The governed decision for a collab share/accept.

    REFUSES (raises :class:`CollabPolicyRefused`) when *counterparty_instance_id*
    is not in *allowlist* — authorisation is the FIRST gate and it is closed by
    default (an empty allowlist accepts no one). Only an authorised counterparty
    reaches the auto|ask|never cell (:func:`resolve_collab_decision`)."""

    allowed = {str(x).strip() for x in (allowlist or ()) if str(x).strip()}
    ident = str(counterparty_instance_id or "").strip()
    if not ident or ident not in allowed:
        raise CollabPolicyRefused(
            instance_id=counterparty_instance_id, direction=direction, share_class=share_class
        )
    return resolve_collab_decision(direction, share_class)


def resolve_collab_policy(direction: ShareDirection) -> dict[str, Any]:
    """The full resolved collab matrix for a direction — for logging onto the
    collab event trail so a decision is auditable exactly like a JobRecord's."""

    return {
        "direction": direction.value,
        "decisions": {
            c.value: resolve_collab_decision(direction, c).value for c in ShareClass
        },
    }


__all__ = [
    "ActionClass",
    "Decision",
    "RunMode",
    "DEFAULTS",
    "PolicyRefused",
    "ApprovalRequired",
    "config_key",
    "resolve_run_mode",
    "resolve_decision",
    "resolve_policy",
    "is_bounded",
    "request_approval",
    "approve_job",
    # collab share/accept axis (M3)
    "ShareClass",
    "ShareDirection",
    "COLLAB_DEFAULTS",
    "COLLAB_ALLOWLIST_CONFIG_KEY",
    "CollabPolicyRefused",
    "collab_config_key",
    "share_class_for_kind",
    "resolve_collab_decision",
    "resolve_collab_action",
    "resolve_collab_policy",
]
