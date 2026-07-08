"""Measurement-honesty slice: cohort scoreboard separation, artifact quarantine,
CRPS backfill idempotency, and continuous-miss postmortem stubs.

The headline discipline under test: no surface may report a POOLED all-artifact
Brier as a skill claim. Score aggregates report BY COHORT — the tiny live
calibration-eligible stratum kept apart from the market-visible baselines
(backtest / imported_baseline / market_nightly) — with a SEPARATE continuous
(CRPS / log) scorecard, and the pooled number retained only as an explicitly
labelled ledger-wide diagnostic.
"""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace


def _ledger(tmp_path):
    return ForecastLedger(tmp_path / "honesty.db")


def _binary_score(
    ledger,
    *,
    title: str,
    probability: float,
    outcome: str,
    origin: str = "live",
    calibration_eligible: bool = True,
    domain: str | None = None,
):
    """Create a resolved+scored binary question and return its score row."""
    question = ledger.create_question(
        title=title,
        resolution_criteria="Resolves YES if the stated event occurs by the deadline per the official source, else NO.",
        outcome_space=OutcomeSpace(type="binary", choices=["yes", "no"]),
        domain=domain,
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=probability,
        rationale="Binary forecast.",
        forecast_origin=origin,
        calibration_eligible=calibration_eligible,
    )
    ledger.resolve_question(question_id=question.id, outcome=outcome)
    return question, ledger.get_current_score(question.id)


def _dist_payload(*, median, lo50, hi50, lo90, hi90):
    """A fully renderable predictive distribution (central + ordered quantiles),
    mirroring the live snapshot shape so the output-structure hook passes."""
    return {
        "median": median,
        "mean": median,
        "sd": (hi90 - lo90) / 3.29,
        "interval_50_low": lo50,
        "interval_50_high": hi50,
        "interval_90_low": lo90,
        "interval_90_high": hi90,
        "q05": lo90,
        "q25": lo50,
        "q50": median,
        "q75": hi50,
        "q95": hi90,
    }


def _distribution_miss(
    ledger,
    *,
    title: str,
    payload: dict,
    outcome: str,
    origin: str = "live",
):
    question = ledger.create_question(
        title=title,
        resolution_criteria="Resolved to the published value.",
        outcome_space=OutcomeSpace(type="distribution", units="units"),
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=payload,
        rationale="Distribution forecast.",
        forecast_origin=origin,
    )
    ledger.resolve_question(question_id=question.id, outcome=outcome)
    return question, ledger.get_current_score(question.id)


# ── 1. cohort separation math ────────────────────────────────────────────────


def test_cohort_scoreboard_separates_never_pools(tmp_path):
    ledger = _ledger(tmp_path)
    # Live calibration-eligible binaries (the ONLY skill-claim stratum).
    _binary_score(ledger, title="live A", probability=0.9, outcome="yes", domain="politics")  # brier 0.01
    _binary_score(ledger, title="live B", probability=0.7, outcome="no", domain="macro")      # brier 0.49
    # A market-visible backtest baseline — must never merge into the live number.
    _binary_score(ledger, title="bt A", probability=0.2, outcome="yes",
                  origin="backtest", calibration_eligible=False)  # brier 0.64
    # An imported baseline.
    _binary_score(ledger, title="imp A", probability=0.5, outcome="no",
                  origin="imported_baseline", calibration_eligible=False)  # brier 0.25
    # A live continuous miss — CRPS, never a Brier.
    _distribution_miss(
        ledger,
        title="cont A",
        payload=_dist_payload(median=57.0, lo50=53.0, hi50=61.0, lo90=45.0, hi90=67.0),
        outcome="81",
    )

    board = ledger.cohort_scoreboard()
    cohorts = board["cohorts"]

    live = cohorts["live_calibration_eligible"]
    assert live["n_brier"] == 2
    assert live["mean_brier"] == pytest.approx((0.01 + 0.49) / 2)
    assert set(live["domains"]) == {"politics", "macro"}

    assert cohorts["backtest"]["mean_brier"] == pytest.approx(0.64)
    assert cohorts["imported_baseline"]["mean_brier"] == pytest.approx(0.25)

    # The continuous class is a SEPARATE scorecard — no Brier, a CRPS mean.
    cont = board["continuous_scorecard"]
    assert cont["n"] == 1
    assert cont["mean_crps"] is not None and cont["mean_crps"] > 0

    # The pooled number survives ONLY as a labelled diagnostic (0.01+0.49+0.64+0.25)/4.
    pooled = board["pooled_diagnostic"]
    assert pooled["mean_brier"] == pytest.approx((0.01 + 0.49 + 0.64 + 0.25) / 4)
    assert "not a skill claim" in pooled["label"].lower()
    # And the live number is NOT the pooled number.
    assert live["mean_brier"] != pytest.approx(pooled["mean_brier"])


def test_cohort_scoreboard_empty_ledger_is_honest(tmp_path):
    board = _ledger(tmp_path).cohort_scoreboard()
    assert board["cohorts"]["live_calibration_eligible"]["mean_brier"] is None
    assert board["continuous_scorecard"]["mean_crps"] is None
    assert board["pooled_diagnostic"]["mean_brier"] is None


# ── 2. pathological-row classification ───────────────────────────────────────


def test_scores_audit_classifies_pathological_rows(tmp_path):
    ledger = _ledger(tmp_path)
    # Synthetic imported target-price row: baseline probability 0.0 resolves "yes"
    # → Brier 1.0, log at the clamp floor. An INGESTION ARTIFACT.
    _binary_score(
        ledger, title="yes Target Price: $2,093.88", probability=0.0, outcome="yes",
        origin="imported_baseline", calibration_eligible=False,
    )
    # A real live continuous miss with a tight band, so the Gaussian NLL tail
    # clears |log|>10 — a genuine large miss, NOT an artifact.
    _distribution_miss(
        ledger, title="M5.0+ earthquakes worldwide",
        payload=_dist_payload(median=57.0, lo50=55.0, hi50=59.0, lo90=52.0, hi90=62.0),
        outcome="81",
    )
    # A real live binary that was confidently wrong — NOT an artifact.
    _binary_score(ledger, title="Will X happen?", probability=0.02, outcome="yes")

    audit = ledger.scores_audit()
    by_reason = {row["question_id"]: row["reason"] for row in audit["rows"]}
    reasons = set(by_reason.values())
    assert "artifact_degenerate_import" in reasons
    assert "real_continuous_miss" in reasons
    # The confidently-wrong live binary (brier 0.9604) is flagged but NOT an artifact.
    assert audit["counts"]["artifact_degenerate_import"] == 1
    assert audit["counts"]["real_continuous_miss"] >= 1
    # Only the artifact is proposed for quarantine.
    assert len(audit["proposed_quarantine"]) == 1
    assert all(r["reason"] == "artifact_degenerate_import" for r in audit["proposed_quarantine"])


# ── 2b. artifact quarantine (gated dry-run → apply → idempotent) ─────────────


def test_quarantine_artifact_scores_dry_run_then_apply(tmp_path):
    ledger = _ledger(tmp_path)
    _binary_score(
        ledger, title="yes Target Price: $76,607.28", probability=0.0, outcome="yes",
        origin="imported_baseline", calibration_eligible=False, domain="markets",
    )
    _binary_score(
        ledger, title="imp clean", probability=0.4, outcome="no",
        origin="imported_baseline", calibration_eligible=False,
    )

    before = ledger.cohort_scoreboard()["cohorts"]["imported_baseline"]["mean_brier"]

    dry = ledger.quarantine_artifact_scores(dry_run=True)
    assert dry["dry_run"] is True
    assert dry["count"] == 1
    # Dry-run writes nothing.
    assert ledger.cohort_scoreboard()["cohorts"]["imported_baseline"]["mean_brier"] == pytest.approx(before)

    applied = ledger.quarantine_artifact_scores(dry_run=False)
    assert applied["count"] == 1
    after = ledger.cohort_scoreboard()
    # The degenerate 1.0 is gone from the imported cohort; only the clean 0.16 remains.
    assert after["cohorts"]["imported_baseline"]["mean_brier"] == pytest.approx(0.16)
    assert after["quarantined"]["n"] == 1
    assert after["quarantined"]["reasons"].get("artifact_degenerate_import") == 1

    # Idempotent: re-applying finds nothing new.
    assert ledger.quarantine_artifact_scores(dry_run=False)["count"] == 0


# ── 3. CRPS rescore idempotency ──────────────────────────────────────────────


def test_backfill_crps_idempotent(tmp_path):
    ledger = _ledger(tmp_path)
    question, score = _distribution_miss(
        ledger, title="WTI crude front-month close",
        payload=_dist_payload(median=79.5, lo50=73.0, hi50=86.0, lo90=60.0, hi90=112.0),
        outcome="69.5",
    )
    assert score.score_rule == "crps_discrete_cdf"
    crps_before = score.proper_score

    report = ledger.backfill_crps_scores(dry_run=True)
    detail = {d["question_id"]: d for d in report["details"]}
    # Already CRPS-scored → the backfill reports it unchanged, proposes no rewrite.
    assert detail[question.id]["action"] == "unchanged"
    assert report["counts"]["rescored"] == 0

    # A non-dry run leaves the existing CRPS score byte-identical.
    ledger.backfill_crps_scores(dry_run=False)
    assert ledger.get_current_score(question.id).proper_score == pytest.approx(crps_before)


# ── 4. continuous-miss postmortem stubs ──────────────────────────────────────


def test_continuous_miss_postmortem_stubs(tmp_path):
    ledger = _ledger(tmp_path)
    # Forecast central ~57 but outcome 81 → we forecast LOW.
    q_low, _ = _distribution_miss(
        ledger, title="M5.0+ earthquakes worldwide",
        payload=_dist_payload(median=57.0, lo50=53.0, hi50=61.0, lo90=45.0, hi90=67.0),
        outcome="81",
    )
    # Forecast central ~64000 but outcome 58557 → we forecast HIGH.
    q_high, _ = _distribution_miss(
        ledger, title="Bitcoin close",
        payload=_dist_payload(median=64000.0, lo50=59000.0, hi50=69000.0, lo90=50000.0, hi90=80500.0),
        outcome="58557.7",
    )

    dry = ledger.create_continuous_miss_postmortem_stubs(dry_run=True)
    props = {p["question_id"]: p for p in dry["proposed"]}
    assert props[q_low.id]["direction"] == "low"
    assert props[q_high.id]["direction"] == "high"
    assert dry["created"] == 0
    # Dry-run created no postmortems.
    assert ledger.list_postmortems(question_id=q_low.id) == []

    applied = ledger.create_continuous_miss_postmortem_stubs(dry_run=False)
    assert applied["created"] == 2
    pms = ledger.list_postmortems(question_id=q_low.id)
    assert len(pms) == 1
    pm = pms[0]
    # Direction + magnitude pre-filled; it is a STUB (a review item), never a
    # concluded lesson.
    assert "low" in pm["what_happened"].lower() or "low" in pm["summary"].lower()
    assert pm["lesson"] == ""
    # No calibration lesson was auto-created from a stub.
    assert ledger.list_calibration_lessons() == []

    # Idempotent: a second run skips questions that already have a postmortem.
    assert ledger.create_continuous_miss_postmortem_stubs(dry_run=False)["created"] == 0


# ── 5. payload / doctor conformance ──────────────────────────────────────────


def test_workspace_payload_carries_cohort_scoreboard(tmp_path):
    ledger = _ledger(tmp_path)
    _binary_score(ledger, title="live A", probability=0.9, outcome="yes", domain="politics")
    from forecasting.dashboard import build_workspace_payload

    payload = build_workspace_payload(ledger=ledger, include_related=False, include_lessons=False)
    board = payload["cohort_scoreboard"]
    assert "cohorts" in board and "continuous_scorecard" in board and "pooled_diagnostic" in board
    assert "not a skill claim" in board["pooled_diagnostic"]["label"].lower()


def test_scoreboard_cli_end_to_end(tmp_path, capsys):
    """The `forecast scoreboard` command group: board / audit / quarantine
    (dry-run → --apply) drive the same gated ledger surface end-to-end."""
    from forecasting.cli.core import main

    ledger = _ledger(tmp_path)
    db = str(tmp_path / "honesty.db")
    _binary_score(ledger, title="live A", probability=0.9, outcome="yes", domain="politics")
    _binary_score(
        ledger, title="yes Target Price: $2,093.88", probability=0.0, outcome="yes",
        origin="imported_baseline", calibration_eligible=False,
    )

    main(["--db", db, "scoreboard", "board"])
    board_out = capsys.readouterr().out
    assert "by cohort" in board_out and "NOT a skill claim" in board_out

    main(["--db", db, "scoreboard", "audit"])
    audit_out = capsys.readouterr().out
    assert "artifact_degenerate_import: 1" in audit_out

    main(["--db", db, "scoreboard", "quarantine"])  # dry-run
    assert "would quarantine 1" in capsys.readouterr().out

    main(["--db", db, "scoreboard", "quarantine", "--apply"])
    assert "quarantined 1" in capsys.readouterr().out
    # Applied → the artifact is out of the imported cohort and re-apply is a no-op.
    assert ForecastLedger(tmp_path / "honesty.db").cohort_scoreboard()["quarantined"]["n"] == 1
