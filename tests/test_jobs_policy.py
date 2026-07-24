"""The APPROVAL / SPEND POLICY MATRIX (architecture review item #9).

Pins the whole contract of ``forecasting/jobs/policy.py`` + the ``ctx.authorize``
enforcement seam:

* resolution PRECEDENCE — the all-auto matrix default overlaid by the
  ``FORECAST_POLICY_<MODE>_<CLASS>`` appconfig key (a bad value falls SAFE);
* run_mode THREADING — explicit spec wins, else ``triggered_by``, else interactive;
* ``authorize`` mechanics — auto proceeds + LOGS, never REFUSES naming the key, ask
  PARKS (status ``awaiting_approval``) + surfaces an ``alert_events`` request that
  DEDUPES, and an operator approval RESUMES the parked job to completion;
* per-type CALL POINTS — refresh/reforecast/task/quorum authorize (proven by the
  ``never`` early-refusal), while backup + free-tier warnings authorize NOTHING;
* the ZERO-BEHAVIOUR-CHANGE contract — under the default matrix a real type runs
  byte-identically (the refresh tally is untouched, one auto decision logged).
"""

from __future__ import annotations

import pytest

from forecasting.jobs import policy, runtime
from forecasting.jobs.model import JobRecord
from forecasting.jobs.policy import ActionClass, Decision, RunMode
from forecasting.jobs.store import JobStore
from forecasting.jobs.types import JobType, register, resolve


# ── a probe job type: authorizes one class from spec, marks that it SPENT ──────


def _probe_execute(spec, ctx):
    ctx.authorize(spec.get("authorize_class", "llm_spend"), spec.get("detail", "probe action"))
    return {"spent": True}


register(JobType(name="policy_probe", execute=_probe_execute, min_interval_s=0.0))


@pytest.fixture(autouse=True)
def _fresh_appconfig():
    """Reset the appconfig singleton to read LIVE os.environ (so monkeypatch.setenv of
    a FORECAST_POLICY_* key is honoured regardless of any other test's configure())."""
    from forecasting import appconfig

    appconfig.configure(environ=None, config_file=None)
    yield
    appconfig.configure(environ=None, config_file=None)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("FORECAST_LEDGER_DB", raising=False)
    return tmp_path


def _start(store, type_name, spec):
    job_id = store.new_id()
    store.write(JobRecord(job_id=job_id, type=type_name, spec=spec))
    return job_id


def _open_approval_alerts(job_id=None):
    from forecasting.ledger import ForecastLedger

    out = []
    for a in ForecastLedger().list_alerts(unresolved_only=True):
        if a.scope_type == "job" and a.reason.startswith("approval required:"):
            if job_id is None or a.scope_ref == job_id:
                out.append(a)
    return out


# ── resolution precedence ─────────────────────────────────────────────────────


def test_every_default_cell_is_auto():
    """The matrix FORMALIZES current practice: every cell is auto (zero behaviour
    change until an operator tightens a key)."""
    for mode in RunMode:
        for cls in ActionClass:
            assert policy.DEFAULTS[mode][cls] is Decision.AUTO
            assert policy.resolve_decision(mode, cls) is Decision.AUTO


def test_config_overlay_overrides_a_single_cell(monkeypatch):
    monkeypatch.setenv("FORECAST_POLICY_CRON_LLM_SPEND", "ask")
    assert policy.resolve_decision(RunMode.CRON, ActionClass.LLM_SPEND) is Decision.ASK
    # Only that ONE cell moves — other modes/classes stay auto.
    assert policy.resolve_decision(RunMode.INTERACTIVE, ActionClass.LLM_SPEND) is Decision.AUTO
    assert policy.resolve_decision(RunMode.CRON, ActionClass.LEDGER_WRITES) is Decision.AUTO


def test_never_and_case_insensitive_override(monkeypatch):
    monkeypatch.setenv("FORECAST_POLICY_INTERACTIVE_LEDGER_WRITES", "NEVER")
    assert policy.resolve_decision(RunMode.INTERACTIVE, ActionClass.LEDGER_WRITES) is Decision.NEVER


def test_bad_override_value_falls_safe_to_default(monkeypatch):
    monkeypatch.setenv("FORECAST_POLICY_CRON_LLM_SPEND", "banana")
    # A typo never crashes — it uses the (auto) matrix default.
    assert policy.resolve_decision(RunMode.CRON, ActionClass.LLM_SPEND) is Decision.AUTO


def test_config_key_spelling():
    assert policy.config_key(RunMode.CRON, ActionClass.LLM_SPEND) == "FORECAST_POLICY_CRON_LLM_SPEND"


def test_bounded_marks_cycle_and_cron_llm_spend():
    assert policy.is_bounded(RunMode.CYCLE, ActionClass.LLM_SPEND)
    assert policy.is_bounded(RunMode.CRON, ActionClass.LLM_SPEND)
    assert not policy.is_bounded(RunMode.INTERACTIVE, ActionClass.LLM_SPEND)
    assert not policy.is_bounded(RunMode.CRON, ActionClass.LEDGER_WRITES)


# ── run_mode threading ────────────────────────────────────────────────────────


def test_run_mode_explicit_spec_wins():
    assert policy.resolve_run_mode({"run_mode": "cron"}) is RunMode.CRON
    assert policy.resolve_run_mode({"run_mode": "CYCLE"}) is RunMode.CYCLE


def test_run_mode_from_triggered_by():
    assert policy.resolve_run_mode({"triggered_by": "cron"}) is RunMode.CRON
    assert policy.resolve_run_mode({"triggered_by": "backup_cron"}) is RunMode.CRON
    assert policy.resolve_run_mode({"triggered_by": "autonomous"}) is RunMode.CYCLE


def test_run_mode_defaults_to_interactive():
    assert policy.resolve_run_mode({}) is RunMode.INTERACTIVE
    assert policy.resolve_run_mode({"triggered_by": "desk_mass_agent"}) is RunMode.INTERACTIVE
    assert policy.resolve_run_mode({"run_mode": "garbage"}) is RunMode.INTERACTIVE


def test_run_mode_threads_into_the_resolved_policy_log(home):
    store = JobStore(home=home)
    job_id = _start(store, "policy_probe", {"triggered_by": "cron"})
    record = runtime.run(job_id, store=store)
    assert record.status == "done"
    assert record.resolved_policy["run_mode"] == "cron"
    assert record.policy_decisions[-1]["run_mode"] == "cron"
    # cron.llm_spend is bounded — the audit entry records that a cap governs the spend.
    assert record.policy_decisions[-1]["bounded"] is True


# ── authorize: auto proceeds + logs ───────────────────────────────────────────


def test_auto_proceeds_and_logs_into_the_record(home):
    store = JobStore(home=home)
    job_id = _start(store, "policy_probe", {"authorize_class": "llm_spend", "detail": "d"})
    record = runtime.run(job_id, store=store)

    assert record.status == "done"
    assert record.result == {"spent": True}
    # resolved_policy stamped once (the all-auto interactive row).
    assert record.resolved_policy["run_mode"] == "interactive"
    assert record.resolved_policy["decisions"] == {c.value: "auto" for c in ActionClass}
    # one decision logged, honestly.
    assert len(record.policy_decisions) == 1
    entry = record.policy_decisions[0]
    assert entry["class"] == "llm_spend"
    assert entry["detail"] == "d"
    assert entry["decision"] == "auto"
    assert entry["outcome"] == "auto"
    assert "at" in entry


# ── authorize: never refuses, naming the key ──────────────────────────────────


def test_never_refuses_with_a_teaching_error_naming_the_key(home, monkeypatch):
    monkeypatch.setenv("FORECAST_POLICY_INTERACTIVE_LLM_SPEND", "never")
    store = JobStore(home=home)
    job_id = _start(store, "policy_probe", {"authorize_class": "llm_spend"})
    record = runtime.run(job_id, store=store)

    assert record.status == "error"
    # The teaching error NAMES the config key + the logical knob.
    assert "FORECAST_POLICY_INTERACTIVE_LLM_SPEND" in record.error
    assert "policy.interactive.llm_spend = never" in record.error
    # No spend happened — execute never returned its result.
    assert record.result is None
    assert record.policy_decisions[-1]["outcome"] == "refused"


# ── authorize: ask parks + surfaces + resumes ─────────────────────────────────


def test_ask_parks_the_job_and_surfaces_an_alert(home, monkeypatch):
    monkeypatch.setenv("FORECAST_POLICY_INTERACTIVE_LLM_SPEND", "ask")
    store = JobStore(home=home)
    job_id = _start(store, "policy_probe", {"authorize_class": "llm_spend", "detail": "spendy"})

    completed, errored = [], []
    record = runtime.run(
        job_id, store=store, on_complete=completed.append, on_error=errored.append
    )

    # PARKED — neither completed nor errored.
    assert record.status == "awaiting_approval"
    assert record.result is None
    assert completed == [] and errored == []

    # It parked BEFORE spending (execute never returned).
    persisted = store.read(job_id)
    assert persisted.status == "awaiting_approval"

    # A single approval request surfaced on alert_events, riding scope_ref/reason.
    alerts = _open_approval_alerts(job_id)
    assert len(alerts) == 1
    assert alerts[0].reason == "approval required: llm_spend for policy_probe job " + job_id
    assert "spendy" in alerts[0].recommended_action
    assert "FORECAST_POLICY_INTERACTIVE_LLM_SPEND=auto" in alerts[0].recommended_action
    # the decision log carries the alert id for the resume path.
    assert persisted.policy_decisions[-1]["alert_id"] == alerts[0].id


def test_ask_alert_dedupes_on_a_re_park(home, monkeypatch):
    monkeypatch.setenv("FORECAST_POLICY_INTERACTIVE_LLM_SPEND", "ask")
    store = JobStore(home=home)
    job_id = _start(store, "policy_probe", {"authorize_class": "llm_spend"})

    runtime.run(job_id, store=store)  # park #1
    runtime.run(job_id, store=store)  # re-run → parks again, but must NOT stack a 2nd alert

    assert len(_open_approval_alerts(job_id)) == 1


def test_approval_resumes_the_parked_job_to_completion(home, monkeypatch):
    monkeypatch.setenv("FORECAST_POLICY_INTERACTIVE_LLM_SPEND", "ask")
    store = JobStore(home=home)
    job_id = _start(store, "policy_probe", {"authorize_class": "llm_spend"})

    parked = runtime.run(job_id, store=store)
    assert parked.status == "awaiting_approval"

    # Approve → grants the class, acks the alert, re-runs to completion.
    resumed = policy.approve_job(job_id, store=store)
    assert resumed.status == "done"
    assert resumed.result == {"spent": True}
    assert "llm_spend" in resumed.policy_grants
    # The surfaced approval alert was acknowledged (dropped from the open backlog).
    assert _open_approval_alerts(job_id) == []
    # The resumed authorize logged a granted decision.
    assert resumed.policy_decisions[-1].get("granted") is True


def test_approve_rejects_a_job_not_awaiting_approval(home):
    store = JobStore(home=home)
    job_id = _start(store, "policy_probe", {})
    runtime.run(job_id, store=store)  # runs to done under the auto default
    with pytest.raises(ValueError, match="not awaiting approval"):
        policy.approve_job(job_id, store=store)


# ── per-type CALL POINTS (proven by the `never` early-refusal) ────────────────


def _refused_key(record):
    return record.status == "error" and "FORECAST_POLICY_" in (record.error or "")


def test_refresh_authorizes_ledger_writes(home, monkeypatch):
    monkeypatch.setenv("FORECAST_POLICY_INTERACTIVE_LEDGER_WRITES", "never")
    store = JobStore(home=home)
    job_id = _start(store, "refresh", {"question_ids": ["fq_a"]})
    record = runtime.run(job_id, store=store)
    assert _refused_key(record)
    assert "LEDGER_WRITES" in record.error
    assert record.policy_decisions[-1]["class"] == "ledger_writes"


def test_reforecast_authorizes_llm_spend(home, monkeypatch):
    monkeypatch.setenv("FORECAST_POLICY_INTERACTIVE_LLM_SPEND", "never")
    store = JobStore(home=home)
    job_id = _start(store, "reforecast", {"question_ids": ["fq_a"]})
    record = runtime.run(job_id, store=store)
    assert _refused_key(record)
    assert "LLM_SPEND" in record.error


def test_task_authorizes_llm_spend(home, monkeypatch):
    monkeypatch.setenv("FORECAST_POLICY_INTERACTIVE_LLM_SPEND", "never")
    store = JobStore(home=home)
    job_id = _start(store, "task", {"instruction": "fix them", "question_ids": ["fq_a"]})
    record = runtime.run(job_id, store=store)
    assert _refused_key(record)
    assert "LLM_SPEND" in record.error


def test_quorum_authorizes_llm_spend(home, monkeypatch):
    monkeypatch.setenv("FORECAST_POLICY_INTERACTIVE_LLM_SPEND", "never")
    store = JobStore(home=home)
    job_id = _start(store, "quorum", {"question_id": "fq_a"})
    record = runtime.run(job_id, store=store)
    # Refused at the authorize BEFORE the panel is resolved (no real question needed).
    assert _refused_key(record)
    assert "LLM_SPEND" in record.error


def test_backup_authorizes_nothing(home, monkeypatch):
    # Even with every cell set to never, backup runs — it authorizes NO class.
    for cls in ("LEDGER_WRITES", "LLM_SPEND", "NETWORK", "SUBPROCESS"):
        monkeypatch.setenv(f"FORECAST_POLICY_INTERACTIVE_{cls}", "never")

    from forecasting.ledger import ForecastLedger

    monkeypatch.setattr(
        ForecastLedger, "backup",
        lambda self, dest, **k: {"path": "/x.db", "bytes": 1, "created_at": "t", "retention": {}},
        raising=True,
    )
    monkeypatch.setattr(
        ForecastLedger, "integrity_check",
        lambda self: {"ok": True, "violations": [], "counts": {}},
        raising=True,
    )
    store = JobStore(home=home)
    job_id = _start(store, "backup", {})
    record = runtime.run(job_id, store=store)
    assert record.status == "done"
    assert record.policy_decisions == []
    assert record.resolved_policy is None  # never authorized → no matrix stamped


def test_free_tier_warnings_authorizes_nothing(home, monkeypatch):
    for cls in ("LEDGER_WRITES", "LLM_SPEND", "NETWORK", "SUBPROCESS"):
        monkeypatch.setenv(f"FORECAST_POLICY_INTERACTIVE_{cls}", "never")
    store = JobStore(home=home)
    job_id = _start(store, "warnings", {"dry_run": True})
    record = runtime.run(job_id, store=store)
    # The free-tier sweep runs unimpeded (no paid marker → no llm_spend authorize).
    assert record.status == "done"
    assert record.policy_decisions == []


# ── zero-behaviour-change: a real type is byte-identical under the auto default ─


def test_refresh_under_auto_default_is_byte_identical(home, monkeypatch):
    """The refresh tally + outcomes are untouched by the (auto) matrix — the only
    addition is ONE logged ledger_writes/auto decision."""
    from forecasting.ledger import ForecastLedger

    def fake_refresh(self, qid, **kwargs):
        if qid == "fq_a":
            return {"status": "committed", "prior_probability": 0.4, "proposed_probability": 0.55}
        return {"status": "no_change", "message": "no new readings"}

    monkeypatch.setattr(ForecastLedger, "refresh_forecast", fake_refresh, raising=True)
    store = JobStore(home=home)
    job_id = _start(store, "refresh", {"question_ids": ["fq_a", "fq_b"]})
    record = runtime.run(job_id, store=store)

    assert record.status == "done"
    assert record.result["tally"] == {
        "refreshed": 1,
        "unchanged": 1,
        "no_sources": 0,
        "needs_estimation": 0,
        "error": 0,
    }
    # Exactly one authorize call, auto, at the batch's real action point.
    assert len(record.policy_decisions) == 1
    assert record.policy_decisions[0]["class"] == "ledger_writes"
    assert record.policy_decisions[0]["decision"] == "auto"
