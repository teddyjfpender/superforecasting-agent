"""Slice S4 — recurrence by default.

Idempotent cron install, config-gated default routines, deterministic self-refresh
in the cadence sweep, deadline-aware cadence escalation, `freshen`, and cron health.
"""

from __future__ import annotations

import argparse
from datetime import timedelta

import pytest

from forecasting import scheduler
from forecasting.cli import register_cli
from forecasting.ledger import ForecastLedger
from forecasting.models import timestamp_to_datetime, utc_now_iso


# ── fixtures / helpers ───────────────────────────────────────────────────────


@pytest.fixture
def cron_env(tmp_path, monkeypatch):
    """Isolated cron store rooted at a temp HERMES_HOME (the autouse conftest
    fixture already repoints cron.jobs paths, but make it explicit + robust)."""
    home = tmp_path / ".hermes"
    (home / "cron" / "output").mkdir(parents=True)
    (home / "scripts").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))

    import cron.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "HERMES_DIR", home)
    monkeypatch.setattr(jobs_mod, "CRON_DIR", home / "cron")
    monkeypatch.setattr(jobs_mod, "JOBS_FILE", home / "cron" / "jobs.json")
    monkeypatch.setattr(jobs_mod, "OUTPUT_DIR", home / "cron" / "output")
    return home


def _ledger(tmp_path) -> ForecastLedger:
    ledger = ForecastLedger(db_path=str(tmp_path / "recurrence.db"))
    ledger.initialize_schema()
    return ledger


def _market_question(ledger, *, close_time=None):
    q = ledger.create_question(
        title="Will candidate R win the 2026 race?",
        resolution_criteria="Resolves yes if the Republican nominee is certified as the winner; otherwise no.",
        close_time=close_time,
    )
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.55,
        rationale="baseline ensemble",
        method="log_odds_pool",
        ensemble_components={
            "components": [
                {"name": "markets", "source": "manifold:race", "probability": 0.55, "weight": 3},
                {"name": "base_rate", "probability": 0.40, "weight": 2},
            ]
        },
        require_panel=False,
    )
    ledger.add_watched_source(scope_type="question", scope_ref=q.id, source="race", source_type="manifold")
    return q


def _market_fetcher(probability):
    def fetch(specs):
        return [
            {
                "source_type": spec["source_type"],
                "source": spec["source"],
                "success": True,
                "payloads": [
                    {
                        "source_or_note": f"{spec['source_type']} {spec['source']}",
                        "source_type": f"adapter:{spec['source_type']}",
                        "claim": "market reading",
                        "summary": "",
                        "metadata": {
                            "adapter": spec["source_type"],
                            "source": spec["source"],
                            "adapter_item": {"probability": probability},
                        },
                    }
                ],
                "error": None,
            }
            for spec in specs
        ]

    return fetch


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forecast-test")
    sub = parser.add_subparsers(dest="command")
    register_cli(sub)
    return parser


# ── 1. idempotent install / remove ───────────────────────────────────────────


def test_double_install_does_not_stack_duplicates(cron_env):
    from cron.jobs import list_jobs

    scheduler.install_forecast_cron(schedule="0 8 * * *")
    scheduler.install_forecast_cron(schedule="0 8 * * *")
    self_checks = [j for j in list_jobs(include_disabled=True) if j.get("script") == scheduler.FORECAST_CRON_SCRIPT]
    assert len(self_checks) == 1


def test_remove_forecast_cron(cron_env):
    from cron.jobs import list_jobs

    scheduler.install_forecast_cron(schedule="0 8 * * *")
    removed = scheduler.remove_forecast_cron()
    assert removed == 1
    assert not [j for j in list_jobs(include_disabled=True) if j.get("script") == scheduler.FORECAST_CRON_SCRIPT]


def test_default_schedule_is_nightly_not_hourly(cron_env):
    job = scheduler.install_forecast_cron()
    assert job["schedule"]["display"] == "0 8 * * *"


def test_install_cron_with_different_name_preserves_auto_routine(cron_env):
    """The idempotent re-arm matches on NAME only, so installing a differently-named
    cron never nukes the feature-rich auto-installed 'Forecast self-check' routine
    (which shares the script)."""
    from cron.jobs import list_jobs

    scheduler.ensure_default_routines()  # auto-install the feature-rich nightly routine
    assert scheduler.default_routines_installed() is True

    scheduler.install_forecast_cron(name="My custom check")  # different name

    scripts = [j for j in list_jobs(include_disabled=True) if j.get("script") == scheduler.FORECAST_CRON_SCRIPT]
    names = {j.get("name") for j in scripts}
    assert scheduler.FORECAST_CRON_NAME in names  # the auto routine survived
    assert "My custom check" in names
    assert len(scripts) == 2


def test_remove_forecast_cron_match_script_is_opt_in(cron_env):
    """Name-only removal spares a differently-named self-check job; match_script=True
    sweeps any self-check-script job regardless of name (the uninstall/teardown path)."""
    from cron.jobs import list_jobs

    scheduler.install_forecast_cron(name=scheduler.FORECAST_CRON_NAME)
    scheduler.install_forecast_cron(name="My custom check")

    # name-only removal leaves the differently-named job in place
    removed = scheduler.remove_forecast_cron(name=scheduler.FORECAST_CRON_NAME)
    assert removed == 1
    assert [j for j in list_jobs(include_disabled=True) if j.get("script") == scheduler.FORECAST_CRON_SCRIPT]

    # match_script=True sweeps the remaining self-check-script job even by a wrong name
    removed2 = scheduler.remove_forecast_cron(name="does-not-match", match_script=True)
    assert removed2 == 1
    assert not [j for j in list_jobs(include_disabled=True) if j.get("script") == scheduler.FORECAST_CRON_SCRIPT]


def test_cli_install_cron_defaults_to_full_feature_flags(tmp_path, cron_env):
    """A bare `forecast schedule install-cron` must be as capable as the auto-installed
    nightly routine — every learning flag ON by default (not a feature-poor downgrade)."""
    from hermes_constants import get_hermes_home

    parser = _parser()
    args = parser.parse_args(["forecast", "--db", str(tmp_path / "recurrence.db"), "schedule", "install-cron"])
    args._forecast_handler(args)

    script = (get_hermes_home() / "scripts" / scheduler.FORECAST_CRON_SCRIPT).read_text()
    assert "--auto-score" in script
    assert "--auto-postmortem" in script
    assert "--thesis-aggregate" in script
    assert "--synthesize-lessons" in script


def test_cli_install_cron_no_flags_opt_out(tmp_path, cron_env):
    """The `--no-*` opt-outs turn individual features off without touching the rest."""
    from hermes_constants import get_hermes_home

    parser = _parser()
    args = parser.parse_args([
        "forecast", "--db", str(tmp_path / "recurrence.db"), "schedule", "install-cron",
        "--no-synthesize-lessons", "--no-thesis-aggregate",
    ])
    args._forecast_handler(args)

    script = (get_hermes_home() / "scripts" / scheduler.FORECAST_CRON_SCRIPT).read_text()
    assert "--auto-score" in script          # still on by default
    assert "--auto-postmortem" in script     # still on by default
    assert "--synthesize-lessons" not in script
    assert "--thesis-aggregate" not in script


# ── 2. ensure_default_routines: config gate + silent-when-present ─────────────


def test_ensure_default_routines_installs_once(cron_env):
    first = scheduler.ensure_default_routines()
    assert first["installed"] and first["created"]
    second = scheduler.ensure_default_routines()
    assert second["installed"] and not second["created"]  # silent, no duplicate


def test_ensure_default_routines_respects_config_flag(cron_env, monkeypatch):
    monkeypatch.setattr(scheduler, "_auto_install_enabled", lambda: False)
    result = scheduler.ensure_default_routines()
    assert not result["installed"] and not result["created"]
    assert scheduler.default_routines_installed() is False
    # force=True bypasses the config gate (explicit operator intent).
    forced = scheduler.ensure_default_routines(force=True)
    assert forced["installed"] and forced["created"]


def test_installed_routine_carries_learning_flags(cron_env):
    from hermes_constants import get_hermes_home

    scheduler.ensure_default_routines()
    script = (get_hermes_home() / "scripts" / scheduler.FORECAST_CRON_SCRIPT).read_text()
    assert "--auto-score" in script
    assert "--auto-postmortem" in script
    assert "--thesis-aggregate" in script
    assert "--synthesize-lessons" in script


# ── 3. deterministic refresh in the cadence sweep ────────────────────────────


def _schedule_due(ledger, qid, *, cadence="daily"):
    # Far-past next_run_at so the row is due under the sweep's real-clock `now`
    # (a fixed past `now` would stamp fresh evidence after its own cutoff).
    ledger.schedule_review(
        scope_type="question",
        scope_ref=qid,
        cadence=cadence,
        next_run_at="2020-01-01T00:00:00Z",
        trigger_reason="test_due",
    )


def test_due_sweep_refreshes_refreshable_question(tmp_path):
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)
    _schedule_due(ledger, q.id)
    before = len(ledger.list_snapshots(q.id))

    results = ledger.run_due_scheduled_reviews(refresh_fetcher=_market_fetcher(0.80))

    row = next(r for r in results if (r["review"] or {}).get("scope_ref") == q.id)
    assert row["refresh"] is not None
    assert row["refresh"]["status"] == "committed"
    assert row["refresh_error"] is None
    assert len(ledger.list_snapshots(q.id)) == before + 1  # a fresh snapshot landed


def test_due_sweep_records_refresh_error_but_continues(tmp_path):
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)
    _schedule_due(ledger, q.id)

    def boom(specs):
        raise RuntimeError("fetch down")

    results = ledger.run_due_scheduled_reviews(refresh_fetcher=boom)
    row = next(r for r in results if (r["review"] or {}).get("scope_ref") == q.id)
    assert row["refresh"] is None
    assert "fetch down" in (row["refresh_error"] or "")
    # The sweep still ran the self-check (alerts key present, cadence advanced).
    assert "alerts" in row


def test_due_sweep_skips_question_without_watched_sources(tmp_path):
    ledger = _ledger(tmp_path)
    q = ledger.create_question(
        title="Will the index close above 5000 by year end?",
        resolution_criteria="Resolves yes if the official close exceeds 5000; otherwise no.",
    )
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.5,
        rationale="prior",
        method="log_odds_pool",
        ensemble_components={"components": [{"name": "base_rate", "probability": 0.5, "weight": 1}]},
        require_panel=False,
    )
    _schedule_due(ledger, q.id)
    results = ledger.run_due_scheduled_reviews(refresh_fetcher=_market_fetcher(0.9))
    row = next(r for r in results if (r["review"] or {}).get("scope_ref") == q.id)
    assert row["refresh"] is None  # no watched sources -> skipped, no error
    assert row["refresh_error"] is None


# ── 4. freshen CLI ───────────────────────────────────────────────────────────


def test_freshen_sets_cadence_and_installs_cron(tmp_path, cron_env, capsys):
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)
    parser = _parser()
    args = parser.parse_args(["forecast", "--db", str(tmp_path / "recurrence.db"), "freshen", q.id, "--cadence", "daily"])
    args._forecast_handler(args)

    assert ledger.get_question(q.id).review_cadence == "daily"
    assert scheduler.default_routines_installed() is True
    out = capsys.readouterr().out
    assert "refreshes daily" in out
    assert "nightly self-check cron" in out


# ── 5. deadline-aware cadence escalation ─────────────────────────────────────


def test_deadline_clamp_escalates_within_seven_days(tmp_path):
    ledger = _ledger(tmp_path)
    now = "2026-07-01T00:00:00Z"
    close = "2026-07-04T00:00:00Z"  # 3 days out -> clamp weekly down to daily
    nxt = ledger._advance_cadence(now, "weekly", deadlines=[close])
    assert timestamp_to_datetime(nxt) == timestamp_to_datetime(now) + timedelta(days=1)


def test_deadline_clamp_escalates_within_48h(tmp_path):
    ledger = _ledger(tmp_path)
    now = "2026-07-01T00:00:00Z"
    close = "2026-07-02T06:00:00Z"  # 30h out -> clamp to twice-daily
    nxt = ledger._advance_cadence(now, "weekly", deadlines=[close])
    assert timestamp_to_datetime(nxt) == timestamp_to_datetime(now) + timedelta(hours=12)


def test_deadline_clamp_never_slows_a_fast_cadence(tmp_path):
    ledger = _ledger(tmp_path)
    now = "2026-07-01T00:00:00Z"
    close = "2026-07-03T00:00:00Z"  # 2 days out
    # An hourly base cadence is already faster than the daily clamp -> unchanged.
    nxt = ledger._advance_cadence(now, "hourly", deadlines=[close])
    assert timestamp_to_datetime(nxt) == timestamp_to_datetime(now) + timedelta(hours=1)


def test_deadline_clamp_ignores_far_deadline(tmp_path):
    ledger = _ledger(tmp_path)
    now = "2026-07-01T00:00:00Z"
    close = "2026-09-01T00:00:00Z"  # far away -> base weekly unchanged
    nxt = ledger._advance_cadence(now, "weekly", deadlines=[close])
    assert timestamp_to_datetime(nxt) == timestamp_to_datetime(now) + timedelta(days=7)


# ── 6. cron health visibility ────────────────────────────────────────────────


def test_cron_health_flags_errored_job(cron_env):
    from cron.jobs import update_job

    job = scheduler.install_forecast_cron(schedule="0 8 * * *")
    update_job(job["id"], {"last_status": "error", "last_error": "boom", "last_run_at": utc_now_iso()})
    health = scheduler.forecast_cron_health()
    assert health["installed"] == 1
    assert job["id"] in health["errored"]
    assert health["healthy"] is False


def test_cron_health_flags_missed_job(cron_env):
    from cron.jobs import update_job

    # An interval job whose last run is far older than 2x its cadence is "missed".
    job = scheduler.install_forecast_cron(schedule="every 1h")
    stale = (timestamp_to_datetime(utc_now_iso()) - timedelta(hours=10)).isoformat().replace("+00:00", "Z")
    update_job(job["id"], {"last_status": "ok", "last_run_at": stale})
    health = scheduler.forecast_cron_health()
    assert job["id"] in health["missed"]
    assert health["healthy"] is False


def test_cron_health_clean_when_fresh(cron_env):
    from cron.jobs import update_job

    job = scheduler.install_forecast_cron(schedule="every 1h")
    update_job(job["id"], {"last_status": "ok", "last_run_at": utc_now_iso()})
    health = scheduler.forecast_cron_health()
    assert health["errored"] == [] and health["missed"] == []
    assert health["healthy"] is True


def test_keep_fresh_tool_action(tmp_path, cron_env):
    import json as _json

    import tools.forecasting_tool as ft

    ledger = _ledger(tmp_path)
    q = _market_question(ledger)
    out = _json.loads(ft.forecast_ledger_tool({
        "db": str(tmp_path / "recurrence.db"),
        "action": "keep_fresh",
        "question_id": q.id,
        "cadence": "daily",
    }))
    assert out["success"] is True
    assert out["cadence"] == "daily"
    assert "refreshes daily" in out["message"]
    assert ledger.get_question(q.id).review_cadence == "daily"
    assert scheduler.default_routines_installed() is True


def test_doctor_report_includes_cron_health(tmp_path, cron_env, capsys):
    import json as _json

    _ledger(tmp_path)  # initialize the ledger db the doctor reads
    scheduler.install_forecast_cron(schedule="0 8 * * *")
    parser = _parser()
    args = parser.parse_args([
        "forecast", "--db", str(tmp_path / "recurrence.db"), "doctor", "--json",
        "--min-questions", "0", "--min-structured-source-questions", "0",
        "--min-scores", "0", "--min-postmortems", "0",
        "--min-scheduled-reviews", "0", "--min-scheduled-review-runs", "0",
    ])
    args._forecast_handler(args)
    report = _json.loads(capsys.readouterr().out)
    assert "cron_health" in report
    assert report["cron_health"]["installed"] == 1
