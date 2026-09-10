"""The cron sweep closes the calibration learning loop on a cadence.

``run_due_reviews`` runs ``synthesize_bias_lessons`` when forced, never when
disabled, and — in the default auto mode — exactly when the sweep minted new
score records or postmortems (i.e. when resolutions accrued and the bias
measurement has fresh data).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from forecasting import cron_runner
from forecasting.ledger import ForecastLedger


@pytest.fixture()
def synth_spy(monkeypatch):
    calls: list[dict] = []

    def fake_synthesize(self, **kwargs):
        calls.append(kwargs)
        return [
            {
                "scope_type": "domain",
                "scope_ref": "macro",
                "action": {"written": True, "lesson_status": "active", "retired": []},
            }
        ]

    monkeypatch.setattr(ForecastLedger, "synthesize_bias_lessons", fake_synthesize)
    return calls


def _alert(reason):
    return SimpleNamespace(
        reason=reason,
        severity="info",
        scope_ref="fq_x",
        recommended_action="noted",
    )


def _fake_reviews(monkeypatch, alerts):
    monkeypatch.setattr(
        ForecastLedger,
        "run_due_scheduled_reviews",
        lambda self, **kw: ([{"run": {"id": "sr_1"}, "alerts": alerts}] if alerts else []),
    )


def test_forced_synthesis_runs_even_without_events(tmp_path, synth_spy, monkeypatch):
    _fake_reviews(monkeypatch, [])
    text = cron_runner.run_due_reviews(db_path=tmp_path / "f.db", synthesize_lessons=True)
    assert len(synth_spy) == 1
    assert "Lesson synthesis" in text
    assert "macro: lesson active" in text


def test_disabled_synthesis_never_runs(tmp_path, synth_spy, monkeypatch):
    _fake_reviews(monkeypatch, [_alert("score_created:sc_1")])
    cron_runner.run_due_reviews(db_path=tmp_path / "f.db", synthesize_lessons=False)
    assert synth_spy == []


def test_auto_mode_skips_when_no_resolutions_accrued(tmp_path, synth_spy, monkeypatch):
    _fake_reviews(monkeypatch, [_alert("review_due:fq_x")])
    cron_runner.run_due_reviews(db_path=tmp_path / "f.db")
    assert synth_spy == []


def test_auto_mode_runs_on_new_scores(tmp_path, synth_spy, monkeypatch):
    _fake_reviews(monkeypatch, [_alert("score_created:sc_1")])
    text = cron_runner.run_due_reviews(db_path=tmp_path / "f.db")
    assert len(synth_spy) == 1
    assert "Lesson synthesis" in text


def test_auto_mode_runs_on_new_postmortems(tmp_path, synth_spy, monkeypatch):
    _fake_reviews(monkeypatch, [_alert("postmortem_created:pm_1")])
    cron_runner.run_due_reviews(db_path=tmp_path / "f.db")
    assert len(synth_spy) == 1


def test_synthesis_error_never_breaks_the_sweep(tmp_path, monkeypatch):
    _fake_reviews(monkeypatch, [])

    def boom(self, **kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(ForecastLedger, "synthesize_bias_lessons", boom)
    text = cron_runner.run_due_reviews(db_path=tmp_path / "f.db", synthesize_lessons=True)
    assert "Lesson synthesis" in text
    assert "ERROR" in text


def test_cli_flags_wire_through(tmp_path, synth_spy, monkeypatch, capsys):
    _fake_reviews(monkeypatch, [])
    monkeypatch.setenv("FORECAST_LEDGER_DB", str(tmp_path / "f.db"))
    assert cron_runner.main(["--synthesize-lessons"]) == 0
    assert len(synth_spy) == 1
    assert cron_runner.main(["--no-synthesize-lessons"]) == 0
    assert len(synth_spy) == 1  # unchanged


def test_obsidian_sync_phase_publishes_to_vault(tmp_path, monkeypatch):
    _fake_reviews(monkeypatch, [])
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    text = cron_runner.run_due_reviews(db_path=tmp_path / "f.db", obsidian_sync=True)
    assert "Obsidian sync" in text
    assert "published" in text
    assert (vault / "Forecasting" / "Forecast Desk Index.md").is_file()


def test_obsidian_sync_phase_degrades_without_vault(tmp_path, monkeypatch):
    _fake_reviews(monkeypatch, [])
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "missing"))
    text = cron_runner.run_due_reviews(db_path=tmp_path / "f.db", obsidian_sync=True)
    assert "skipped: no vault" in text


def test_obsidian_sync_off_by_default(tmp_path, monkeypatch):
    _fake_reviews(monkeypatch, [])
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    text = cron_runner.run_due_reviews(db_path=tmp_path / "f.db")
    assert "Obsidian sync" not in text
    assert not (vault / "Forecasting").exists()


def test_finalization_triggers_synthesis_without_review_alerts(tmp_path, synth_spy, monkeypatch):
    _fake_reviews(monkeypatch, [])
    monkeypatch.setattr('forecasting.lifecycle.run_lifecycle', lambda *a, **k: [{'status': 'completed'}])
    text = cron_runner.run_due_reviews(db_path=tmp_path / 'f.db')
    assert len(synth_spy) == 1
    assert 'Resolution finalization' in text
    assert 'Lesson synthesis' in text
