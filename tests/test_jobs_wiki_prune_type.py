"""The WIKI_PRUNE job type end-to-end on the detached-job runtime: the second
brain's anti-rot pass — dry-run proposal (alert-surfaced) by default, tombstone
apply only on explicit confirm, policy-matrix-gated in unattended modes.

All state (JobStore + scratch ledger + scratch vault) lands under a pinned
per-test HERMES_HOME / tmp_path — never the operator's live home or vault.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forecasting.jobs import runtime
from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore
from forecasting.jobs.types import resolve
from forecasting.jobs.types import wiki_prune as wiki_prune_type
from forecasting.ledger import ForecastLedger


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("FORECAST_LEDGER_DB", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    return tmp_path


def _seed(home: Path) -> tuple[str, Path, str]:
    """A scratch ledger with one RESOLVED question + a synced scratch vault —
    the minimal setup that yields a resolution_condensation proposal."""
    db = home / "ledger.db"
    ledger = ForecastLedger(db)
    question = ledger.create_question(
        title="Will the bill pass committee before the August recess?",
        resolution_criteria="Resolves YES if the committee reports the bill before the recess date.",
        domain="policy",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.4,
        rationale="Base rate for stalled bills in an election year.",
        as_of="2026-07-01T00:00:00Z",
    )
    vault = home / "scratch-vault"
    vault.mkdir()
    from plugins.obsidian.wiki import sync_wiki

    sync_wiki(vault, db=str(db))
    ledger.resolve_question(question_id=question.id, outcome="yes")
    return str(db), vault, question.id


def _run(home: Path, spec: dict) -> JobRecord:
    store = JobStore(home=home)
    job_id = store.new_id()
    store.write(JobRecord(job_id=job_id, type="wiki_prune", spec=spec))
    return runtime.run(job_id, store=store)


# ── registration + validation ────────────────────────────────────────────────


def test_wiki_prune_type_is_registered():
    jt = resolve("wiki_prune")
    assert jt.name == "wiki_prune"
    assert jt.alias_namespace is None  # net-new capability, no legacy family
    assert jt.spend_class == "free"  # deterministic scan — no LLM spend
    assert jt.validate_spec is not None


def test_validate_spec_rejects_bad_input():
    with pytest.raises(ValueError):
        wiki_prune_type.validate_spec({"classes": "resolution_condensation"})
    with pytest.raises(ValueError):
        wiki_prune_type.validate_spec({"classes": ["stale"]})  # not applyable
    with pytest.raises(ValueError):
        wiki_prune_type.validate_spec({"stale_days": "soon"})
    with pytest.raises(ValueError):
        wiki_prune_type.validate_spec({"page_byte_budget": 0})
    wiki_prune_type.validate_spec({})  # all-optional spec
    wiki_prune_type.validate_spec(
        {"classes": ["resolution_condensation", "near_duplicates"], "stale_days": 30}
    )


# ── dry-run: propose, alert, mutate nothing ──────────────────────────────────


def test_dry_run_proposes_and_surfaces_alert_without_mutation(home):
    db, vault, question_id = _seed(home)
    from plugins.obsidian.wiki import is_tombstone_text

    record = _run(home, {"db": db, "vault": str(vault)})

    assert record.status == "done"
    result = record.result
    assert result["dry_run"] is True
    assert result["proposal_count"] >= 1
    rc = result["proposals"]["resolution_condensation"]
    assert any(p["question_id"] == question_id for p in rc)

    # the proposal rode alert_events (the same seam resolution proposals use)
    ledger = ForecastLedger(db)
    alerts = [
        a for a in ledger.list_alerts() if a.reason == wiki_prune_type.PROPOSAL_ALERT_REASON
    ]
    assert len(alerts) == 1
    assert result["alert_id"] == alerts[0].id
    assert "apply=true" in alerts[0].recommended_action

    # NOTHING was tombstoned on a dry run
    page = vault / rc[0]["path"]
    assert not is_tombstone_text(page.read_text())
    assert result["applied"] is None


# ── apply: operator confirm → tombstones + a logged policy decision ──────────


def test_apply_tombstones_and_logs_the_policy_decision(home):
    db, vault, _ = _seed(home)
    from plugins.obsidian.wiki import is_tombstone_text

    record = _run(home, {"db": db, "vault": str(vault), "apply": True})

    assert record.status == "done"
    result = record.result
    assert result["dry_run"] is False
    applied = result["applied"]
    assert len(applied["tombstoned"]) >= 1
    entry = applied["tombstoned"][0]
    assert is_tombstone_text((vault / entry["path"]).read_text())
    assert (vault / entry["archive"]).is_file()  # never a deletion

    # the apply was authorized through the policy matrix and AUDITED
    decisions = [d for d in record.policy_decisions if d["class"] == "ledger_writes"]
    assert decisions and decisions[0]["outcome"] == "auto"
    assert record.resolved_policy is not None


# ── unattended apply obeys the policy matrix (ask → park) ────────────────────


def test_cron_apply_parks_awaiting_approval_under_ask_policy(home, monkeypatch):
    db, vault, _ = _seed(home)
    monkeypatch.setenv("FORECAST_POLICY_CRON_LEDGER_WRITES", "ask")
    from plugins.obsidian.wiki import is_tombstone_text

    record = _run(
        home, {"db": db, "vault": str(vault), "apply": True, "run_mode": "cron"}
    )

    assert record.status == "awaiting_approval"
    parked = [
        d for d in record.policy_decisions if d["outcome"] == "awaiting_approval"
    ]
    assert parked and parked[0]["class"] == "ledger_writes"
    # nothing mutated while parked
    assert not any(
        is_tombstone_text(p.read_text()) for p in vault.rglob("*.md")
    )


# ── enqueue helpers ───────────────────────────────────────────────────────────


def test_start_job_runs_inline_and_read_back(home):
    db, vault, _ = _seed(home)
    job_id = wiki_prune_type.start_job({"db": db, "vault": str(vault)})
    row = wiki_prune_type.read_job(job_id)
    assert row["status"] == "done"
    assert row["result"]["dry_run"] is True
    assert any(r["job_id"] == job_id for r in wiki_prune_type.list_jobs())
