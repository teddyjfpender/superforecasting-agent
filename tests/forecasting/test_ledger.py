from __future__ import annotations

import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from forecasting import ForecastLedger
from forecasting.cron_runner import run_due_reviews
from forecasting.dashboard import build_dashboard_summary, render_dashboard_text
from forecasting.ensembles import bayesian_binary_update, weighted_binary_probability
from forecasting.models import OutcomeSpace, ValidationError
from forecasting.protocol import build_forecast_chat_system_prompt, build_protocol_messages
from forecasting.source_adapters import (
    ArxivPaper,
    BlueskyPost,
    BlsObservation,
    CensusRecord,
    CisaKevVulnerability,
    ClinicalTrialStudy,
    CoinGeckoMarketSnapshot,
    CourtListenerSearchResult,
    CrossrefWork,
    EiaObservation,
    FederalRegisterDocument,
    FiveThirtyEightPollObservation,
    FredObservation,
    GdeltArticle,
    HackerNewsItem,
    GitHubCommit,
    GitHubIssue,
    GitHubRelease,
    GitHubWorkflowRun,
    KalshiMarketImport,
    ManifoldMarketImport,
    MetaculusQuestionImport,
    NasaEonetEvent,
    NpmPackageVersion,
    NvdCve,
    NwsAlert,
    OpenFdaDrugApplication,
    OpenMeteoAirQualityForecast,
    OpenMeteoDailyForecast,
    OpenMeteoHistoricalWeatherObservation,
    OpenAlexWork,
    OwidObservation,
    PolymarketMarketImport,
    PubMedArticle,
    PypiRelease,
    RedditPost,
    ReliefWebReport,
    SecCompanyFact,
    SecFiling,
    SocrataRecord,
    StooqPriceObservation,
    TreasuryRecord,
    UsgsEarthquakeEvent,
    WikipediaPage,
    WikimediaPageviewObservation,
    WorldBankObservation,
    YahooFinancePriceObservation,
)


class _SnapshotHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b"<html><body>snapshot source</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002
        return


def _serve_snapshot_source():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SnapshotHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class _MutableSourceHandler(BaseHTTPRequestHandler):
    body = b"initial watched source"

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format, *args):  # noqa: A002
        return


def _serve_mutable_source():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MutableSourceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _watch_market_item(kind: str, probability: float):
    outcome_space = OutcomeSpace(type="binary")
    if kind == "manifold":
        return ManifoldMarketImport(
            market_id="m1",
            slug="market-slug",
            question="Will the market prior move?",
            description="A watched Manifold market.",
            url="https://manifold.markets/u/market-slug",
            outcome_space=outcome_space,
            probability=probability,
            distribution=None,
            close_time="2026-12-31T00:00:00Z",
            resolution_time=None,
            resolution=None,
            is_resolved=False,
            as_of="2026-05-01T00:00:00Z",
            raw={"probability": probability},
        )
    if kind == "metaculus":
        return MetaculusQuestionImport(
            question_id="12345",
            title="Will the crowd prior move?",
            description="A watched Metaculus question.",
            resolution_criteria_text="Resolved by the linked question.",
            url="https://www.metaculus.com/questions/12345/",
            outcome_space=outcome_space,
            probability=probability,
            distribution=None,
            close_time="2026-12-31T00:00:00Z",
            resolution_time=None,
            resolution=None,
            status="open",
            as_of="2026-05-01T00:00:00Z",
            raw={"probability": probability},
        )
    if kind == "polymarket":
        return PolymarketMarketImport(
            market_id="pm1",
            slug="poly-slug",
            question="Will the Polymarket prior move?",
            description="A watched Polymarket market.",
            url="https://polymarket.com/event/poly-slug",
            outcome_space=outcome_space,
            probability=probability,
            distribution=None,
            close_time="2026-12-31T00:00:00Z",
            resolution_time=None,
            as_of="2026-05-01T00:00:00Z",
            raw={"probability": probability},
        )
    if kind == "kalshi":
        return KalshiMarketImport(
            ticker="KXWATCH-26",
            event_ticker="KXWATCH",
            question="Will the Kalshi prior move?",
            description="A watched Kalshi market.",
            url="https://kalshi.com/markets/KXWATCH-26",
            outcome_space=outcome_space,
            probability=probability,
            close_time="2026-12-31T00:00:00Z",
            resolution_time=None,
            status="active",
            result=None,
            as_of="2026-05-01T00:00:00Z",
            raw={"probability": probability},
        )
    raise AssertionError(f"unknown market kind: {kind}")


def test_forecast_updates_are_append_only(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will the bill pass committee?",
        resolution_criteria="Resolved yes if the committee reports the bill by the stated date.",
        close_time="2026-06-15T00:00:00Z",
        domain="policy",
    )

    first = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.42,
        rationale="Initial base rate and weak inside-view support.",
        as_of="2026-05-01T00:00:00Z",
        confidence=0.55,
    )
    evidence = ledger.add_evidence(
        question_id=question.id,
        source_or_note="Cosponsor count increased.",
        available_at="2026-05-09T00:00:00Z",
    )
    second = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.58,
        rationale="New cosponsor evidence increases passage odds.",
        as_of="2026-05-10T00:00:00Z",
        evidence_refs=[evidence.id],
    )

    history = ledger.list_snapshots(question.id)
    current = ledger.get_current_snapshot(question.id)

    assert [snapshot.forecast_id for snapshot in history] == [first.forecast_id, second.forecast_id]
    assert current is not None
    assert current.forecast_id == second.forecast_id
    assert second.parent_forecast_id == first.forecast_id
    assert first.probability_or_distribution == 0.42


def test_shared_dashboard_summary_renders_active_forecast_book(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will shared forecast dashboard render?",
        resolution_criteria="Resolved yes if shared dashboard rendering works.",
        close_time="2026-06-01T00:00:00Z",
        next_review_at="2026-01-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.4,
        rationale="Initial dashboard render fixture.",
        as_of="2026-05-01T00:00:00Z",
        confidence=0.5,
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.55,
        rationale="Updated dashboard render fixture.",
        as_of="2026-05-02T00:00:00Z",
        confidence=0.7,
    )
    ledger.add_assumption(question_id=question.id, text="Dashboard render assumption")
    ledger.add_baseline_comparison(
        question_id=question.id,
        source="dashboard-market",
        baseline_type="market",
        probability_or_distribution=0.5,
        as_of="2026-01-02T00:00:00Z",
    )
    ledger.create_alert(
        severity="info",
        scope_type="question",
        scope_ref=question.id,
        reason="dashboard_render_fixture",
        recommended_action="Review dashboard render fixture.",
    )
    calibration_question = ledger.create_question(
        title="Will dashboard include calibration health?",
        resolution_criteria="Resolved yes if calibration health is summarized.",
        close_time="2026-02-01T00:00:00Z",
        domain="dashboard",
    )
    ledger.create_snapshot(
        question_id=calibration_question.id,
        probability_or_distribution=0.75,
        rationale="Calibration dashboard fixture.",
        as_of="2026-01-01T00:00:00Z",
        ensemble_components={
            "components": [
                {"name": "market", "probability": 0.8, "weight": 3},
                {"name": "base_rate", "probability": 0.6, "weight": 1},
            ]
        },
    )
    ledger.resolve_question(question_id=calibration_question.id, outcome="yes")
    ledger.create_postmortem(
        question_id=calibration_question.id,
        summary="Dashboard calibration resolved cleanly.",
        lesson="Dashboard forecasts should keep calibration health visible.",
        calibration_adjustment={"dashboard_confidence_cap": 0.05},
    )
    ledger.run_backtest_dataset(
        dataset="dashboard-fixture",
        cases=[
            {
                "title": "Will dashboard include backtest performance?",
                "resolution_criteria": "Resolved yes if backtest performance is summarized.",
                "as_of": "2026-01-01T00:00:00Z",
                "probability": 0.7,
                "outcome": "yes",
                "baselines": [
                    {"source": "fixture-crowd", "baseline_type": "crowd", "probability": 0.6}
                ],
            }
        ],
    )

    summary = build_dashboard_summary(ledger=ledger)
    text = render_dashboard_text(summary)

    assert summary["active_count"] == 1
    row = summary["questions"][0]
    assert row["probability"] == 0.55
    assert row["delta"] == pytest.approx(0.15)
    assert row["baseline_count"] == 1
    assert row["open_assumption_count"] == 1
    assert summary["open_assumption_count"] == 1
    assert summary["stale_assumption_count"] == 0
    assert row["open_alert_count"] == 1
    assert summary["review_queue_count"] == 1
    assert summary["review_queue"][0]["id"] == question.id
    assert summary["review_queue"][0]["close_time"] == "2026-06-01T00:00:00Z"
    assert "review_due" in summary["review_queue"][0]["reasons"]
    assert summary["review_queue"][0]["next_action"].startswith("forecast research")
    assert summary["alerts"][0]["scope_ref"] == question.id
    assert summary["alerts"][0]["reason"] == "dashboard_render_fixture"
    assert summary["alerts"][0]["recommended_action"] == "Review dashboard render fixture."
    assert summary["calibration"]["count"] == 1
    assert summary["calibration"]["mean_brier"] == pytest.approx(0.0625)
    assert summary["calibration"]["mean_sharpness"] == pytest.approx(0.5)
    type_rows = {
        row["question_type"]: row for row in summary["calibration"]["question_type_breakdown"]
    }
    assert type_rows["binary"]["mean_brier"] == pytest.approx(0.0625)
    component_rows = {
        row["name"]: row for row in summary["calibration"]["ensemble_component_contributions"]
    }
    assert component_rows["market"]["mean_contribution"] == pytest.approx(0.6)
    assert component_rows["base_rate"]["mean_contribution"] == pytest.approx(0.15)
    assert summary["learning"]["total_lessons"] == 1
    assert summary["learning"]["tentative_lessons"] == 1
    assert summary["learning"]["top_error_profiles"][0]["domain"] == "dashboard"
    assert summary["learning"]["top_error_profiles"][0]["mean_brier"] == pytest.approx(0.0625)
    assert summary["learning"]["recent_lessons"][0]["lesson"] == (
        "Dashboard forecasts should keep calibration health visible."
    )
    assert summary["recent_backtests"][0]["dataset"] == "dashboard-fixture"
    assert summary["recent_backtests"][0]["probability_sources"] == ["dataset"]
    assert summary["recent_backtests"][0]["agent_mean_brier"] == pytest.approx(0.09)
    assert summary["recent_backtests"][0]["best_baseline"] == "crowd:fixture-crowd"
    assert summary["recent_backtests"][0]["paired_agent_wins"] == 1
    assert summary["recent_backtests"][0]["paired_baseline_wins"] == 0
    assert summary["recent_backtests"][0]["paired_ties"] == 0
    assert summary["recent_backtests"][0]["claim_status"]["verdict"] == "benchmark_replay_only"
    assert summary["recent_backtests"][0]["claim_status"]["can_claim_live_superforecasting"] is False
    assert summary["evidence_status"]["verdict"] == "insufficient_live_evidence"
    assert summary["evidence_status"]["score_counts"]["live"] == 1
    assert summary["evidence_status"]["backtests"]["leakage_free_run_count"] == 1
    assert summary["evidence_status"]["backtests"]["positive_best_baseline_edge_run_count"] == 0
    assert "agent_protocol_scored_cases" in summary["evidence_status"]["gaps"]
    assert {
        item["requirement_id"]
        for item in summary["evidence_status"]["next_actions"]
    } >= {"live_scored_forecasts", "agent_protocol_scored_cases"}
    assert "Superforecasting Agent" in text
    assert "Will shared forecast dashboard render?" in text
    assert "assumptions: 1/0" in text
    assert "AsOf" in text
    assert "2026-05-02T00:00:00Z" in text
    assert "Review Queue" in text
    assert "Close" in text
    assert "2026-06-01T00:00:00Z" in text
    assert "review_due" in text
    assert "Open Alerts" in text
    assert "dashboard_render_fixture" in text
    assert "Review dashboard render fixture." in text
    assert "Calibration" in text
    assert "mean_brier: 0.062500" in text
    assert "ensemble_component_contributions:" in text
    assert "market: n=1 mean_contribution=0.600000 weight_share=0.750000" in text
    assert "question_type_breakdown:" in text
    assert "binary: n=1 brier_n=1 mean_brier=0.062500" in text
    assert "Learning Memory" in text
    assert "dashboard:binary" in text
    assert "Dashboard forecasts should keep calibration health visible." in text
    assert "Evidence Status" in text
    assert "positive_edge_runs: 0" in text
    assert "next live_scored_forecasts:" in text
    assert "Recent Backtests" in text
    assert "dataset" in text
    assert "dashboard-fixture" in text
    assert "1/0/0" in text
    assert "+0.150" in text
    assert "replay only" in text


def test_evidence_tracks_available_at_for_backtests(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will Company Y default?",
        resolution_criteria="Resolved yes if Company Y misses a bond payment before resolution.",
        domain="credit",
    )

    evidence = ledger.add_evidence(
        question_id=question.id,
        source_or_note="https://example.com/company-y-filing",
        claim="Liquidity fell below the covenant threshold.",
        claim_type="estimate",
        published_at="2026-05-04T12:00:00Z",
        reliability_rating=0.9,
        relevance_rating=0.8,
        stance="increases",
    )

    assert evidence.source_url == "https://example.com/company-y-filing"
    assert evidence.available_at == "2026-05-04T12:00:00Z"
    assert evidence.claim_type == "estimate"
    assert evidence.admissible_for_backtests is True


def test_file_evidence_is_classified_explicitly(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    source = tmp_path / "source.txt"
    source.write_text("source material", encoding="utf-8")
    question = ledger.create_question(
        title="Will file evidence be tracked?",
        resolution_criteria="Resolved yes if file evidence is recorded as a file.",
    )

    evidence = ledger.add_evidence(question_id=question.id, source_or_note=str(source))

    assert evidence.source_type == "file"
    assert evidence.source_name == str(source)
    assert evidence.snapshot_path != str(source)
    assert evidence.metadata["source_file_path"] == str(source)
    snapshot_path = Path(evidence.snapshot_path)
    assert snapshot_path.exists()
    assert snapshot_path.read_text(encoding="utf-8") == "source material"
    source.write_text("mutated source material", encoding="utf-8")
    assert snapshot_path.read_text(encoding="utf-8") == "source material"


def test_url_evidence_snapshot_is_archived_when_fetchable(tmp_path):
    server = _serve_snapshot_source()
    try:
        host, port = server.server_address
        url = f"http://{host}:{port}/source"
        ledger = ForecastLedger(tmp_path / "forecasting.db")
        question = ledger.create_question(
            title="Will URL evidence be snapshotted?",
            resolution_criteria="Resolved yes if URL evidence has a local snapshot.",
        )

        evidence = ledger.add_evidence(question_id=question.id, source_or_note=url)

        snapshot_path = Path(evidence.snapshot_path)
        metadata_path = Path(evidence.metadata["source_snapshot"]["metadata_path"])
        assert evidence.source_type == "url"
        assert evidence.source_url == url
        assert snapshot_path.exists()
        assert snapshot_path.read_text(encoding="utf-8") == "<html><body>snapshot source</body></html>"
        assert metadata_path.exists()
        assert evidence.metadata["source_snapshot"]["sha256"]
    finally:
        server.shutdown()
        server.server_close()


def test_ingest_candidate_requires_confirmation_before_active_forecast(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    candidate = ledger.create_ingest_candidate(
        source="https://example.com/questions/will-x-happen",
        title="Will X happen?",
        resolution_criteria="Resolved yes if X happens before year-end.",
        metadata={
            "baseline": {
                "source": "crowd",
                "baseline_type": "crowd",
                "probability_or_distribution": 0.62,
                "as_of": "2026-05-01T00:00:00Z",
            }
        },
    )

    assert candidate["status"] == "proposed"
    assert ledger.list_questions() == []

    question = ledger.confirm_ingest_candidate(
        candidate["id"],
        domain="general",
        tags=["external"],
    )
    confirmed = ledger.get_ingest_candidate(candidate["id"])
    evidence = ledger.list_evidence(question.id)

    assert question.title == "Will X happen?"
    assert confirmed["status"] == "confirmed"
    assert confirmed["confirmed_question_id"] == question.id
    assert evidence[0].source_url == "https://example.com/questions/will-x-happen"
    assert ledger.list_baseline_comparisons(question.id)[0]["probability_or_distribution"] == 0.62


def test_ingest_candidate_extracts_question_metadata_from_json_file(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    source = tmp_path / "forecast.json"
    source.write_text(
        json.dumps(
            {
                "title": "Will JSON ingest work?",
                "description": "Structured source file.",
                "resolution_criteria": "Resolved yes if JSON metadata creates a question.",
                "close_time": "2026-06-01T00:00:00Z",
                "outcome_space": {"type": "binary", "choices": ["yes", "no"]},
                "baseline_probability": 0.64,
                "baseline_type": "crowd",
                "baseline_as_of": "2026-05-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    candidate = ledger.create_ingest_candidate(source=str(source))
    question = ledger.confirm_ingest_candidate(candidate["id"], domain="benchmarks")

    assert candidate["candidate_title"] == "Will JSON ingest work?"
    assert candidate["description"] == "Structured source file."
    assert candidate["resolution_criteria"] == "Resolved yes if JSON metadata creates a question."
    assert question.close_time == "2026-06-01T00:00:00Z"
    assert ledger.list_baseline_comparisons(question.id)[0]["probability_or_distribution"] == 0.64
    assert ledger.list_evidence(question.id)[0].source_type == "file"


def test_ingest_candidate_extracts_question_metadata_from_csv_file(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    source = tmp_path / "market.csv"
    source.write_text(
        "\n".join(
            [
                "title,resolution_criteria,close_time,baseline_probability,baseline_type,baseline_source",
                "Will CSV market ingest work?,Resolved yes if CSV market metadata creates a baseline.,2026-07-01T00:00:00Z,0.59,market,example-market",
            ]
        ),
        encoding="utf-8",
    )

    candidate = ledger.create_ingest_candidate(source=str(source))
    question = ledger.confirm_ingest_candidate(candidate["id"], domain="markets")
    baseline = ledger.list_baseline_comparisons(question.id)[0]

    assert candidate["candidate_title"] == "Will CSV market ingest work?"
    assert question.close_time == "2026-07-01T00:00:00Z"
    assert baseline["source"] == "example-market"
    assert baseline["baseline_type"] == "market"
    assert baseline["probability_or_distribution"] == 0.59


def test_ingest_candidate_confirmation_requires_resolution_criteria(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    candidate = ledger.create_ingest_candidate(source="manual question seed")

    with pytest.raises(ValidationError, match="resolution criteria"):
        ledger.confirm_ingest_candidate(candidate["id"])


def test_create_question_blocks_obviously_unscoreable_resolution_criteria(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")

    with pytest.raises(ValidationError, match="ambiguous or unscoreable"):
        ledger.create_question(
            title="Will it happen?",
            resolution_criteria="TBD",
        )


def test_snapshot_evidence_cutoff_blocks_late_evidence(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will late evidence leak?",
        resolution_criteria="Resolved yes if late evidence is rejected.",
    )
    evidence = ledger.add_evidence(
        question_id=question.id,
        source_or_note="A retrospective source",
        available_at="2026-02-01T00:00:00Z",
    )

    with pytest.raises(ValidationError, match="after the evidence cutoff"):
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.5,
            rationale="Should not be allowed to use late evidence.",
            evidence_refs=[evidence.id],
            evidence_cutoff="2026-01-01T00:00:00Z",
        )


def test_snapshot_as_of_blocks_evidence_newer_than_forecast_time(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will as-of enforce evidence availability?",
        resolution_criteria="Resolved yes if future evidence is rejected.",
    )
    evidence = ledger.add_evidence(
        question_id=question.id,
        source_or_note="Future evidence",
        available_at="2026-02-01T00:00:00Z",
    )

    with pytest.raises(ValidationError, match="after the evidence cutoff"):
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.5,
            rationale="Should not cite evidence newer than the forecast time.",
            as_of="2026-01-01T00:00:00Z",
            evidence_refs=[evidence.id],
        )


def test_snapshot_requires_acknowledgement_for_stale_cited_evidence(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will stale cited evidence be acknowledged?",
        resolution_criteria="Resolved yes if stale evidence is explicit.",
    )
    evidence = ledger.add_evidence(
        question_id=question.id,
        source_or_note="Old evidence",
        available_at="2026-01-01T00:00:00Z",
    )

    with pytest.raises(ValidationError, match="stale evidence requires acknowledgement"):
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.5,
            rationale="Uses old evidence.",
            as_of="2026-02-15T00:00:00Z",
            evidence_refs=[evidence.id],
            stale_evidence_days=30,
        )

    snapshot = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Uses old evidence with explicit acknowledgement.",
        as_of="2026-02-15T00:00:00Z",
        evidence_refs=[evidence.id],
        stale_evidence_days=30,
        acknowledge_stale_evidence=True,
    )

    assert snapshot.metadata["stale_evidence_acknowledgement"]["evidence_refs"] == [evidence.id]


def test_snapshot_strict_citation_policy_requires_traceable_refs(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will strict citation policy work?",
        resolution_criteria="Resolved yes if uncited rationales can be blocked.",
    )

    with pytest.raises(ValidationError, match="requires citations"):
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.5,
            rationale="This factual rationale needs a source.",
            require_citations=True,
        )

    evidence = ledger.add_evidence(
        question_id=question.id,
        source_or_note="Cited evidence",
        available_at="2026-01-01T00:00:00Z",
    )
    snapshot = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.55,
        rationale="Cited evidence supports a small increase.",
        evidence_refs=[evidence.id],
        require_citations=True,
    )

    assert snapshot.evidence_refs == [evidence.id]
    assert snapshot.metadata["citation_policy"] == "required"


def test_snapshot_refs_must_belong_to_question(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    first = ledger.create_question(
        title="First question",
        resolution_criteria="Resolved yes if first event happens.",
    )
    second = ledger.create_question(
        title="Second question",
        resolution_criteria="Resolved yes if second event happens.",
    )
    assumption = ledger.add_assumption(question_id=first.id, text="Only belongs to first.")

    with pytest.raises(ValidationError, match="does not belong"):
        ledger.create_snapshot(
            question_id=second.id,
            probability_or_distribution=0.5,
            rationale="Should reject cross-question refs.",
            assumption_refs=[assumption["id"]],
        )


def test_unconfirmed_resolution_cannot_be_scored(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will the product launch by Q3?",
        resolution_criteria="Resolved yes if the public launch happens before the end of Q3.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.7,
        rationale="Timeline risk is moderate.",
    )
    ledger.resolve_question(
        question_id=question.id,
        outcome="yes",
        resolution_status="proposed",
        criteria_satisfied=True,
    )

    with pytest.raises(ValidationError, match="confirmed"):
        ledger.score_question(question.id)


def test_corrected_resolution_requires_correction_ref(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will corrected resolutions be governed?",
        resolution_criteria="Resolved yes if corrections require refs.",
    )

    with pytest.raises(ValidationError, match="correction_ref"):
        ledger.resolve_question(
            question_id=question.id,
            outcome="yes",
            resolution_status="corrected",
        )


def test_resolution_source_file_is_archived_as_snapshot(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    source = tmp_path / "resolution.txt"
    source.write_text("official result: yes", encoding="utf-8")
    question = ledger.create_question(
        title="Will resolution source be archived?",
        resolution_criteria="Resolved yes if the source snapshot is preserved.",
    )

    resolution = ledger.resolve_question(
        question_id=question.id,
        outcome="yes",
        resolution_source=str(source),
    )

    assert resolution.resolution_source_snapshot_ref is not None
    snapshot_path = Path(resolution.resolution_source_snapshot_ref)
    assert snapshot_path.exists()
    assert snapshot_path.read_text(encoding="utf-8") == "official result: yes"
    source.write_text("official result: changed", encoding="utf-8")
    assert snapshot_path.read_text(encoding="utf-8") == "official result: yes"


def test_confirmed_binary_resolution_gets_brier_score(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will X win?",
        resolution_criteria="Resolved yes if X wins the final certified result.",
        domain="elections",
    )
    snapshot = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.7,
        rationale="Polling and incumbency favor X.",
        as_of="2026-05-01T00:00:00Z",
    )
    resolution = ledger.resolve_question(
        question_id=question.id,
        outcome="yes",
        resolution_status="confirmed",
        criteria_satisfied=True,
        resolution_source="official result",
    )

    score = ledger.score_question(question.id)
    duplicate = ledger.score_question(question.id)

    assert score.forecast_id == snapshot.forecast_id
    assert score.resolution_id == resolution.id
    assert score.brier_score == pytest.approx(0.09)
    assert score.log_score == pytest.approx(-math.log(0.7))
    assert score.calibration_bucket == "0.7-0.8"
    assert duplicate.id == score.id
    assert ledger.list_scores(domain="elections", bucket="0.7-0.8")[0].id == score.id


def test_calibration_summary_filters_horizon_and_reports_sharpness(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will X close by date?",
        resolution_criteria="Resolved yes if X closes.",
        close_time="2026-01-11T00:00:00Z",
        domain="deals",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.55,
        rationale="Initial deal odds reflect an early base rate.",
        as_of="2026-01-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.75,
        rationale="Near-term deal catalysts are strong.",
        as_of="2026-01-05T00:00:00Z",
        ensemble_components={
            "components": [
                {"name": "base_rate", "probability": 0.6, "weight": 1},
                {"name": "market", "probability": 0.8, "weight": 3},
            ]
        },
    )
    ledger.resolve_question(question_id=question.id, outcome="yes")
    ledger.score_question(question.id)

    summary = ledger.calibration_summary(domain="deals", horizon="0-30")
    excluded = ledger.calibration_summary(domain="deals", horizon="0-5")

    assert summary["count"] == 1
    assert summary["mean_sharpness"] == pytest.approx(0.5)
    assert summary["probability_movement_count"] == 1
    assert summary["mean_probability_movement_before_close"] == pytest.approx(0.2)
    assert summary["mean_abs_probability_movement_before_close"] == pytest.approx(0.2)
    type_rows = {
        row["question_type"]: row for row in summary["question_type_breakdown"]
    }
    assert type_rows["binary"]["count"] == 1
    assert type_rows["binary"]["brier_count"] == 1
    assert type_rows["binary"]["mean_brier"] == pytest.approx(0.0625)
    assert type_rows["binary"]["mean_proper_score"] == pytest.approx(0.0625)
    contributions = {
        row["name"]: row for row in summary["ensemble_component_contributions"]
    }
    assert contributions["market"]["mean_weight_share"] == pytest.approx(0.75)
    assert contributions["market"]["mean_contribution"] == pytest.approx(0.6)
    assert contributions["base_rate"]["mean_weight_share"] == pytest.approx(0.25)
    assert contributions["base_rate"]["mean_contribution"] == pytest.approx(0.15)
    assert summary["buckets"][0]["sample_status"] == "empty"
    assert next(row for row in summary["buckets"] if row["bucket"] == "0.7-0.8")["sample_status"] == "low_sample"
    assert excluded["count"] == 0
    assert excluded["probability_movement_count"] == 0


def test_categorical_distribution_scoring_uses_resolved_outcome(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Which team will win the group?",
        resolution_criteria="Resolved to the team that finishes first.",
        outcome_space=OutcomeSpace(type="categorical", choices=["alpha", "beta", "gamma"]),
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution={"alpha": 0.4, "beta": 0.35, "gamma": 0.25},
        rationale="Alpha has the strongest schedule-adjusted rating.",
    )
    ledger.resolve_question(question_id=question.id, outcome="beta")

    score = ledger.score_question(question.id)

    assert score.brier_score == pytest.approx((0.4 - 0.0) ** 2 + (0.35 - 1.0) ** 2 + (0.25 - 0.0) ** 2)
    assert score.calibration_bucket == "0.3-0.4"


def test_numeric_forecasts_are_scored_with_normalized_squared_error(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="What will revenue be?",
        resolution_criteria="Resolved by audited annual revenue.",
        outcome_space=OutcomeSpace(type="numeric", choices=[], units="usd", bounds=[0, 1_000_000_000]),
    )
    snapshot = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=123_456_789.0,
        rationale="Revenue model point estimate.",
    )
    ledger.resolve_question(question_id=question.id, outcome=125_000_000.0)

    score = ledger.score_question(question.id)

    assert snapshot.probability_or_distribution == 123_456_789.0
    assert score.brier_score is None
    assert score.log_score is None
    assert score.proper_score == pytest.approx(((123_456_789.0 - 125_000_000.0) / 1_000_000_000.0) ** 2)
    assert score.score_rule == "normalized_squared_error"
    assert score.calibration_bucket == "0.1-0.2"
    summary = ledger.calibration_summary()
    type_rows = {
        row["question_type"]: row for row in summary["question_type_breakdown"]
    }
    assert summary["count"] == 0
    assert type_rows["numeric"]["count"] == 1
    assert type_rows["numeric"]["brier_count"] == 0
    assert type_rows["numeric"]["mean_proper_score"] == pytest.approx(score.proper_score)


def test_normal_distribution_forecasts_use_negative_log_likelihood(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="What will annual inflation be?",
        resolution_criteria="Resolved by final reported annual inflation.",
        outcome_space=OutcomeSpace(type="distribution", choices=[], units="percent", bounds=[0, 10]),
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution={"mean": 3.0, "std": 1.0},
        rationale="Inflation distribution forecast.",
    )
    ledger.resolve_question(question_id=question.id, outcome=4.0)

    score = ledger.score_question(question.id)

    expected_nll = 0.5 * math.log(2 * math.pi) + 0.5
    assert score.brier_score is None
    assert score.log_score == pytest.approx(expected_nll)
    assert score.proper_score == pytest.approx(expected_nll)
    assert score.score_rule == "normal_negative_log_likelihood"
    assert score.calibration_bucket == "0.3-0.4"


def test_self_check_creates_alerts_without_mutating_forecast_history(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will the trial report topline data?",
        resolution_criteria="Resolved yes if topline data are publicly reported.",
        domain="biotech",
        next_review_at="2026-01-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.51,
        rationale="Prior trial timelines imply roughly even odds.",
        as_of="2026-01-02T00:00:00Z",
    )

    alerts = ledger.self_check(question_id=question.id, stale_days=1)

    assert {alert.reason for alert in alerts} >= {"review_due", "last_update_1d_plus"}
    assert len(ledger.list_snapshots(question.id)) == 1


def test_global_self_check_flags_benchmark_evidence_gaps(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")

    alerts = ledger.self_check()

    gap_alerts = [alert for alert in alerts if alert.reason == "benchmark_evidence_gaps"]
    assert len(gap_alerts) == 1
    assert gap_alerts[0].scope_type == "global"
    assert gap_alerts[0].scope_ref == "benchmark_evidence"
    assert "forecast performance --json" in gap_alerts[0].recommended_action
    assert "live_scored_forecasts" in gap_alerts[0].recommended_action
    assert ledger.self_check(domain="macro") == []


def test_question_review_cadence_creates_scheduled_review(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will review cadence schedule itself?",
        resolution_criteria="Resolved yes if question review cadence creates a schedule.",
        review_cadence="3d",
        next_review_at="2026-01-02T00:00:00Z",
    )

    reviews = ledger.list_scheduled_reviews()

    assert reviews[0]["scope_type"] == "question"
    assert reviews[0]["scope_ref"] == question.id
    assert reviews[0]["cadence"] == "3d"
    assert reviews[0]["next_run_at"] == "2026-01-02T00:00:00Z"
    assert reviews[0]["trigger_reason"] == "question_review_cadence"


def test_export_packet_includes_auditable_forecast_data(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will the central bank cut rates?",
        resolution_criteria="Resolved yes if the target rate is lowered at the meeting.",
        domain="macro",
    )
    evidence = ledger.add_evidence(
        question_id=question.id,
        source_or_note="Inflation print came in below consensus.",
        available_at="2026-05-05T08:30:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.63,
        rationale="Weak inflation and labor data support a cut.",
        evidence_refs=[evidence.id],
    )
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="https://example.com/macro-calendar",
        source_type="url",
    )

    packet = json.loads(ledger.export_question(question.id, fmt="json"))

    assert packet["product"]["product_name"] == "Superforecasting Agent"
    assert packet["question"]["id"] == question.id
    assert packet["forecast_history"][0]["probability_or_distribution"] == 0.63
    assert packet["evidence"][0]["available_at"] == "2026-05-05T08:30:00Z"
    assert packet["watched_sources"][0]["id"] == watch["id"]


def test_export_all_includes_questions_candidates_and_alerts(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will portfolio export work?",
        resolution_criteria="Resolved yes if export all includes this question.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Test forecast.",
    )
    candidate = ledger.create_ingest_candidate(source="portfolio candidate")
    ledger.create_alert(
        severity="warning",
        scope_type="question",
        scope_ref=question.id,
        reason="test_alert",
        recommended_action="Inspect test alert.",
    )

    packet = json.loads(ledger.export_all(fmt="json"))

    assert packet["product"]["product_slug"] == "superforecasting-agent"
    assert packet["questions"][0]["question"]["id"] == question.id
    assert packet["ingest_candidates"][0]["id"] == candidate["id"]
    assert packet["alerts"][0]["reason"] == "test_alert"


def test_pilot_report_summarizes_tester_exit_artifacts(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will the tester pilot complete one full forecast loop?",
        resolution_criteria="Resolved yes if the pilot has one scored forecast with a postmortem.",
        domain="macro",
        topics=["rates"],
    )
    evidence = ledger.add_evidence(
        question_id=question.id,
        source_or_note="Imported macro source.",
        source_type="fred",
        available_at="2026-05-23T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.7,
        rationale="Structured evidence supports a yes resolution.",
        evidence_refs=[evidence.id],
    )
    ledger.schedule_review(
        scope_type="question",
        scope_ref=question.id,
        cadence="1d",
        next_run_at="2026-05-24T09:00:00Z",
    )
    ledger.resolve_question(
        question_id=question.id,
        outcome="yes",
        resolution_source="https://example.com/resolution",
    )
    ledger.score_question(question.id)
    ledger.create_postmortem(
        question_id=question.id,
        summary="The full loop resolved as expected.",
        lesson="Keep the structured source attached to the update.",
    )

    report = ledger.pilot_report(
        min_questions=1,
        min_structured_source_questions=1,
        min_scores=1,
        min_postmortems=1,
        min_scheduled_reviews=1,
    )

    assert report["pilot_status"] == "pilot_exit_ready"
    assert report["passed_checks"] == report["total_checks"]
    assert report["summary"]["question_count"] == 1
    assert report["summary"]["score_counts_by_origin"]["live"] == 1
    assert report["source_types"]["fred"] == 1
    assert report["domains"]["macro"] == 1
    assert report["topics"]["rates"] == 1
    assert report["questions"][0]["structured_source_types"] == ["fred"]


def test_alert_acknowledgement_removes_alert_from_open_list(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    alert = ledger.create_alert(
        severity="warning",
        scope_type="portfolio",
        scope_ref="default",
        reason="test",
        recommended_action="ack",
    )

    acknowledged = ledger.acknowledge_alert(alert.id, acknowledged_at="2026-01-01T00:00:00Z")

    assert acknowledged.acknowledged_at == "2026-01-01T00:00:00Z"
    assert ledger.list_alerts() == []
    assert ledger.list_alerts(unresolved_only=False)[0].id == alert.id


def test_reference_class_and_model_run_are_durable_and_exported(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will the drug receive approval?",
        resolution_criteria="Resolved yes if the regulator approves the application.",
        domain="biotech",
    )

    reference_class = ledger.add_reference_class(
        question_id=question.id,
        name="Comparable phase-three approvals",
        inclusion_criteria="Same indication and pivotal trial quality.",
        base_rate=0.62,
        base_rate_uncertainty=0.08,
    )
    model_run = ledger.record_model_run(
        question_id=question.id,
        model_type="base_rate",
        inputs={"reference_class_id": reference_class["id"]},
        output={"base_rate": 0.62},
    )
    failed_run = ledger.record_model_run(
        question_id=question.id,
        model_type="time_series",
        status="failure",
        diagnostics={"error": "not enough history"},
    )

    packet = json.loads(ledger.export_question(question.id, fmt="json"))

    assert packet["reference_classes"][0]["id"] == reference_class["id"]
    assert packet["model_runs"][0]["id"] == model_run["id"]
    assert ledger.get_model_run(failed_run["id"])["status"] == "failure"


def test_postmortem_creates_calibration_lesson_and_error_profile(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will the agency approve by June?",
        resolution_criteria="Resolved yes if approval is announced by June 30.",
        domain="biotech",
        topics=["regulatory-delay"],
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.9,
        rationale="The filing looked clean.",
    )
    ledger.resolve_question(question_id=question.id, outcome="no")

    postmortem = ledger.create_postmortem(
        question_id=question.id,
        summary="Approval was delayed.",
        base_rate_error="Underweighted regulatory delay.",
        lesson="Regulatory delay should be checked explicitly in biotech approvals.",
        calibration_adjustment={"biotech_delay_penalty": 0.05},
    )
    lessons = ledger.list_calibration_lessons(scope_type="domain", scope_ref="biotech")
    profiles = ledger.list_domain_error_profiles(domain="biotech")
    ledger.create_question(
        title="Will another agency approval happen?",
        resolution_criteria="Resolved yes if another approval is announced.",
        domain="biotech",
        topics=["regulatory-delay"],
    )
    alerts = ledger.self_check(domain="biotech")

    assert postmortem["question_id"] == question.id
    assert lessons[0]["source_postmortem_refs"] == [postmortem["id"]]
    assert profiles[0]["sample_count"] == 1
    assert "base_rate_error" in profiles[0]["recurring_errors"]
    assert "overconfidence" in profiles[0]["recurring_errors"]
    assert profiles[0]["calibration_summary"]["error_counts"]["base_rate_error"] == 1
    assert any("Refresh reference classes" in item for item in profiles[0]["recommended_adjustments"])
    assert ledger.list_domain_error_profiles(domain="biotech", topic="regulatory-delay")[0]["sample_count"] == 1
    error_alerts = [alert for alert in alerts if alert.reason == "domain_error_profile_review"]
    assert error_alerts
    assert profiles[0]["id"] in {alert.scope_ref for alert in error_alerts}
    assert any("base_rate_error" in alert.recommended_action for alert in error_alerts)


def test_scoring_updates_domain_and_topic_error_profiles(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will scoring update profiles?",
        resolution_criteria="Resolved yes if scoring creates error profiles.",
        domain="macro",
        topics=["inflation"],
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.9,
        rationale="High-confidence live forecast.",
    )
    ledger.resolve_question(question_id=question.id, outcome="no")

    ledger.score_question(question.id)

    domain_profile = ledger.list_domain_error_profiles(domain="macro")[0]
    topic_profile = ledger.list_domain_error_profiles(domain="macro", topic="inflation")[0]
    assert domain_profile["sample_count"] == 1
    assert topic_profile["sample_count"] == 1
    assert "elevated_mean_brier" in domain_profile["recurring_errors"]
    assert "overconfidence" in domain_profile["recurring_errors"]


def test_postmortem_does_not_create_lesson_from_ineligible_backtest_score(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Backtest question",
        resolution_criteria="Resolved yes if the historical event happened.",
        domain="macro",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.8,
        rationale="Historical replay forecast.",
        forecast_origin="backtest",
        calibration_eligible=False,
        calibration_weight=0.0,
    )
    ledger.resolve_question(question_id=question.id, outcome="yes")

    ledger.create_postmortem(
        question_id=question.id,
        lesson="This should not become live calibration memory.",
    )

    assert ledger.list_calibration_lessons(scope_type="domain", scope_ref="macro") == []


def test_forecast_updates_can_only_cite_active_calibration_lessons(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will calibration lesson gating work?",
        resolution_criteria="Resolved yes if inactive lessons cannot be cited.",
        domain="macro",
    )
    lesson = ledger.create_calibration_lesson(
        scope_type="domain",
        scope_ref="macro",
        lesson="Adjust modestly for recurring overconfidence.",
        status="tentative",
    )

    with pytest.raises(ValidationError, match="calibration lesson refs must be active"):
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.5,
            rationale="Should not cite tentative lessons.",
            calibration_lesson_refs=[lesson["id"]],
        )

    active = ledger.update_calibration_lesson(lesson["id"], status="active", confidence=0.8)
    snapshot = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.55,
        rationale="Uses an active calibration lesson.",
        calibration_lesson_refs=[active["id"]],
    )

    assert snapshot.calibration_lesson_refs == [lesson["id"]]
    assert ledger.list_calibration_lessons(scope_type="domain", scope_ref="macro", active_only=True)[0]["id"] == lesson["id"]


def test_backtest_dataset_excludes_post_cutoff_evidence_and_scores_case(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    run = ledger.run_backtest_dataset(
        dataset="fixture",
        default_forecast_time_cutoff="2026-01-10T00:00:00Z",
        cases=[
            {
                "id": "case-1",
                "title": "Will X happen?",
                "resolution_criteria": "Resolved yes if X happens.",
                "domain": "macro",
                "probability": 0.6,
                "outcome": "yes",
                "evidence": [
                    {
                        "note": "Before cutoff",
                        "available_at": "2026-01-05T00:00:00Z",
                    },
                    {
                        "note": "After cutoff",
                        "available_at": "2026-01-20T00:00:00Z",
                    },
                ],
                "baselines": [
                    {"source": "crowd", "baseline_type": "crowd", "probability": 0.55}
                ],
            }
        ],
    )

    case = run["cases"][0]
    question = ledger.get_question(case["question_id"])
    evidence = ledger.list_evidence(question.id)
    baselines = ledger.list_baseline_comparisons(question.id)
    report = ledger.backtest_performance_report(run["id"])
    baseline_summary = ledger.calibration_summary(
        forecast_origin="imported_baseline",
        calibration_eligible=None,
    )

    assert run["result_summary"]["scored_cases"] == 1
    assert ledger.list_backtest_runs()[0]["id"] == run["id"]
    assert run["leakage_checks_passed"] is True
    assert case["excluded_evidence_count"] == 1
    assert case["leakage_check_status"] == "passed"
    assert len(evidence) == 1
    assert ledger.get_score(case["score_record_id"]).forecast_origin == "backtest"
    assert baselines[0]["score_record_id"] is not None
    assert ledger.get_score(baselines[0]["score_record_id"]).forecast_origin == "imported_baseline"
    assert ledger.get_score(baselines[0]["score_record_id"]).baseline_ref == baselines[0]["id"]
    assert ledger.get_current_snapshot(question.id).forecast_id == case["generated_forecast_id"]
    assert report["agent"]["mean_brier"] == pytest.approx(0.16)
    assert report["baselines"][0]["mean_brier"] == pytest.approx(0.2025)
    assert report["baselines"][0]["mean_brier_improvement_vs_baseline"] == pytest.approx(0.0425)
    assert baseline_summary["count"] == 1
    assert baseline_summary["mean_brier"] == pytest.approx(0.2025)


def test_imported_benchmark_dataset_is_durable_and_replayable(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    dataset = ledger.import_benchmark_dataset(
        source="fixture.csv",
        name="fixture-resolved",
        description="Resolved fixture cases.",
        cases=[
            {
                "id": "fixture-1",
                "title": "Will durable benchmark imports replay?",
                "resolution_criteria": "Resolved yes if imported benchmark cases can be replayed.",
                "as_of": "2026-01-10T00:00:00Z",
                "probability": 0.65,
                "outcome": "yes",
            }
        ],
        metadata={"format": "csv"},
    )

    listed = ledger.list_benchmark_datasets()
    imported = ledger.get_benchmark_dataset(f"imported:{dataset['id']}")
    run = ledger.run_backtest_dataset(
        dataset=f"imported:{dataset['id']}",
        cases=imported["cases"],
    )

    assert dataset["case_count"] == 1
    assert listed[0]["id"] == dataset["id"]
    assert imported["name"] == "fixture-resolved"
    assert imported["metadata"]["format"] == "csv"
    assert run["result_summary"]["scored_cases"] == 1


def test_backtest_dataset_adds_naive_and_base_rate_baselines_when_missing(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    run = ledger.run_backtest_dataset(
        dataset="baseline-fixture",
        default_forecast_time_cutoff="2026-01-10T00:00:00Z",
        cases=[
            {
                "title": "Will automatic baselines be scored?",
                "resolution_criteria": "Resolved yes if automatic baselines are scored.",
                "domain": "macro",
                "close_time": "2026-01-25T00:00:00Z",
                "probability": 0.7,
                "base_rate": 0.6,
                "outcome": "yes",
            }
        ],
    )

    case = ledger.list_backtest_cases(run["id"])[0]
    baselines = [ledger.get_baseline_comparison(ref) for ref in case["baseline_comparison_refs"]]
    baseline_keys = {(baseline["baseline_type"], baseline["source"]) for baseline in baselines}
    report = ledger.backtest_performance_report(run["id"])

    assert ("naive_0_5", "auto") in baseline_keys
    assert ("base_rate", "dataset") in baseline_keys
    assert all(baseline["score_record_id"] for baseline in baselines)
    assert {item["baseline_type"] for item in report["baselines"]} >= {"naive_0_5", "base_rate"}
    assert report["agent_by_domain"]["macro"]["count"] == 1
    assert report["agent_by_horizon"]["8-30d"]["count"] == 1


def test_calibration_summary_handles_100_resolved_binary_forecasts(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    for index in range(100):
        question = ledger.create_question(
            title=f"Will calibration scale case {index} resolve?",
            resolution_criteria="Resolved yes or no from the synthetic scale fixture.",
            domain="scale",
        )
        probability = 0.7 if index % 2 == 0 else 0.3
        outcome = "yes" if index % 3 else "no"
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=probability,
            rationale="Synthetic scale fixture forecast.",
            as_of="2026-01-01T00:00:00Z",
        )
        ledger.resolve_question(
            question_id=question.id,
            outcome=outcome,
            resolution_status="confirmed",
            criteria_satisfied=True,
        )
        ledger.score_question(question.id)

    summary = ledger.calibration_summary(domain="scale")

    assert summary["count"] == 100
    assert summary["mean_brier"] is not None
    assert sum(bucket["count"] for bucket in summary["buckets"]) == 100


def test_backtest_run_with_any_leakage_disables_calibration_memory_for_all_replay_scores(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    run = ledger.run_backtest_dataset(
        dataset="fixture",
        default_forecast_time_cutoff="2026-01-10T00:00:00Z",
        allow_calibration_memory=True,
        cases=[
            {
                "title": "Clean historical case",
                "resolution_criteria": "Resolved yes if clean case happens.",
                "probability": 0.7,
                "outcome": "yes",
                "evidence": [{"note": "before", "available_at": "2026-01-05T00:00:00Z"}],
            },
            {
                "title": "Ambiguous historical case",
                "resolution_criteria": "Resolved yes if ambiguous case happens.",
                "probability": 0.7,
                "outcome": "yes",
                "evidence": [{"note": "missing availability timestamp"}],
            },
        ],
    )

    replay_scores = ledger.list_scores(forecast_origin="backtest", calibration_eligible=None)
    eligible_scores = ledger.list_scores(forecast_origin="backtest", calibration_eligible=True)

    assert run["leakage_checks_passed"] is False
    assert {score.calibration_eligible for score in replay_scores} == {False}
    assert eligible_scores == []


def test_due_scheduled_review_runs_self_check_and_advances_next_run(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will this stale forecast be reviewed?",
        resolution_criteria="Resolved yes if review happens.",
        domain="operations",
        next_review_at="2026-01-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Initial placeholder forecast.",
        as_of="2026-01-01T00:00:00Z",
    )
    review = ledger.schedule_review(
        scope_type="domain",
        scope_ref="operations",
        cadence="1d",
        next_run_at="2026-01-02T00:00:00Z",
        stale_days=3,
    )

    results = ledger.run_due_scheduled_reviews(now="2026-01-10T00:00:00Z")

    assert results[0]["review"]["id"] == review["id"]
    assert results[0]["review"]["stale_days"] == 3
    assert results[0]["review"]["last_run_at"] == "2026-01-10T00:00:00Z"
    assert results[0]["review"]["next_run_at"] == "2026-01-11T00:00:00Z"
    assert {alert.reason for alert in results[0]["alerts"]} >= {"review_due", "last_update_3d_plus"}


def test_watched_file_source_creates_alert_on_change(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched file changes be detected?",
        resolution_criteria="Resolved yes if watched file changes create alerts.",
    )
    source = tmp_path / "source.txt"
    source.write_text("initial evidence", encoding="utf-8")
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source=str(source),
    )

    assert watch["source_type"] == "file"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    source.write_text("changed evidence", encoding="utf-8")
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-01-10T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-01-10T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_url_source_creates_alert_on_content_change(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched URL changes be detected?",
        resolution_criteria="Resolved yes if watched URL changes create alerts.",
    )
    _MutableSourceHandler.body = b"initial watched source"
    server = _serve_mutable_source()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/source"
        watch = ledger.add_watched_source(
            scope_type="question",
            scope_ref=question.id,
            source=url,
        )

        assert watch["source_type"] == "url"
        assert watch["last_seen_signature"].startswith("url:200:")
        assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

        _MutableSourceHandler.body = b"changed watched source"
        alerts = ledger.check_watched_sources(
            scope_type="question",
            scope_ref=question.id,
            now="2026-01-10T00:00:00Z",
        )
    finally:
        server.shutdown()

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-01-10T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_rss_source_creates_alert_on_feed_change(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched RSS changes be detected?",
        resolution_criteria="Resolved yes if watched RSS changes create alerts.",
    )
    feed = tmp_path / "feed.xml"
    feed.write_text(
        """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Forecast Feed</title>
<item><guid>item-1</guid><title>Initial item</title><pubDate>Fri, 01 May 2026 00:00:00 GMT</pubDate></item>
</channel></rss>
""",
        encoding="utf-8",
    )
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source=f"rss:{feed}",
    )

    assert watch["source_type"] == "rss"
    assert watch["last_seen_signature"].startswith("rss:1:")
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    feed.write_text(
        """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Forecast Feed</title>
<item><guid>item-2</guid><title>New item</title><pubDate>Sat, 02 May 2026 00:00:00 GMT</pubDate></item>
</channel></rss>
""",
        encoding="utf-8",
    )
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-02T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-02T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_gdelt_source_creates_alert_on_article_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched GDELT changes be detected?",
        resolution_criteria="Resolved yes if watched GDELT article changes create alerts.",
    )
    titles = ["Initial policy article"]
    captured_queries = []

    def fake_load_gdelt_articles(query: str, **kwargs):
        captured_queries.append(query)
        return [
            GdeltArticle(
                title=titles[0],
                summary="",
                url=f"https://example.test/{titles[0].lower().replace(' ', '-')}",
                published_at="2026-05-01T00:00:00Z",
                source_name="example.test",
                entry_id=titles[0],
                domain="example.test",
                source_country="US",
                language="English",
                image_url=None,
                raw={"title": titles[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_gdelt_articles", fake_load_gdelt_articles)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="gdelt:policy bill",
    )

    assert watch["source_type"] == "gdelt"
    assert watch["last_seen_signature"].startswith("gdelt:1:")
    assert captured_queries[-1] == "policy bill"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    titles[0] = "New policy article"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-02T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import gdelt "policy bill" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-02T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_fivethirtyeight_source_creates_alert_on_poll_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched polling changes be detected?",
        resolution_criteria="Resolved yes if watched polling changes create alerts.",
    )
    pct = [48.4]
    captured_sources = []

    def fake_load_fivethirtyeight_polls(source: str, **kwargs):
        captured_sources.append(source)
        return [
            FiveThirtyEightPollObservation(
                dataset="president_polls",
                poll_id="p1",
                question_id="q1",
                pollster="Example Polls",
                pollster_grade="A",
                race_id="r1",
                office_type="PRES",
                state="PA",
                cycle=2026,
                stage="general",
                candidate_name="Jane Candidate",
                answer="Jane Candidate",
                party="DEM",
                pct=pct[0],
                sample_size=1000,
                population="lv",
                start_date="2026-05-20",
                end_date="2026-05-22",
                published_at="2026-05-23T00:00:00Z",
                source_url="https://polls.test/p1",
                source_name="Example Polls",
                entry_id="president_polls:p1:q1:Jane Candidate",
                raw={"poll_id": "p1", "pct": pct[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_fivethirtyeight_polls", fake_load_fivethirtyeight_polls)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="fivethirtyeight:president",
    )

    assert watch["source_type"] == "fivethirtyeight"
    assert watch["last_seen_signature"].startswith("fivethirtyeight:1:")
    assert captured_sources[-1] == "president"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    pct[0] = 49.2
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-02T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import fivethirtyeight president --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-02T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_github_source_creates_alert_on_release_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched GitHub releases be detected?",
        resolution_criteria="Resolved yes if watched GitHub release changes create alerts.",
    )
    tags = ["v1.0.0"]
    captured_sources = []

    def fake_load_github_releases(source: str, **kwargs):
        captured_sources.append(source)
        return [
            GitHubRelease(
                repo="acme/desk",
                release_id=str(len(tags[0])),
                tag_name=tags[0],
                name=f"Release {tags[0]}",
                body="Release notes for forecast desk.",
                url=f"https://api.github.test/repos/acme/desk/releases/{tags[0]}",
                html_url=f"https://github.com/acme/desk/releases/tag/{tags[0]}",
                created_at="2026-05-20T10:00:00Z",
                published_at="2026-05-21T11:00:00Z",
                draft=False,
                prerelease=False,
                source_name="GitHub",
                entry_id=str(len(tags[0])),
                raw={"tag_name": tags[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_github_releases", fake_load_github_releases)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="github:acme/desk",
    )

    assert watch["source_type"] == "github"
    assert watch["last_seen_signature"].startswith("github:1:")
    assert captured_sources[-1] == "acme/desk"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    tags[0] = "v1.1.0"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import github acme/desk --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_githubissues_source_creates_alert_on_issue_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched GitHub issues be detected?",
        resolution_criteria="Resolved yes if watched GitHub issue changes create alerts.",
    )
    states = ["open"]
    captured_sources = []

    def fake_load_github_issues(source: str, **kwargs):
        captured_sources.append(source)
        return [
            GitHubIssue(
                repo="acme/desk",
                issue_number=42,
                title=f"Forecast issue {states[0]}",
                state=states[0],
                is_pull_request=False,
                author="analyst",
                labels=["forecasting"],
                created_at="2026-05-20T10:00:00Z",
                updated_at="2026-05-21T11:00:00Z",
                closed_at=None,
                comments=1,
                url="https://api.github.test/repos/acme/desk/issues/42",
                html_url="https://github.com/acme/desk/issues/42",
                source_name="GitHub",
                entry_id="acme/desk#42",
                raw={"state": states[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_github_issues", fake_load_github_issues)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="githubissues:acme/desk",
    )

    assert watch["source_type"] == "githubissues"
    assert watch["last_seen_signature"].startswith("githubissues:1:")
    assert captured_sources[-1] == "acme/desk"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    states[0] = "closed"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import githubissues acme/desk --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_githubcommits_source_creates_alert_on_commit_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched GitHub commits be detected?",
        resolution_criteria="Resolved yes if watched GitHub commit changes create alerts.",
    )
    messages = ["Initial forecast commit"]
    captured_sources = []

    def fake_load_github_commits(source: str, **kwargs):
        captured_sources.append(source)
        sha = f"{len(messages[0]):040x}"
        return [
            GitHubCommit(
                repo="acme/desk",
                sha=sha,
                short_sha=sha[:7],
                message=messages[0],
                author_name="Ada Analyst",
                author_login="ada",
                authored_at="2026-05-20T10:00:00Z",
                committed_at="2026-05-21T11:00:00Z",
                comments=0,
                url="https://api.github.test/repos/acme/desk/commits/" + sha,
                html_url="https://github.com/acme/desk/commit/" + sha,
                source_name="GitHub",
                entry_id=f"acme/desk@{sha}",
                raw={"message": messages[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_github_commits", fake_load_github_commits)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="githubcommits:acme/desk",
    )

    assert watch["source_type"] == "githubcommits"
    assert watch["last_seen_signature"].startswith("githubcommits:1:")
    assert captured_sources[-1] == "acme/desk"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    messages[0] = "New forecast commit"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import githubcommits acme/desk --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_githubactions_source_creates_alert_on_workflow_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched GitHub Actions be detected?",
        resolution_criteria="Resolved yes if watched GitHub Actions run changes create alerts.",
    )
    conclusions = ["success"]
    captured_sources = []

    def fake_load_github_workflow_runs(source: str, **kwargs):
        captured_sources.append(source)
        return [
            GitHubWorkflowRun(
                repo="acme/desk",
                run_id="987",
                name="CI",
                display_title=f"Forecast workflow {conclusions[0]}",
                status="completed",
                conclusion=conclusions[0],
                event="push",
                head_branch="main",
                head_sha="abcdef1234567890",
                short_sha="abcdef1",
                workflow_id="1234",
                workflow_url="https://api.github.test/repos/acme/desk/actions/workflows/1234",
                actor_login="ada",
                triggering_actor_login="ci-bot",
                run_started_at="2026-05-21T10:30:00Z",
                created_at="2026-05-21T10:00:00Z",
                updated_at="2026-05-21T11:00:00Z",
                url="https://api.github.test/repos/acme/desk/actions/runs/987",
                html_url="https://github.com/acme/desk/actions/runs/987",
                source_name="GitHub",
                entry_id="acme/desk/actions/runs/987",
                raw={"conclusion": conclusions[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_github_workflow_runs", fake_load_github_workflow_runs)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="githubactions:acme/desk",
    )

    assert watch["source_type"] == "githubactions"
    assert watch["last_seen_signature"].startswith("githubactions:1:")
    assert captured_sources[-1] == "acme/desk"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    conclusions[0] = "failure"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import githubactions acme/desk --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_coingecko_source_creates_alert_on_market_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched CoinGecko prices be detected?",
        resolution_criteria="Resolved yes if watched CoinGecko market changes create alerts.",
    )
    prices = [109500]
    captured_sources = []

    def fake_load_coingecko_snapshots(source: str, **kwargs):
        captured_sources.append(source)
        return [
            CoinGeckoMarketSnapshot(
                coin_id="bitcoin",
                symbol="btc",
                name="Bitcoin",
                vs_currency="usd",
                current_price=prices[0],
                market_cap=2170000000000,
                market_cap_rank=1,
                total_volume=51200000000,
                price_change_percentage_24h=2.34,
                last_updated="2026-05-21T11:00:00Z",
                source_url="https://www.coingecko.com/en/coins/bitcoin",
                source_name="CoinGecko",
                entry_id="bitcoin:usd:2026-05-21T11:00:00Z",
                raw={"current_price": prices[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_coingecko_market_snapshots", fake_load_coingecko_snapshots)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="coingecko:bitcoin",
    )

    assert watch["source_type"] == "coingecko"
    assert watch["last_seen_signature"].startswith("coingecko:1:")
    assert captured_sources[-1] == "bitcoin"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    prices[0] = 111000
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import coingecko bitcoin --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_hackernews_source_creates_alert_on_story_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched Hacker News search be detected?",
        resolution_criteria="Resolved yes if watched Hacker News story changes create alerts.",
    )
    points = [128]
    captured_sources = []

    def fake_load_hackernews_items(source: str, **kwargs):
        captured_sources.append(source)
        return [
            HackerNewsItem(
                object_id="12345",
                title="Forecast Desk launches public beta",
                url="https://example.test/forecast-desk",
                hn_url="https://news.ycombinator.com/item?id=12345",
                author="analyst",
                created_at="2026-05-21T14:30:00Z",
                points=points[0],
                comments=34,
                story_id=12345,
                story_text="Public beta discussion.",
                source_name="Hacker News",
                entry_id="12345",
                raw={"points": points[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_hackernews_items", fake_load_hackernews_items)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="hackernews:forecast desk",
    )

    assert watch["source_type"] == "hackernews"
    assert watch["last_seen_signature"].startswith("hackernews:1:")
    assert captured_sources[-1] == "forecast desk"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    points[0] = 180
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import hackernews "forecast desk" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_reddit_source_creates_alert_on_post_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched Reddit search be detected?",
        resolution_criteria="Resolved yes if watched Reddit post changes create alerts.",
    )
    scores = [128]
    captured_sources = []

    def fake_load_reddit_posts(source: str, **kwargs):
        captured_sources.append(source)
        return [
            RedditPost(
                post_id="t3_abc123",
                title="Forecast Desk launches public beta",
                subreddit="forecasting",
                author="analyst",
                url="https://example.test/forecast-desk",
                permalink="https://www.reddit.com/r/forecasting/comments/abc123/forecast_desk/",
                created_at="2026-05-21T14:30:00Z",
                score=scores[0],
                comments=34,
                upvote_ratio=0.91,
                selftext="Public beta discussion.",
                source_name="Reddit r/forecasting",
                entry_id="t3_abc123",
                raw={"score": scores[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_reddit_posts", fake_load_reddit_posts)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="reddit:forecast desk",
    )

    assert watch["source_type"] == "reddit"
    assert watch["last_seen_signature"].startswith("reddit:1:")
    assert captured_sources[-1] == "forecast desk"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    scores[0] = 180
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import reddit "forecast desk" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_bluesky_source_creates_alert_on_post_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched Bluesky search be detected?",
        resolution_criteria="Resolved yes if watched Bluesky post changes create alerts.",
    )
    likes = [128]
    captured_sources = []

    def fake_load_bluesky_posts(source: str, **kwargs):
        captured_sources.append(source)
        return [
            BlueskyPost(
                post_uri="at://did:plc:abc/app.bsky.feed.post/3kforecast",
                cid="bafyforecast",
                text="Forecast Desk launches public beta",
                author_handle="analyst.bsky.social",
                author_display_name="Analyst",
                author_did="did:plc:abc",
                created_at="2026-05-21T14:30:00Z",
                indexed_at="2026-05-21T14:31:00Z",
                reply_count=4,
                repost_count=12,
                like_count=likes[0],
                quote_count=3,
                url="https://bsky.app/profile/analyst.bsky.social/post/3kforecast",
                source_name="Bluesky @analyst.bsky.social",
                entry_id="at://did:plc:abc/app.bsky.feed.post/3kforecast",
                raw={"likeCount": likes[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_bluesky_posts", fake_load_bluesky_posts)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="bluesky:forecast desk",
    )

    assert watch["source_type"] == "bluesky"
    assert watch["last_seen_signature"].startswith("bluesky:1:")
    assert captured_sources[-1] == "forecast desk"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    likes[0] = 180
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import bluesky "forecast desk" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_reliefweb_source_creates_alert_on_report_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched ReliefWeb search be detected?",
        resolution_criteria="Resolved yes if watched ReliefWeb report changes create alerts.",
    )
    titles = ["Initial flood update"]
    captured_queries = []

    def fake_load_reliefweb_reports(query: str, **kwargs):
        captured_queries.append(query)
        return [
            ReliefWebReport(
                report_id="rw_123",
                title=titles[0],
                summary="Humanitarian partners reported new flooding impacts.",
                url="https://reliefweb.int/report/kenya/flood-response-update",
                published_at="2026-05-21T14:30:00Z",
                changed_at="2026-05-22T09:00:00Z",
                sources=["OCHA"],
                countries=["Kenya"],
                disasters=["Floods"],
                formats=["Situation Report"],
                themes=["Shelter and Non-Food Items"],
                source_name="OCHA",
                entry_id="rw_123",
                raw={"title": titles[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_reliefweb_reports", fake_load_reliefweb_reports)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="reliefweb:Kenya floods",
    )

    assert watch["source_type"] == "reliefweb"
    assert watch["last_seen_signature"].startswith("reliefweb:1:")
    assert captured_queries[-1] == "Kenya floods"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    titles[0] = "Updated flood response"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import reliefweb "Kenya floods" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_federalregister_source_creates_alert_on_document_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched Federal Register documents be detected?",
        resolution_criteria="Resolved yes if watched Federal Register document changes create alerts.",
    )
    titles = ["Initial policy rule"]
    captured_queries = []

    def fake_load_federal_register_documents(query: str, **kwargs):
        captured_queries.append(query)
        return [
            FederalRegisterDocument(
                document_number=str(len(titles[0])),
                title=titles[0],
                abstract="A monitored regulatory document.",
                url=f"https://www.federalregister.gov/documents/2026/05/21/{len(titles[0])}/rule",
                pdf_url=None,
                published_at="2026-05-21T00:00:00Z",
                document_type="Rule",
                agencies=["Department of Forecasting"],
                citation="91 FR 12345",
                source_name="Federal Register",
                entry_id=str(len(titles[0])),
                raw={"title": titles[0]},
            )
        ]

    monkeypatch.setattr(
        "forecasting.source_adapters.load_federal_register_documents",
        fake_load_federal_register_documents,
    )
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="federalregister:forecast desk rule",
    )

    assert watch["source_type"] == "federalregister"
    assert watch["last_seen_signature"].startswith("federalregister:1:")
    assert captured_queries[-1] == "forecast desk rule"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    titles[0] = "Updated policy rule"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert (
        f'forecast import federalregister "forecast desk rule" --question {question.id}'
        in alerts[0].recommended_action
    )
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_courtlistener_source_creates_alert_on_result_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched CourtListener results be detected?",
        resolution_criteria="Resolved yes if watched legal search results create alerts.",
    )
    titles = ["Forecast Desk v. Benchmark"]
    captured_queries = []

    def fake_load_courtlistener_search_results(query: str, **kwargs):
        captured_queries.append(query)
        return [
            CourtListenerSearchResult(
                result_id=str(len(titles[0])),
                title=titles[0],
                snippet="A monitored legal result.",
                url=f"https://www.courtlistener.com/opinion/{len(titles[0])}/forecast/",
                court="Supreme Court of Forecasting",
                court_id="scotus",
                docket_number="24-123",
                date_filed="2026-05-21T00:00:00Z",
                date_argued=None,
                status="Published",
                citation="123 F.4th 456",
                judge="Forecaster, J.",
                cite_count=17,
                search_type="o",
                source_name="CourtListener scotus",
                entry_id=str(len(titles[0])),
                raw={"title": titles[0]},
            )
        ]

    monkeypatch.setattr(
        "forecasting.source_adapters.load_courtlistener_search_results",
        fake_load_courtlistener_search_results,
    )
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="courtlistener:forecast desk",
    )

    assert watch["source_type"] == "courtlistener"
    assert watch["last_seen_signature"].startswith("courtlistener:1:")
    assert captured_queries[-1] == "forecast desk"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    titles[0] = "Updated Legal Result"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert (
        f'forecast import courtlistener "forecast desk" --question {question.id}'
        in alerts[0].recommended_action
    )
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_nvd_source_creates_alert_on_cve_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched NVD CVEs be detected?",
        resolution_criteria="Resolved yes if watched NVD CVE changes create alerts.",
    )
    statuses = ["Analyzed"]
    captured_queries = []

    def fake_load_nvd_cves(query: str, **kwargs):
        captured_queries.append(query)
        return [
            NvdCve(
                cve_id="CVE-2026-12345",
                description="A monitored vulnerability.",
                url="https://nvd.nist.gov/vuln/detail/CVE-2026-12345",
                published_at="2026-05-20T10:00:00Z",
                last_modified_at="2026-05-21T11:00:00Z",
                vuln_status=statuses[0],
                severity="HIGH",
                base_score=8.8,
                cvss_version="3.1",
                references=["https://vendor.example.test/advisory"],
                source_identifier="security@example.test",
                source_name="NVD",
                entry_id="CVE-2026-12345",
                raw={"vulnStatus": statuses[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_nvd_cves", fake_load_nvd_cves)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="nvd:forecast product",
    )

    assert watch["source_type"] == "nvd"
    assert watch["last_seen_signature"].startswith("nvd:1:")
    assert captured_queries[-1] == "forecast product"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    statuses[0] = "Modified"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import nvd "forecast product" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_cisa_kev_source_creates_alert_on_vulnerability_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched CISA KEV records be detected?",
        resolution_criteria="Resolved yes if watched CISA KEV changes create alerts.",
    )
    due_dates = ["2026-06-10T00:00:00Z"]
    captured_sources = []

    def fake_load_cisa_kev_vulnerabilities(source: str, **kwargs):
        captured_sources.append(source)
        return [
            CisaKevVulnerability(
                cve_id="CVE-2026-23456",
                vendor_project="ForecastSoft",
                product="Forecast Server",
                vulnerability_name="ForecastSoft Forecast Server Command Injection",
                short_description="A known exploited command injection vulnerability.",
                date_added="2026-05-20T00:00:00Z",
                due_date=due_dates[0],
                required_action="Apply vendor mitigations.",
                ransomware_use="Known",
                notes="Observed exploitation in the wild.",
                cwes=["CWE-77"],
                source_url="https://cisa.test/kev.json",
                source_name="CISA Known Exploited Vulnerabilities",
                entry_id="CVE-2026-23456",
                raw={"dueDate": due_dates[0]},
            )
        ]

    monkeypatch.setattr(
        "forecasting.source_adapters.load_cisa_kev_vulnerabilities",
        fake_load_cisa_kev_vulnerabilities,
    )
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="cisakev:ForecastSoft",
    )

    assert watch["source_type"] == "cisakev"
    assert watch["last_seen_signature"].startswith("cisakev:1:")
    assert captured_sources[-1] == "ForecastSoft"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    due_dates[0] = "2026-06-17T00:00:00Z"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import cisakev "ForecastSoft" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_openmeteo_source_creates_alert_on_forecast_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched Open-Meteo forecasts be detected?",
        resolution_criteria="Resolved yes if watched Open-Meteo forecast changes create alerts.",
    )
    max_temps = [21.5]
    captured_sources = []

    def fake_load_openmeteo_daily_forecasts(source: str, **kwargs):
        captured_sources.append(source)
        return [
            OpenMeteoDailyForecast(
                latitude=37.77,
                longitude=-122.42,
                forecast_date="2026-05-21",
                temperature_2m_max=max_temps[0],
                temperature_2m_min=12.1,
                precipitation_sum=0.0,
                wind_speed_10m_max=18.0,
                source_name="Open-Meteo",
                entry_id="37.77,-122.42:2026-05-21",
                raw={"temperature_2m_max": max_temps[0]},
            )
        ]

    monkeypatch.setattr(
        "forecasting.source_adapters.load_openmeteo_daily_forecasts",
        fake_load_openmeteo_daily_forecasts,
    )
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="openmeteo:37.77,-122.42",
    )

    assert watch["source_type"] == "openmeteo"
    assert watch["last_seen_signature"].startswith("openmeteo:1:")
    assert captured_sources[-1] == "37.77,-122.42"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    max_temps[0] = 24.0
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import openmeteo 37.77,-122.42 --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_airquality_source_creates_alert_on_forecast_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched air-quality forecasts be detected?",
        resolution_criteria="Resolved yes if watched air-quality forecast changes create alerts.",
    )
    us_aqi_values = [42.0]
    captured_sources = []

    def fake_load_openmeteo_air_quality_forecasts(source: str, **kwargs):
        captured_sources.append(source)
        return [
            OpenMeteoAirQualityForecast(
                latitude=37.77,
                longitude=-122.42,
                forecast_time="2026-05-21T00:00:00Z",
                us_aqi=us_aqi_values[0],
                european_aqi=31.0,
                pm10=12.0,
                pm2_5=8.4,
                carbon_monoxide=220.0,
                nitrogen_dioxide=16.0,
                ozone=80.0,
                source_name="Open-Meteo Air Quality",
                entry_id="37.77,-122.42:2026-05-21T00:00:00Z",
                raw={"us_aqi": us_aqi_values[0]},
            )
        ]

    monkeypatch.setattr(
        "forecasting.source_adapters.load_openmeteo_air_quality_forecasts",
        fake_load_openmeteo_air_quality_forecasts,
    )
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="airquality:37.77,-122.42",
    )

    assert watch["source_type"] == "airquality"
    assert watch["last_seen_signature"].startswith("airquality:1:")
    assert captured_sources[-1] == "37.77,-122.42"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    us_aqi_values[0] = 60.0
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import airquality 37.77,-122.42 --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_weatherhistory_source_creates_alert_on_observation_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched historical weather be detected?",
        resolution_criteria="Resolved yes if watched historical weather changes create alerts.",
    )
    mean_temps = [16.2]
    captured_sources = []

    def fake_load_openmeteo_historical_weather(source: str, **kwargs):
        captured_sources.append(source)
        return [
            OpenMeteoHistoricalWeatherObservation(
                latitude=37.77,
                longitude=-122.42,
                observation_date="2026-05-20",
                temperature_2m_mean=mean_temps[0],
                temperature_2m_max=21.5,
                temperature_2m_min=12.1,
                precipitation_sum=0.0,
                wind_speed_10m_max=18.0,
                source_name="Open-Meteo Historical Weather",
                entry_id="37.77,-122.42:2026-05-20",
                raw={"temperature_2m_mean": mean_temps[0]},
            )
        ]

    monkeypatch.setattr(
        "forecasting.source_adapters.load_openmeteo_historical_weather",
        fake_load_openmeteo_historical_weather,
    )
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="weatherhistory:37.77,-122.42?start=2026-05-20&end=2026-05-21",
    )

    assert watch["source_type"] == "weatherhistory"
    assert watch["last_seen_signature"].startswith("weatherhistory:1:")
    assert captured_sources[-1] == "37.77,-122.42?start=2026-05-20&end=2026-05-21"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    mean_temps[0] = 18.0
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert (
        f"forecast import weatherhistory 37.77,-122.42 --start-date 2026-05-20 "
        f"--end-date 2026-05-21 --question {question.id}"
    ) in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_usgs_source_creates_alert_on_event_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched USGS events be detected?",
        resolution_criteria="Resolved yes if watched USGS event changes create alerts.",
    )
    magnitudes = [5.7]
    captured_sources = []

    def fake_load_usgs_earthquakes(source: str, **kwargs):
        captured_sources.append(source)
        return [
            UsgsEarthquakeEvent(
                event_id="us7000abcd",
                title=f"M {magnitudes[0]} - Testville",
                url="https://earthquake.usgs.gov/earthquakes/eventpage/us7000abcd",
                time="2026-05-20T00:00:00Z",
                updated_at="2026-05-20T01:00:00Z",
                magnitude=magnitudes[0],
                place="Testville",
                event_type="earthquake",
                status="reviewed",
                tsunami=0,
                significance=500,
                longitude=-122.4,
                latitude=37.7,
                depth_km=8.5,
                source_name="USGS Earthquake Catalog",
                entry_id="us7000abcd",
                raw={"magnitude": magnitudes[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_usgs_earthquakes", fake_load_usgs_earthquakes)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="usgs:minmagnitude=5",
    )

    assert watch["source_type"] == "usgs"
    assert watch["last_seen_signature"].startswith("usgs:1:")
    assert captured_sources[-1] == "minmagnitude=5"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    magnitudes[0] = 6.1
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import usgs "minmagnitude=5" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_eonet_source_creates_alert_on_event_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched EONET events be detected?",
        resolution_criteria="Resolved yes if watched EONET event changes create alerts.",
    )
    titles = ["Wildfire near Test Ridge"]
    captured_sources = []

    def fake_load_nasa_eonet_events(source: str, **kwargs):
        captured_sources.append(source)
        return [
            NasaEonetEvent(
                event_id="EONET_123",
                title=titles[0],
                description="A public hazard event.",
                url="https://eonet.gsfc.nasa.gov/api/v3/events/EONET_123",
                status="open",
                closed_at=None,
                latest_geometry_at="2026-05-20T00:00:00Z",
                categories=["Wildfires"],
                source_names=["NASA"],
                source_urls=[],
                longitude=-121.2,
                latitude=38.5,
                source_name="NASA EONET",
                entry_id="EONET_123",
                raw={"title": titles[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_nasa_eonet_events", fake_load_nasa_eonet_events)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="eonet:category=wildfires&status=open",
    )

    assert watch["source_type"] == "eonet"
    assert watch["last_seen_signature"].startswith("eonet:1:")
    assert captured_sources[-1] == "category=wildfires&status=open"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    titles[0] = "Updated wildfire near Test Ridge"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import eonet "category=wildfires&status=open" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_nws_source_creates_alert_on_weather_alert_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched NWS alerts be detected?",
        resolution_criteria="Resolved yes if watched NWS alert changes create alerts.",
    )
    severities = ["Moderate"]
    captured_sources = []

    def fake_load_nws_alerts(source: str, **kwargs):
        captured_sources.append(source)
        return [
            NwsAlert(
                alert_id="urn:oid:alert-1",
                event="Flood Warning",
                headline=f"Flood Warning severity {severities[0]}",
                description="Flooding is possible.",
                instruction="Avoid flooded roads.",
                url="https://api.weather.gov/alerts/urn:oid:alert-1",
                area_desc="Test County",
                severity=severities[0],
                certainty="Likely",
                urgency="Expected",
                status="Actual",
                message_type="Alert",
                category="Met",
                response="Avoid",
                sent_at="2026-05-20T12:00:00Z",
                effective_at="2026-05-20T12:05:00Z",
                onset_at=None,
                expires_at="2026-05-20T18:00:00Z",
                ends_at=None,
                source_name="National Weather Service",
                entry_id="urn:oid:alert-1",
                raw={"severity": severities[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_nws_alerts", fake_load_nws_alerts)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="nws:area=CA&event=Flood Warning",
    )

    assert watch["source_type"] == "nws"
    assert watch["last_seen_signature"].startswith("nws:1:")
    assert captured_sources[-1] == "area=CA&event=Flood Warning"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    severities[0] = "Severe"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import nws "area=CA&event=Flood Warning" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_clinicaltrials_source_creates_alert_on_study_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched ClinicalTrials.gov studies be detected?",
        resolution_criteria="Resolved yes if watched clinical trial changes create alerts.",
    )
    statuses = ["RECRUITING"]
    captured_sources = []

    def fake_load_clinicaltrials_studies(source: str, **kwargs):
        captured_sources.append(source)
        return [
            ClinicalTrialStudy(
                nct_id="NCT01234567",
                brief_title=f"Trial status {statuses[0]}",
                official_title="A test oncology trial",
                url="https://clinicaltrials.gov/study/NCT01234567",
                status=statuses[0],
                phases=["PHASE2"],
                study_type="INTERVENTIONAL",
                conditions=["Lung Cancer"],
                interventions=["Drug A"],
                sponsors=["Acme Bio"],
                start_date="2026-01-01T00:00:00Z",
                primary_completion_date="2027-06-30T00:00:00Z",
                completion_date=None,
                last_update_submitted_at="2026-05-20T00:00:00Z",
                last_update_posted_at="2026-05-21T00:00:00Z",
                has_results=False,
                source_name="ClinicalTrials.gov",
                entry_id="NCT01234567",
                raw={"status": statuses[0]},
            )
        ]

    monkeypatch.setattr(
        "forecasting.source_adapters.load_clinicaltrials_studies",
        fake_load_clinicaltrials_studies,
    )
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="clinicaltrials:NCT01234567",
    )

    assert watch["source_type"] == "clinicaltrials"
    assert watch["last_seen_signature"].startswith("clinicaltrials:1:")
    assert captured_sources[-1] == "NCT01234567"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    statuses[0] = "ACTIVE_NOT_RECRUITING"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import clinicaltrials "NCT01234567" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_openfda_source_creates_alert_on_application_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched openFDA applications be detected?",
        resolution_criteria="Resolved yes if watched FDA application changes create alerts.",
    )
    statuses = ["AP"]
    captured_sources = []

    def fake_load_openfda_drug_applications(source: str, **kwargs):
        captured_sources.append(source)
        return [
            OpenFdaDrugApplication(
                application_number="BLA125514",
                sponsor_name="ACME BIO",
                brand_names=["TESTMAB"],
                generic_names=["testimab"],
                routes=["INTRAVENOUS"],
                substances=["TESTIMAB"],
                dosage_forms=["INJECTION"],
                marketing_statuses=["Prescription"],
                latest_submission_status=statuses[0],
                latest_submission_status_date="2026-05-21T00:00:00Z",
                latest_submission_type="ORIG",
                latest_submission_class="TYPE 1",
                url="https://www.accessdata.fda.gov/test-label.pdf",
                source_name="openFDA Drugs@FDA",
                entry_id="BLA125514",
                raw={"status": statuses[0]},
            )
        ]

    monkeypatch.setattr(
        "forecasting.source_adapters.load_openfda_drug_applications",
        fake_load_openfda_drug_applications,
    )
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="openfda:BLA125514",
    )

    assert watch["source_type"] == "openfda"
    assert watch["last_seen_signature"].startswith("openfda:1:")
    assert captured_sources[-1] == "BLA125514"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    statuses[0] = "TA"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import openfda "BLA125514" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_pubmed_source_creates_alert_on_article_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched PubMed articles be detected?",
        resolution_criteria="Resolved yes if watched PubMed article changes create alerts.",
    )
    titles = ["Initial PubMed article"]
    captured_queries = []

    def fake_load_pubmed_articles(query: str, **kwargs):
        captured_queries.append(query)
        return [
            PubMedArticle(
                pmid="12345678",
                title=titles[0],
                abstract="A biomedical article about forecasting.",
                journal="Journal of Forecasting Medicine",
                url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
                doi="10.1234/pubmed.forecast",
                published_at="2026-05-21T00:00:00Z",
                revised_at="2026-05-22T00:00:00Z",
                authors=["Ada Forecaster"],
                publication_types=["Journal Article"],
                source_name="PubMed",
                entry_id="12345678",
                raw={"title": titles[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_pubmed_articles", fake_load_pubmed_articles)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="pubmed:forecasting calibration",
    )

    assert watch["source_type"] == "pubmed"
    assert watch["last_seen_signature"].startswith("pubmed:1:")
    assert captured_queries[-1] == "forecasting calibration"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    titles[0] = "New PubMed article"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import pubmed "forecasting calibration" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_pypi_source_creates_alert_on_release_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched PyPI releases be detected?",
        resolution_criteria="Resolved yes if watched PyPI release changes create alerts.",
    )
    versions = ["1.2.3"]
    captured_sources = []

    def fake_load_pypi_releases(source: str, **kwargs):
        captured_sources.append(source)
        return [
            PypiRelease(
                package=source,
                version=versions[0],
                summary="Forecasting command line tools.",
                url=f"https://pypi.org/project/{source}/{versions[0]}/",
                project_url=f"https://pypi.org/project/{source}/",
                uploaded_at="2026-05-21T11:00:00Z",
                latest_upload_at="2026-05-21T11:05:00Z",
                file_count=2,
                package_types=["bdist_wheel", "sdist"],
                python_versions=["py3", "source"],
                yanked=False,
                yanked_reason=None,
                source_name="PyPI",
                entry_id=f"{source}:{versions[0]}",
                raw={"version": versions[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_pypi_releases", fake_load_pypi_releases)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="pypi:forecast-desk",
    )

    assert watch["source_type"] == "pypi"
    assert watch["last_seen_signature"].startswith("pypi:1:")
    assert captured_sources[-1] == "forecast-desk"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    versions[0] = "1.2.4"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import pypi forecast-desk --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_npm_source_creates_alert_on_version_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched npm package versions be detected?",
        resolution_criteria="Resolved yes if watched npm package changes create alerts.",
    )
    versions = ["2.0.0"]
    captured_sources = []

    def fake_load_npm_versions(source: str, **kwargs):
        captured_sources.append(source)
        return [
            NpmPackageVersion(
                package=source,
                version=versions[0],
                description="Forecasting interface components.",
                url=f"https://www.npmjs.com/package/{source}/v/{versions[0]}",
                tarball_url=f"https://registry.npm.test/{source}/-/{versions[0]}.tgz",
                published_at="2026-05-21T11:00:00Z",
                license="Apache-2.0",
                maintainers=["analyst"],
                keywords=["forecasting"],
                deprecated=None,
                dependency_count=2,
                source_name="npm",
                entry_id=f"{source}:{versions[0]}",
                raw={"version": versions[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_npm_package_versions", fake_load_npm_versions)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="npm:@forecast/desk",
    )

    assert watch["source_type"] == "npm"
    assert watch["last_seen_signature"].startswith("npm:1:")
    assert captured_sources[-1] == "@forecast/desk"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    versions[0] = "2.1.0"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import npm @forecast/desk --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_owid_source_creates_alert_on_observation_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched OWID observations be detected?",
        resolution_criteria="Resolved yes if watched OWID observation changes create alerts.",
    )
    values = [67_000.0]
    captured_sources = []

    def fake_load_owid_observations(source: str, **kwargs):
        captured_sources.append(source)
        return [
            OwidObservation(
                slug="gdp-per-capita",
                entity="United States",
                code="USA",
                observation_date="2025",
                value=values[0],
                value_column="gdp_per_capita",
                published_at="2025-01-01T00:00:00Z",
                source_url="https://ourworldindata.org/grapher/gdp-per-capita.csv",
                source_name="Our World in Data",
                entry_id="gdp-per-capita:United States:2025",
                raw={"value": values[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_owid_observations", fake_load_owid_observations)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="owid:gdp-per-capita",
    )

    assert watch["source_type"] == "owid"
    assert watch["last_seen_signature"].startswith("owid:1:")
    assert captured_sources[-1] == "gdp-per-capita"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    values[0] = 68_000.0
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import owid gdp-per-capita --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_fred_source_creates_alert_on_observation_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched FRED changes be detected?",
        resolution_criteria="Resolved yes if watched FRED observation changes create alerts.",
    )
    values = [4.1]
    captured_series = []

    def fake_load_fred_observations(series_id: str, **kwargs):
        captured_series.append(series_id)
        return [
            FredObservation(
                series_id=series_id,
                observation_date="2026-03-01",
                value=values[0],
                published_at="2026-03-01T00:00:00Z",
                source_url=f"https://fred.stlouisfed.org/series/{series_id}",
                source_name="FRED",
                entry_id=f"{series_id}:2026-03-01",
                raw={"observation_date": "2026-03-01", series_id: str(values[0])},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_fred_observations", fake_load_fred_observations)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="fred:UNRATE",
    )

    assert watch["source_type"] == "fred"
    assert watch["last_seen_signature"].startswith("fred:1:")
    assert captured_series[-1] == "UNRATE"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    values[0] = 4.2
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-02T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import fred UNRATE --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-02T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_eia_source_creates_alert_on_observation_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched EIA changes be detected?",
        resolution_criteria="Resolved yes if watched EIA observation changes create alerts.",
    )
    values = [72.1]
    captured_sources = []

    def fake_load_eia_observations(source: str, **kwargs):
        captured_sources.append(source)
        return [
            EiaObservation(
                series_id=source,
                series_name="WTI crude oil spot price",
                observation_period="2026-03",
                value=values[0],
                unit="dollars per barrel",
                published_at="2026-03-01T00:00:00Z",
                source_url=f"https://api.eia.gov/series/?series_id={source}",
                source_name="EIA",
                entry_id=f"{source}:2026-03",
                raw={"period": "2026-03", "value": str(values[0])},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_eia_observations", fake_load_eia_observations)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="eia:PET.RWTC.M",
    )

    assert watch["source_type"] == "eia"
    assert watch["last_seen_signature"].startswith("eia:1:")
    assert captured_sources[-1] == "PET.RWTC.M"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    values[0] = 73.4
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-02T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import eia PET.RWTC.M --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-02T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_treasury_source_creates_alert_on_record_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched Treasury Fiscal Data changes be detected?",
        resolution_criteria="Resolved yes if watched Treasury Fiscal Data records create alerts.",
    )
    values = [4.25]
    captured_sources = []

    def fake_load_treasury_records(source: str, **kwargs):
        captured_sources.append(source)
        return [
            TreasuryRecord(
                dataset=source,
                record_date="2026-04-01",
                value=values[0],
                value_field="avg_interest_rate_amt",
                value_label="Average Interest Rate",
                published_at="2026-04-01T00:00:00Z",
                source_url=f"https://api.fiscaldata.treasury.gov/services/api/fiscal_service/{source}",
                source_name="U.S. Treasury Fiscal Data",
                entry_id=f"{source}:2026-04-01:0",
                raw={"record_date": "2026-04-01", "avg_interest_rate_amt": str(values[0])},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_treasury_records", fake_load_treasury_records)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="treasury:v2/accounting/od/avg_interest_rates",
    )

    assert watch["source_type"] == "treasury"
    assert watch["last_seen_signature"].startswith("treasury:1:")
    assert captured_sources[-1] == "v2/accounting/od/avg_interest_rates"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    values[0] = 4.4
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-02T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import treasury v2/accounting/od/avg_interest_rates --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-02T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_bls_source_creates_alert_on_observation_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched BLS changes be detected?",
        resolution_criteria="Resolved yes if watched BLS observation changes create alerts.",
    )
    values = [4.1]
    captured_series = []

    def fake_load_bls_observations(series_id: str, **kwargs):
        captured_series.append(series_id)
        return [
            BlsObservation(
                series_id=series_id,
                observation_date="2026-03-01",
                period="M03",
                period_name="March",
                value=values[0],
                published_at="2026-03-01T00:00:00Z",
                source_url=f"https://data.bls.gov/timeseries/{series_id}",
                source_name="BLS",
                entry_id=f"{series_id}:2026:M03",
                raw={"year": "2026", "period": "M03", "value": str(values[0])},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_bls_observations", fake_load_bls_observations)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="bls:LNS14000000",
    )

    assert watch["source_type"] == "bls"
    assert watch["last_seen_signature"].startswith("bls:1:")
    assert captured_series[-1] == "LNS14000000"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    values[0] = 4.2
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-02T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import bls LNS14000000 --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-02T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_worldbank_source_creates_alert_on_observation_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched World Bank changes be detected?",
        resolution_criteria="Resolved yes if watched World Bank observations create alerts.",
    )
    values = [28_000_000_000_000.0]
    captured_sources = []

    def fake_load_worldbank_observations(source: str, **kwargs):
        captured_sources.append(source)
        return [
            WorldBankObservation(
                country="US",
                country_name="United States",
                indicator="NY.GDP.MKTP.CD",
                indicator_name="GDP (current US$)",
                observation_date="2025-12-31",
                value=values[0],
                published_at="2025-12-31T00:00:00Z",
                source_url="https://data.worldbank.org/indicator/NY.GDP.MKTP.CD?locations=US",
                source_name="World Bank",
                entry_id="US:NY.GDP.MKTP.CD:2025",
                raw={"date": "2025", "value": str(values[0])},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_worldbank_observations", fake_load_worldbank_observations)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="worldbank:USA/NY.GDP.MKTP.CD",
    )

    assert watch["source_type"] == "worldbank"
    assert watch["last_seen_signature"].startswith("worldbank:1:")
    assert captured_sources[-1] == "USA/NY.GDP.MKTP.CD"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    values[0] = 30_000_000_000_000.0
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-02T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import worldbank USA/NY.GDP.MKTP.CD --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-02T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_census_source_creates_alert_on_record_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched Census changes be detected?",
        resolution_criteria="Resolved yes if watched Census records create alerts.",
    )
    values = [39_100_000.0]
    captured_sources = []

    def fake_load_census_records(source: str, **kwargs):
        captured_sources.append(source)
        return [
            CensusRecord(
                dataset="2023/acs/acs5",
                dataset_year=2023,
                observation_date="2023-12-31",
                values={"NAME": "California", "B01003_001E": values[0]},
                geography={"state": "06"},
                published_at="2023-12-31T00:00:00Z",
                source_url="https://api.census.gov/data/2023/acs/acs5?get=NAME,B01003_001E&for=state:*",
                source_name="U.S. Census Bureau",
                entry_id="2023/acs/acs5:2023-12-31:0",
                raw={"row_index": 0, "value": str(values[0])},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_census_records", fake_load_census_records)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="census:2023/acs/acs5?get=NAME,B01003_001E&for=state:*",
    )

    assert watch["source_type"] == "census"
    assert watch["last_seen_signature"].startswith("census:1:")
    assert captured_sources[-1] == "2023/acs/acs5?get=NAME,B01003_001E&for=state:*"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    values[0] = 39_200_000.0
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert (
        f'forecast import census "2023/acs/acs5?get=NAME,B01003_001E&for=state:*" --question {question.id}'
        in alerts[0].recommended_action
    )
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_socrata_source_creates_alert_on_record_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched Socrata changes be detected?",
        resolution_criteria="Resolved yes if watched Socrata records create alerts.",
    )
    cases = ["42"]
    captured_sources = []

    def fake_load_socrata_records(source: str, **kwargs):
        captured_sources.append(source)
        return [
            SocrataRecord(
                domain="data.cdc.gov",
                dataset_id="abcd-1234",
                row_id="row-1",
                observation_time="2026-05-20T00:00:00Z",
                updated_at="2026-05-21T11:00:00Z",
                values={"report_date": "2026-05-20", "county": "King", "cases": cases[0]},
                source_url="https://data.cdc.gov/resource/abcd-1234.json?county=King",
                source_name="Socrata",
                entry_id="data.cdc.gov/abcd-1234:row-1",
                raw={"cases": cases[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_socrata_records", fake_load_socrata_records)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="socrata:data.cdc.gov/abcd-1234?county=King",
    )

    assert watch["source_type"] == "socrata"
    assert watch["last_seen_signature"].startswith("socrata:1:")
    assert captured_sources[-1] == "data.cdc.gov/abcd-1234?county=King"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    cases[0] = "43"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert (
        f'forecast import socrata "data.cdc.gov/abcd-1234?county=King" --question {question.id}'
        in alerts[0].recommended_action
    )
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_stooq_source_creates_alert_on_price_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched Stooq prices be detected?",
        resolution_criteria="Resolved yes if watched Stooq price changes create alerts.",
    )
    close_prices = [198.4]
    captured_sources = []

    def fake_load_stooq_prices(source: str, **kwargs):
        captured_sources.append(source)
        return [
            StooqPriceObservation(
                symbol=source,
                interval="d",
                observation_date="2026-05-22",
                open_price=197.2,
                high_price=199.0,
                low_price=196.8,
                close_price=close_prices[0],
                volume=62000000,
                published_at="2026-05-22T00:00:00Z",
                source_url=f"https://stooq.test/q/d/l/?s={source.lower()}&i=d",
                source_name="Stooq",
                entry_id=f"{source}:d:2026-05-22",
                raw={"Date": "2026-05-22", "Close": str(close_prices[0])},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_stooq_prices", fake_load_stooq_prices)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="stooq:AAPL.US",
    )

    assert watch["source_type"] == "stooq"
    assert watch["last_seen_signature"].startswith("stooq:1:")
    assert captured_sources[-1] == "AAPL.US"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    close_prices[0] = 201.2
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-23T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import stooq AAPL.US --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-23T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_yahoo_source_creates_alert_on_price_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched Yahoo Finance prices be detected?",
        resolution_criteria="Resolved yes if watched Yahoo Finance price changes create alerts.",
    )
    close_prices = [199.1]

    def fake_load_yahoo_finance_prices(source: str, **kwargs):
        return [
            YahooFinancePriceObservation(
                symbol=source,
                interval="1d",
                observation_time="2026-05-23T00:00:00Z",
                open_price=198.0,
                high_price=200.0,
                low_price=197.5,
                close_price=close_prices[0],
                volume=63000000,
                published_at="2026-05-23T00:00:00Z",
                currency="USD",
                exchange_name="NMS",
                source_url=f"https://finance.yahoo.com/quote/{source}",
                source_name="Yahoo Finance",
                entry_id=f"{source}:1d:2026-05-23T00:00:00Z",
                raw={"Close": close_prices[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_yahoo_finance_prices", fake_load_yahoo_finance_prices)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="yahoo:AAPL",
    )

    assert watch["source_type"] == "yahoo"
    assert watch["last_seen_signature"].startswith("yahoo:1:")

    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    close_prices[0] = 201.2
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-24T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import yahoo AAPL --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-24T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_sec_source_creates_alert_on_filing_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched SEC filings be detected?",
        resolution_criteria="Resolved yes if watched SEC filing changes create alerts.",
    )
    forms = ["10-Q"]
    captured_sources = []

    def fake_load_sec_filings(source: str, **kwargs):
        captured_sources.append(source)
        return [
            SecFiling(
                cik="0000320193",
                company_name="Apple Inc.",
                ticker="AAPL",
                form=forms[0],
                filing_date="2026-02-01",
                report_date="2025-12-31",
                acceptance_time="2026-02-01T16:30:00.000Z",
                published_at="2026-02-01T16:30:00Z",
                accession_number=f"0000320193-26-0000{len(forms[0])}",
                primary_document="aapl-20251231.htm",
                description=f"FORM {forms[0]}",
                source_url="https://www.sec.gov/Archives/edgar/data/320193/000032019326000010/aapl-20251231.htm",
                source_name="SEC EDGAR",
                entry_id=f"0000320193:0000320193-26-0000{len(forms[0])}",
                raw={"form": forms[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_sec_filings", fake_load_sec_filings)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="sec:0000320193",
    )

    assert watch["source_type"] == "sec"
    assert watch["last_seen_signature"].startswith("sec:1:")
    assert captured_sources[-1] == "0000320193"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    forms[0] = "8-K"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-02T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import sec 0000320193 --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-02T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_sec_company_facts_source_creates_alert_on_observation_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched SEC company facts be detected?",
        resolution_criteria="Resolved yes if watched SEC company facts changes create alerts.",
    )
    values = [391035000000]
    captured_sources = []

    def fake_load_sec_company_facts(source: str, **kwargs):
        captured_sources.append(source)
        return [
            SecCompanyFact(
                cik="0000320193",
                company_name="Apple Inc.",
                taxonomy="us-gaap",
                concept="Revenues",
                label="Revenues",
                description="Revenue from contract with customer.",
                unit="USD",
                observation_date="2025-09-27",
                value=values[0],
                filed_at="2025-10-31T00:00:00Z",
                published_at="2025-10-31T00:00:00Z",
                form="10-K",
                fiscal_year=2025,
                fiscal_period="FY",
                accession_number=f"0000320193-25-{values[0]}",
                frame="CY2025",
                source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
                source_name="SEC Company Facts",
                entry_id=f"0000320193:us-gaap:Revenues:USD:2025-09-27:{values[0]}",
                raw={"value": values[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_sec_company_facts", fake_load_sec_company_facts)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="secfacts:0000320193/Revenues",
    )

    assert watch["source_type"] == "secfacts"
    assert watch["last_seen_signature"].startswith("secfacts:1:")
    assert captured_sources[-1] == "0000320193/Revenues"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    values[0] = 400000000000
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-02T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f"forecast import secfacts 0000320193/Revenues --question {question.id}" in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-02T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_arxiv_source_creates_alert_on_paper_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched arXiv papers be detected?",
        resolution_criteria="Resolved yes if watched arXiv paper changes create alerts.",
    )
    titles = ["Initial forecasting paper"]
    captured_queries = []

    def fake_load_arxiv_papers(query: str, **kwargs):
        captured_queries.append(query)
        return [
            ArxivPaper(
                arxiv_id=f"2605.{len(titles[0]):05d}v1",
                title=titles[0],
                abstract="A paper about forecasting.",
                url=f"https://arxiv.org/abs/2605.{len(titles[0]):05d}v1",
                pdf_url=None,
                published_at="2026-05-20T12:00:00Z",
                updated_at="2026-05-21T12:00:00Z",
                authors=["Ada Forecaster"],
                categories=["cs.AI"],
                source_name="arXiv",
                entry_id=f"https://arxiv.org/abs/2605.{len(titles[0]):05d}v1",
                raw={"title": titles[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_arxiv_papers", fake_load_arxiv_papers)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="arxiv:cat:cs.AI AND forecasting",
    )

    assert watch["source_type"] == "arxiv"
    assert watch["last_seen_signature"].startswith("arxiv:1:")
    assert captured_queries[-1] == "cat:cs.AI AND forecasting"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    titles[0] = "New forecasting paper"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import arxiv "cat:cs.AI AND forecasting" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_openalex_source_creates_alert_on_work_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched OpenAlex works be detected?",
        resolution_criteria="Resolved yes if watched OpenAlex work changes create alerts.",
    )
    titles = ["Initial scholarly work"]
    captured_queries = []

    def fake_load_openalex_works(query: str, **kwargs):
        captured_queries.append(query)
        return [
            OpenAlexWork(
                work_id=f"https://openalex.org/W{len(titles[0])}",
                title=titles[0],
                abstract="A scholarly work about forecasting.",
                url=f"https://doi.org/10.0000/{len(titles[0])}",
                doi=f"https://doi.org/10.0000/{len(titles[0])}",
                published_at="2026-05-20T00:00:00Z",
                updated_at="2026-05-21T00:00:00Z",
                authors=["Ada Forecaster"],
                concepts=["Forecasting"],
                source_name="OpenAlex",
                entry_id=f"https://openalex.org/W{len(titles[0])}",
                raw={"title": titles[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_openalex_works", fake_load_openalex_works)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="openalex:forecasting calibration",
    )

    assert watch["source_type"] == "openalex"
    assert watch["last_seen_signature"].startswith("openalex:1:")
    assert captured_queries[-1] == "forecasting calibration"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    titles[0] = "New scholarly work"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import openalex "forecasting calibration" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_crossref_source_creates_alert_on_work_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched Crossref works be detected?",
        resolution_criteria="Resolved yes if watched Crossref work changes create alerts.",
    )
    titles = ["Initial DOI work"]
    captured_queries = []

    def fake_load_crossref_works(query: str, **kwargs):
        captured_queries.append(query)
        return [
            CrossrefWork(
                doi=f"10.0000/{len(titles[0])}",
                title=titles[0],
                abstract="A DOI-indexed work about forecasting.",
                url=f"https://doi.org/10.0000/{len(titles[0])}",
                published_at="2026-05-20T00:00:00Z",
                updated_at="2026-05-21T00:00:00Z",
                authors=["Ada Forecaster"],
                subjects=["Forecasting"],
                container_title="Journal of Forecasting",
                publisher="Forecasting Society",
                work_type="journal-article",
                reference_count=12,
                cited_by_count=7,
                source_name="Journal of Forecasting",
                entry_id=f"10.0000/{len(titles[0])}",
                raw={"title": titles[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_crossref_works", fake_load_crossref_works)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="crossref:forecasting calibration",
    )

    assert watch["source_type"] == "crossref"
    assert watch["last_seen_signature"].startswith("crossref:1:")
    assert captured_queries[-1] == "forecasting calibration"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    titles[0] = "New DOI work"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import crossref "forecasting calibration" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_wikipedia_source_creates_alert_on_page_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched Wikipedia pages be detected?",
        resolution_criteria="Resolved yes if watched Wikipedia page changes create alerts.",
    )
    titles = ["Initial page"]
    captured_queries = []

    def fake_load_wikipedia_pages(query: str, **kwargs):
        captured_queries.append(query)
        return [
            WikipediaPage(
                page_id=str(len(titles[0])),
                title=titles[0],
                extract="A reference page about forecasting.",
                url=f"https://en.wikipedia.org/wiki/{titles[0].replace(' ', '_')}",
                updated_at="2026-05-21T00:00:00Z",
                source_name="Wikipedia",
                entry_id=str(len(titles[0])),
                raw={"title": titles[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_wikipedia_pages", fake_load_wikipedia_pages)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="wikipedia:forecasting calibration",
    )

    assert watch["source_type"] == "wikipedia"
    assert watch["last_seen_signature"].startswith("wikipedia:1:")
    assert captured_queries[-1] == "forecasting calibration"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    titles[0] = "Updated page"
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import wikipedia "forecasting calibration" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_watched_wikimedia_pageviews_source_creates_alert_on_view_change(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will watched Wikimedia pageviews be detected?",
        resolution_criteria="Resolved yes if watched Wikimedia pageview changes create alerts.",
    )
    views = [1234]
    captured_sources = []

    def fake_load_wikimedia_pageviews(source: str, **kwargs):
        captured_sources.append(source)
        return [
            WikimediaPageviewObservation(
                project="en.wikipedia.org",
                article="Artificial_intelligence",
                access="all-access",
                agent="user",
                granularity="daily",
                observation_date="2026-05-01",
                views=views[0],
                published_at="2026-05-01T00:00:00Z",
                source_url=f"https://wikimedia.org/pageviews/{source}",
                source_name="Wikimedia Pageviews",
                entry_id=f"{source}:2026-05-01",
                raw={"views": views[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_wikimedia_pageviews", fake_load_wikimedia_pageviews)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="wikipediapageviews:en.wikipedia.org/Artificial_intelligence",
    )

    assert watch["source_type"] == "wikipediapageviews"
    assert watch["last_seen_signature"].startswith("wikipediapageviews:1:")
    assert captured_sources[-1] == "en.wikipedia.org/Artificial_intelligence"
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    views[0] = 2345
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert (
        f"forecast import wikipediapageviews en.wikipedia.org/Artificial_intelligence --question {question.id}"
        in alerts[0].recommended_action
    )
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


@pytest.mark.parametrize(
    ("source_type", "source_value", "loader_path"),
    [
        ("manifold", "market-slug", "forecasting.source_adapters.load_manifold_market"),
        ("metaculus", "12345", "forecasting.source_adapters.load_metaculus_question"),
        ("polymarket", "poly-slug", "forecasting.source_adapters.load_polymarket_market"),
        ("kalshi", "KXWATCH-26", "forecasting.source_adapters.load_kalshi_market"),
    ],
)
def test_watched_market_prior_source_creates_alert_on_probability_change(
    tmp_path,
    monkeypatch,
    source_type,
    source_value,
    loader_path,
):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title=f"Will watched {source_type} priors be detected?",
        resolution_criteria=f"Resolved yes if watched {source_type} prior changes create alerts.",
    )
    values = [0.55]
    captured_sources = []

    def fake_load_market(source: str, **kwargs):
        captured_sources.append(source)
        return _watch_market_item(source_type, values[0])

    monkeypatch.setattr(loader_path, fake_load_market)
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source=f"{source_type}:{source_value}",
    )

    assert watch["source_type"] == source_type
    assert watch["last_seen_signature"].startswith(f"{source_type}:1:")
    assert captured_sources[-1] == source_value
    assert ledger.check_watched_sources(scope_type="question", scope_ref=question.id) == []

    values[0] = 0.63
    alerts = ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-22T00:00:00Z",
    )

    assert [alert.scope_ref for alert in alerts] == [question.id]
    assert alerts[0].reason == f"watched_source_changed:{watch['id']}"
    assert f'forecast import {source_type} "{source_value}" --question {question.id}' in alerts[0].recommended_action
    updated = ledger.get_watched_source(watch["id"])
    assert updated["last_checked_at"] == "2026-05-22T00:00:00Z"
    assert updated["last_seen_signature"] != watch["last_seen_signature"]


def test_scheduled_review_includes_watched_source_alerts(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will scheduled watches create alerts?",
        resolution_criteria="Resolved yes if scheduled watches create alerts.",
        next_review_at="2026-01-20T00:00:00Z",
    )
    source = tmp_path / "domain-source.txt"
    source.write_text("first", encoding="utf-8")
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source=str(source),
    )
    ledger.schedule_review(
        scope_type="question",
        scope_ref=question.id,
        cadence="1d",
        next_run_at="2026-01-02T00:00:00Z",
    )

    source.write_text("second", encoding="utf-8")
    results = ledger.run_due_scheduled_reviews(now="2026-01-10T00:00:00Z")

    assert f"watched_source_changed:{watch['id']}" in {alert.reason for alert in results[0]["alerts"]}


def test_portfolio_scheduled_review_only_checks_matching_questions(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    alpha = ledger.create_question(
        title="Will alpha portfolio question need review?",
        resolution_criteria="Resolved yes if alpha is reviewed.",
        tags=["portfolio:alpha"],
        next_review_at="2026-01-01T00:00:00Z",
    )
    beta = ledger.create_question(
        title="Will beta portfolio question be ignored?",
        resolution_criteria="Resolved yes if beta is ignored by alpha.",
        tags=["portfolio:beta"],
        next_review_at="2026-01-01T00:00:00Z",
    )
    ledger.schedule_review(
        scope_type="portfolio",
        scope_ref="alpha",
        cadence="1d",
        next_run_at="2026-01-02T00:00:00Z",
    )

    results = ledger.run_due_scheduled_reviews(now="2026-01-10T00:00:00Z")
    alert_refs = {alert.scope_ref for alert in results[0]["alerts"]}

    assert alpha.id in alert_refs
    assert beta.id not in alert_refs


def test_domain_topic_scheduled_review_filters_on_both_fields(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    matching = ledger.create_question(
        title="Will matching domain topic be reviewed?",
        resolution_criteria="Resolved yes if matching domain/topic creates an alert.",
        domain="biotech",
        topics=["regulatory"],
        next_review_at="2026-01-01T00:00:00Z",
    )
    wrong_topic = ledger.create_question(
        title="Will wrong topic be ignored?",
        resolution_criteria="Resolved yes if wrong topic is ignored.",
        domain="biotech",
        topics=["clinical"],
        next_review_at="2026-01-01T00:00:00Z",
    )
    wrong_domain = ledger.create_question(
        title="Will wrong domain be ignored?",
        resolution_criteria="Resolved yes if wrong domain is ignored.",
        domain="macro",
        topics=["regulatory"],
        next_review_at="2026-01-01T00:00:00Z",
    )
    ledger.schedule_review(
        scope_type="domain_topic",
        scope_ref='{"domain":"biotech","topic":"regulatory"}',
        cadence="1d",
        next_run_at="2026-01-02T00:00:00Z",
    )

    results = ledger.run_due_scheduled_reviews(now="2026-01-10T00:00:00Z")
    alert_refs = {alert.scope_ref for alert in results[0]["alerts"]}

    assert matching.id in alert_refs
    assert wrong_topic.id not in alert_refs
    assert wrong_domain.id not in alert_refs


def test_horizon_scheduled_review_filters_on_forecast_horizon(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    short_horizon = ledger.create_question(
        title="Will short horizon scheduled review run?",
        resolution_criteria="Resolved yes if short horizon creates an alert.",
        close_time="2026-01-25T00:00:00Z",
    )
    long_horizon = ledger.create_question(
        title="Will long horizon scheduled review be ignored?",
        resolution_criteria="Resolved yes if long horizon is ignored.",
        close_time="2026-06-01T00:00:00Z",
    )
    for question in (short_horizon, long_horizon):
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.5,
            rationale="Initial forecast.",
            as_of="2026-01-01T00:00:00Z",
        )
    ledger.schedule_review(
        scope_type="horizon",
        scope_ref="30",
        cadence="1d",
        next_run_at="2026-01-02T00:00:00Z",
    )

    results = ledger.run_due_scheduled_reviews(now="2026-01-10T00:00:00Z")
    alert_refs = {alert.scope_ref for alert in results[0]["alerts"]}

    assert results[0]["review"]["scope_type"] == "horizon"
    assert short_horizon.id in alert_refs
    assert long_horizon.id not in alert_refs


def test_scheduled_self_check_filters_by_confidence(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    low_confidence = ledger.create_question(
        title="Will low-confidence scheduled review run?",
        resolution_criteria="Resolved yes if low-confidence schedules create alerts.",
        domain="macro",
        next_review_at="2026-01-01T00:00:00Z",
    )
    high_confidence = ledger.create_question(
        title="Will high-confidence scheduled review be ignored?",
        resolution_criteria="Resolved yes if confidence filtering excludes this forecast.",
        domain="macro",
        next_review_at="2026-01-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=low_confidence.id,
        probability_or_distribution=0.5,
        confidence=0.35,
        rationale="Low-confidence forecast.",
        as_of="2026-01-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=high_confidence.id,
        probability_or_distribution=0.5,
        confidence=0.85,
        rationale="High-confidence forecast.",
        as_of="2026-01-01T00:00:00Z",
    )
    schedule = ledger.schedule_review(
        scope_type="domain",
        scope_ref="macro",
        cadence="1d",
        next_run_at="2026-01-02T00:00:00Z",
        confidence_below=0.5,
    )

    results = ledger.run_due_scheduled_reviews(now="2026-01-10T00:00:00Z")
    alert_refs = {alert.scope_ref for alert in results[0]["alerts"]}

    assert schedule["confidence_below"] == pytest.approx(0.5)
    assert low_confidence.id in alert_refs
    assert high_confidence.id not in alert_refs


def test_self_check_flags_due_assumptions_and_invalidated_reference_classes(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will assumptions be checked?",
        resolution_criteria="Resolved yes if assumption checks create alerts.",
        domain="science",
    )
    assumption = ledger.add_assumption(
        question_id=question.id,
        text="The trial enrollment rate remains on schedule.",
        check_cadence="7d",
    )
    ledger.update_assumption(
        assumption["id"],
        status="active",
        last_checked_at="2026-01-01T00:00:00Z",
    )
    reference_class = ledger.add_reference_class(
        question_id=question.id,
        name="Comparable trial timelines",
        inclusion_criteria="Same phase and indication.",
        base_rate=0.5,
    )
    ledger.update_reference_class(reference_class["id"], status="invalidated")
    due_reference_class = ledger.add_reference_class(
        question_id=question.id,
        name="Comparable enrollment rates",
        inclusion_criteria="Same phase and site footprint.",
        base_rate=0.45,
        check_cadence="7d",
    )
    ledger.update_reference_class(
        due_reference_class["id"],
        status="active",
        last_checked_at="2026-01-01T00:00:00Z",
    )

    alerts = ledger.self_check(question_id=question.id, now="2026-01-10T00:00:00Z")
    reasons = {alert.reason for alert in alerts}

    assert f"assumption_check_due:{assumption['id']}" in reasons
    assert f"reference_class_invalidated:{reference_class['id']}" in reasons
    assert f"reference_class_check_due:{due_reference_class['id']}" in reasons


def test_review_flags_stale_evidence(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will evidence become stale?",
        resolution_criteria="Resolved yes if stale evidence is flagged.",
    )
    ledger.add_evidence(
        question_id=question.id,
        source_or_note="Old evidence",
        available_at="2026-01-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Evidence is old.",
        as_of="2026-01-09T00:00:00Z",
    )

    rows = ledger.review_questions(stale=True, last_days=7, now="2026-01-10T00:00:00Z")

    assert "evidence_stale_7d_plus" in rows[0]["reasons"]


def test_review_prioritizes_new_evidence_over_merely_old_forecasts(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    old = ledger.create_question(
        title="Will old forecast be lower priority?",
        resolution_criteria="Resolved yes if old forecasts are reviewed after new evidence.",
    )
    ledger.add_evidence(
        question_id=old.id,
        source_or_note="Old background evidence.",
        available_at="2026-01-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=old.id,
        probability_or_distribution=0.5,
        rationale="Old but unchanged.",
        as_of="2026-01-01T00:00:00Z",
    )
    new = ledger.create_question(
        title="Will new evidence be top priority?",
        resolution_criteria="Resolved yes if new evidence is prioritized.",
    )
    ledger.create_snapshot(
        question_id=new.id,
        probability_or_distribution=0.5,
        rationale="Initial forecast.",
        as_of="2026-01-08T00:00:00Z",
    )
    evidence = ledger.add_evidence(
        question_id=new.id,
        source_or_note="Material update after forecast.",
        available_at="2026-01-09T00:00:00Z",
    )

    rows = ledger.review_questions(stale=True, last_days=7, now="2026-01-10T00:00:00Z")

    assert rows[0]["question"].id == new.id
    assert rows[0]["priority"] == 0
    assert rows[0]["reasons"] == [f"new_evidence:{evidence.id}"]
    assert any(row["question"].id == old.id and row["priority"] == 4 for row in rows)


def test_review_can_filter_by_domain_and_topic(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    inflation = ledger.create_question(
        title="Will inflation stay elevated?",
        resolution_criteria="Resolved yes if inflation remains elevated.",
        domain="macro",
        topics=["inflation"],
    )
    employment = ledger.create_question(
        title="Will unemployment rise?",
        resolution_criteria="Resolved yes if unemployment rises.",
        domain="macro",
        topics=["employment"],
    )
    for question in (inflation, employment):
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.5,
            rationale="Initial forecast.",
            as_of="2026-01-01T00:00:00Z",
        )

    rows = ledger.review_questions(
        stale=True,
        last_days=7,
        domain="macro",
        topic="inflation",
        now="2026-01-10T00:00:00Z",
    )

    assert [row["question"].id for row in rows] == [inflation.id]
    assert "last_update_7d_plus" in rows[0]["reasons"]


def test_review_can_filter_by_confidence(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    low_confidence = ledger.create_question(
        title="Will low confidence item need review?",
        resolution_criteria="Resolved yes if confidence filtering works.",
    )
    high_confidence = ledger.create_question(
        title="Will high confidence item be excluded?",
        resolution_criteria="Resolved yes if confidence filtering excludes it.",
    )
    ledger.create_snapshot(
        question_id=low_confidence.id,
        probability_or_distribution=0.5,
        confidence=0.35,
        rationale="Uncertain forecast.",
        as_of="2026-01-10T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=high_confidence.id,
        probability_or_distribution=0.5,
        confidence=0.85,
        rationale="Confident forecast.",
        as_of="2026-01-10T00:00:00Z",
    )

    rows = ledger.review_questions(confidence_below=0.5, now="2026-01-10T00:00:00Z")

    assert [row["question"].id for row in rows] == [low_confidence.id]
    assert rows[0]["reasons"] == []


def test_review_can_filter_by_forecast_horizon(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    short_horizon = ledger.create_question(
        title="Will short horizon item need review?",
        resolution_criteria="Resolved yes if short horizon filtering works.",
        close_time="2026-01-25T00:00:00Z",
    )
    long_horizon = ledger.create_question(
        title="Will long horizon item be excluded?",
        resolution_criteria="Resolved yes if long horizon filtering excludes it.",
        close_time="2026-06-01T00:00:00Z",
    )
    for question in (short_horizon, long_horizon):
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.5,
            rationale="Initial forecast.",
            as_of="2026-01-01T00:00:00Z",
        )

    rows = ledger.review_questions(
        stale=True,
        last_days=7,
        horizon="30",
        now="2026-01-10T00:00:00Z",
    )

    assert [row["question"].id for row in rows] == [short_horizon.id]
    assert "last_update_7d_plus" in rows[0]["reasons"]


def test_review_flags_questions_approaching_close_time(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will close time be reviewed before passing?",
        resolution_criteria="Resolved yes if approaching close time is flagged.",
        close_time="2026-01-12T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Recent forecast.",
        as_of="2026-01-10T00:00:00Z",
    )

    rows = ledger.review_questions(stale=True, last_days=3, now="2026-01-10T00:00:00Z")

    assert rows[0]["question"].id == question.id
    assert "close_time_within_3d" in rows[0]["reasons"]
    assert rows[0]["priority"] == 1


def test_review_and_scheduled_self_check_flag_large_forecast_delta(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will large forecast deltas be reviewed?",
        resolution_criteria="Resolved yes if large deltas create review work.",
        domain="macro",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.35,
        rationale="Initial forecast.",
        as_of="2026-01-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.68,
        rationale="Large update.",
        as_of="2026-01-02T00:00:00Z",
    )
    schedule = ledger.schedule_review(
        scope_type="domain",
        scope_ref="macro",
        cadence="1d",
        next_run_at="2026-01-03T00:00:00Z",
        large_delta_threshold=0.25,
    )

    rows = ledger.review_questions(
        stale=True,
        last_days=30,
        large_delta_threshold=0.25,
        now="2026-01-04T00:00:00Z",
    )
    results = ledger.run_due_scheduled_reviews(now="2026-01-04T00:00:00Z")

    assert schedule["large_delta_threshold"] == pytest.approx(0.25)
    assert rows[0]["question"].id == question.id
    assert any(reason.startswith("large_forecast_delta:") for reason in rows[0]["reasons"])
    assert rows[0]["priority"] == 3
    assert any(alert.reason.startswith("large_forecast_delta:") for alert in results[0]["alerts"])


def test_self_check_flags_evidence_newer_than_current_forecast(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will new evidence be reviewed?",
        resolution_criteria="Resolved yes if new evidence creates an alert.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Initial forecast.",
        as_of="2026-01-01T00:00:00Z",
    )
    evidence = ledger.add_evidence(
        question_id=question.id,
        source_or_note="New evidence",
        available_at="2026-01-05T00:00:00Z",
    )

    alerts = ledger.self_check(question_id=question.id, now="2026-01-06T00:00:00Z")

    assert f"new_evidence:{evidence.id}" in {alert.reason for alert in alerts}


def test_self_check_flags_resolved_forecasts_needing_score_and_postmortem(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will a resolved forecast need scoring?",
        resolution_criteria="Resolved yes if scoring is due.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.7,
        rationale="Initial forecast.",
    )
    ledger.resolve_question(question_id=question.id, outcome="yes")

    score_alerts = ledger.self_check(question_id=question.id)
    ledger.score_question(question.id)
    postmortem_alerts = ledger.self_check(question_id=question.id)

    assert {alert.reason for alert in score_alerts} == {"score_due"}
    assert {alert.reason for alert in postmortem_alerts} == {"postmortem_due"}


def test_self_check_prioritizes_high_impact_resolution_learning(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will a high-impact forecast need learning review?",
        resolution_criteria="Resolved yes if high-impact learning work is prioritized.",
        impact="high",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.7,
        rationale="Initial high-impact forecast.",
    )
    ledger.resolve_question(question_id=question.id, outcome="yes")

    score_alerts = ledger.self_check(question_id=question.id)
    ledger.score_question(question.id)
    postmortem_alerts = ledger.self_check(question_id=question.id)

    assert {alert.reason for alert in score_alerts} == {"high_impact_score_due"}
    assert score_alerts[0].severity == "high"
    assert {alert.reason for alert in postmortem_alerts} == {"high_impact_postmortem_due"}
    assert postmortem_alerts[0].severity == "high"


def test_self_check_auto_scores_confirmed_resolved_forecasts(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will self-check score resolved questions?",
        resolution_criteria="Resolved yes if auto scoring records a score.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.7,
        rationale="Initial forecast.",
    )
    ledger.resolve_question(question_id=question.id, outcome="yes")

    alerts = ledger.self_check(question_id=question.id, auto_score=True)
    reasons = {alert.reason for alert in alerts}

    assert any(reason.startswith("score_created:") for reason in reasons)
    assert "postmortem_due" in reasons
    assert ledger.list_scores()[0].question_id == question.id


def test_self_check_auto_postmortem_updates_learning_records(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will self-check create learning records?",
        resolution_criteria="Resolved yes if auto postmortems update learning records.",
        domain="macro",
        topics=["inflation"],
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.9,
        rationale="High-confidence forecast that should miss.",
    )
    ledger.resolve_question(question_id=question.id, outcome="no")

    alerts = ledger.self_check(question_id=question.id, auto_score=True, auto_postmortem=True)
    reasons = {alert.reason for alert in alerts}

    assert any(reason.startswith("score_created:") for reason in reasons)
    assert any(reason.startswith("postmortem_created:") for reason in reasons)
    assert "postmortem_due" not in reasons
    assert ledger.list_postmortems(question_id=question.id)[0]["question_id"] == question.id
    lesson = ledger.list_calibration_lessons(scope_type="domain", scope_ref="macro")[0]
    profile = ledger.list_domain_error_profiles(domain="macro", topic="inflation")[0]
    assert lesson["status"] == "tentative"
    assert lesson["recommended_adjustment"]["error_tags"] == ["overconfidence", "high_brier_miss"]
    assert profile["sample_count"] == 1
    assert "overconfidence" in profile["recurring_errors"]


def test_domain_topic_schedule_can_auto_update_learning_records(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    matching = ledger.create_question(
        title="Will scheduled domain-topic learning update?",
        resolution_criteria="Resolved yes if scoped scheduled self-checks write learning records.",
        domain="macro",
        topics=["inflation"],
    )
    ignored = ledger.create_question(
        title="Will unscoped resolved question be ignored?",
        resolution_criteria="Resolved yes if unrelated scopes do not write learning records.",
        domain="macro",
        topics=["growth"],
    )
    for question in (matching, ignored):
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.9,
            rationale="High-confidence forecast that should miss.",
        )
        ledger.resolve_question(question_id=question.id, outcome="no")

    ledger.schedule_review(
        scope_type="domain_topic",
        scope_ref=json.dumps({"domain": "macro", "topic": "inflation"}, sort_keys=True),
        cadence="1d",
        next_run_at="2026-01-02T00:00:00Z",
        auto_score=True,
        auto_postmortem=True,
    )

    results = ledger.run_due_scheduled_reviews(now="2026-01-03T00:00:00Z")
    reasons = {alert.reason for alert in results[0]["alerts"]}

    assert any(reason.startswith("score_created:") for reason in reasons)
    assert any(reason.startswith("postmortem_created:") for reason in reasons)
    assert [score.question_id for score in ledger.list_scores()] == [matching.id]
    assert ledger.list_postmortems(question_id=matching.id)
    assert not ledger.list_postmortems(question_id=ignored.id)
    assert ledger.list_calibration_lessons(scope_type="domain", scope_ref="macro")[0]["status"] == "tentative"
    assert ledger.list_domain_error_profiles(domain="macro", topic="inflation")[0]["sample_count"] == 1
    assert ledger.list_domain_error_profiles(domain="macro", topic="growth") == []


def test_domain_topic_schedule_alerts_for_tentative_lessons(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will scheduled lesson review be surfaced?",
        resolution_criteria="Resolved yes if tentative scoped lessons create review alerts.",
        domain="macro",
        topics=["inflation"],
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.8,
        rationale="High-confidence forecast that should be reviewed after resolution.",
    )
    ledger.resolve_question(question_id=question.id, outcome="no")
    ledger.self_check(question_id=question.id, auto_score=True, auto_postmortem=True)
    lesson = ledger.list_calibration_lessons(scope_type="domain", scope_ref="macro")[0]

    ledger.schedule_review(
        scope_type="domain_topic",
        scope_ref=json.dumps({"domain": "macro", "topic": "inflation"}, sort_keys=True),
        cadence="1d",
        next_run_at="2026-01-04T00:00:00Z",
    )

    results = ledger.run_due_scheduled_reviews(now="2026-01-05T00:00:00Z")
    lesson_alerts = [alert for alert in results[0]["alerts"] if alert.reason == "calibration_lesson_review"]

    assert [alert.scope_ref for alert in lesson_alerts] == [lesson["id"]]
    assert lesson_alerts[0].scope_type == "calibration_lesson"
    assert f"forecast lesson status {lesson['id']} --status active" in lesson_alerts[0].recommended_action

    ledger.update_calibration_lesson(lesson["id"], status="active")
    results = ledger.run_due_scheduled_reviews(now="2026-01-06T00:00:00Z")

    assert "calibration_lesson_review" not in {alert.reason for alert in results[0]["alerts"]}


def test_cron_runner_reports_alerts_and_stays_silent_without_work(tmp_path):
    db_path = tmp_path / "forecasting.db"
    ledger = ForecastLedger(db_path)
    question = ledger.create_question(
        title="Will cron find stale work?",
        resolution_criteria="Resolved yes if the cron runner emits an alert.",
        next_review_at="2026-01-01T00:00:00Z",
    )
    ledger.schedule_review(
        scope_type="question",
        scope_ref=question.id,
        cadence="1d",
        next_run_at="2026-01-02T00:00:00Z",
    )

    report = run_due_reviews(db_path=str(db_path), now="2026-01-03T00:00:00Z")
    silent = run_due_reviews(db_path=str(db_path), now="2026-01-03T01:00:00Z")

    assert "Forecast self-check alerts" in report
    assert question.id in report
    assert silent == ""


def test_cron_runner_uses_schedule_auto_learning_flags(tmp_path):
    db_path = tmp_path / "forecasting.db"
    ledger = ForecastLedger(db_path)
    question = ledger.create_question(
        title="Will cron update domain learning?",
        resolution_criteria="Resolved yes if cron writes scoped learning records.",
        domain="macro",
        topics=["inflation"],
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.9,
        rationale="High-confidence forecast that should miss.",
    )
    ledger.resolve_question(question_id=question.id, outcome="no")
    ledger.schedule_review(
        scope_type="domain_topic",
        scope_ref=json.dumps({"domain": "macro", "topic": "inflation"}, sort_keys=True),
        cadence="1d",
        next_run_at="2026-01-02T00:00:00Z",
        auto_score=True,
        auto_postmortem=True,
    )

    report = run_due_reviews(db_path=str(db_path), now="2026-01-03T00:00:00Z")

    assert "score_created:" in report
    assert "postmortem_created:" in report
    assert ledger.list_calibration_lessons(scope_type="domain", scope_ref="macro")
    assert ledger.list_domain_error_profiles(domain="macro", topic="inflation")[0]["sample_count"] == 1


def test_weighted_binary_probability_supports_component_dicts():
    probability = weighted_binary_probability(
        {
            "base_rate": {"probability": 0.4, "weight": 2},
            "market": {"probability": 0.7, "weight": 1},
        }
    )

    assert probability == pytest.approx(0.5)


def test_bayesian_binary_update_combines_prior_and_likelihoods():
    posterior = bayesian_binary_update(
        prior=0.4,
        likelihood_if_true=0.8,
        likelihood_if_false=0.2,
    )

    assert posterior == pytest.approx(0.7272727273)


def test_forecast_chat_system_prompt_scopes_general_chat_to_forecasting():
    prompt = build_forecast_chat_system_prompt("Use a concise style.")

    assert "Superforecasting Agent" in prompt
    assert "forecasting desk" in prompt
    assert "scoreable forecasts" in prompt
    assert "raw LLM intuition" in prompt
    assert "Use a concise style." in prompt


def test_protocol_messages_include_forecast_context_and_stage_task(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will the macro release surprise?",
        resolution_criteria="Resolved yes if the release beats consensus.",
        domain="macro",
    )
    ledger.add_evidence(
        question_id=question.id,
        source_or_note="Consensus estimate moved lower.",
        available_at="2026-01-01T00:00:00Z",
    )
    ledger.add_reference_class(
        question_id=question.id,
        name="Similar releases",
        inclusion_criteria="Same indicator and cycle phase.",
        base_rate=0.45,
    )
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="https://example.com/economic-calendar",
        source_type="url",
    )
    alert = ledger.create_alert(
        severity="warning",
        scope_type="question",
        scope_ref=question.id,
        reason="review_due",
        recommended_action="Review the macro release forecast.",
    )
    ledger.create_calibration_lesson(
        scope_type="domain",
        scope_ref="macro",
        lesson="Tentative lessons require review before use.",
        status="tentative",
    )
    ledger.create_calibration_lesson(
        scope_type="domain",
        scope_ref="macro",
        lesson="Active macro lessons can guide updates.",
        status="active",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.55,
        rationale="Base rate plus modest inside-view evidence.",
    )

    messages = build_protocol_messages(ledger, question.id, stage="update")

    assert messages[0].role == "system"
    assert "forecasting desk" in messages[0].content
    assert "Will the macro release surprise?" in messages[1].content
    assert "Reference Classes" in messages[1].content
    assert "Watched Sources" in messages[1].content
    assert watch["id"] in messages[1].content
    assert "Open Alerts" in messages[1].content
    assert alert.id in messages[1].content
    assert "Active macro lessons can guide updates." in messages[1].content
    assert "Tentative lessons require review before use." not in messages[1].content
    assert "Prepare a forecast update preview" in messages[1].content


def test_correction_records_affected_learning_artifacts(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will the regulation pass?",
        resolution_criteria="Resolved yes if the final regulation passes.",
        domain="policy",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.8,
        rationale="Committee support looked high.",
    )
    resolution = ledger.resolve_question(question_id=question.id, outcome="no")
    score = ledger.score_question(question.id)
    postmortem = ledger.create_postmortem(
        question_id=question.id,
        lesson="Do not overread committee signals.",
    )

    correction = ledger.create_correction(
        target_type="resolution",
        target_id=resolution.id,
        reason="Resolution source was updated.",
        status="applied",
    )

    assert correction["affected_score_record_refs"] == [score.id]
    assert correction["affected_postmortem_refs"] == [postmortem["id"]]
    assert correction["affected_calibration_lesson_refs"]
    assert ledger.list_scores() == []
    invalidated_score = ledger.get_score(score.id)
    invalidated_postmortem = ledger.get_postmortem(postmortem["id"])
    invalidated_lesson = ledger.get_calibration_lesson(correction["affected_calibration_lesson_refs"][0])
    packet = json.loads(ledger.export_question(question.id, fmt="json"))
    assert invalidated_score.invalidated_by_correction_id == correction["id"]
    assert invalidated_postmortem["invalidated_by_correction_id"] == correction["id"]
    assert invalidated_lesson["invalidated_by_correction_id"] == correction["id"]
    assert invalidated_lesson["status"] == "superseded"
    assert ledger.list_scores(include_invalidated=True)[0].id == score.id
    assert packet["scores"][0]["invalidated_by_correction_id"] == correction["id"]
    assert packet["postmortems"][0]["invalidated_by_correction_id"] == correction["id"]
    assert packet["calibration_lessons"][0]["invalidated_by_correction_id"] == correction["id"]
    assert packet["corrections"][0]["id"] == correction["id"]
    assert ledger.list_alerts()[0].reason == "correction_affects_learning_records"


def test_trusted_resolver_policy_is_auditable(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")

    policy = ledger.create_trusted_resolver_policy(
        resolver_plugin="official-results",
        plugin_version="1.0.0",
        scope_type="domain",
        scope_ref="elections",
        enabled=True,
        approved_by="analyst",
        audit_log_ref="audit-123",
    )

    policies = ledger.list_trusted_resolver_policies(enabled=True)
    assert policies[0]["id"] == policy["id"]
    assert policies[0]["scope_ref"] == "elections"


def test_confirmed_resolution_updates_trusted_policy_last_used(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will trusted resolver be audited?",
        resolution_criteria="Resolved yes if policy last_used_at updates.",
    )
    policy = ledger.create_trusted_resolver_policy(
        resolver_plugin="official-results",
        plugin_version="1.0.0",
        scope_type="global",
        enabled=True,
    )

    resolution = ledger.resolve_question(
        question_id=question.id,
        outcome="yes",
        resolver_type="source_adapter",
        trusted_policy_id=policy["id"],
    )

    assert resolution.trusted_policy_id == policy["id"]
    assert ledger.get_resolution(resolution.id).trusted_policy_id == policy["id"]
    assert ledger.get_trusted_resolver_policy(policy["id"])["last_used_at"] is not None
