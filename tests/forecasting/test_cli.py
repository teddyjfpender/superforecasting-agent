from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from forecasting.agent_protocol import build_backtest_agent_protocol_messages, parse_agent_protocol_response
from forecasting.cli import main as forecast_main
from forecasting.cli import _apply_backtest_probability_source
from forecasting.cli import register_cli
from forecasting.benchmarks import load_builtin_benchmark
from forecasting.ledger import ForecastLedger
from forecasting.source_adapters import (
    ArxivPaper,
    BlueskyPost,
    BlsObservation,
    CensusRecord,
    CkanDataset,
    CisaKevVulnerability,
    ClinicalTrialStudy,
    CoinGeckoMarketSnapshot,
    CourtListenerSearchResult,
    CrossrefWork,
    EiaObservation,
    FederalRegisterDocument,
    FemaDisasterDeclaration,
    FiveThirtyEightPollObservation,
    FredObservation,
    GdeltArticle,
    HackerNewsItem,
    GitHubCommit,
    GitHubIssue,
    GitHubRelease,
    GitHubRepositorySnapshot,
    GitHubWorkflowRun,
    ImfDataMapperObservation,
    MastodonStatus,
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
    WhoGhoObservation,
    WorldBankObservation,
    YahooFinancePriceObservation,
)
import forecasting.source_adapters as source_adapters
from hermes_constants import reset_hermes_home_override, set_hermes_home_override


class _ImportPayloadHandler(BaseHTTPRequestHandler):
    body = b"{}"
    content_type = "application/json"
    last_path = ""

    def do_GET(self):  # noqa: N802
        type(self).last_path = self.path
        self.send_response(200)
        self.send_header("Content-Type", self.content_type)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format, *args):  # noqa: A002
        return


def _serve_import_payload(body: str, *, content_type: str = "application/json"):
    _ImportPayloadHandler.body = body.encode("utf-8")
    _ImportPayloadHandler.content_type = content_type
    _ImportPayloadHandler.last_path = ""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ImportPayloadHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes")
    subparsers = parser.add_subparsers(dest="command")
    register_cli(subparsers)
    return parser


def _run(parser: argparse.ArgumentParser, argv: list[str]) -> None:
    args = parser.parse_args(argv)
    args.func(args)


def test_forecast_cli_lifecycle(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will X win?",
            "--resolution-criteria",
            "Resolved yes if X wins the certified result.",
            "--domain",
            "elections",
        ],
    )
    new_output = capsys.readouterr().out
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", new_output).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "update",
            question_id,
            "--probability",
            "0.64",
            "--rationale",
            "Polling and fundamentals favor X.",
            "--as-of",
            "2026-05-01T00:00:00Z",
        ],
    )
    assert "created forecast snapshot" in capsys.readouterr().out

    _run(parser, ["forecast", "--db", db, "list"])
    list_output = capsys.readouterr().out
    assert "AsOf" in list_output
    assert "2026-05-01T00:00:00Z" in list_output

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "resolve",
            question_id,
            "--outcome",
            "yes",
            "--source",
            "official result",
        ],
    )
    assert "recorded resolution" in capsys.readouterr().out

    _run(parser, ["forecast", "--db", db, "score", question_id])
    score_output = capsys.readouterr().out

    assert "brier_score: 0.129600" in score_output
    assert "log_score:" in score_output

    _run(parser, ["forecast", "--db", db, "scores", "--domain", "elections", "--bucket", "0.6-0.7"])
    scores_output = capsys.readouterr().out
    assert "0.1296" in scores_output
    assert "Log" in scores_output
    assert "elections" in scores_output

    _run(parser, ["forecast", "--db", db, "calibration", "--domain", "elections"])
    calibration_output = capsys.readouterr().out
    assert "mean_log_score:" in calibration_output
    assert "mean_sharpness:" in calibration_output
    assert "probability_movement_n:" in calibration_output
    assert "mean_abs_probability_movement_before_close:" in calibration_output
    assert "question_type_breakdown:" in calibration_output
    assert "binary: n=1 brier_n=1" in calibration_output
    assert "empty" in calibration_output
    assert "low_sample" in calibration_output


def test_forecast_cli_update_can_derive_weighted_ensemble_probability(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will the ensemble be explicit?",
            "--resolution-criteria",
            "Resolved yes if the ensemble is stored.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "update",
            question_id,
            "--component-json",
            '{"base_rate":{"probability":0.4,"weight":2},"market":{"probability":0.7,"weight":1}}',
            "--rationale",
            "Weighted ensemble from base rate and market components.",
        ],
    )
    output = capsys.readouterr().out

    assert "probability: 0.500" in output
    assert "ensemble_components: 2" in output
    assert "strongest_driver:" in output
    assert "component_drivers:" in output
    assert "base_rate" in output
    assert "market" in output

    _run(parser, ["forecast", "--db", db, "resolve", question_id, "--outcome", "yes"])
    capsys.readouterr()
    _run(parser, ["forecast", "--db", db, "score", question_id])
    capsys.readouterr()
    _run(parser, ["forecast", "--db", db, "calibration", "--all"])
    calibration_output = capsys.readouterr().out
    assert "ensemble_component_contributions:" in calibration_output
    assert "base_rate: n=1 mean_contribution=0.266667 weight_share=0.666667" in calibration_output
    assert "market: n=1 mean_contribution=0.233333 weight_share=0.333333" in calibration_output


def test_forecast_cli_update_can_apply_active_calibration_lessons(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will active lessons adjust this forecast?",
            "--resolution-criteria",
            "Resolved yes if active lessons are applied.",
            "--domain",
            "macro",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    ledger = ForecastLedger(db_path)
    lesson = ledger.create_calibration_lesson(
        scope_type="domain",
        scope_ref="macro",
        lesson="Macro forecasts have been overconfident after policy shocks.",
        status="active",
        confidence=0.8,
        recommended_adjustment={"probability_delta": -0.08},
    )

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "update",
            question_id,
            "--probability",
            "0.70",
            "--rationale",
            "Apply active calibration lesson.",
            "--use-active-lessons",
        ],
    )
    output = capsys.readouterr().out
    snapshot = ledger.get_current_snapshot(question_id)

    assert "probability: 0.620" in output
    assert "calibration_lessons: 1" in output
    assert "raw_probability: 0.700" in output
    assert "applied_probability_delta: -0.080" in output
    assert snapshot is not None
    assert snapshot.probability_or_distribution == pytest.approx(0.62)
    assert snapshot.calibration_lesson_refs == [lesson["id"]]
    assert snapshot.calibration_adjustment["raw_probability"] == pytest.approx(0.7)
    assert snapshot.calibration_adjustment["applied_probability_delta"] == pytest.approx(-0.08)


def test_forecast_cli_can_store_numeric_forecast_value(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "What will revenue be?",
            "--resolution-criteria",
            "Resolved by audited annual revenue.",
            "--outcome-type",
            "numeric",
            "--unit",
            "usd",
            "--bound",
            "0",
            "--bound",
            "1000000000",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "update",
            question_id,
            "--numeric-value",
            "123456789",
            "--rationale",
            "Revenue model point estimate.",
        ],
    )
    output = capsys.readouterr().out
    snapshot = ForecastLedger(db_path).get_current_snapshot(question_id)

    assert "probability: 123456789.000" in output
    assert snapshot is not None
    assert snapshot.probability_or_distribution == 123456789.0

    _run(parser, ["forecast", "--db", db, "resolve", question_id, "--outcome", "125000000"])
    capsys.readouterr()
    _run(parser, ["forecast", "--db", db, "score", question_id])
    score_output = capsys.readouterr().out

    assert "brier_score: -" in score_output
    assert "proper_score:" in score_output
    assert "score_rule: normalized_squared_error" in score_output


def test_forecast_cli_model_can_compute_bayesian_update(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Bayesian model runs compute posteriors?",
            "--resolution-criteria",
            "Resolved yes if model runs store posteriors.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "model",
            question_id,
            "--type",
            "bayesian_update",
            "--prior",
            "0.4",
            "--likelihood-if-true",
            "0.8",
            "--likelihood-if-false",
            "0.2",
        ],
    )
    output = capsys.readouterr().out
    model_run_id = re.search(r"model_run: (mr_[a-f0-9]+)", output).group(1)
    model_run = ForecastLedger(db_path).get_model_run(model_run_id)

    assert "posterior: 0.727" in output
    assert model_run["output"]["posterior"] == pytest.approx(0.7272727273)


def test_forecast_cli_model_can_compute_trend_projection(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will trend projection compute a model run?",
            "--resolution-criteria",
            "Resolved yes if the trend projection model run is stored.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "model",
            question_id,
            "--type",
            "trend_projection",
            "--series-json",
            json.dumps(
                [
                    {"date": "2026-01-01", "value": 10},
                    {"date": "2026-01-02", "value": 12},
                    {"date": "2026-01-03", "value": 14},
                ]
            ),
            "--target-date",
            "2026-01-04",
        ],
    )
    output = capsys.readouterr().out
    model_run_id = re.search(r"model_run: (mr_[a-f0-9]+)", output).group(1)
    model_run = ForecastLedger(db_path).get_model_run(model_run_id)

    assert "projected_value: 16.000" in output
    assert "slope: 2.000000 per_day" in output
    assert "r_squared: 1.000" in output
    assert model_run["output"]["projected_value"] == pytest.approx(16.0)
    assert model_run["parameters"]["target_date"] == "2026-01-04"


def test_forecast_cli_update_preview_does_not_write_snapshot(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will preview avoid writes?",
            "--resolution-criteria",
            "Resolved yes if preview avoids ledger writes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "update",
            question_id,
            "--component-json",
            '{"base_rate":{"probability":0.4,"weight":1},"inside_view":{"probability":0.8,"weight":1}}',
            "--rationale",
            "Preview only.",
            "--as-of",
            "2026-05-01T00:00:00Z",
            "--preview",
        ],
    )
    output = capsys.readouterr().out

    assert "forecast update preview" in output
    assert "proposed_as_of: 2026-05-01T00:00:00Z" in output
    assert "proposed_probability: 0.600" in output
    assert "component_drivers:" in output
    assert ForecastLedger(db_path).list_snapshots(question_id) == []


def test_forecast_cli_update_requires_ack_for_stale_evidence_refs(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will stale evidence be explicit?",
            "--resolution-criteria",
            "Resolved yes if stale evidence is acknowledged.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    ledger = ForecastLedger(db_path)
    evidence = ledger.add_evidence(
        question_id=question_id,
        source_or_note="Old source",
        available_at="2026-01-01T00:00:00Z",
    )

    try:
        _run(
            parser,
            [
                "forecast",
                "--db",
                db,
                "update",
                question_id,
                "--probability",
                "0.5",
                "--rationale",
                "Uses old evidence.",
                "--as-of",
                "2026-02-15T00:00:00Z",
                "--evidence-ref",
                evidence.id,
            ],
        )
    except SystemExit as exc:
        assert exc.code == 1
    assert "stale evidence requires acknowledgement" in capsys.readouterr().err

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "update",
            question_id,
            "--probability",
            "0.5",
            "--rationale",
            "Uses old evidence with acknowledgement.",
            "--as-of",
            "2026-02-15T00:00:00Z",
            "--evidence-ref",
            evidence.id,
            "--ack-stale-evidence",
        ],
    )
    capsys.readouterr()
    snapshot = ForecastLedger(db_path).get_current_snapshot(question_id)

    assert snapshot is not None
    assert snapshot.metadata["stale_evidence_acknowledgement"]["evidence_refs"] == [evidence.id]


def test_forecast_cli_update_can_require_citations(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will citation policy be enforced?",
            "--resolution-criteria",
            "Resolved yes if strict updates require citations.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    with pytest.raises(SystemExit) as exc:
        _run(
            parser,
            [
                "forecast",
                "--db",
                db,
                "update",
                question_id,
                "--probability",
                "0.5",
                "--rationale",
                "Uncited factual claim.",
                "--require-citations",
            ],
        )

    assert exc.value.code == 1
    assert "forecast update requires citations" in capsys.readouterr().err

    ledger = ForecastLedger(db_path)
    evidence = ledger.add_evidence(
        question_id=question_id,
        source_or_note="Cited source",
        available_at="2026-01-01T00:00:00Z",
    )
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "update",
            question_id,
            "--probability",
            "0.55",
            "--rationale",
            "Cited source supports the update.",
            "--as-of",
            "2026-01-02T00:00:00Z",
            "--evidence-ref",
            evidence.id,
            "--require-citations",
        ],
    )
    capsys.readouterr()
    snapshot = ForecastLedger(db_path).get_current_snapshot(question_id)

    assert snapshot is not None
    assert snapshot.evidence_refs == [evidence.id]
    assert snapshot.metadata["citation_policy"] == "required"


def test_forecast_cli_evidence_claim_type_is_visible(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will evidence taxonomy be visible?",
            "--resolution-criteria",
            "Resolved yes if evidence claim types are displayed.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "evidence",
            "add",
            question_id,
            "A market desk rumor.",
            "--claim-type",
            "rumor",
            "--stance",
            "increases",
        ],
    )
    assert "claim_type: rumor" in capsys.readouterr().out

    _run(parser, ["forecast", "--db", db, "evidence", "list", question_id])
    assert "rumor" in capsys.readouterr().out


def test_forecast_cli_research_summarizes_new_evidence_since_current_forecast(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will research summarize new evidence?",
            "--resolution-criteria",
            "Resolved yes if research reports new evidence.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "update",
            question_id,
            "--probability",
            "0.5",
            "--rationale",
            "Initial forecast.",
            "--as-of",
            "2026-01-01T00:00:00Z",
        ],
    )
    capsys.readouterr()

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "research",
            question_id,
            "New source",
            "--available-at",
            "2026-01-05T00:00:00Z",
            "--reliability",
            "0.4",
            "--relevance",
            "0.8",
            "--stance",
            "mixed",
        ],
    )
    output = capsys.readouterr().out

    assert "new_since_current_forecast: 1" in output
    assert "reliability=0.40" in output
    assert "relevance=0.80" in output
    ledger = ForecastLedger(db_path)
    evidence = ledger.list_evidence(question_id)[0]
    assert evidence.reliability_rating == 0.4
    assert evidence.relevance_rating == 0.8
    assert evidence.stance == "mixed"
    assert ledger.get_current_snapshot(question_id).probability_or_distribution == 0.5


def test_forecast_cli_review_shows_next_actions_and_priorities(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    ledger = ForecastLedger(db_path)
    question = ledger.create_question(
        title="Will review list include action hints?",
        resolution_criteria="Resolved yes if review output includes next actions.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Initial forecast.",
        as_of="2026-01-01T00:00:00Z",
    )
    ledger.add_evidence(
        question_id=question.id,
        source_or_note="New material evidence.",
        available_at="2026-01-02T00:00:00Z",
    )

    _run(parser, ["forecast", "--db", db, "review", "--stale", "--last", "1d"])
    output = capsys.readouterr().out

    assert "Priority" in output
    assert "next: forecast research" in output
    assert f"forecast update {question.id} --preview" in output


def test_forecast_cli_review_filters_by_domain_and_topic(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    ledger = ForecastLedger(db_path)
    inflation = ledger.create_question(
        title="Will inflation stay high?",
        resolution_criteria="Resolved yes if inflation remains high.",
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

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "review",
            "--stale",
            "--last",
            "7d",
            "--domain",
            "macro",
            "--topic",
            "inflation",
            "--now",
            "2026-01-10T00:00:00Z",
        ],
    )
    output = capsys.readouterr().out

    assert "Will inflation stay high?" in output
    assert "Will unemployment rise?" not in output
    assert f"forecast research {inflation.id}" in output


def test_forecast_cli_review_filters_by_confidence(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    ledger = ForecastLedger(db_path)
    low_confidence = ledger.create_question(
        title="Will low confidence CLI review appear?",
        resolution_criteria="Resolved yes if confidence filtering works.",
    )
    high_confidence = ledger.create_question(
        title="Will high confidence CLI review be hidden?",
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

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "review",
            "--confidence-below",
            "0.5",
            "--now",
            "2026-01-10T00:00:00Z",
        ],
    )
    output = capsys.readouterr().out

    assert "Will low confidence CLI review appear?" in output
    assert "Will high confidence CLI review be hidden?" not in output


def test_forecast_cli_self_check_and_schedule_filter_by_confidence(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    ledger = ForecastLedger(db_path)
    low_confidence = ledger.create_question(
        title="Will low confidence CLI self-check alert?",
        resolution_criteria="Resolved yes if confidence-filtered self-checks alert.",
        domain="macro",
        next_review_at="2026-01-01T00:00:00Z",
    )
    high_confidence = ledger.create_question(
        title="Will high confidence CLI self-check be skipped?",
        resolution_criteria="Resolved yes if confidence-filtered self-checks skip this.",
        domain="macro",
        next_review_at="2026-01-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=low_confidence.id,
        probability_or_distribution=0.5,
        confidence=0.35,
        rationale="Uncertain forecast.",
        as_of="2026-01-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=high_confidence.id,
        probability_or_distribution=0.5,
        confidence=0.85,
        rationale="Confident forecast.",
        as_of="2026-01-01T00:00:00Z",
    )

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "self-check",
            "--domain",
            "macro",
            "--confidence-below",
            "0.5",
            "--now",
            "2026-01-10T00:00:00Z",
        ],
    )
    output = capsys.readouterr().out

    assert low_confidence.id in output
    assert high_confidence.id not in output

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "schedule",
            "add",
            "--domain",
            "macro",
            "--cadence",
            "1d",
            "--next-run-at",
            "2026-01-02T00:00:00Z",
            "--confidence-below",
            "0.5",
        ],
    )
    capsys.readouterr()
    _run(parser, ["forecast", "--db", db, "schedule", "list"])
    schedule_output = capsys.readouterr().out
    assert "<0.50" in schedule_output

    _run(parser, ["forecast", "--db", db, "schedule", "run", "--now", "2026-01-10T00:00:00Z"])
    run_output = capsys.readouterr().out

    assert low_confidence.id in run_output
    assert high_confidence.id not in run_output


def test_forecast_cli_review_and_schedule_flag_large_delta(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    ledger = ForecastLedger(db_path)
    question = ledger.create_question(
        title="Will large CLI deltas be reviewed?",
        resolution_criteria="Resolved yes if CLI review flags large forecast deltas.",
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

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "review",
            "--stale",
            "--large-delta-threshold",
            "0.25",
            "--now",
            "2026-01-04T00:00:00Z",
        ],
    )
    review_output = capsys.readouterr().out
    assert question.id in review_output
    assert "large_forecast_delta:+0.330" in review_output

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "schedule",
            "add",
            "--domain",
            "macro",
            "--cadence",
            "1d",
            "--next-run-at",
            "2026-01-03T00:00:00Z",
            "--large-delta-threshold",
            "0.25",
        ],
    )
    capsys.readouterr()
    _run(parser, ["forecast", "--db", db, "schedule", "list"])
    assert ">=0.25" in capsys.readouterr().out

    _run(parser, ["forecast", "--db", db, "schedule", "run", "--now", "2026-01-04T00:00:00Z"])
    run_output = capsys.readouterr().out
    assert question.id in run_output
    assert "large_forecast_delta:+0.330" in run_output


def test_forecast_cli_review_flags_approaching_close_time(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    ledger = ForecastLedger(db_path)
    question = ledger.create_question(
        title="Will close review show in CLI?",
        resolution_criteria="Resolved yes if close review appears in CLI output.",
        close_time="2026-01-12T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Recent forecast.",
        as_of="2026-01-10T00:00:00Z",
    )

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "review",
            "--stale",
            "--last",
            "3d",
            "--now",
            "2026-01-10T00:00:00Z",
        ],
    )
    output = capsys.readouterr().out

    assert "close_time_within_3d" in output
    assert f"next: forecast resolve {question.id}" in output


def test_forecast_cli_protocol_outputs_stage_prompt(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will protocol prompts be forecast-native?",
            "--resolution-criteria",
            "Resolved yes if the prompt includes forecast context.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(parser, ["forecast", "--db", db, "protocol", question_id, "--stage", "research"])
    output = capsys.readouterr().out

    assert "You are a forecasting desk" in output
    assert "Identify evidence gaps" in output
    assert question_id in output


def test_forecast_cli_agent_dry_run_uses_protocol_prompt(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will agent dry-run be forecast-native?",
            "--resolution-criteria",
            "Resolved yes if dry-run prints protocol messages.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(parser, ["forecast", "--db", db, "agent", question_id, "--stage", "update", "--dry-run"])
    output = capsys.readouterr().out

    assert "You are a forecasting desk" in output
    assert "enabled_toolsets: forecasting" in output
    assert "Prepare a forecast update preview" in output
    assert "terminal" not in output.splitlines()[0]


def test_forecast_cli_assumption_and_reference_class_status(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will assumptions be manageable?",
            "--resolution-criteria",
            "Resolved yes if assumptions can be listed and checked.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "assumption",
            "add",
            question_id,
            "The base-rate cohort remains comparable.",
            "--check-cadence",
            "7d",
        ],
    )
    assumption_output = capsys.readouterr().out
    assumption_id = re.search(r"assumption: (as_[a-f0-9]+)", assumption_output).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "assumption",
            "status",
            assumption_id,
            "--status",
            "stale",
            "--last-checked-at",
            "2026-01-01T00:00:00Z",
        ],
    )
    assert "status: stale" in capsys.readouterr().out

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "base-rate",
            question_id,
            "--name",
            "Comparable cases",
            "--inclusion-criteria",
            "Similar event type.",
            "--base-rate",
            "0.5",
            "--check-cadence",
            "14d",
        ],
    )
    reference_id = re.search(r"reference_class: (rc_[a-f0-9]+)", capsys.readouterr().out).group(1)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "reference-class",
            "status",
            reference_id,
            "--status",
            "invalidated",
            "--check-cadence",
            "21d",
        ],
    )
    reference_output = capsys.readouterr().out
    assert "status: invalidated" in reference_output
    assert "check_cadence: 21d" in reference_output


def test_forecast_cli_ingest_candidate_confirm_flow(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "ingest",
            "https://example.com/questions/will-x-happen",
            "--title",
            "Will X happen?",
            "--resolution-criteria",
            "Resolved yes if X happens before year-end.",
        ],
    )
    output = capsys.readouterr().out
    candidate_id = re.search(r"created ingest candidate (ic_[a-f0-9]+)", output).group(1)
    assert "confirmation required" in output

    _run(parser, ["forecast", "--db", db, "list"])
    assert "No forecast questions found." in capsys.readouterr().out

    _run(parser, ["forecast", "--db", db, "ingest", "--list"])
    assert candidate_id in capsys.readouterr().out

    _run(parser, ["forecast", "--db", db, "ingest", "--confirm", candidate_id, "--domain", "general"])
    confirm_output = capsys.readouterr().out

    assert "confirmed ingest candidate" in confirm_output
    assert "created forecast question" in confirm_output


def test_forecast_cli_ingest_extracts_local_json_candidate(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    source = tmp_path / "candidate.json"
    source.write_text(
        json.dumps(
            {
                "title": "Will CLI JSON ingest work?",
                "resolution_criteria": "Resolved yes if CLI ingest extracts JSON metadata.",
                "close_time": "2026-06-01T00:00:00Z",
                "baseline_probability": 0.57,
                "baseline_type": "crowd",
            }
        ),
        encoding="utf-8",
    )

    _run(parser, ["forecast", "--db", db, "ingest", str(source)])
    output = capsys.readouterr().out
    candidate_id = re.search(r"created ingest candidate (ic_[a-f0-9]+)", output).group(1)

    _run(parser, ["forecast", "--db", db, "ingest", "--show", candidate_id])
    show_output = capsys.readouterr().out
    assert "Will CLI JSON ingest work?" in show_output
    assert "Resolved yes if CLI ingest extracts JSON metadata." in show_output

    _run(parser, ["forecast", "--db", db, "ingest", "--confirm", candidate_id, "--domain", "benchmarks"])
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    baseline = ForecastLedger(db_path).list_baseline_comparisons(question_id)[0]
    assert baseline["probability_or_distribution"] == 0.57


def test_forecast_cli_ingest_extracts_url_html_candidate(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    html = """
    <html>
      <head>
        <title>Will URL HTML ingest work?</title>
        <meta name="description" content="A generic URL ingest fixture.">
      </head>
      <body>
        <p>Resolution criteria: Resolved yes if URL HTML ingest extracts metadata.</p>
        <p>Close time: 2026-06-01T00:00:00Z</p>
      </body>
    </html>
    """
    server = _serve_import_payload(html, content_type="text/html")
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/forecast.html"
        _run(parser, ["forecast", "--db", db, "ingest", url])
    finally:
        server.shutdown()
        server.server_close()

    output = capsys.readouterr().out
    candidate_id = re.search(r"created ingest candidate (ic_[a-f0-9]+)", output).group(1)

    _run(parser, ["forecast", "--db", db, "ingest", "--show", candidate_id])
    show_output = capsys.readouterr().out
    assert "Will URL HTML ingest work?" in show_output
    assert "Resolved yes if URL HTML ingest extracts metadata." in show_output

    _run(parser, ["forecast", "--db", db, "ingest", "--confirm", candidate_id, "--domain", "web"])
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    question = ForecastLedger(db_path).get_question(question_id)
    assert question.title == "Will URL HTML ingest work?"
    assert question.close_time == "2026-06-01T00:00:00Z"


def test_forecast_cli_market_import_extracts_local_csv_baseline(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    source = tmp_path / "market.csv"
    source.write_text(
        "\n".join(
            [
                "title,resolution_criteria,baseline_probability,baseline_type,baseline_source",
                "Will market CSV import work?,Resolved yes if market CSV import creates a baseline.,0.62,market,example-market",
            ]
        ),
        encoding="utf-8",
    )

    _run(parser, ["forecast", "--db", db, "import", "market", str(source)])
    output = capsys.readouterr().out
    candidate_id = re.search(r"created market import candidate (ic_[a-f0-9]+)", output).group(1)

    _run(parser, ["forecast", "--db", db, "ingest", "--confirm", candidate_id, "--domain", "markets"])
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    baseline = ForecastLedger(db_path).list_baseline_comparisons(question_id)[0]

    assert baseline["source"] == "example-market"
    assert baseline["baseline_type"] == "market"
    assert baseline["probability_or_distribution"] == 0.62


def test_forecast_cli_market_import_adds_csv_baselines_to_existing_question(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will market baselines attach?",
            "--resolution-criteria",
            "Resolved yes if market baselines attach to an existing question.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    source = tmp_path / "market.csv"
    source.write_text(
        "\n".join(
            [
                "market,market_probability,updated_at,market_id",
                "prediction-market-a,0.41,2026-05-01T00:00:00Z,mkt-1",
                "prediction-market-b,0.47,2026-05-02T00:00:00Z,mkt-2",
            ]
        ),
        encoding="utf-8",
    )

    _run(parser, ["forecast", "--db", db, "import", "market", str(source), "--question", question_id])
    output = capsys.readouterr().out
    baselines = ForecastLedger(db_path).list_baseline_comparisons(question_id)

    assert "captured 2 market baseline comparison(s)" in output
    assert [baseline["source"] for baseline in baselines] == ["prediction-market-a", "prediction-market-b"]
    assert [baseline["probability_or_distribution"] for baseline in baselines] == [0.41, 0.47]
    assert baselines[0]["metadata"]["market_id"] == "mkt-1"


def test_forecast_cli_market_import_adds_url_json_baselines_to_existing_question(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will market URL baselines attach?",
            "--resolution-criteria",
            "Resolved yes if market URL baselines attach to an existing question.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    server = _serve_import_payload(
        json.dumps(
            {
                "markets": [
                    {
                        "source": "url-market",
                        "implied_probability": 0.36,
                        "updated_at": "2026-05-03T00:00:00Z",
                        "market_id": "url-mkt-1",
                    }
                ]
            }
        )
    )
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/markets.json"
        _run(parser, ["forecast", "--db", db, "import", "market", url, "--question", question_id])
    finally:
        server.shutdown()
    output = capsys.readouterr().out
    baselines = ForecastLedger(db_path).list_baseline_comparisons(question_id)

    assert "captured 1 market baseline comparison(s)" in output
    assert baselines[0]["source"] == "url-market"
    assert baselines[0]["probability_or_distribution"] == 0.36
    assert baselines[0]["metadata"]["market_id"] == "url-mkt-1"


def test_forecast_cli_manifold_import_stages_candidate_with_market_baseline(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    server = _serve_import_payload(
        json.dumps(
            {
                "id": "mkt123",
                "slug": "will-manifold-import-work",
                "question": "Will Manifold import work?",
                "textDescription": "Resolved by the public Manifold market.",
                "url": "https://manifold.markets/test/will-manifold-import-work",
                "outcomeType": "BINARY",
                "probability": 0.64,
                "closeTime": 1780272000000,
                "lastUpdatedTime": 1777593600000,
                "isResolved": False,
            }
        )
    )
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v0/slug/will-manifold-import-work"
        _run(parser, ["forecast", "--db", db, "import", "manifold", url])
    finally:
        server.shutdown()
    output = capsys.readouterr().out
    candidate_id = re.search(r"created manifold import candidate (ic_[a-f0-9]+)", output).group(1)

    assert "confirmation required" in output
    assert "market_probability: 0.640" in output

    _run(parser, ["forecast", "--db", db, "ingest", "--confirm", candidate_id, "--domain", "markets"])
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    ledger = ForecastLedger(db_path)
    question = ledger.get_question(question_id)
    baselines = ledger.list_baseline_comparisons(question_id)

    assert question.title == "Will Manifold import work?"
    assert question.resolution_criteria == "Resolved by the public Manifold market."
    assert baselines[0]["source"] == "manifold:will-manifold-import-work"
    assert baselines[0]["baseline_type"] == "market"
    assert baselines[0]["probability_or_distribution"] == 0.64


def test_forecast_cli_metaculus_import_stages_candidate_with_crowd_baseline(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    server = _serve_import_payload(
        json.dumps(
            {
                "id": 15141,
                "title": "Will Metaculus import work?",
                "description": "Question background from Metaculus.",
                "resolution_criteria": "Resolved yes if the Metaculus importer stages a candidate.",
                "type": "binary",
                "close_time": "2026-06-01T00:00:00Z",
                "scheduled_resolve_time": "2026-07-01T00:00:00Z",
                "community_prediction": {"full": {"q2": 0.58}},
                "status": "open",
                "last_prediction_time": "2026-05-01T00:00:00Z",
            }
        )
    )
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/api/questions/15141/"
        _run(parser, ["forecast", "--db", db, "import", "metaculus", url])
    finally:
        server.shutdown()
    output = capsys.readouterr().out
    candidate_id = re.search(r"created metaculus import candidate (ic_[a-f0-9]+)", output).group(1)

    assert "confirmation required" in output
    assert "crowd_probability: 0.580" in output

    _run(parser, ["forecast", "--db", db, "ingest", "--confirm", candidate_id, "--domain", "benchmarks"])
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    ledger = ForecastLedger(db_path)
    question = ledger.get_question(question_id)
    baselines = ledger.list_baseline_comparisons(question_id)

    assert question.title == "Will Metaculus import work?"
    assert question.resolution_criteria == "Resolved yes if the Metaculus importer stages a candidate."
    assert baselines[0]["source"] == "metaculus:15141"
    assert baselines[0]["baseline_type"] == "crowd"
    assert baselines[0]["probability_or_distribution"] == 0.58


def test_forecast_cli_manifold_import_adds_baseline_to_existing_question(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Manifold baselines attach?",
            "--resolution-criteria",
            "Resolved yes if a Manifold baseline attaches.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    server = _serve_import_payload(
        json.dumps(
            {
                "id": "mkt456",
                "slug": "will-manifold-baselines-attach",
                "question": "Will Manifold baselines attach?",
                "textDescription": "Resolved by Manifold.",
                "url": "https://manifold.markets/test/will-manifold-baselines-attach",
                "outcomeType": "BINARY",
                "probability": 0.41,
                "lastUpdatedTime": 1777680000000,
                "isResolved": False,
            }
        )
    )
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v0/market/mkt456"
        _run(parser, ["forecast", "--db", db, "import", "manifold", url, "--question", question_id])
    finally:
        server.shutdown()
    output = capsys.readouterr().out
    ledger = ForecastLedger(db_path)
    evidence = ledger.list_evidence(question_id)
    baselines = ledger.list_baseline_comparisons(question_id)

    assert "captured manifold evidence" in output
    assert "captured manifold baseline comparison" in output
    assert "probability: 0.410" in output
    assert evidence[0].source_type == "adapter:manifold"
    assert evidence[0].metadata["market_id"] == "mkt456"
    assert baselines[0]["source"] == "manifold:will-manifold-baselines-attach"
    assert baselines[0]["probability_or_distribution"] == 0.41
    assert baselines[0]["metadata"]["adapter"] == "manifold"


def test_forecast_cli_polymarket_import_adds_baseline_to_existing_question(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Polymarket baselines attach?",
            "--resolution-criteria",
            "Resolved yes if a Polymarket baseline attaches.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    server = _serve_import_payload(
        json.dumps(
            [
                {
                    "id": "pm-123",
                    "slug": "will-polymarket-baselines-attach",
                    "question": "Will Polymarket baselines attach?",
                    "description": "Resolved by Polymarket settlement.",
                    "outcomes": '["Yes","No"]',
                    "outcomePrices": '["0.37","0.63"]',
                    "endDate": "2026-06-01T00:00:00Z",
                    "updatedAt": "2026-05-01T00:00:00Z",
                }
            ]
        )
    )
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/markets?slug=will-polymarket-baselines-attach"
        _run(parser, ["forecast", "--db", db, "import", "polymarket", url, "--question", question_id])
    finally:
        server.shutdown()
    output = capsys.readouterr().out
    ledger = ForecastLedger(db_path)
    evidence = ledger.list_evidence(question_id)
    baselines = ledger.list_baseline_comparisons(question_id)

    assert evidence[0].source_type == "adapter:polymarket"
    assert evidence[0].metadata["market_id"] == "pm-123"
    assert baselines[0]["source"] == "polymarket:will-polymarket-baselines-attach"
    assert baselines[0]["probability_or_distribution"] == 0.37
    assert baselines[0]["metadata"]["adapter"] == "polymarket"
    if output:
        assert "captured polymarket evidence" in output
        assert "captured polymarket baseline comparison" in output
        assert "probability: 0.370" in output


def test_forecast_cli_metaculus_import_adds_baseline_to_existing_question(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Metaculus baselines attach?",
            "--resolution-criteria",
            "Resolved yes if a Metaculus baseline attaches.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    server = _serve_import_payload(
        json.dumps(
            {
                "question": {
                    "id": 3530,
                    "title": "Will Metaculus baselines attach?",
                    "description": "Resolved by Metaculus.",
                    "resolution_criteria": "Resolved by Metaculus admins.",
                    "type": "binary",
                    "aggregations": {
                        "recency_weighted": {
                            "latest": {
                                "forecast_values": [0.46],
                            }
                        }
                    },
                    "last_prediction_time": "2026-05-01T00:00:00Z",
                    "status": "open",
                }
            }
        )
    )
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/api/questions/3530/"
        _run(parser, ["forecast", "--db", db, "import", "metaculus", url, "--question", question_id])
    finally:
        server.shutdown()
    output = capsys.readouterr().out
    ledger = ForecastLedger(db_path)
    evidence = ledger.list_evidence(question_id)
    baselines = ledger.list_baseline_comparisons(question_id)

    assert "captured metaculus evidence" in output
    assert "captured metaculus baseline comparison" in output
    assert "probability: 0.460" in output
    assert evidence[0].source_type == "adapter:metaculus"
    assert evidence[0].metadata["question_id"] == "3530"
    assert baselines[0]["source"] == "metaculus:3530"
    assert baselines[0]["probability_or_distribution"] == 0.46
    assert baselines[0]["metadata"]["adapter"] == "metaculus"


def test_forecast_cli_kalshi_import_adds_baseline_to_existing_question(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Kalshi baselines attach?",
            "--resolution-criteria",
            "Resolved yes if a Kalshi baseline attaches.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    server = _serve_import_payload(
        json.dumps(
            {
                "market": {
                    "ticker": "KXTEST-26",
                    "event_ticker": "KXTEST",
                    "title": "Will Kalshi baselines attach?",
                    "rules_primary": "Resolved by Kalshi settlement.",
                    "yes_bid": 52,
                    "yes_ask": 56,
                    "status": "active",
                    "close_time": "2026-06-01T00:00:00Z",
                    "last_update_time": "2026-05-01T00:00:00Z",
                }
            }
        )
    )
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/trade-api/v2/markets/KXTEST-26"
        _run(parser, ["forecast", "--db", db, "import", "kalshi", url, "--question", question_id])
    finally:
        server.shutdown()
    output = capsys.readouterr().out
    ledger = ForecastLedger(db_path)
    evidence = ledger.list_evidence(question_id)
    baselines = ledger.list_baseline_comparisons(question_id)

    assert "captured kalshi evidence" in output
    assert "captured kalshi baseline comparison" in output
    assert "probability: 0.540" in output
    assert evidence[0].source_type == "adapter:kalshi"
    assert evidence[0].metadata["ticker"] == "KXTEST-26"
    assert baselines[0]["source"] == "kalshi:KXTEST-26"
    assert baselines[0]["probability_or_distribution"] == 0.54
    assert baselines[0]["metadata"]["adapter"] == "kalshi"


def test_forecast_import_adapter_stages_candidate_with_baseline(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "metaculus",
            "https://example.com/metaculus/question",
            "--title",
            "Will adapter context remain optional?",
            "--resolution-criteria",
            "Resolved yes if the adapter remains optional.",
            "--baseline-probability",
            "0.61",
            "--baseline-type",
            "crowd",
            "--as-of",
            "2026-05-01T00:00:00Z",
        ],
    )
    output = capsys.readouterr().out
    candidate_id = re.search(r"created metaculus import candidate (ic_[a-f0-9]+)", output).group(1)

    _run(parser, ["forecast", "--db", db, "ingest", "--confirm", candidate_id, "--domain", "general"])
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    baselines = ForecastLedger(db_path).list_baseline_comparisons(question_id)

    assert baselines[0]["source"] == "metaculus"
    assert baselines[0]["baseline_type"] == "crowd"
    assert baselines[0]["probability_or_distribution"] == 0.61


def test_forecast_cli_news_import_captures_rss_items_as_evidence(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will RSS evidence import work?",
            "--resolution-criteria",
            "Resolved yes if RSS evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    feed = tmp_path / "feed.xml"
    feed.write_text(
        """<?xml version="1.0" encoding="UTF-8" ?>
        <rss version="2.0">
          <channel>
            <title>Example News</title>
            <item>
              <title>Old item</title>
              <description>Old context.</description>
              <pubDate>Thu, 01 Jan 2026 00:00:00 GMT</pubDate>
              <guid>old-1</guid>
            </item>
            <item>
              <title>Material update</title>
              <description>Fresh evidence for the forecast.</description>
              <pubDate>Sat, 03 Jan 2026 12:30:00 GMT</pubDate>
              <guid>fresh-1</guid>
            </item>
          </channel>
        </rss>
        """,
        encoding="utf-8",
    )

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "news",
            str(feed),
            "--question",
            question_id,
            "--since",
            "2026-01-02T00:00:00Z",
            "--limit",
            "5",
            "--reliability",
            "0.8",
            "--relevance",
            "0.7",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 news evidence item(s)" in output
    assert evidence[0].claim == "Material update"
    assert evidence[0].summary == "Fresh evidence for the forecast."
    assert evidence[0].source_name == "Example News"
    assert evidence[0].source_type == "adapter:news"
    assert evidence[0].published_at == "2026-01-03T12:30:00Z"
    assert evidence[0].metadata["feed_entry_id"] == "fresh-1"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.7


def test_forecast_cli_data_import_adds_csv_rows_as_evidence(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will data adapters create evidence?",
            "--resolution-criteria",
            "Resolved yes if generic data import creates timestamped evidence.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    source = tmp_path / "indicators.csv"
    source.write_text(
        "\n".join(
            [
                "date,dataset,metric,value,summary,stance",
                "2026-01-01T00:00:00Z,macro-feed,unemployment,4.8,Old observation,context",
                "2026-01-03T00:00:00Z,macro-feed,unemployment,5.1,Fresh observation,increases",
            ]
        ),
        encoding="utf-8",
    )

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "data",
            str(source),
            "--question",
            question_id,
            "--since",
            "2026-01-02T00:00:00Z",
            "--limit",
            "5",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.9",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 data evidence item(s)" in output
    assert evidence[0].claim == "unemployment: 5.1"
    assert evidence[0].summary == "Fresh observation"
    assert evidence[0].available_at == "2026-01-03T00:00:00Z"
    assert evidence[0].source_name == "macro-feed"
    assert evidence[0].source_type == "adapter:data"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].stance == "increases"
    assert evidence[0].reliability_rating == 0.9
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["row_index"] == 1


def test_gdelt_adapter_builds_article_list_query(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "articles": [
                {
                    "title": "Policy bill advances",
                    "url": "https://example.test/policy-bill",
                    "domain": "example.test",
                    "sourcecountry": "US",
                    "language": "English",
                    "seendate": "20260521083000",
                    "socialimage": "https://example.test/image.jpg",
                }
            ]
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    articles = source_adapters.load_gdelt_articles(
        "policy bill",
        limit=2,
        since="2026-05-20T00:00:00Z",
        timespan="7d",
        source_country="United States",
        source_lang="English",
        api_base_url="https://gdelt.test/api/v2/doc/doc",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "gdelt article list"
    assert parsed.netloc == "gdelt.test"
    assert params["mode"] == ["ArtList"]
    assert params["format"] == ["json"]
    assert params["maxrecords"] == ["2"]
    assert params["timespan"] == ["7d"]
    assert params["startdatetime"] == ["20260520000000"]
    assert params["query"] == ["policy bill sourcecountry:unitedstates sourcelang:english"]
    assert articles[0].title == "Policy bill advances"
    assert articles[0].published_at == "2026-05-21T08:30:00Z"
    assert articles[0].domain == "example.test"


def test_forecast_cli_gdelt_import_captures_articles_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_gdelt_articles(query: str, **kwargs):
        captured["query"] = query
        captured["kwargs"] = kwargs
        return [
            GdeltArticle(
                title="Material policy update",
                summary="A monitored bill advanced out of committee.",
                url=None,
                published_at="2026-05-21T08:30:00Z",
                source_name="example.test",
                entry_id="gdelt-article-1",
                domain="example.test",
                source_country="US",
                language="English",
                image_url="https://example.test/image.jpg",
                raw={"title": "Material policy update"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_gdelt_articles", fake_load_gdelt_articles)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will GDELT evidence import work?",
            "--resolution-criteria",
            "Resolved yes if GDELT evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "gdelt",
            "policy bill",
            "--question",
            question_id,
            "--timespan",
            "7d",
            "--source-country",
            "US",
            "--source-lang",
            "English",
            "--limit",
            "3",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.85",
            "--relevance",
            "0.75",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 gdelt evidence item(s)" in output
    assert captured["query"] == "policy bill"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["timespan"] == "7d"
    assert captured["kwargs"]["source_country"] == "US"
    assert captured["kwargs"]["source_lang"] == "English"
    assert evidence[0].claim == "Material policy update"
    assert evidence[0].summary == "A monitored bill advanced out of committee."
    assert evidence[0].source_name == "example.test"
    assert evidence[0].source_type == "adapter:gdelt"
    assert evidence[0].published_at == "2026-05-21T08:30:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.85
    assert evidence[0].relevance_rating == 0.75
    assert evidence[0].metadata["adapter"] == "gdelt"
    assert evidence[0].metadata["gdelt_query"] == "policy bill"
    assert evidence[0].metadata["gdelt_article_id"] == "gdelt-article-1"
    assert evidence[0].metadata["domain"] == "example.test"


def test_fivethirtyeight_adapter_loads_and_filters_poll_csv(monkeypatch):
    captured = {}
    csv_text = "\n".join(
        [
            "poll_id,question_id,pollster,fte_grade,state,start_date,end_date,created_at,cycle,office_type,candidate_name,answer,party,pct,sample_size,population,url",
            "p1,q1,Example Polls,A,PA,5/20/26,5/22/26,5/23/26,2026,PRES,Jane Candidate,Jane Candidate,DEM,48.4,1000,lv,https://polls.test/p1",
            "p2,q2,Other Polls,B,MI,5/21/26,5/23/26,5/24/26,2026,PRES,Other Candidate,Other Candidate,REP,45.1,900,rv,https://polls.test/p2",
        ]
    )

    def fake_read_text_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return csv_text

    monkeypatch.setattr(source_adapters, "_read_text_endpoint", fake_read_text_endpoint)

    observations = source_adapters.load_fivethirtyeight_polls(
        "fivethirtyeight:president",
        limit=5,
        since="2026-05-22",
        state="PA",
        candidate="Jane",
        pollster="Example",
        cycle=2026,
        office_type="PRES",
        api_base_url="https://polls.test/data",
    )

    assert captured["label"] == "fivethirtyeight polls"
    assert captured["endpoint"] == "https://polls.test/data/president_polls.csv"
    assert len(observations) == 1
    assert observations[0].dataset == "president_polls"
    assert observations[0].poll_id == "p1"
    assert observations[0].question_id == "q1"
    assert observations[0].pollster == "Example Polls"
    assert observations[0].pollster_grade == "A"
    assert observations[0].state == "PA"
    assert observations[0].candidate_name == "Jane Candidate"
    assert observations[0].pct == 48.4
    assert observations[0].sample_size == 1000
    assert observations[0].start_date == "2026-05-20"
    assert observations[0].end_date == "2026-05-22"
    assert observations[0].published_at == "2026-05-23T00:00:00Z"


def test_forecast_cli_fivethirtyeight_import_captures_polls_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_fivethirtyeight_polls(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
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
                pct=48.4,
                sample_size=1000,
                population="lv",
                start_date="2026-05-20",
                end_date="2026-05-22",
                published_at="2026-05-23T00:00:00Z",
                source_url="https://polls.test/p1",
                source_name="Example Polls",
                entry_id="president_polls:p1:q1:Jane Candidate",
                raw={"poll_id": "p1"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_fivethirtyeight_polls", fake_load_fivethirtyeight_polls)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will the candidate win Pennsylvania?",
            "--resolution-criteria",
            "Resolved by certified election result.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "fivethirtyeight",
            "president",
            "--question",
            question_id,
            "--state",
            "PA",
            "--candidate",
            "Jane",
            "--pollster",
            "Example",
            "--cycle",
            "2026",
            "--office-type",
            "PRES",
            "--limit",
            "3",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 fivethirtyeight evidence item(s)" in output
    assert captured["source"] == "president"
    assert captured["kwargs"]["state"] == "PA"
    assert captured["kwargs"]["candidate"] == "Jane"
    assert captured["kwargs"]["pollster"] == "Example"
    assert captured["kwargs"]["cycle"] == 2026
    assert captured["kwargs"]["office_type"] == "PRES"
    assert evidence[0].source_name == "Example Polls"
    assert evidence[0].source_type == "adapter:fivethirtyeight"
    assert evidence[0].published_at == "2026-05-23T00:00:00Z"
    assert evidence[0].claim == "FiveThirtyEight poll: Jane Candidate 48.4% in PA"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "fivethirtyeight"
    assert evidence[0].metadata["dataset"] == "president_polls"
    assert evidence[0].metadata["poll_id"] == "p1"
    assert evidence[0].metadata["pct"] == 48.4


def test_github_adapter_loads_repository_releases(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return [
            {
                "id": 123,
                "tag_name": "v1.2.3",
                "name": "Forecast release",
                "body": " Adds calibrated release notes. ",
                "url": "https://api.github.test/repos/acme/desk/releases/123",
                "html_url": "https://github.com/acme/desk/releases/tag/v1.2.3",
                "created_at": "2026-05-20T10:00:00Z",
                "published_at": "2026-05-21T11:00:00Z",
                "draft": False,
                "prerelease": True,
            }
        ]

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    releases = source_adapters.load_github_releases(
        "https://github.com/acme/desk",
        limit=2,
        since="2026-05-01T00:00:00Z",
        api_base_url="https://api.github.test",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "github releases"
    assert parsed.path == "/repos/acme/desk/releases"
    assert params["per_page"] == ["2"]
    assert releases[0].repo == "acme/desk"
    assert releases[0].release_id == "123"
    assert releases[0].tag_name == "v1.2.3"
    assert releases[0].body == "Adds calibrated release notes."
    assert releases[0].published_at == "2026-05-21T11:00:00Z"
    assert releases[0].prerelease is True


def test_forecast_cli_github_import_captures_releases_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_github_releases(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            GitHubRelease(
                repo="acme/desk",
                release_id="123",
                tag_name="v1.2.3",
                name="Forecast release",
                body="Adds calibrated release notes.",
                url="https://api.github.test/repos/acme/desk/releases/123",
                html_url="https://github.com/acme/desk/releases/tag/v1.2.3",
                created_at="2026-05-20T10:00:00Z",
                published_at="2026-05-21T11:00:00Z",
                draft=False,
                prerelease=True,
                source_name="GitHub",
                entry_id="123",
                raw={"id": 123},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_github_releases", fake_load_github_releases)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will GitHub release evidence import work?",
            "--resolution-criteria",
            "Resolved yes if GitHub release evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "github",
            "acme/desk",
            "--question",
            question_id,
            "--limit",
            "3",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 github evidence item(s)" in output
    assert captured["source"] == "acme/desk"
    assert captured["kwargs"]["limit"] == 3
    assert evidence[0].claim == "GitHub release: acme/desk v1.2.3"
    assert evidence[0].summary == "Adds calibrated release notes."
    assert evidence[0].source_name == "GitHub"
    assert evidence[0].source_type == "adapter:github"
    assert evidence[0].published_at == "2026-05-21T11:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "github"
    assert evidence[0].metadata["repo"] == "acme/desk"
    assert evidence[0].metadata["release_id"] == "123"
    assert evidence[0].metadata["tag_name"] == "v1.2.3"
    assert evidence[0].metadata["prerelease"] is True


def test_githubrepo_adapter_loads_repository_snapshot(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "id": 456,
            "node_id": "R_456",
            "full_name": "acme/desk",
            "owner": {"login": "acme"},
            "description": " Forecasting desk repository. ",
            "language": "Python",
            "default_branch": "main",
            "visibility": "public",
            "license": {"spdx_id": "MIT"},
            "topics": ["forecasting", "agents"],
            "archived": False,
            "disabled": False,
            "fork": False,
            "stargazers_count": 1234,
            "watchers_count": 1234,
            "forks_count": 56,
            "open_issues_count": 7,
            "subscribers_count": 89,
            "network_count": 60,
            "url": "https://api.github.test/repos/acme/desk",
            "html_url": "https://github.com/acme/desk",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2026-05-21T11:00:00Z",
            "pushed_at": "2026-05-20T10:00:00Z",
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    snapshots = source_adapters.load_github_repository_snapshots(
        "githubrepo:acme/desk",
        limit=1,
        since="2026-05-01T00:00:00Z",
        api_base_url="https://api.github.test",
    )
    parsed = urlparse(captured["endpoint"])

    assert captured["label"] == "github repository"
    assert parsed.path == "/repos/acme/desk"
    assert snapshots[0].repo == "acme/desk"
    assert snapshots[0].repo_id == "456"
    assert snapshots[0].description == "Forecasting desk repository."
    assert snapshots[0].stargazers_count == 1234
    assert snapshots[0].forks_count == 56
    assert snapshots[0].open_issues_count == 7
    assert snapshots[0].topics == ["forecasting", "agents"]


def test_forecast_cli_githubrepo_import_captures_repository_snapshot_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_github_repository_snapshots(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            GitHubRepositorySnapshot(
                repo="acme/desk",
                repo_id="456",
                owner_login="acme",
                description="Forecasting desk repository.",
                language="Python",
                default_branch="main",
                visibility="public",
                license_spdx_id="MIT",
                topics=["forecasting", "agents"],
                archived=False,
                disabled=False,
                fork=False,
                stargazers_count=1234,
                watchers_count=1234,
                forks_count=56,
                open_issues_count=7,
                subscribers_count=89,
                network_count=60,
                created_at="2024-01-01T00:00:00Z",
                updated_at="2026-05-21T11:00:00Z",
                pushed_at="2026-05-20T10:00:00Z",
                url="https://api.github.test/repos/acme/desk",
                html_url="https://github.com/acme/desk",
                source_name="GitHub",
                entry_id="R_456",
                raw={"id": 456},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_github_repository_snapshots", fake_load_github_repository_snapshots)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will GitHub repository metadata import work?",
            "--resolution-criteria",
            "Resolved yes if GitHub repository metadata evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "githubrepo",
            "acme/desk",
            "--question",
            question_id,
            "--limit",
            "1",
            "--claim-type",
            "fact",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 githubrepo evidence item(s)" in output
    assert captured["source"] == "acme/desk"
    assert captured["kwargs"]["limit"] == 1
    assert evidence[0].claim == "GitHub repository snapshot: acme/desk 1234 stars 56 forks"
    assert "7 open issues" in evidence[0].summary
    assert evidence[0].source_name == "GitHub"
    assert evidence[0].source_type == "adapter:githubrepo"
    assert evidence[0].published_at == "2026-05-21T11:00:00Z"
    assert evidence[0].claim_type == "fact"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "githubrepo"
    assert evidence[0].metadata["repo"] == "acme/desk"
    assert evidence[0].metadata["stargazers_count"] == 1234
    assert evidence[0].metadata["topics"] == ["forecasting", "agents"]


def test_githubissues_adapter_loads_repository_issues(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return [
            {
                "id": 456,
                "number": 42,
                "title": "Ship forecast ledger",
                "state": "open",
                "user": {"login": "analyst"},
                "labels": [{"name": "forecasting"}, {"name": "release"}],
                "created_at": "2026-05-20T10:00:00Z",
                "updated_at": "2026-05-21T11:00:00Z",
                "closed_at": None,
                "comments": 7,
                "url": "https://api.github.test/repos/acme/desk/issues/42",
                "html_url": "https://github.com/acme/desk/issues/42",
                "pull_request": {"url": "https://api.github.test/repos/acme/desk/pulls/42"},
            }
        ]

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    issues = source_adapters.load_github_issues(
        "githubissues:acme/desk",
        limit=2,
        since="2026-05-01T00:00:00Z",
        state="all",
        api_base_url="https://api.github.test",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "github issues"
    assert parsed.path == "/repos/acme/desk/issues"
    assert params["per_page"] == ["2"]
    assert params["state"] == ["all"]
    assert params["sort"] == ["updated"]
    assert issues[0].repo == "acme/desk"
    assert issues[0].issue_number == 42
    assert issues[0].title == "Ship forecast ledger"
    assert issues[0].is_pull_request is True
    assert issues[0].labels == ["forecasting", "release"]
    assert issues[0].updated_at == "2026-05-21T11:00:00Z"
    assert issues[0].comments == 7


def test_forecast_cli_githubissues_import_captures_issues_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_github_issues(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            GitHubIssue(
                repo="acme/desk",
                issue_number=42,
                title="Ship forecast ledger",
                state="open",
                is_pull_request=True,
                author="analyst",
                labels=["forecasting", "release"],
                created_at="2026-05-20T10:00:00Z",
                updated_at="2026-05-21T11:00:00Z",
                closed_at=None,
                comments=7,
                url="https://api.github.test/repos/acme/desk/issues/42",
                html_url="https://github.com/acme/desk/pull/42",
                source_name="GitHub",
                entry_id="acme/desk#42",
                raw={"number": 42},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_github_issues", fake_load_github_issues)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will GitHub issue evidence import work?",
            "--resolution-criteria",
            "Resolved yes if GitHub issue evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "githubissues",
            "acme/desk",
            "--question",
            question_id,
            "--limit",
            "3",
            "--since",
            "2026-05-01T00:00:00Z",
            "--state",
            "all",
            "--api-base-url",
            "https://api.github.test",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 githubissues evidence item(s)" in output
    assert captured["source"] == "acme/desk"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["state"] == "all"
    assert captured["kwargs"]["api_base_url"] == "https://api.github.test"
    assert evidence[0].claim == "GitHub pull request: acme/desk #42 open"
    assert evidence[0].summary.startswith("GitHub pull request acme/desk #42")
    assert evidence[0].source_name == "GitHub"
    assert evidence[0].source_type == "adapter:githubissues"
    assert evidence[0].published_at == "2026-05-21T11:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "githubissues"
    assert evidence[0].metadata["repo"] == "acme/desk"
    assert evidence[0].metadata["issue_number"] == 42
    assert evidence[0].metadata["is_pull_request"] is True
    assert evidence[0].metadata["labels"] == ["forecasting", "release"]


def test_githubcommits_adapter_loads_repository_commits(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return [
            {
                "sha": "abcdef1234567890",
                "commit": {
                    "message": "Add calibrated forecast dashboard\n\nDetails.",
                    "author": {"name": "Ada Analyst", "date": "2026-05-20T10:00:00Z"},
                    "committer": {"date": "2026-05-21T11:00:00Z"},
                    "comment_count": 2,
                },
                "author": {"login": "ada"},
                "url": "https://api.github.test/repos/acme/desk/commits/abcdef1234567890",
                "html_url": "https://github.com/acme/desk/commit/abcdef1234567890",
            }
        ]

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    commits = source_adapters.load_github_commits(
        "githubcommits:acme/desk",
        limit=2,
        since="2026-05-01T00:00:00Z",
        api_base_url="https://api.github.test",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "github commits"
    assert parsed.path == "/repos/acme/desk/commits"
    assert params["per_page"] == ["2"]
    assert params["since"] == ["2026-05-01T00:00:00Z"]
    assert commits[0].repo == "acme/desk"
    assert commits[0].sha == "abcdef1234567890"
    assert commits[0].short_sha == "abcdef1"
    assert commits[0].message == "Add calibrated forecast dashboard Details."
    assert commits[0].author_name == "Ada Analyst"
    assert commits[0].author_login == "ada"
    assert commits[0].committed_at == "2026-05-21T11:00:00Z"
    assert commits[0].comments == 2


def test_forecast_cli_githubcommits_import_captures_commits_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_github_commits(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            GitHubCommit(
                repo="acme/desk",
                sha="abcdef1234567890",
                short_sha="abcdef1",
                message="Add calibrated forecast dashboard",
                author_name="Ada Analyst",
                author_login="ada",
                authored_at="2026-05-20T10:00:00Z",
                committed_at="2026-05-21T11:00:00Z",
                comments=2,
                url="https://api.github.test/repos/acme/desk/commits/abcdef1234567890",
                html_url="https://github.com/acme/desk/commit/abcdef1234567890",
                source_name="GitHub",
                entry_id="acme/desk@abcdef1234567890",
                raw={"sha": "abcdef1234567890"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_github_commits", fake_load_github_commits)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will GitHub commit evidence import work?",
            "--resolution-criteria",
            "Resolved yes if GitHub commit evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "githubcommits",
            "acme/desk",
            "--question",
            question_id,
            "--limit",
            "3",
            "--since",
            "2026-05-01T00:00:00Z",
            "--api-base-url",
            "https://api.github.test",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 githubcommits evidence item(s)" in output
    assert captured["source"] == "acme/desk"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["api_base_url"] == "https://api.github.test"
    assert evidence[0].claim == "GitHub commit: acme/desk abcdef1"
    assert evidence[0].summary.startswith("GitHub commit acme/desk@abcdef1")
    assert evidence[0].source_name == "GitHub"
    assert evidence[0].source_type == "adapter:githubcommits"
    assert evidence[0].published_at == "2026-05-21T11:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "githubcommits"
    assert evidence[0].metadata["repo"] == "acme/desk"
    assert evidence[0].metadata["sha"] == "abcdef1234567890"
    assert evidence[0].metadata["author_login"] == "ada"


def test_githubactions_adapter_loads_workflow_runs(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 987,
                    "name": "CI",
                    "display_title": "Add calibrated forecast dashboard",
                    "status": "completed",
                    "conclusion": "success",
                    "event": "push",
                    "head_branch": "main",
                    "head_sha": "abcdef1234567890",
                    "workflow_id": 1234,
                    "workflow_url": "https://api.github.test/repos/acme/desk/actions/workflows/1234",
                    "actor": {"login": "ada"},
                    "triggering_actor": {"login": "ci-bot"},
                    "run_started_at": "2026-05-21T10:30:00Z",
                    "created_at": "2026-05-21T10:00:00Z",
                    "updated_at": "2026-05-21T11:00:00Z",
                    "url": "https://api.github.test/repos/acme/desk/actions/runs/987",
                    "html_url": "https://github.com/acme/desk/actions/runs/987",
                }
            ],
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    runs = source_adapters.load_github_workflow_runs(
        "githubactions:acme/desk",
        limit=2,
        since="2026-05-01T00:00:00Z",
        api_base_url="https://api.github.test",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "github actions workflow runs"
    assert parsed.path == "/repos/acme/desk/actions/runs"
    assert params["per_page"] == ["2"]
    assert runs[0].repo == "acme/desk"
    assert runs[0].run_id == "987"
    assert runs[0].name == "CI"
    assert runs[0].display_title == "Add calibrated forecast dashboard"
    assert runs[0].status == "completed"
    assert runs[0].conclusion == "success"
    assert runs[0].event == "push"
    assert runs[0].head_branch == "main"
    assert runs[0].short_sha == "abcdef1"
    assert runs[0].triggering_actor_login == "ci-bot"
    assert runs[0].updated_at == "2026-05-21T11:00:00Z"


def test_forecast_cli_githubactions_import_captures_runs_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_github_workflow_runs(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            GitHubWorkflowRun(
                repo="acme/desk",
                run_id="987",
                name="CI",
                display_title="Add calibrated forecast dashboard",
                status="completed",
                conclusion="failure",
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
                raw={"id": 987},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_github_workflow_runs", fake_load_github_workflow_runs)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will GitHub Actions evidence import work?",
            "--resolution-criteria",
            "Resolved yes if GitHub Actions evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "githubactions",
            "acme/desk",
            "--question",
            question_id,
            "--limit",
            "3",
            "--since",
            "2026-05-01T00:00:00Z",
            "--api-base-url",
            "https://api.github.test",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 githubactions evidence item(s)" in output
    assert captured["source"] == "acme/desk"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["api_base_url"] == "https://api.github.test"
    assert evidence[0].claim == "GitHub Actions run: acme/desk 987 failure"
    assert evidence[0].summary.startswith("GitHub Actions run acme/desk #987")
    assert evidence[0].source_name == "GitHub"
    assert evidence[0].source_type == "adapter:githubactions"
    assert evidence[0].published_at == "2026-05-21T11:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "githubactions"
    assert evidence[0].metadata["repo"] == "acme/desk"
    assert evidence[0].metadata["run_id"] == "987"
    assert evidence[0].metadata["conclusion"] == "failure"
    assert evidence[0].metadata["head_branch"] == "main"


def test_coingecko_adapter_loads_market_snapshots(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return [
            {
                "id": "bitcoin",
                "symbol": "btc",
                "name": "Bitcoin",
                "current_price": 109500,
                "market_cap": 2170000000000,
                "market_cap_rank": 1,
                "total_volume": 51200000000,
                "price_change_percentage_24h": 2.34,
                "last_updated": "2026-05-21T11:00:00.000Z",
            }
        ]

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    snapshots = source_adapters.load_coingecko_market_snapshots(
        "coingecko:bitcoin,ethereum",
        limit=2,
        since="2026-05-01T00:00:00Z",
        vs_currency="usd",
        api_base_url="https://api.coingecko.test/api/v3/coins/markets",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "coingecko markets"
    assert parsed.path == "/api/v3/coins/markets"
    assert params["ids"] == ["bitcoin,ethereum"]
    assert params["vs_currency"] == ["usd"]
    assert params["per_page"] == ["2"]
    assert params["price_change_percentage"] == ["24h"]
    assert snapshots[0].coin_id == "bitcoin"
    assert snapshots[0].symbol == "btc"
    assert snapshots[0].current_price == 109500
    assert snapshots[0].market_cap_rank == 1
    assert snapshots[0].last_updated == "2026-05-21T11:00:00Z"


def test_forecast_cli_coingecko_import_captures_snapshots_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_coingecko_snapshots(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            CoinGeckoMarketSnapshot(
                coin_id="bitcoin",
                symbol="btc",
                name="Bitcoin",
                vs_currency="usd",
                current_price=109500,
                market_cap=2170000000000,
                market_cap_rank=1,
                total_volume=51200000000,
                price_change_percentage_24h=2.34,
                last_updated="2026-05-21T11:00:00Z",
                source_url="https://www.coingecko.com/en/coins/bitcoin",
                source_name="CoinGecko",
                entry_id="bitcoin:usd:2026-05-21T11:00:00Z",
                raw={"id": "bitcoin"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_coingecko_market_snapshots", fake_load_coingecko_snapshots)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will CoinGecko evidence import work?",
            "--resolution-criteria",
            "Resolved yes if CoinGecko crypto evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "coingecko",
            "bitcoin",
            "--question",
            question_id,
            "--limit",
            "3",
            "--since",
            "2026-05-01T00:00:00Z",
            "--vs-currency",
            "usd",
            "--api-base-url",
            "https://api.coingecko.test/api/v3/coins/markets",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 coingecko evidence item(s)" in output
    assert captured["source"] == "bitcoin"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["vs_currency"] == "usd"
    assert captured["kwargs"]["api_base_url"] == "https://api.coingecko.test/api/v3/coins/markets"
    assert evidence[0].claim == "CoinGecko bitcoin price: 109500 USD"
    assert evidence[0].summary.startswith("CoinGecko market snapshot for Bitcoin")
    assert evidence[0].source_name == "CoinGecko"
    assert evidence[0].source_type == "adapter:coingecko"
    assert evidence[0].published_at == "2026-05-21T11:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "coingecko"
    assert evidence[0].metadata["coin_id"] == "bitcoin"
    assert evidence[0].metadata["current_price"] == 109500
    assert evidence[0].metadata["price_change_percentage_24h"] == 2.34


def test_pypi_adapter_loads_package_releases(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "info": {
                "name": "forecast-desk",
                "summary": "Forecasting command line tools.",
                "version": "1.2.3",
                "package_url": "https://pypi.org/project/forecast-desk/",
            },
            "releases": {
                "1.2.3": [
                    {
                        "filename": "forecast_desk-1.2.3-py3-none-any.whl",
                        "packagetype": "bdist_wheel",
                        "python_version": "py3",
                        "upload_time_iso_8601": "2026-05-21T11:00:00.000000Z",
                        "url": "https://files.pythonhosted.org/packages/forecast_desk.whl",
                        "yanked": False,
                    },
                    {
                        "filename": "forecast_desk-1.2.3.tar.gz",
                        "packagetype": "sdist",
                        "python_version": "source",
                        "upload_time_iso_8601": "2026-05-21T11:05:00.000000Z",
                        "yanked": False,
                    },
                ],
                "1.1.0": [
                    {
                        "filename": "forecast_desk-1.1.0.tar.gz",
                        "packagetype": "sdist",
                        "python_version": "source",
                        "upload_time_iso_8601": "2026-04-01T09:00:00Z",
                        "yanked": True,
                        "yanked_reason": "bad metadata",
                    }
                ],
            },
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    releases = source_adapters.load_pypi_releases(
        "https://pypi.org/project/forecast-desk/",
        limit=2,
        since="2026-05-01",
        api_base_url="https://pypi.test/pypi",
    )
    parsed = urlparse(captured["endpoint"])

    assert captured["label"] == "pypi package"
    assert parsed.path == "/pypi/forecast-desk/json"
    assert len(releases) == 1
    assert releases[0].package == "forecast-desk"
    assert releases[0].version == "1.2.3"
    assert releases[0].summary == "Forecasting command line tools."
    assert releases[0].uploaded_at == "2026-05-21T11:00:00Z"
    assert releases[0].latest_upload_at == "2026-05-21T11:05:00Z"
    assert releases[0].file_count == 2
    assert releases[0].package_types == ["bdist_wheel", "sdist"]
    assert releases[0].python_versions == ["py3", "source"]
    assert releases[0].yanked is False


def test_forecast_cli_pypi_import_captures_releases_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_pypi_releases(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            PypiRelease(
                package="forecast-desk",
                version="1.2.3",
                summary="Forecasting command line tools.",
                url="https://pypi.org/project/forecast-desk/1.2.3/",
                project_url="https://pypi.org/project/forecast-desk/",
                uploaded_at="2026-05-21T11:00:00Z",
                latest_upload_at="2026-05-21T11:05:00Z",
                file_count=2,
                package_types=["bdist_wheel", "sdist"],
                python_versions=["py3", "source"],
                yanked=False,
                yanked_reason=None,
                source_name="PyPI",
                entry_id="forecast-desk:1.2.3",
                raw={"version": "1.2.3"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_pypi_releases", fake_load_pypi_releases)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will PyPI release evidence import work?",
            "--resolution-criteria",
            "Resolved yes if PyPI release evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "pypi",
            "forecast-desk",
            "--question",
            question_id,
            "--limit",
            "3",
            "--since",
            "2026-05-01",
            "--api-base-url",
            "https://pypi.test/pypi",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.82",
            "--relevance",
            "0.88",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 pypi evidence item(s)" in output
    assert captured["source"] == "forecast-desk"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-05-01"
    assert captured["kwargs"]["api_base_url"] == "https://pypi.test/pypi"
    assert evidence[0].claim == "PyPI release: forecast-desk 1.2.3"
    assert evidence[0].summary.startswith("PyPI release forecast-desk 1.2.3")
    assert evidence[0].source_name == "PyPI"
    assert evidence[0].source_type == "adapter:pypi"
    assert evidence[0].published_at == "2026-05-21T11:00:00Z"
    assert evidence[0].available_at == "2026-05-21T11:05:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.82
    assert evidence[0].relevance_rating == 0.88
    assert evidence[0].metadata["adapter"] == "pypi"
    assert evidence[0].metadata["package"] == "forecast-desk"
    assert evidence[0].metadata["version"] == "1.2.3"
    assert evidence[0].metadata["file_count"] == 2
    assert evidence[0].metadata["package_types"] == ["bdist_wheel", "sdist"]


def test_npm_adapter_loads_package_versions(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "name": "@forecast/desk",
            "description": "Forecasting interface components.",
            "dist-tags": {"latest": "2.0.0"},
            "time": {
                "created": "2026-04-01T00:00:00Z",
                "1.0.0": "2026-04-10T10:00:00.000Z",
                "2.0.0": "2026-05-21T11:00:00.000Z",
                "modified": "2026-05-21T11:05:00.000Z",
            },
            "versions": {
                "1.0.0": {
                    "name": "@forecast/desk",
                    "version": "1.0.0",
                    "description": "Old version.",
                    "license": "MIT",
                    "dist": {"tarball": "https://registry.npm.test/@forecast/desk/-/desk-1.0.0.tgz"},
                },
                "2.0.0": {
                    "name": "@forecast/desk",
                    "version": "2.0.0",
                    "description": "Forecasting interface components.",
                    "license": {"type": "Apache-2.0"},
                    "maintainers": [{"name": "analyst"}],
                    "keywords": ["forecasting", "calibration"],
                    "dependencies": {"react": "^19.0.0"},
                    "peerDependencies": {"ink": "^6.0.0"},
                    "dist": {"tarball": "https://registry.npm.test/@forecast/desk/-/desk-2.0.0.tgz"},
                },
            },
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    versions = source_adapters.load_npm_package_versions(
        "https://www.npmjs.com/package/@forecast/desk",
        limit=2,
        since="2026-05-01",
        api_base_url="https://registry.npm.test",
    )
    parsed = urlparse(captured["endpoint"])

    assert captured["label"] == "npm package"
    assert parsed.path == "/%40forecast%2Fdesk"
    assert len(versions) == 1
    assert versions[0].package == "@forecast/desk"
    assert versions[0].version == "2.0.0"
    assert versions[0].description == "Forecasting interface components."
    assert versions[0].published_at == "2026-05-21T11:00:00Z"
    assert versions[0].license == "Apache-2.0"
    assert versions[0].maintainers == ["analyst"]
    assert versions[0].keywords == ["forecasting", "calibration"]
    assert versions[0].dependency_count == 2


def test_forecast_cli_npm_import_captures_versions_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_npm_versions(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            NpmPackageVersion(
                package="@forecast/desk",
                version="2.0.0",
                description="Forecasting interface components.",
                url="https://www.npmjs.com/package/@forecast/desk/v/2.0.0",
                tarball_url="https://registry.npm.test/@forecast/desk/-/desk-2.0.0.tgz",
                published_at="2026-05-21T11:00:00Z",
                license="Apache-2.0",
                maintainers=["analyst"],
                keywords=["forecasting", "calibration"],
                deprecated=None,
                dependency_count=2,
                source_name="npm",
                entry_id="@forecast/desk:2.0.0",
                raw={"version": "2.0.0"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_npm_package_versions", fake_load_npm_versions)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will npm evidence import work?",
            "--resolution-criteria",
            "Resolved yes if npm package evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "npm",
            "@forecast/desk",
            "--question",
            question_id,
            "--limit",
            "2",
            "--since",
            "2026-05-01",
            "--api-base-url",
            "https://registry.npm.test",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.81",
            "--relevance",
            "0.87",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 npm evidence item(s)" in output
    assert captured["source"] == "@forecast/desk"
    assert captured["kwargs"]["limit"] == 2
    assert captured["kwargs"]["since"] == "2026-05-01"
    assert captured["kwargs"]["api_base_url"] == "https://registry.npm.test"
    assert evidence[0].claim == "npm package version: @forecast/desk 2.0.0"
    assert evidence[0].summary.startswith("npm package @forecast/desk 2.0.0")
    assert evidence[0].source_name == "npm"
    assert evidence[0].source_type == "adapter:npm"
    assert evidence[0].published_at == "2026-05-21T11:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.81
    assert evidence[0].relevance_rating == 0.87
    assert evidence[0].metadata["adapter"] == "npm"
    assert evidence[0].metadata["package"] == "@forecast/desk"
    assert evidence[0].metadata["version"] == "2.0.0"
    assert evidence[0].metadata["dependency_count"] == 2


def test_hackernews_adapter_loads_search_results(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "hits": [
                {
                    "objectID": "12345",
                    "title": "Forecast Desk launches public beta",
                    "url": "https://example.test/forecast-desk",
                    "author": "analyst",
                    "created_at": "2026-05-21T14:30:00Z",
                    "points": 128,
                    "num_comments": 34,
                    "story_id": 12345,
                    "story_text": "Public beta discussion.",
                }
            ]
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    items = source_adapters.load_hackernews_items(
        "forecast desk",
        limit=2,
        since="2026-05-01T00:00:00Z",
        api_base_url="https://hn.test/api/v1/search_by_date",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "hackernews search"
    assert parsed.path == "/api/v1/search_by_date"
    assert params["query"] == ["forecast desk"]
    assert params["tags"] == ["story"]
    assert params["hitsPerPage"] == ["2"]
    assert "numericFilters" in params
    assert items[0].object_id == "12345"
    assert items[0].title == "Forecast Desk launches public beta"
    assert items[0].url == "https://example.test/forecast-desk"
    assert items[0].hn_url == "https://news.ycombinator.com/item?id=12345"
    assert items[0].author == "analyst"
    assert items[0].created_at == "2026-05-21T14:30:00Z"
    assert items[0].points == 128
    assert items[0].comments == 34


def test_forecast_cli_hackernews_import_captures_items_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_hackernews_items(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            HackerNewsItem(
                object_id="12345",
                title="Forecast Desk launches public beta",
                url="https://example.test/forecast-desk",
                hn_url="https://news.ycombinator.com/item?id=12345",
                author="analyst",
                created_at="2026-05-21T14:30:00Z",
                points=128,
                comments=34,
                story_id=12345,
                story_text="Public beta discussion.",
                source_name="Hacker News",
                entry_id="12345",
                raw={"objectID": "12345"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_hackernews_items", fake_load_hackernews_items)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Hacker News evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Hacker News evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "hackernews",
            "forecast desk",
            "--question",
            question_id,
            "--limit",
            "3",
            "--since",
            "2026-05-01T00:00:00Z",
            "--api-base-url",
            "https://hn.test/api/v1/search_by_date",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.72",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 hackernews evidence item(s)" in output
    assert captured["source"] == "forecast desk"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-05-01T00:00:00Z"
    assert captured["kwargs"]["api_base_url"] == "https://hn.test/api/v1/search_by_date"
    assert evidence[0].claim == "Hacker News: Forecast Desk launches public beta"
    assert evidence[0].summary.startswith("Hacker News story by analyst")
    assert evidence[0].source_name == "Hacker News"
    assert evidence[0].source_type == "adapter:hackernews"
    assert evidence[0].published_at == "2026-05-21T14:30:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.72
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["adapter"] == "hackernews"
    assert evidence[0].metadata["object_id"] == "12345"
    assert evidence[0].metadata["points"] == 128
    assert evidence[0].metadata["comments"] == 34


def test_reddit_adapter_loads_search_results(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "data": {
                "children": [
                    {
                        "data": {
                            "name": "t3_abc123",
                            "id": "abc123",
                            "title": "Forecast Desk launches public beta",
                            "subreddit": "forecasting",
                            "author": "analyst",
                            "url": "https://example.test/forecast-desk",
                            "permalink": "/r/forecasting/comments/abc123/forecast_desk/",
                            "created_utc": 1779373800,
                            "score": 128,
                            "num_comments": 34,
                            "upvote_ratio": 0.91,
                            "selftext": "Public beta discussion.",
                        }
                    }
                ]
            }
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    posts = source_adapters.load_reddit_posts(
        "forecast desk",
        limit=2,
        since="2026-05-01T00:00:00Z",
        api_base_url="https://reddit.test/search.json",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "reddit search"
    assert parsed.path == "/search.json"
    assert params["q"] == ["forecast desk"]
    assert params["sort"] == ["new"]
    assert params["limit"] == ["2"]
    assert posts[0].post_id == "t3_abc123"
    assert posts[0].title == "Forecast Desk launches public beta"
    assert posts[0].subreddit == "forecasting"
    assert posts[0].author == "analyst"
    assert posts[0].permalink == "https://www.reddit.com/r/forecasting/comments/abc123/forecast_desk/"
    assert posts[0].created_at == "2026-05-21T14:30:00Z"
    assert posts[0].score == 128
    assert posts[0].comments == 34
    assert posts[0].upvote_ratio == 0.91


def test_forecast_cli_reddit_import_captures_posts_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_reddit_posts(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            RedditPost(
                post_id="t3_abc123",
                title="Forecast Desk launches public beta",
                subreddit="forecasting",
                author="analyst",
                url="https://example.test/forecast-desk",
                permalink="https://www.reddit.com/r/forecasting/comments/abc123/forecast_desk/",
                created_at="2026-05-21T14:30:00Z",
                score=128,
                comments=34,
                upvote_ratio=0.91,
                selftext="Public beta discussion.",
                source_name="Reddit r/forecasting",
                entry_id="t3_abc123",
                raw={"name": "t3_abc123"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_reddit_posts", fake_load_reddit_posts)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Reddit evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Reddit evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "reddit",
            "forecast desk",
            "--question",
            question_id,
            "--limit",
            "3",
            "--since",
            "2026-05-01T00:00:00Z",
            "--api-base-url",
            "https://reddit.test/search.json",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.65",
            "--relevance",
            "0.75",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 reddit evidence item(s)" in output
    assert captured["source"] == "forecast desk"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-05-01T00:00:00Z"
    assert captured["kwargs"]["api_base_url"] == "https://reddit.test/search.json"
    assert evidence[0].claim == "Reddit: Forecast Desk launches public beta"
    assert evidence[0].summary.startswith("Reddit post by analyst in r/forecasting")
    assert evidence[0].source_name == "Reddit r/forecasting"
    assert evidence[0].source_type == "adapter:reddit"
    assert evidence[0].published_at == "2026-05-21T14:30:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.65
    assert evidence[0].relevance_rating == 0.75
    assert evidence[0].metadata["adapter"] == "reddit"
    assert evidence[0].metadata["post_id"] == "t3_abc123"
    assert evidence[0].metadata["score"] == 128
    assert evidence[0].metadata["comments"] == 34


def test_bluesky_adapter_loads_search_results(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "posts": [
                {
                    "uri": "at://did:plc:abc/app.bsky.feed.post/3kforecast",
                    "cid": "bafyforecast",
                    "author": {
                        "did": "did:plc:abc",
                        "handle": "analyst.bsky.social",
                        "displayName": "Analyst",
                    },
                    "record": {
                        "text": "Forecast Desk launches public beta",
                        "createdAt": "2026-05-21T14:30:00.000Z",
                    },
                    "indexedAt": "2026-05-21T14:31:00.000Z",
                    "replyCount": 4,
                    "repostCount": 12,
                    "likeCount": 128,
                    "quoteCount": 3,
                }
            ]
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    posts = source_adapters.load_bluesky_posts(
        "forecast desk",
        limit=2,
        since="2026-05-01T00:00:00Z",
        sort="top",
        author="analyst.bsky.social",
        lang="en",
        link_domain="example.test",
        url_filter="https://example.test/forecast-desk",
        api_base_url="https://bsky.test/xrpc/app.bsky.feed.searchPosts",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "bluesky search"
    assert parsed.path == "/xrpc/app.bsky.feed.searchPosts"
    assert params["q"] == ["forecast desk"]
    assert params["sort"] == ["top"]
    assert params["limit"] == ["2"]
    assert params["since"] == ["2026-05-01T00:00:00Z"]
    assert params["author"] == ["analyst.bsky.social"]
    assert params["lang"] == ["en"]
    assert params["domain"] == ["example.test"]
    assert params["url"] == ["https://example.test/forecast-desk"]
    assert posts[0].post_uri == "at://did:plc:abc/app.bsky.feed.post/3kforecast"
    assert posts[0].cid == "bafyforecast"
    assert posts[0].text == "Forecast Desk launches public beta"
    assert posts[0].author_handle == "analyst.bsky.social"
    assert posts[0].created_at == "2026-05-21T14:30:00Z"
    assert posts[0].indexed_at == "2026-05-21T14:31:00Z"
    assert posts[0].url == "https://bsky.app/profile/analyst.bsky.social/post/3kforecast"
    assert posts[0].reply_count == 4
    assert posts[0].repost_count == 12
    assert posts[0].like_count == 128
    assert posts[0].quote_count == 3


def test_forecast_cli_bluesky_import_captures_posts_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_bluesky_posts(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
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
                like_count=128,
                quote_count=3,
                url="https://bsky.app/profile/analyst.bsky.social/post/3kforecast",
                source_name="Bluesky @analyst.bsky.social",
                entry_id="at://did:plc:abc/app.bsky.feed.post/3kforecast",
                raw={"uri": "at://did:plc:abc/app.bsky.feed.post/3kforecast"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_bluesky_posts", fake_load_bluesky_posts)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Bluesky evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Bluesky evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "bluesky",
            "forecast desk",
            "--question",
            question_id,
            "--limit",
            "3",
            "--since",
            "2026-05-01T00:00:00Z",
            "--sort",
            "top",
            "--author",
            "analyst.bsky.social",
            "--lang",
            "en",
            "--link-domain",
            "example.test",
            "--url-filter",
            "https://example.test/forecast-desk",
            "--api-base-url",
            "https://bsky.test/xrpc/app.bsky.feed.searchPosts",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.66",
            "--relevance",
            "0.74",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 bluesky evidence item(s)" in output
    assert captured["source"] == "forecast desk"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-05-01T00:00:00Z"
    assert captured["kwargs"]["sort"] == "top"
    assert captured["kwargs"]["author"] == "analyst.bsky.social"
    assert captured["kwargs"]["lang"] == "en"
    assert captured["kwargs"]["link_domain"] == "example.test"
    assert captured["kwargs"]["url_filter"] == "https://example.test/forecast-desk"
    assert captured["kwargs"]["api_base_url"] == "https://bsky.test/xrpc/app.bsky.feed.searchPosts"
    assert evidence[0].claim == "Bluesky: Forecast Desk launches public beta"
    assert evidence[0].summary.startswith("Bluesky post by @analyst.bsky.social")
    assert evidence[0].source_name == "Bluesky @analyst.bsky.social"
    assert evidence[0].source_type == "adapter:bluesky"
    assert evidence[0].published_at == "2026-05-21T14:30:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.66
    assert evidence[0].relevance_rating == 0.74
    assert evidence[0].metadata["adapter"] == "bluesky"
    assert evidence[0].metadata["post_uri"] == "at://did:plc:abc/app.bsky.feed.post/3kforecast"
    assert evidence[0].metadata["author_handle"] == "analyst.bsky.social"
    assert evidence[0].metadata["like_count"] == 128


def test_mastodon_adapter_loads_hashtag_timeline(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return [
            {
                "id": "110123",
                "uri": "https://mastodon.social/users/analyst/statuses/110123",
                "url": "https://mastodon.social/@analyst/110123",
                "content": "<p>Forecast Desk launches public beta &amp; opens signups.</p>",
                "created_at": "2026-05-21T14:30:00.000Z",
                "replies_count": 4,
                "reblogs_count": 12,
                "favourites_count": 128,
                "language": "en",
                "visibility": "public",
                "account": {
                    "acct": "analyst",
                    "username": "analyst",
                    "display_name": "Analyst",
                    "url": "https://mastodon.social/@analyst",
                },
                "tags": [{"name": "forecasting"}, {"name": "prediction"}],
                "card": {
                    "url": "https://example.test/forecast-desk",
                    "title": "Forecast Desk",
                },
            }
        ]

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    statuses = source_adapters.load_mastodon_statuses(
        "mastodon.social/forecasting",
        limit=2,
        since="2026-05-01T00:00:00Z",
        local=True,
        only_media=True,
        api_base_url="https://mastodon.social/api/v1/timelines/tag",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "mastodon hashtag timeline"
    assert parsed.netloc == "mastodon.social"
    assert parsed.path == "/api/v1/timelines/tag/forecasting"
    assert params["limit"] == ["2"]
    assert params["local"] == ["true"]
    assert params["only_media"] == ["true"]
    assert statuses[0].status_id == "110123"
    assert statuses[0].url == "https://mastodon.social/@analyst/110123"
    assert statuses[0].content_text == "Forecast Desk launches public beta & opens signups."
    assert statuses[0].account_acct == "analyst"
    assert statuses[0].created_at == "2026-05-21T14:30:00Z"
    assert statuses[0].replies_count == 4
    assert statuses[0].reblogs_count == 12
    assert statuses[0].favourites_count == 128
    assert statuses[0].tags == ["forecasting", "prediction"]
    assert statuses[0].card_url == "https://example.test/forecast-desk"


def test_forecast_cli_mastodon_import_captures_statuses_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_mastodon_statuses(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            MastodonStatus(
                status_id="110123",
                uri="https://mastodon.social/users/analyst/statuses/110123",
                url="https://mastodon.social/@analyst/110123",
                content_text="Forecast Desk launches public beta.",
                account_acct="analyst",
                account_username="analyst",
                account_display_name="Analyst",
                account_url="https://mastodon.social/@analyst",
                created_at="2026-05-21T14:30:00Z",
                replies_count=4,
                reblogs_count=12,
                favourites_count=128,
                language="en",
                visibility="public",
                tags=["forecasting", "prediction"],
                card_url="https://example.test/forecast-desk",
                card_title="Forecast Desk",
                source_name="Mastodon @analyst",
                entry_id="110123",
                raw={"id": "110123"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_mastodon_statuses", fake_load_mastodon_statuses)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Mastodon evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Mastodon evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "mastodon",
            "mastodon.social/forecasting",
            "--question",
            question_id,
            "--limit",
            "3",
            "--since",
            "2026-05-01T00:00:00Z",
            "--local",
            "--only-media",
            "--api-base-url",
            "https://mastodon.social/api/v1/timelines/tag",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.64",
            "--relevance",
            "0.73",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 mastodon evidence item(s)" in output
    assert captured["source"] == "mastodon.social/forecasting"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-05-01T00:00:00Z"
    assert captured["kwargs"]["local"] is True
    assert captured["kwargs"]["only_media"] is True
    assert captured["kwargs"]["api_base_url"] == "https://mastodon.social/api/v1/timelines/tag"
    assert evidence[0].claim == "Mastodon: Forecast Desk launches public beta."
    assert evidence[0].summary.startswith("Mastodon status by @analyst")
    assert evidence[0].source_name == "Mastodon @analyst"
    assert evidence[0].source_type == "adapter:mastodon"
    assert evidence[0].published_at == "2026-05-21T14:30:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.64
    assert evidence[0].relevance_rating == 0.73
    assert evidence[0].metadata["adapter"] == "mastodon"
    assert evidence[0].metadata["status_id"] == "110123"
    assert evidence[0].metadata["favourites_count"] == 128


def test_reliefweb_adapter_loads_reports(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "data": [
                {
                    "id": "rw_123",
                    "href": "https://api.reliefweb.int/v1/reports/rw_123",
                    "fields": {
                        "title": "Flood response update",
                        "body-html": "<p>Humanitarian partners reported new flooding impacts.</p>",
                        "date": {
                            "created": "2026-05-21T14:30:00+00:00",
                            "changed": "2026-05-22T09:00:00+00:00",
                        },
                        "source": [{"name": "OCHA"}],
                        "country": [{"name": "Kenya"}],
                        "disaster": [{"name": "Floods"}],
                        "format": [{"name": "Situation Report"}],
                        "theme": [{"name": "Shelter and Non-Food Items"}],
                        "url": "https://reliefweb.int/report/kenya/flood-response-update",
                    },
                }
            ]
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    reports = source_adapters.load_reliefweb_reports(
        "Kenya floods",
        limit=2,
        since="2026-05-01T00:00:00Z",
        appname="forecast-test",
        api_base_url="https://api.reliefweb.test/v1/reports",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "reliefweb reports"
    assert parsed.path == "/v1/reports"
    assert params["appname"] == ["forecast-test"]
    assert params["query[value]"] == ["Kenya floods"]
    assert params["limit"] == ["2"]
    assert params["sort[]"] == ["date.created:desc"]
    assert params["filter[field]"] == ["date.created"]
    assert params["filter[value][from]"] == ["2026-05-01"]
    assert "title" in params["fields[include][]"]
    assert reports[0].report_id == "rw_123"
    assert reports[0].title == "Flood response update"
    assert reports[0].summary == "Humanitarian partners reported new flooding impacts."
    assert reports[0].published_at == "2026-05-21T14:30:00Z"
    assert reports[0].changed_at == "2026-05-22T09:00:00Z"
    assert reports[0].sources == ["OCHA"]
    assert reports[0].countries == ["Kenya"]
    assert reports[0].disasters == ["Floods"]
    assert reports[0].formats == ["Situation Report"]
    assert reports[0].themes == ["Shelter and Non-Food Items"]


def test_forecast_cli_reliefweb_import_captures_reports_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_reliefweb_reports(query: str, **kwargs):
        captured["query"] = query
        captured["kwargs"] = kwargs
        return [
            ReliefWebReport(
                report_id="rw_123",
                title="Flood response update",
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
                raw={"id": "rw_123"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_reliefweb_reports", fake_load_reliefweb_reports)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will ReliefWeb evidence import work?",
            "--resolution-criteria",
            "Resolved yes if ReliefWeb evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "reliefweb",
            "Kenya floods",
            "--question",
            question_id,
            "--limit",
            "3",
            "--since",
            "2026-05-01T00:00:00Z",
            "--api-base-url",
            "https://api.reliefweb.test/v1/reports",
            "--appname",
            "forecast-test",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.74",
            "--relevance",
            "0.82",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 reliefweb evidence item(s)" in output
    assert captured["query"] == "Kenya floods"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-05-01T00:00:00Z"
    assert captured["kwargs"]["api_base_url"] == "https://api.reliefweb.test/v1/reports"
    assert captured["kwargs"]["appname"] == "forecast-test"
    assert evidence[0].claim == "ReliefWeb: Flood response update"
    assert evidence[0].summary.startswith("Humanitarian partners reported new flooding impacts.")
    assert evidence[0].source_name == "OCHA"
    assert evidence[0].source_type == "adapter:reliefweb"
    assert evidence[0].published_at == "2026-05-21T14:30:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.74
    assert evidence[0].relevance_rating == 0.82
    assert evidence[0].metadata["adapter"] == "reliefweb"
    assert evidence[0].metadata["report_id"] == "rw_123"
    assert evidence[0].metadata["countries"] == ["Kenya"]
    assert evidence[0].metadata["disasters"] == ["Floods"]


def test_federalregister_adapter_loads_documents(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "results": [
                {
                    "document_number": "2026-11223",
                    "title": "Forecast Desk Policy Rule",
                    "abstract": " A final rule affecting monitored policy forecasts. ",
                    "html_url": "https://www.federalregister.gov/documents/2026/05/21/2026-11223/rule",
                    "pdf_url": "https://www.govinfo.gov/content/pkg/FR-2026-05-21/pdf/2026-11223.pdf",
                    "publication_date": "2026-05-21",
                    "type": "Rule",
                    "agencies": [{"name": "Department of Forecasting"}],
                    "citation": "91 FR 12345",
                }
            ]
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    documents = source_adapters.load_federal_register_documents(
        "forecast desk",
        limit=2,
        since="2026-05-01T00:00:00Z",
        api_base_url="https://federalregister.test/api/v1/documents.json",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "federal register documents"
    assert parsed.path == "/api/v1/documents.json"
    assert params["conditions[term]"] == ["forecast desk"]
    assert params["conditions[publication_date][gte]"] == ["2026-05-01"]
    assert params["per_page"] == ["2"]
    assert documents[0].document_number == "2026-11223"
    assert documents[0].title == "Forecast Desk Policy Rule"
    assert documents[0].abstract == "A final rule affecting monitored policy forecasts."
    assert documents[0].published_at == "2026-05-21T00:00:00Z"
    assert documents[0].agencies == ["Department of Forecasting"]


def test_forecast_cli_federalregister_import_captures_documents_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_federal_register_documents(query: str, **kwargs):
        captured["query"] = query
        captured["kwargs"] = kwargs
        return [
            FederalRegisterDocument(
                document_number="2026-11223",
                title="Forecast Desk Policy Rule",
                abstract="A final rule affecting monitored policy forecasts.",
                url="https://www.federalregister.gov/documents/2026/05/21/2026-11223/rule",
                pdf_url="https://www.govinfo.gov/content/pkg/FR-2026-05-21/pdf/2026-11223.pdf",
                published_at="2026-05-21T00:00:00Z",
                document_type="Rule",
                agencies=["Department of Forecasting"],
                citation="91 FR 12345",
                source_name="Federal Register",
                entry_id="2026-11223",
                raw={"document_number": "2026-11223"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_federal_register_documents", fake_load_federal_register_documents)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Federal Register evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Federal Register evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "federalregister",
            "forecast desk",
            "--question",
            question_id,
            "--limit",
            "3",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 federalregister evidence item(s)" in output
    assert captured["query"] == "forecast desk"
    assert captured["kwargs"]["limit"] == 3
    assert evidence[0].claim == "Federal Register: Forecast Desk Policy Rule"
    assert evidence[0].summary == "A final rule affecting monitored policy forecasts."
    assert evidence[0].source_name == "Federal Register"
    assert evidence[0].source_type == "adapter:federalregister"
    assert evidence[0].published_at == "2026-05-21T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "federalregister"
    assert evidence[0].metadata["document_number"] == "2026-11223"
    assert evidence[0].metadata["document_type"] == "Rule"
    assert evidence[0].metadata["agencies"] == ["Department of Forecasting"]


def test_courtlistener_adapter_loads_search_results(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "results": [
                {
                    "id": 123,
                    "caseName": "Forecast Desk v. Benchmark",
                    "snippet": " A legal result affecting benchmark questions. ",
                    "absolute_url": "/opinion/123/forecast-desk-v-benchmark/",
                    "court": "Supreme Court of Forecasting",
                    "court_id": "scotus",
                    "docketNumber": "24-123",
                    "dateFiled": "2026-05-21",
                    "status": "Published",
                    "citation": [{"cite": "123 F.4th 456"}],
                    "judge": "Forecaster, J.",
                    "citeCount": 17,
                }
            ]
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    results = source_adapters.load_courtlistener_search_results(
        "forecast desk",
        limit=2,
        since="2026-05-01T00:00:00Z",
        search_type="o",
        api_base_url="https://courtlistener.test/api/rest/v4/search/",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "courtlistener search"
    assert parsed.path == "/api/rest/v4/search/"
    assert params["q"] == ["forecast desk"]
    assert params["type"] == ["o"]
    assert params["page_size"] == ["2"]
    assert results[0].result_id == "123"
    assert results[0].title == "Forecast Desk v. Benchmark"
    assert results[0].snippet == "A legal result affecting benchmark questions."
    assert results[0].url == "https://www.courtlistener.com/opinion/123/forecast-desk-v-benchmark/"
    assert results[0].date_filed == "2026-05-21T00:00:00Z"
    assert results[0].citation == "123 F.4th 456"
    assert results[0].cite_count == 17


def test_forecast_cli_courtlistener_import_captures_results_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_courtlistener_search_results(query: str, **kwargs):
        captured["query"] = query
        captured["kwargs"] = kwargs
        return [
            CourtListenerSearchResult(
                result_id="123",
                title="Forecast Desk v. Benchmark",
                snippet="A legal result affecting benchmark questions.",
                url="https://www.courtlistener.com/opinion/123/forecast-desk-v-benchmark/",
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
                entry_id="123",
                raw={"id": 123},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_courtlistener_search_results", fake_load_courtlistener_search_results)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will CourtListener evidence import work?",
            "--resolution-criteria",
            "Resolved yes if CourtListener evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "courtlistener",
            "forecast desk",
            "--question",
            question_id,
            "--limit",
            "3",
            "--search-type",
            "o",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 courtlistener evidence item(s)" in output
    assert captured["query"] == "forecast desk"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["search_type"] == "o"
    assert evidence[0].claim == "CourtListener: Forecast Desk v. Benchmark"
    assert evidence[0].summary.startswith("CourtListener result (scotus) filed 2026-05-21T00:00:00Z.")
    assert evidence[0].source_name == "CourtListener scotus"
    assert evidence[0].source_type == "adapter:courtlistener"
    assert evidence[0].published_at == "2026-05-21T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "courtlistener"
    assert evidence[0].metadata["result_id"] == "123"
    assert evidence[0].metadata["court_id"] == "scotus"
    assert evidence[0].metadata["citation"] == "123 F.4th 456"


def test_nvd_adapter_loads_cves(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "vulnerabilities": [
                {
                    "cve": {
                        "id": "CVE-2026-12345",
                        "sourceIdentifier": "security@example.test",
                        "published": "2026-05-20T10:00:00.000Z",
                        "lastModified": "2026-05-21T11:00:00.000Z",
                        "vulnStatus": "Analyzed",
                        "descriptions": [
                            {"lang": "en", "value": " A forecast-relevant vulnerability. "}
                        ],
                        "metrics": {
                            "cvssMetricV31": [
                                {
                                    "cvssData": {
                                        "version": "3.1",
                                        "baseScore": 9.8,
                                        "baseSeverity": "CRITICAL",
                                    }
                                }
                            ]
                        },
                        "references": {
                            "referenceData": [
                                {"url": "https://vendor.example.test/advisory"}
                            ]
                        },
                    }
                }
            ]
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    cves = source_adapters.load_nvd_cves(
        "forecast product",
        limit=2,
        since="2026-05-01T00:00:00Z",
        api_base_url="https://nvd.test/rest/json/cves/2.0",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "nvd cves"
    assert parsed.path == "/rest/json/cves/2.0"
    assert params["keywordSearch"] == ["forecast product"]
    assert params["resultsPerPage"] == ["2"]
    assert cves[0].cve_id == "CVE-2026-12345"
    assert cves[0].description == "A forecast-relevant vulnerability."
    assert cves[0].published_at == "2026-05-20T10:00:00Z"
    assert cves[0].last_modified_at == "2026-05-21T11:00:00Z"
    assert cves[0].severity == "CRITICAL"
    assert cves[0].base_score == 9.8
    assert cves[0].references == ["https://vendor.example.test/advisory"]

    source_adapters.load_nvd_cves(
        "CVE-2026-12345",
        limit=1,
        api_base_url="https://nvd.test/rest/json/cves/2.0",
    )
    id_params = parse_qs(urlparse(captured["endpoint"]).query)
    assert id_params["cveIds"] == ["CVE-2026-12345"]


def test_forecast_cli_nvd_import_captures_cves_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_nvd_cves(query: str, **kwargs):
        captured["query"] = query
        captured["kwargs"] = kwargs
        return [
            NvdCve(
                cve_id="CVE-2026-12345",
                description="A forecast-relevant vulnerability.",
                url="https://nvd.nist.gov/vuln/detail/CVE-2026-12345",
                published_at="2026-05-20T10:00:00Z",
                last_modified_at="2026-05-21T11:00:00Z",
                vuln_status="Analyzed",
                severity="CRITICAL",
                base_score=9.8,
                cvss_version="3.1",
                references=["https://vendor.example.test/advisory"],
                source_identifier="security@example.test",
                source_name="NVD",
                entry_id="CVE-2026-12345",
                raw={"id": "CVE-2026-12345"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_nvd_cves", fake_load_nvd_cves)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will NVD evidence import work?",
            "--resolution-criteria",
            "Resolved yes if NVD evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "nvd",
            "forecast product",
            "--question",
            question_id,
            "--limit",
            "3",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 nvd evidence item(s)" in output
    assert captured["query"] == "forecast product"
    assert captured["kwargs"]["limit"] == 3
    assert evidence[0].claim == "NVD CVE: CVE-2026-12345 CRITICAL CVSS 9.8"
    assert evidence[0].summary == "A forecast-relevant vulnerability."
    assert evidence[0].source_name == "NVD"
    assert evidence[0].source_type == "adapter:nvd"
    assert evidence[0].published_at == "2026-05-20T10:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "nvd"
    assert evidence[0].metadata["cve_id"] == "CVE-2026-12345"
    assert evidence[0].metadata["severity"] == "CRITICAL"
    assert evidence[0].metadata["base_score"] == 9.8
    assert evidence[0].metadata["references"] == ["https://vendor.example.test/advisory"]


def test_cisa_kev_adapter_loads_known_exploited_vulnerabilities(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "vulnerabilities": [
                {
                    "cveID": "CVE-2026-23456",
                    "vendorProject": "ForecastSoft",
                    "product": "Forecast Server",
                    "vulnerabilityName": "ForecastSoft Forecast Server Command Injection",
                    "dateAdded": "2026-05-20",
                    "shortDescription": "A known exploited command injection vulnerability.",
                    "requiredAction": "Apply vendor mitigations.",
                    "dueDate": "2026-06-10",
                    "knownRansomwareCampaignUse": "Known",
                    "notes": "Observed exploitation in the wild.",
                    "cwes": ["CWE-77"],
                },
                {
                    "cveID": "CVE-2026-99999",
                    "vendorProject": "Other",
                    "product": "Other Product",
                    "vulnerabilityName": "Other vulnerability",
                    "dateAdded": "2026-05-21",
                },
            ]
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    vulnerabilities = source_adapters.load_cisa_kev_vulnerabilities(
        "ForecastSoft",
        limit=2,
        since="2026-05-01T00:00:00Z",
        api_base_url="https://cisa.test/kev.json",
    )

    assert captured["endpoint"] == "https://cisa.test/kev.json"
    assert captured["label"] == "cisa kev catalog"
    assert len(vulnerabilities) == 1
    assert vulnerabilities[0].cve_id == "CVE-2026-23456"
    assert vulnerabilities[0].vendor_project == "ForecastSoft"
    assert vulnerabilities[0].product == "Forecast Server"
    assert vulnerabilities[0].date_added == "2026-05-20T00:00:00Z"
    assert vulnerabilities[0].due_date == "2026-06-10T00:00:00Z"
    assert vulnerabilities[0].ransomware_use == "Known"
    assert vulnerabilities[0].cwes == ["CWE-77"]


def test_forecast_cli_cisa_kev_import_captures_vulnerabilities_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_cisa_kev_vulnerabilities(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            CisaKevVulnerability(
                cve_id="CVE-2026-23456",
                vendor_project="ForecastSoft",
                product="Forecast Server",
                vulnerability_name="ForecastSoft Forecast Server Command Injection",
                short_description="A known exploited command injection vulnerability.",
                date_added="2026-05-20T00:00:00Z",
                due_date="2026-06-10T00:00:00Z",
                required_action="Apply vendor mitigations.",
                ransomware_use="Known",
                notes="Observed exploitation in the wild.",
                cwes=["CWE-77"],
                source_url="https://cisa.test/kev.json",
                source_name="CISA Known Exploited Vulnerabilities",
                entry_id="CVE-2026-23456",
                raw={"cveID": "CVE-2026-23456"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_cisa_kev_vulnerabilities", fake_load_cisa_kev_vulnerabilities)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will CISA KEV evidence import work?",
            "--resolution-criteria",
            "Resolved yes if CISA KEV evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "cisakev",
            "ForecastSoft",
            "--question",
            question_id,
            "--limit",
            "3",
            "--since",
            "2026-05-01T00:00:00Z",
            "--api-base-url",
            "https://cisa.test/kev.json",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.84",
            "--relevance",
            "0.91",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 cisakev evidence item(s)" in output
    assert captured["source"] == "ForecastSoft"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-05-01T00:00:00Z"
    assert captured["kwargs"]["api_base_url"] == "https://cisa.test/kev.json"
    assert evidence[0].claim == "CISA KEV: CVE-2026-23456 ForecastSoft Forecast Server"
    assert evidence[0].summary.startswith("A known exploited command injection vulnerability.")
    assert evidence[0].source_name == "CISA Known Exploited Vulnerabilities"
    assert evidence[0].source_type == "adapter:cisakev"
    assert evidence[0].published_at == "2026-05-20T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.84
    assert evidence[0].relevance_rating == 0.91
    assert evidence[0].metadata["adapter"] == "cisakev"
    assert evidence[0].metadata["cve_id"] == "CVE-2026-23456"
    assert evidence[0].metadata["vendor_project"] == "ForecastSoft"
    assert evidence[0].metadata["ransomware_use"] == "Known"
    assert evidence[0].metadata["cwes"] == ["CWE-77"]


def test_openmeteo_adapter_loads_daily_forecasts(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "latitude": 37.77,
            "longitude": -122.42,
            "daily_units": {"temperature_2m_max": "C", "precipitation_sum": "mm"},
            "daily": {
                "time": ["2026-05-21", "2026-05-22"],
                "temperature_2m_max": [21.5, 22.0],
                "temperature_2m_min": [12.1, 13.2],
                "precipitation_sum": [0.0, 2.5],
                "wind_speed_10m_max": [18.0, 20.5],
            },
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    forecasts = source_adapters.load_openmeteo_daily_forecasts(
        "37.77,-122.42",
        limit=2,
        since="2026-05-01T00:00:00Z",
        forecast_days=5,
        api_base_url="https://openmeteo.test/v1/forecast",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "openmeteo forecast"
    assert parsed.path == "/v1/forecast"
    assert params["latitude"] == ["37.77"]
    assert params["longitude"] == ["-122.42"]
    assert params["forecast_days"] == ["5"]
    assert "temperature_2m_max" in params["daily"][0]
    assert forecasts[0].latitude == 37.77
    assert forecasts[0].longitude == -122.42
    assert forecasts[0].forecast_date == "2026-05-21"
    assert forecasts[0].temperature_2m_max == 21.5
    assert forecasts[0].precipitation_sum == 0.0


def test_forecast_cli_openmeteo_import_captures_forecasts_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_openmeteo_daily_forecasts(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            OpenMeteoDailyForecast(
                latitude=37.77,
                longitude=-122.42,
                forecast_date="2026-05-21",
                temperature_2m_max=21.5,
                temperature_2m_min=12.1,
                precipitation_sum=0.0,
                wind_speed_10m_max=18.0,
                source_name="Open-Meteo",
                entry_id="37.77,-122.42:2026-05-21",
                raw={"daily_units": {"temperature_2m_max": "C"}},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_openmeteo_daily_forecasts", fake_load_openmeteo_daily_forecasts)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Open-Meteo evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Open-Meteo evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "openmeteo",
            "37.77,-122.42",
            "--question",
            question_id,
            "--limit",
            "3",
            "--forecast-days",
            "5",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 openmeteo evidence item(s)" in output
    assert captured["source"] == "37.77,-122.42"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["forecast_days"] == 5
    assert evidence[0].claim == "Open-Meteo daily forecast 2026-05-21: max 21.5, precip 0.0"
    assert evidence[0].summary.startswith("Open-Meteo daily forecast for 37.77,-122.42")
    assert evidence[0].source_name == "Open-Meteo"
    assert evidence[0].source_type == "adapter:openmeteo"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "openmeteo"
    assert evidence[0].metadata["forecast_date"] == "2026-05-21"
    assert evidence[0].metadata["temperature_2m_max"] == 21.5
    assert evidence[0].metadata["precipitation_sum"] == 0.0


def test_airquality_adapter_loads_hourly_forecasts(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "latitude": 37.77,
            "longitude": -122.42,
            "hourly_units": {"us_aqi": "US AQI", "pm2_5": "ug/m3"},
            "hourly": {
                "time": ["2026-05-21T00:00", "2026-05-21T01:00"],
                "us_aqi": [42, 48],
                "european_aqi": [31, 35],
                "pm10": [12.0, 13.5],
                "pm2_5": [8.4, 9.1],
                "carbon_monoxide": [220.0, 230.0],
                "nitrogen_dioxide": [16.0, 18.0],
                "ozone": [80.0, 82.0],
            },
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    forecasts = source_adapters.load_openmeteo_air_quality_forecasts(
        "37.77,-122.42",
        limit=2,
        since="2026-05-21T00:00:00Z",
        forecast_days=3,
        api_base_url="https://airquality.test/v1/air-quality",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "openmeteo air quality"
    assert parsed.path == "/v1/air-quality"
    assert params["latitude"] == ["37.77"]
    assert params["longitude"] == ["-122.42"]
    assert params["forecast_days"] == ["3"]
    assert "us_aqi" in params["hourly"][0]
    assert "pm2_5" in params["hourly"][0]
    assert forecasts[0].latitude == 37.77
    assert forecasts[0].longitude == -122.42
    assert forecasts[0].forecast_time == "2026-05-21T00:00:00Z"
    assert forecasts[0].us_aqi == 42
    assert forecasts[0].pm2_5 == 8.4
    assert forecasts[0].source_name == "Open-Meteo Air Quality"


def test_forecast_cli_airquality_import_captures_forecasts_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_openmeteo_air_quality_forecasts(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            OpenMeteoAirQualityForecast(
                latitude=37.77,
                longitude=-122.42,
                forecast_time="2026-05-21T00:00:00Z",
                us_aqi=42,
                european_aqi=31,
                pm10=12.0,
                pm2_5=8.4,
                carbon_monoxide=220.0,
                nitrogen_dioxide=16.0,
                ozone=80.0,
                source_name="Open-Meteo Air Quality",
                entry_id="37.77,-122.42:2026-05-21T00:00:00Z",
                raw={"hourly_units": {"us_aqi": "US AQI"}},
            )
        ]

    monkeypatch.setattr(
        "forecasting.cli.load_openmeteo_air_quality_forecasts",
        fake_load_openmeteo_air_quality_forecasts,
    )
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Open-Meteo air-quality evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Open-Meteo air-quality evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "airquality",
            "37.77,-122.42",
            "--question",
            question_id,
            "--limit",
            "12",
            "--forecast-days",
            "3",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.82",
            "--relevance",
            "0.93",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 airquality evidence item(s)" in output
    assert captured["source"] == "37.77,-122.42"
    assert captured["kwargs"]["limit"] == 12
    assert captured["kwargs"]["forecast_days"] == 3
    assert evidence[0].claim == "Open-Meteo air quality forecast 2026-05-21T00:00:00Z: US AQI 42, PM2.5 8.4"
    assert evidence[0].summary.startswith("Open-Meteo air quality forecast for 37.77,-122.42")
    assert evidence[0].source_name == "Open-Meteo Air Quality"
    assert evidence[0].source_type == "adapter:airquality"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.82
    assert evidence[0].relevance_rating == 0.93
    assert evidence[0].metadata["adapter"] == "airquality"
    assert evidence[0].metadata["forecast_time"] == "2026-05-21T00:00:00Z"
    assert evidence[0].metadata["us_aqi"] == 42
    assert evidence[0].metadata["pm2_5"] == 8.4


def test_weatherhistory_adapter_loads_daily_observations(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "latitude": 37.77,
            "longitude": -122.42,
            "daily_units": {"temperature_2m_mean": "C", "precipitation_sum": "mm"},
            "daily": {
                "time": ["2026-05-20", "2026-05-21"],
                "temperature_2m_mean": [16.2, 17.4],
                "temperature_2m_max": [21.5, 22.0],
                "temperature_2m_min": [12.1, 13.2],
                "precipitation_sum": [0.0, 2.5],
                "wind_speed_10m_max": [18.0, 20.5],
            },
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    observations = source_adapters.load_openmeteo_historical_weather(
        "weatherhistory:37.77,-122.42?start=2026-05-20&end=2026-05-21",
        limit=2,
        since="2026-05-20T00:00:00Z",
        api_base_url="https://history.test/v1/archive",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "openmeteo historical weather"
    assert parsed.path == "/v1/archive"
    assert params["latitude"] == ["37.77"]
    assert params["longitude"] == ["-122.42"]
    assert params["start_date"] == ["2026-05-20"]
    assert params["end_date"] == ["2026-05-21"]
    assert "temperature_2m_mean" in params["daily"][0]
    assert observations[0].observation_date == "2026-05-20"
    assert observations[0].temperature_2m_mean == 16.2
    assert observations[0].precipitation_sum == 0.0
    assert observations[0].source_name == "Open-Meteo Historical Weather"


def test_forecast_cli_weatherhistory_import_captures_observations_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_openmeteo_historical_weather(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            OpenMeteoHistoricalWeatherObservation(
                latitude=37.77,
                longitude=-122.42,
                observation_date="2026-05-20",
                temperature_2m_mean=16.2,
                temperature_2m_max=21.5,
                temperature_2m_min=12.1,
                precipitation_sum=0.0,
                wind_speed_10m_max=18.0,
                source_name="Open-Meteo Historical Weather",
                entry_id="37.77,-122.42:2026-05-20",
                raw={"daily_units": {"temperature_2m_mean": "C"}},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_openmeteo_historical_weather", fake_load_openmeteo_historical_weather)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Open-Meteo historical weather evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Open-Meteo historical weather evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "weatherhistory",
            "37.77,-122.42",
            "--question",
            question_id,
            "--start-date",
            "2026-05-20",
            "--end-date",
            "2026-05-21",
            "--limit",
            "3",
            "--claim-type",
            "fact",
            "--reliability",
            "0.86",
            "--relevance",
            "0.91",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 weatherhistory evidence item(s)" in output
    assert captured["source"] == "37.77,-122.42"
    assert captured["kwargs"]["start_date"] == "2026-05-20"
    assert captured["kwargs"]["end_date"] == "2026-05-21"
    assert evidence[0].claim == "Open-Meteo historical weather 2026-05-20: mean 16.2, precip 0.0"
    assert evidence[0].summary.startswith("Open-Meteo historical weather for 37.77,-122.42")
    assert evidence[0].source_name == "Open-Meteo Historical Weather"
    assert evidence[0].source_type == "adapter:weatherhistory"
    assert evidence[0].claim_type == "fact"
    assert evidence[0].reliability_rating == 0.86
    assert evidence[0].relevance_rating == 0.91
    assert evidence[0].metadata["adapter"] == "weatherhistory"
    assert evidence[0].metadata["observation_date"] == "2026-05-20"
    assert evidence[0].metadata["temperature_2m_mean"] == 16.2


def test_usgs_adapter_loads_earthquake_events(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "us7000abcd",
                    "properties": {
                        "title": "M 5.7 - 10 km S of Testville",
                        "mag": 5.7,
                        "place": "10 km S of Testville",
                        "time": 1779235200000,
                        "updated": 1779238800000,
                        "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000abcd",
                        "type": "earthquake",
                        "status": "reviewed",
                        "tsunami": 0,
                        "sig": 500,
                    },
                    "geometry": {"type": "Point", "coordinates": [-122.4, 37.7, 8.5]},
                }
            ],
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    events = source_adapters.load_usgs_earthquakes(
        "minmagnitude=5",
        limit=1,
        since="2026-05-20",
        api_base_url="https://usgs.test/fdsnws/event/1/query",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "usgs earthquakes"
    assert parsed.path == "/fdsnws/event/1/query"
    assert params["format"] == ["geojson"]
    assert params["orderby"] == ["time"]
    assert params["limit"] == ["1"]
    assert params["minmagnitude"] == ["5"]
    assert params["starttime"] == ["2026-05-20"]
    assert events[0].event_id == "us7000abcd"
    assert events[0].title == "M 5.7 - 10 km S of Testville"
    assert events[0].time == "2026-05-20T00:00:00Z"
    assert events[0].updated_at == "2026-05-20T01:00:00Z"
    assert events[0].magnitude == 5.7
    assert events[0].place == "10 km S of Testville"
    assert events[0].event_type == "earthquake"
    assert events[0].status == "reviewed"
    assert events[0].tsunami == 0
    assert events[0].significance == 500
    assert events[0].longitude == -122.4
    assert events[0].latitude == 37.7
    assert events[0].depth_km == 8.5


def test_forecast_cli_usgs_import_captures_events_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_usgs_earthquakes(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            UsgsEarthquakeEvent(
                event_id="us7000abcd",
                title="M 5.7 - 10 km S of Testville",
                url="https://earthquake.usgs.gov/earthquakes/eventpage/us7000abcd",
                time="2026-05-20T00:00:00Z",
                updated_at="2026-05-20T01:00:00Z",
                magnitude=5.7,
                place="10 km S of Testville",
                event_type="earthquake",
                status="reviewed",
                tsunami=0,
                significance=500,
                longitude=-122.4,
                latitude=37.7,
                depth_km=8.5,
                source_name="USGS Earthquake Catalog",
                entry_id="us7000abcd",
                raw={"id": "us7000abcd"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_usgs_earthquakes", fake_load_usgs_earthquakes)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will USGS evidence import work?",
            "--resolution-criteria",
            "Resolved yes if USGS evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "usgs",
            "minmagnitude=5",
            "--question",
            question_id,
            "--limit",
            "3",
            "--since",
            "2026-05-19",
            "--api-base-url",
            "https://usgs.test/fdsnws/event/1/query",
            "--claim-type",
            "fact",
            "--reliability",
            "0.9",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 usgs evidence item(s)" in output
    assert captured["source"] == "minmagnitude=5"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-05-19"
    assert captured["kwargs"]["api_base_url"] == "https://usgs.test/fdsnws/event/1/query"
    assert evidence[0].claim == "USGS earthquake M5.7: 10 km S of Testville"
    assert evidence[0].summary.startswith("USGS earthquake M5.7 at 10 km S of Testville.")
    assert evidence[0].source_name == "USGS Earthquake Catalog"
    assert evidence[0].source_type == "adapter:usgs"
    assert evidence[0].published_at == "2026-05-20T00:00:00Z"
    assert evidence[0].claim_type == "fact"
    assert evidence[0].reliability_rating == 0.9
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["adapter"] == "usgs"
    assert evidence[0].metadata["event_id"] == "us7000abcd"
    assert evidence[0].metadata["magnitude"] == 5.7
    assert evidence[0].metadata["depth_km"] == 8.5


def test_eonet_adapter_loads_natural_events(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "events": [
                {
                    "id": "EONET_123",
                    "title": "Wildfire near Test Ridge",
                    "description": "A public hazard event.",
                    "link": "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_123",
                    "status": "open",
                    "closed": None,
                    "categories": [{"id": "wildfires", "title": "Wildfires"}],
                    "sources": [{"id": "NASA", "url": "https://example.test/source"}],
                    "geometry": [
                        {
                            "date": "2026-05-20T00:00:00Z",
                            "type": "Point",
                            "coordinates": [-121.2, 38.5],
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    events = source_adapters.load_nasa_eonet_events(
        "category=wildfires&status=open",
        limit=1,
        since="2026-05-19",
        api_base_url="https://eonet.test/api/v3/events",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "nasa eonet events"
    assert parsed.path == "/api/v3/events"
    assert params["category"] == ["wildfires"]
    assert params["status"] == ["open"]
    assert params["limit"] == ["1"]
    assert params["start"] == ["2026-05-19"]
    assert events[0].event_id == "EONET_123"
    assert events[0].title == "Wildfire near Test Ridge"
    assert events[0].description == "A public hazard event."
    assert events[0].status == "open"
    assert events[0].latest_geometry_at == "2026-05-20T00:00:00Z"
    assert events[0].categories == ["Wildfires"]
    assert events[0].source_names == ["NASA"]
    assert events[0].source_urls == ["https://example.test/source"]
    assert events[0].longitude == -121.2
    assert events[0].latitude == 38.5


def test_forecast_cli_eonet_import_captures_events_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_nasa_eonet_events(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            NasaEonetEvent(
                event_id="EONET_123",
                title="Wildfire near Test Ridge",
                description="A public hazard event.",
                url="https://eonet.gsfc.nasa.gov/api/v3/events/EONET_123",
                status="open",
                closed_at=None,
                latest_geometry_at="2026-05-20T00:00:00Z",
                categories=["Wildfires"],
                source_names=["NASA"],
                source_urls=["https://example.test/source"],
                longitude=-121.2,
                latitude=38.5,
                source_name="NASA EONET",
                entry_id="EONET_123",
                raw={"id": "EONET_123"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_nasa_eonet_events", fake_load_nasa_eonet_events)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will EONET evidence import work?",
            "--resolution-criteria",
            "Resolved yes if EONET evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "eonet",
            "category=wildfires&status=open",
            "--question",
            question_id,
            "--limit",
            "2",
            "--since",
            "2026-05-19",
            "--api-base-url",
            "https://eonet.test/api/v3/events",
            "--reliability",
            "0.85",
            "--relevance",
            "0.75",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 eonet evidence item(s)" in output
    assert captured["source"] == "category=wildfires&status=open"
    assert captured["kwargs"]["limit"] == 2
    assert captured["kwargs"]["since"] == "2026-05-19"
    assert evidence[0].claim == "NASA EONET Wildfires: Wildfire near Test Ridge"
    assert evidence[0].summary.startswith("NASA EONET event Wildfire near Test Ridge.")
    assert evidence[0].source_name == "NASA EONET"
    assert evidence[0].source_type == "adapter:eonet"
    assert evidence[0].published_at == "2026-05-20T00:00:00Z"
    assert evidence[0].reliability_rating == 0.85
    assert evidence[0].relevance_rating == 0.75
    assert evidence[0].metadata["adapter"] == "eonet"
    assert evidence[0].metadata["event_id"] == "EONET_123"
    assert evidence[0].metadata["categories"] == ["Wildfires"]
    assert evidence[0].metadata["latitude"] == 38.5


def test_nws_adapter_loads_weather_alerts(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "features": [
                {
                    "id": "https://api.weather.gov/alerts/urn:oid:alert-1",
                    "properties": {
                        "id": "urn:oid:alert-1",
                        "@id": "https://api.weather.gov/alerts/urn:oid:alert-1",
                        "areaDesc": "Test County",
                        "sent": "2026-05-20T12:00:00-00:00",
                        "effective": "2026-05-20T12:05:00-00:00",
                        "onset": "2026-05-20T12:10:00-00:00",
                        "expires": "2026-05-20T18:00:00-00:00",
                        "ends": "2026-05-20T17:30:00-00:00",
                        "status": "Actual",
                        "messageType": "Alert",
                        "category": "Met",
                        "severity": "Severe",
                        "certainty": "Likely",
                        "urgency": "Immediate",
                        "event": "Severe Thunderstorm Warning",
                        "senderName": "NWS Test Office",
                        "headline": "Severe Thunderstorm Warning issued for Test County",
                        "description": "Quarter-size hail is possible.",
                        "instruction": "Move indoors.",
                        "response": "Shelter",
                    },
                }
            ],
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    alerts = source_adapters.load_nws_alerts(
        "area=CA&event=Severe Thunderstorm Warning",
        limit=1,
        since="2026-05-20T00:00:00Z",
        api_base_url="https://nws.test/alerts/active",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "nws alerts"
    assert parsed.path == "/alerts/active"
    assert params["area"] == ["CA"]
    assert params["event"] == ["Severe Thunderstorm Warning"]
    assert alerts[0].alert_id == "urn:oid:alert-1"
    assert alerts[0].event == "Severe Thunderstorm Warning"
    assert alerts[0].headline == "Severe Thunderstorm Warning issued for Test County"
    assert alerts[0].area_desc == "Test County"
    assert alerts[0].severity == "Severe"
    assert alerts[0].sent_at == "2026-05-20T12:00:00Z"
    assert alerts[0].effective_at == "2026-05-20T12:05:00Z"
    assert alerts[0].source_name == "NWS Test Office"


def test_forecast_cli_nws_import_captures_alerts_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_nws_alerts(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            NwsAlert(
                alert_id="urn:oid:alert-1",
                event="Severe Thunderstorm Warning",
                headline="Severe Thunderstorm Warning issued for Test County",
                description="Quarter-size hail is possible.",
                instruction="Move indoors.",
                url="https://api.weather.gov/alerts/urn:oid:alert-1",
                area_desc="Test County",
                severity="Severe",
                certainty="Likely",
                urgency="Immediate",
                status="Actual",
                message_type="Alert",
                category="Met",
                response="Shelter",
                sent_at="2026-05-20T12:00:00Z",
                effective_at="2026-05-20T12:05:00Z",
                onset_at="2026-05-20T12:10:00Z",
                expires_at="2026-05-20T18:00:00Z",
                ends_at="2026-05-20T17:30:00Z",
                source_name="NWS Test Office",
                entry_id="urn:oid:alert-1",
                raw={"id": "urn:oid:alert-1"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_nws_alerts", fake_load_nws_alerts)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will NWS alert import work?",
            "--resolution-criteria",
            "Resolved yes if NWS evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "nws",
            "area=CA&event=Severe Thunderstorm Warning",
            "--question",
            question_id,
            "--limit",
            "2",
            "--since",
            "2026-05-20T00:00:00Z",
            "--api-base-url",
            "https://nws.test/alerts/active",
            "--reliability",
            "0.88",
            "--relevance",
            "0.81",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 nws evidence item(s)" in output
    assert captured["source"] == "area=CA&event=Severe Thunderstorm Warning"
    assert captured["kwargs"]["limit"] == 2
    assert captured["kwargs"]["since"] == "2026-05-20T00:00:00Z"
    assert captured["kwargs"]["api_base_url"] == "https://nws.test/alerts/active"
    assert evidence[0].claim == "NWS Severe Thunderstorm Warning: Severe Thunderstorm Warning issued for Test County"
    assert evidence[0].summary.startswith("NWS Severe Thunderstorm Warning for Test County.")
    assert evidence[0].source_name == "NWS Test Office"
    assert evidence[0].source_type == "adapter:nws"
    assert evidence[0].published_at == "2026-05-20T12:00:00Z"
    assert evidence[0].reliability_rating == 0.88
    assert evidence[0].relevance_rating == 0.81
    assert evidence[0].metadata["adapter"] == "nws"
    assert evidence[0].metadata["alert_id"] == "urn:oid:alert-1"
    assert evidence[0].metadata["severity"] == "Severe"
    assert evidence[0].metadata["expires_at"] == "2026-05-20T18:00:00Z"


def test_clinicaltrials_adapter_loads_study_rows(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {
                            "nctId": "NCT01234567",
                            "briefTitle": "Test oncology trial",
                            "officialTitle": "A test oncology trial",
                        },
                        "statusModule": {
                            "overallStatus": "RECRUITING",
                            "startDateStruct": {"date": "2026-01"},
                            "primaryCompletionDateStruct": {"date": "2027-06-30"},
                            "completionDateStruct": {"date": "2027-12-31"},
                            "lastUpdatePostDateStruct": {"date": "2026-05-21"},
                            "lastUpdateSubmitDate": "2026-05-20",
                        },
                        "designModule": {"studyType": "INTERVENTIONAL", "phases": ["PHASE2"]},
                        "conditionsModule": {"conditions": ["Lung Cancer"]},
                        "armsInterventionsModule": {
                            "interventions": [{"type": "DRUG", "name": "Drug A"}]
                        },
                        "sponsorCollaboratorsModule": {
                            "leadSponsor": {"name": "Acme Bio"},
                            "collaborators": [{"name": "Test Hospital"}],
                        },
                    },
                    "hasResults": False,
                }
            ]
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    studies = source_adapters.load_clinicaltrials_studies(
        "lung cancer phase 2",
        limit=1,
        since="2026-05-01T00:00:00Z",
        api_base_url="https://clinicaltrials.test/api/v2/studies",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "clinicaltrials studies"
    assert parsed.netloc == "clinicaltrials.test"
    assert params["query.term"] == ["lung cancer phase 2"]
    assert params["pageSize"] == ["1"]
    assert studies[0].nct_id == "NCT01234567"
    assert studies[0].brief_title == "Test oncology trial"
    assert studies[0].status == "RECRUITING"
    assert studies[0].phases == ["PHASE2"]
    assert studies[0].conditions == ["Lung Cancer"]
    assert studies[0].interventions == ["Drug A"]
    assert studies[0].sponsors == ["Acme Bio", "Test Hospital"]
    assert studies[0].start_date == "2026-01-01T00:00:00Z"
    assert studies[0].last_update_posted_at == "2026-05-21T00:00:00Z"


def test_forecast_cli_clinicaltrials_import_captures_studies_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_clinicaltrials_studies(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            ClinicalTrialStudy(
                nct_id="NCT01234567",
                brief_title="Test oncology trial",
                official_title="A test oncology trial",
                url="https://clinicaltrials.gov/study/NCT01234567",
                status="RECRUITING",
                phases=["PHASE2"],
                study_type="INTERVENTIONAL",
                conditions=["Lung Cancer"],
                interventions=["Drug A"],
                sponsors=["Acme Bio"],
                start_date="2026-01-01T00:00:00Z",
                primary_completion_date="2027-06-30T00:00:00Z",
                completion_date="2027-12-31T00:00:00Z",
                last_update_submitted_at="2026-05-20T00:00:00Z",
                last_update_posted_at="2026-05-21T00:00:00Z",
                has_results=False,
                source_name="ClinicalTrials.gov",
                entry_id="NCT01234567",
                raw={"nctId": "NCT01234567"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_clinicaltrials_studies", fake_load_clinicaltrials_studies)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will ClinicalTrials.gov import work?",
            "--resolution-criteria",
            "Resolved yes if clinical trial evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "clinicaltrials",
            "NCT01234567",
            "--question",
            question_id,
            "--limit",
            "2",
            "--since",
            "2026-05-01T00:00:00Z",
            "--api-base-url",
            "https://clinicaltrials.test/api/v2/studies",
            "--reliability",
            "0.9",
            "--relevance",
            "0.82",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 clinicaltrials evidence item(s)" in output
    assert captured["source"] == "NCT01234567"
    assert captured["kwargs"]["limit"] == 2
    assert captured["kwargs"]["since"] == "2026-05-01T00:00:00Z"
    assert captured["kwargs"]["api_base_url"] == "https://clinicaltrials.test/api/v2/studies"
    assert evidence[0].claim == "ClinicalTrials.gov NCT01234567: RECRUITING - Test oncology trial"
    assert evidence[0].summary.startswith("ClinicalTrials.gov study NCT01234567")
    assert evidence[0].source_name == "ClinicalTrials.gov"
    assert evidence[0].source_type == "adapter:clinicaltrials"
    assert evidence[0].published_at == "2026-05-21T00:00:00Z"
    assert evidence[0].reliability_rating == 0.9
    assert evidence[0].relevance_rating == 0.82
    assert evidence[0].metadata["adapter"] == "clinicaltrials"
    assert evidence[0].metadata["nct_id"] == "NCT01234567"
    assert evidence[0].metadata["phases"] == ["PHASE2"]
    assert evidence[0].metadata["primary_completion_date"] == "2027-06-30T00:00:00Z"


def test_openfda_adapter_loads_drug_application_rows(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "results": [
                {
                    "application_number": "BLA125514",
                    "sponsor_name": "ACME BIO",
                    "openfda": {
                        "brand_name": ["TESTMAB"],
                        "generic_name": ["testimab"],
                        "route": ["INTRAVENOUS"],
                        "substance_name": ["TESTIMAB"],
                    },
                    "products": [
                        {
                            "brand_name": "TESTMAB",
                            "dosage_form": "INJECTION",
                            "route": "INTRAVENOUS",
                            "marketing_status": "Prescription",
                            "active_ingredients": [{"name": "TESTIMAB", "strength": "100MG"}],
                        }
                    ],
                    "submissions": [
                        {
                            "submission_type": "ORIG",
                            "submission_status": "AP",
                            "submission_status_date": "20260521",
                            "submission_class_code": "TYPE 1",
                            "application_docs": [{"url": "https://www.accessdata.fda.gov/test-label.pdf"}],
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    applications = source_adapters.load_openfda_drug_applications(
        "TESTMAB",
        limit=1,
        since="2026-05-01T00:00:00Z",
        api_base_url="https://openfda.test/drug/drugsfda.json",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "openFDA Drugs@FDA applications"
    assert parsed.netloc == "openfda.test"
    assert "openfda.brand_name" in params["search"][0]
    assert params["limit"] == ["1"]
    assert applications[0].application_number == "BLA125514"
    assert applications[0].sponsor_name == "ACME BIO"
    assert applications[0].brand_names == ["TESTMAB"]
    assert applications[0].generic_names == ["testimab"]
    assert applications[0].routes == ["INTRAVENOUS"]
    assert applications[0].substances == ["TESTIMAB"]
    assert applications[0].dosage_forms == ["INJECTION"]
    assert applications[0].marketing_statuses == ["Prescription"]
    assert applications[0].latest_submission_status == "AP"
    assert applications[0].latest_submission_status_date == "2026-05-21T00:00:00Z"
    assert applications[0].url == "https://www.accessdata.fda.gov/test-label.pdf"


def test_forecast_cli_openfda_import_captures_applications_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_openfda_drug_applications(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
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
                latest_submission_status="AP",
                latest_submission_status_date="2026-05-21T00:00:00Z",
                latest_submission_type="ORIG",
                latest_submission_class="TYPE 1",
                url="https://www.accessdata.fda.gov/test-label.pdf",
                source_name="openFDA Drugs@FDA",
                entry_id="BLA125514",
                raw={"application_number": "BLA125514"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_openfda_drug_applications", fake_load_openfda_drug_applications)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will openFDA import work?",
            "--resolution-criteria",
            "Resolved yes if FDA application evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "openfda",
            "TESTMAB",
            "--question",
            question_id,
            "--limit",
            "2",
            "--since",
            "2026-05-01T00:00:00Z",
            "--api-base-url",
            "https://openfda.test/drug/drugsfda.json",
            "--reliability",
            "0.93",
            "--relevance",
            "0.84",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 openfda evidence item(s)" in output
    assert captured["source"] == "TESTMAB"
    assert captured["kwargs"]["limit"] == 2
    assert captured["kwargs"]["since"] == "2026-05-01T00:00:00Z"
    assert captured["kwargs"]["api_base_url"] == "https://openfda.test/drug/drugsfda.json"
    assert evidence[0].claim == "openFDA BLA125514: AP - TESTMAB"
    assert evidence[0].summary.startswith("openFDA Drugs@FDA application BLA125514")
    assert evidence[0].source_name == "openFDA Drugs@FDA"
    assert evidence[0].source_type == "adapter:openfda"
    assert evidence[0].published_at == "2026-05-21T00:00:00Z"
    assert evidence[0].reliability_rating == 0.93
    assert evidence[0].relevance_rating == 0.84
    assert evidence[0].metadata["adapter"] == "openfda"
    assert evidence[0].metadata["application_number"] == "BLA125514"
    assert evidence[0].metadata["brand_names"] == ["TESTMAB"]
    assert evidence[0].metadata["latest_submission_class"] == "TYPE 1"


def test_pubmed_adapter_loads_article_rows(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["search_endpoint"] = endpoint
        captured["search_label"] = label
        return {"esearchresult": {"idlist": ["12345678"]}}

    def fake_read_text_endpoint(endpoint: str, label: str):
        captured["fetch_endpoint"] = endpoint
        captured["fetch_label"] = label
        return """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">12345678</PMID>
      <DateRevised><Year>2026</Year><Month>05</Month><Day>22</Day></DateRevised>
      <Article>
        <Journal>
          <Title>Journal of Forecasting Medicine</Title>
          <JournalIssue><PubDate><Year>2026</Year><Month>May</Month><Day>21</Day></PubDate></JournalIssue>
        </Journal>
        <ArticleTitle>Calibrated biomedical forecasts</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">Forecasts need calibrated biomedical priors.</AbstractText>
          <AbstractText Label="METHODS">We tested a forecasting workflow.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Forecaster</LastName><ForeName>Ada</ForeName></Author>
          <Author><CollectiveName>Forecasting Consortium</CollectiveName></Author>
        </AuthorList>
        <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
      </Article>
    </MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1234/pubmed.forecast</ArticleId></ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)
    monkeypatch.setattr(source_adapters, "_read_text_endpoint", fake_read_text_endpoint)

    articles = source_adapters.load_pubmed_articles(
        "forecasting calibration",
        limit=2,
        since="2026-05-01",
        api_base_url="https://pubmed.test/entrez/eutils/esearch.fcgi",
    )
    search_params = parse_qs(urlparse(captured["search_endpoint"]).query)
    fetch = urlparse(captured["fetch_endpoint"])
    fetch_params = parse_qs(fetch.query)

    assert captured["search_label"] == "pubmed search"
    assert captured["fetch_label"] == "pubmed articles"
    assert search_params["term"] == ["forecasting calibration"]
    assert search_params["retmax"] == ["2"]
    assert search_params["mindate"] == ["2026/05/01"]
    assert search_params["datetype"] == ["pdat"]
    assert fetch.path.endswith("/efetch.fcgi")
    assert fetch_params["id"] == ["12345678"]
    assert articles[0].pmid == "12345678"
    assert articles[0].title == "Calibrated biomedical forecasts"
    assert articles[0].journal == "Journal of Forecasting Medicine"
    assert articles[0].doi == "10.1234/pubmed.forecast"
    assert articles[0].published_at == "2026-05-21T00:00:00Z"
    assert articles[0].revised_at == "2026-05-22T00:00:00Z"
    assert articles[0].authors == ["Ada Forecaster", "Forecasting Consortium"]
    assert articles[0].publication_types == ["Journal Article"]
    assert "BACKGROUND: Forecasts need calibrated biomedical priors." in articles[0].abstract


def test_forecast_cli_pubmed_import_captures_articles_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_pubmed_articles(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            PubMedArticle(
                pmid="12345678",
                title="Calibrated biomedical forecasts",
                abstract="Forecasts need calibrated biomedical priors.",
                journal="Journal of Forecasting Medicine",
                url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
                doi="10.1234/pubmed.forecast",
                published_at="2026-05-21T00:00:00Z",
                revised_at="2026-05-22T00:00:00Z",
                authors=["Ada Forecaster"],
                publication_types=["Journal Article"],
                source_name="PubMed",
                entry_id="12345678",
                raw={"pmid": "12345678"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_pubmed_articles", fake_load_pubmed_articles)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will PubMed import work?",
            "--resolution-criteria",
            "Resolved yes if biomedical literature evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "pubmed",
            "forecasting calibration",
            "--question",
            question_id,
            "--limit",
            "2",
            "--since",
            "2026-05-01",
            "--api-base-url",
            "https://pubmed.test/entrez/eutils/esearch.fcgi",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.91",
            "--relevance",
            "0.86",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 pubmed evidence item(s)" in output
    assert captured["source"] == "forecasting calibration"
    assert captured["kwargs"]["limit"] == 2
    assert captured["kwargs"]["since"] == "2026-05-01"
    assert captured["kwargs"]["api_base_url"] == "https://pubmed.test/entrez/eutils/esearch.fcgi"
    assert evidence[0].claim == "PubMed 12345678: Calibrated biomedical forecasts"
    assert evidence[0].summary.startswith("PubMed article 12345678")
    assert evidence[0].source_name == "PubMed"
    assert evidence[0].source_type == "adapter:pubmed"
    assert evidence[0].published_at == "2026-05-21T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.91
    assert evidence[0].relevance_rating == 0.86
    assert evidence[0].metadata["adapter"] == "pubmed"
    assert evidence[0].metadata["pubmed_query"] == "forecasting calibration"
    assert evidence[0].metadata["pmid"] == "12345678"
    assert evidence[0].metadata["doi"] == "10.1234/pubmed.forecast"
    assert evidence[0].metadata["authors"] == ["Ada Forecaster"]


def test_owid_adapter_loads_grapher_rows(monkeypatch):
    captured = {}

    def fake_read_text_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return (
            "Entity,Code,Year,gdp_per_capita\n"
            "United States,USA,2024,65000\n"
            "United States,USA,2025,67000\n"
            "France,FRA,2025,50000\n"
        )

    monkeypatch.setattr(source_adapters, "_read_text_endpoint", fake_read_text_endpoint)

    observations = source_adapters.load_owid_observations(
        "gdp-per-capita",
        limit=2,
        since="2025-01-01T00:00:00Z",
        entity="United States",
        api_base_url="https://owid.test/grapher",
    )

    assert captured["label"] == "owid grapher csv"
    assert captured["endpoint"] == "https://owid.test/grapher/gdp-per-capita.csv"
    assert len(observations) == 1
    assert observations[0].slug == "gdp-per-capita"
    assert observations[0].entity == "United States"
    assert observations[0].code == "USA"
    assert observations[0].observation_date == "2025"
    assert observations[0].published_at == "2025-01-01T00:00:00Z"
    assert observations[0].value == 67000.0
    assert observations[0].value_column == "gdp_per_capita"


def test_forecast_cli_owid_import_captures_observations_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_owid_observations(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            OwidObservation(
                slug="gdp-per-capita",
                entity="United States",
                code="USA",
                observation_date="2025",
                value=67000.0,
                value_column="gdp_per_capita",
                published_at="2025-01-01T00:00:00Z",
                source_url="https://ourworldindata.org/grapher/gdp-per-capita.csv",
                source_name="Our World in Data",
                entry_id="gdp-per-capita:United States:2025",
                raw={"Year": "2025", "gdp_per_capita": "67000"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_owid_observations", fake_load_owid_observations)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will OWID evidence import work?",
            "--resolution-criteria",
            "Resolved yes if OWID evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "owid",
            "gdp-per-capita",
            "--question",
            question_id,
            "--limit",
            "3",
            "--entity",
            "United States",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 owid evidence item(s)" in output
    assert captured["source"] == "gdp-per-capita"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["entity"] == "United States"
    assert evidence[0].claim == "OWID gdp-per-capita United States 2025: 67000.0"
    assert evidence[0].summary == "Our World in Data observation for gdp_per_capita on 2025: 67000.0."
    assert evidence[0].source_name == "Our World in Data"
    assert evidence[0].source_type == "adapter:owid"
    assert evidence[0].published_at == "2025-01-01T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "owid"
    assert evidence[0].metadata["slug"] == "gdp-per-capita"
    assert evidence[0].metadata["entity"] == "United States"
    assert evidence[0].metadata["value"] == 67000.0


def test_who_gho_adapter_loads_indicator_rows(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "value": [
                {
                    "Id": 123,
                    "IndicatorCode": "WHOSIS_000001",
                    "SpatialDim": "USA",
                    "TimeDim": 2025,
                    "Dim1": "BTSX",
                    "NumericValue": 77.4,
                    "Value": "77.4 [75.0-79.0]",
                    "Low": 75.0,
                    "High": 79.0,
                }
            ]
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    observations = source_adapters.load_who_gho_observations(
        "WHOSIS_000001",
        limit=2,
        since="2025-01-01T00:00:00Z",
        country="usa",
        dimensions=["Dim1=BTSX"],
        api_base_url="https://who.test/api",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "WHO GHO observations"
    assert parsed.path == "/api/WHOSIS_000001"
    assert params["$top"] == ["2"]
    assert params["$orderby"] == ["TimeDim desc"]
    assert params["$filter"] == ["SpatialDim eq 'USA' and Dim1 eq 'BTSX'"]
    assert observations[0].indicator == "WHOSIS_000001"
    assert observations[0].spatial_dim == "USA"
    assert observations[0].time_dim == "2025"
    assert observations[0].published_at == "2025-01-01T00:00:00Z"
    assert observations[0].numeric_value == 77.4
    assert observations[0].value == 77.4
    assert observations[0].low == 75.0
    assert observations[0].high == 79.0


def test_forecast_cli_who_gho_import_captures_observations_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_who_gho_observations(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            WhoGhoObservation(
                indicator="WHOSIS_000001",
                spatial_dim="USA",
                time_dim="2025",
                dim1="BTSX",
                dim2=None,
                dim3=None,
                value=77.4,
                numeric_value=77.4,
                low=75.0,
                high=79.0,
                published_at="2025-01-01T00:00:00Z",
                source_url="https://ghoapi.azureedge.net/api/WHOSIS_000001",
                source_name="WHO Global Health Observatory",
                entry_id="123",
                raw={"Id": 123},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_who_gho_observations", fake_load_who_gho_observations)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will WHO GHO evidence import work?",
            "--resolution-criteria",
            "Resolved yes if WHO GHO evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "whogho",
            "WHOSIS_000001",
            "--question",
            question_id,
            "--limit",
            "3",
            "--country",
            "USA",
            "--dimension",
            "Dim1=BTSX",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 whogho evidence item(s)" in output
    assert captured["source"] == "WHOSIS_000001"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["country"] == "USA"
    assert captured["kwargs"]["dimensions"] == ["Dim1=BTSX"]
    assert evidence[0].claim == "WHO GHO WHOSIS_000001 USA 2025: 77.4"
    assert evidence[0].summary == "WHO GHO observation for WHOSIS_000001 USA 2025: 77.4 (low 75.0, high 79.0)."
    assert evidence[0].source_name == "WHO Global Health Observatory"
    assert evidence[0].source_type == "adapter:whogho"
    assert evidence[0].published_at == "2025-01-01T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "whogho"
    assert evidence[0].metadata["indicator"] == "WHOSIS_000001"
    assert evidence[0].metadata["spatial_dim"] == "USA"
    assert evidence[0].metadata["numeric_value"] == 77.4


def test_fema_adapter_loads_disaster_declaration_rows(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "DisasterDeclarationsSummaries": [
                {
                    "id": "abc123",
                    "disasterNumber": 5001,
                    "femaDeclarationString": "DR-5001-CA",
                    "state": "CA",
                    "declarationType": "DR",
                    "declarationDate": "2025-01-03T00:00:00.000Z",
                    "fyDeclared": 2025,
                    "incidentType": "Fire",
                    "declarationTitle": "California Wildfires",
                    "designatedArea": "Los Angeles County",
                    "incidentBeginDate": "2025-01-01T00:00:00.000Z",
                    "incidentEndDate": "2025-01-08T00:00:00.000Z",
                    "iaProgramDeclared": True,
                    "paProgramDeclared": False,
                    "hmProgramDeclared": True,
                    "lastRefresh": "2025-01-04T12:00:00.000Z",
                }
            ]
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    declarations = source_adapters.load_fema_disaster_declarations(
        "state=ca&incident_type=Fire",
        limit=2,
        since="2025-01-01T00:00:00Z",
        declaration_type="DR",
        api_base_url="https://fema.test/api/open/v2/DisasterDeclarationsSummaries",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "FEMA disaster declarations"
    assert parsed.path == "/api/open/v2/DisasterDeclarationsSummaries"
    assert params["$top"] == ["2"]
    assert params["$orderby"] == ["declarationDate desc"]
    assert params["$filter"] == ["state eq 'CA' and incidentType eq 'Fire' and declarationType eq 'DR'"]
    assert declarations[0].disaster_number == 5001
    assert declarations[0].declaration_string == "DR-5001-CA"
    assert declarations[0].state == "CA"
    assert declarations[0].declaration_date == "2025-01-03T00:00:00Z"
    assert declarations[0].incident_type == "Fire"
    assert declarations[0].title == "California Wildfires"
    assert declarations[0].designated_area == "Los Angeles County"
    assert declarations[0].individual_assistance is True
    assert declarations[0].public_assistance is False
    assert declarations[0].hazard_mitigation is True


def test_forecast_cli_fema_import_captures_declarations_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_fema_disaster_declarations(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            FemaDisasterDeclaration(
                disaster_number=5001,
                declaration_string="DR-5001-CA",
                state="CA",
                declaration_type="DR",
                declaration_date="2025-01-03T00:00:00Z",
                fiscal_year=2025,
                incident_type="Fire",
                title="California Wildfires",
                designated_area="Los Angeles County",
                incident_begin_date="2025-01-01T00:00:00Z",
                incident_end_date="2025-01-08T00:00:00Z",
                individual_assistance=True,
                public_assistance=False,
                hazard_mitigation=True,
                last_refresh="2025-01-04T12:00:00Z",
                source_url="https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries?$top=1",
                source_name="FEMA Disaster Declarations Summaries",
                entry_id="abc123",
                raw={"id": "abc123"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_fema_disaster_declarations", fake_load_fema_disaster_declarations)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will FEMA evidence import work?",
            "--resolution-criteria",
            "Resolved yes if FEMA evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "fema",
            "state=CA&incidentType=Fire",
            "--question",
            question_id,
            "--limit",
            "3",
            "--declaration-type",
            "DR",
            "--claim-type",
            "fact",
            "--reliability",
            "0.9",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 fema evidence item(s)" in output
    assert captured["source"] == "state=CA&incidentType=Fire"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["declaration_type"] == "DR"
    assert evidence[0].claim == "FEMA 5001 CA Los Angeles County: Fire"
    assert evidence[0].summary == "FEMA disaster declaration 5001 CA Los Angeles County: Fire, declared 2025-01-03T00:00:00Z."
    assert evidence[0].source_name == "FEMA Disaster Declarations Summaries"
    assert evidence[0].source_type == "adapter:fema"
    assert evidence[0].published_at == "2025-01-03T00:00:00Z"
    assert evidence[0].claim_type == "fact"
    assert evidence[0].reliability_rating == 0.9
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["adapter"] == "fema"
    assert evidence[0].metadata["disaster_number"] == 5001
    assert evidence[0].metadata["state"] == "CA"
    assert evidence[0].metadata["incident_type"] == "Fire"
    assert evidence[0].metadata["hazard_mitigation"] is True


def test_fred_adapter_loads_recent_csv_observations(monkeypatch):
    captured = {}

    def fake_read_text_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return "\n".join(
            [
                "observation_date,UNRATE",
                "2025-12-01,4.0",
                "2026-01-01,.",
                "2026-02-01,4.1",
                "2026-03-01,4.2",
            ]
        )

    monkeypatch.setattr(source_adapters, "_read_text_endpoint", fake_read_text_endpoint)

    observations = source_adapters.load_fred_observations(
        "UNRATE",
        limit=1,
        since="2026-01-01",
        api_base_url="https://fred.test/fredgraph.csv",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "fred observations"
    assert parsed.netloc == "fred.test"
    assert params["id"] == ["UNRATE"]
    assert len(observations) == 1
    assert observations[0].series_id == "UNRATE"
    assert observations[0].observation_date == "2026-03-01"
    assert observations[0].published_at == "2026-03-01T00:00:00Z"
    assert observations[0].value == 4.2


def test_forecast_cli_fred_import_captures_observations_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_fred_observations(series_id: str, **kwargs):
        captured["series_id"] = series_id
        captured["kwargs"] = kwargs
        return [
            FredObservation(
                series_id="UNRATE",
                observation_date="2026-03-01",
                value=4.2,
                published_at="2026-03-01T00:00:00Z",
                source_url=None,
                source_name="FRED",
                entry_id="UNRATE:2026-03-01",
                raw={"observation_date": "2026-03-01", "UNRATE": "4.2"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_fred_observations", fake_load_fred_observations)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will FRED evidence import work?",
            "--resolution-criteria",
            "Resolved yes if FRED evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "fred",
            "UNRATE",
            "--question",
            question_id,
            "--since",
            "2026-01-01",
            "--limit",
            "3",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.95",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 fred evidence item(s)" in output
    assert captured["series_id"] == "UNRATE"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-01-01"
    assert evidence[0].claim == "UNRATE 2026-03-01: 4.2"
    assert evidence[0].summary == "FRED observation for UNRATE on 2026-03-01: 4.2."
    assert evidence[0].source_name == "FRED"
    assert evidence[0].source_type == "adapter:fred"
    assert evidence[0].published_at == "2026-03-01T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.95
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["adapter"] == "fred"
    assert evidence[0].metadata["series_id"] == "UNRATE"
    assert evidence[0].metadata["value"] == 4.2


def test_eia_adapter_loads_energy_series_observations(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "response": {
                "data": [
                    {
                        "period": "2026-02",
                        "value": "71.2",
                        "series-description": "WTI crude oil spot price",
                        "units": "dollars per barrel",
                    },
                    {
                        "period": "2026-03",
                        "value": "72.5",
                        "series-description": "WTI crude oil spot price",
                        "units": "dollars per barrel",
                    },
                ]
            }
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    observations = source_adapters.load_eia_observations(
        "PET.RWTC.M",
        limit=1,
        since="2026-01-01",
        api_base_url="https://eia.test/series/",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "eia observations"
    assert parsed.netloc == "eia.test"
    assert params["series_id"] == ["PET.RWTC.M"]
    assert len(observations) == 1
    assert observations[0].series_id == "PET.RWTC.M"
    assert observations[0].series_name == "WTI crude oil spot price"
    assert observations[0].observation_period == "2026-03"
    assert observations[0].published_at == "2026-03-01T00:00:00Z"
    assert observations[0].value == 72.5
    assert observations[0].unit == "dollars per barrel"


def test_forecast_cli_eia_import_captures_observations_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_eia_observations(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            EiaObservation(
                series_id="PET.RWTC.M",
                series_name="WTI crude oil spot price",
                observation_period="2026-03",
                value=72.5,
                unit="dollars per barrel",
                published_at="2026-03-01T00:00:00Z",
                source_url="https://api.eia.gov/series/?series_id=PET.RWTC.M",
                source_name="EIA",
                entry_id="PET.RWTC.M:2026-03",
                raw={"period": "2026-03", "value": "72.5"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_eia_observations", fake_load_eia_observations)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will EIA evidence import work?",
            "--resolution-criteria",
            "Resolved yes if EIA evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "eia",
            "PET.RWTC.M",
            "--question",
            question_id,
            "--since",
            "2026-01-01",
            "--limit",
            "3",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.95",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 eia evidence item(s)" in output
    assert captured["source"] == "PET.RWTC.M"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-01-01"
    assert evidence[0].claim == "PET.RWTC.M 2026-03: 72.5 dollars per barrel"
    assert evidence[0].summary == "EIA observation for WTI crude oil spot price period 2026-03: 72.5 dollars per barrel."
    assert evidence[0].source_name == "EIA"
    assert evidence[0].source_type == "adapter:eia"
    assert evidence[0].published_at == "2026-03-01T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.95
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["adapter"] == "eia"
    assert evidence[0].metadata["series_id"] == "PET.RWTC.M"
    assert evidence[0].metadata["unit"] == "dollars per barrel"
    assert evidence[0].metadata["value"] == 72.5


def test_treasury_adapter_loads_fiscal_data_records(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "data": [
                {
                    "record_date": "2026-03-01",
                    "security_type_desc": "Treasury Bills",
                    "avg_interest_rate_amt": "4.25",
                },
                {
                    "record_date": "2026-04-01",
                    "security_type_desc": "Treasury Notes",
                    "avg_interest_rate_amt": "4.40",
                },
            ],
            "meta": {"labels": {"avg_interest_rate_amt": "Average Interest Rate"}},
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    records = source_adapters.load_treasury_records(
        "v2/accounting/od/avg_interest_rates",
        limit=1,
        since="2026-01-01",
        value_field="avg_interest_rate_amt",
        api_base_url="https://treasury.test/services/api/fiscal_service",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "treasury fiscal data"
    assert parsed.netloc == "treasury.test"
    assert parsed.path.endswith("/services/api/fiscal_service/v2/accounting/od/avg_interest_rates")
    assert params["page[size]"] == ["100"]
    assert params["sort"] == ["-record_date"]
    assert len(records) == 1
    assert records[0].dataset == "v2/accounting/od/avg_interest_rates"
    assert records[0].record_date == "2026-04-01"
    assert records[0].published_at == "2026-04-01T00:00:00Z"
    assert records[0].value == 4.4
    assert records[0].value_field == "avg_interest_rate_amt"
    assert records[0].value_label == "Average Interest Rate"
    assert records[0].source_name == "U.S. Treasury Fiscal Data"


def test_forecast_cli_treasury_import_captures_records_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_treasury_records(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            TreasuryRecord(
                dataset="v2/accounting/od/avg_interest_rates",
                record_date="2026-04-01",
                value=4.4,
                value_field="avg_interest_rate_amt",
                value_label="Average Interest Rate",
                published_at="2026-04-01T00:00:00Z",
                source_url="https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates",
                source_name="U.S. Treasury Fiscal Data",
                entry_id="v2/accounting/od/avg_interest_rates:2026-04-01:0",
                raw={"record_date": "2026-04-01", "avg_interest_rate_amt": "4.40"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_treasury_records", fake_load_treasury_records)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Treasury evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Treasury evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "treasury",
            "v2/accounting/od/avg_interest_rates",
            "--question",
            question_id,
            "--since",
            "2026-01-01",
            "--limit",
            "3",
            "--value-field",
            "avg_interest_rate_amt",
            "--api-base-url",
            "https://treasury.test/services/api/fiscal_service",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.95",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 treasury evidence item(s)" in output
    assert captured["source"] == "v2/accounting/od/avg_interest_rates"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-01-01"
    assert captured["kwargs"]["value_field"] == "avg_interest_rate_amt"
    assert captured["kwargs"]["api_base_url"] == "https://treasury.test/services/api/fiscal_service"
    assert evidence[0].claim == "v2/accounting/od/avg_interest_rates 2026-04-01: avg_interest_rate_amt=4.4"
    assert (
        evidence[0].summary
        == "Treasury Fiscal Data record for v2/accounting/od/avg_interest_rates on 2026-04-01: avg_interest_rate_amt=4.4."
    )
    assert evidence[0].source_name == "U.S. Treasury Fiscal Data"
    assert evidence[0].source_type == "adapter:treasury"
    assert evidence[0].published_at == "2026-04-01T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.95
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["adapter"] == "treasury"
    assert evidence[0].metadata["dataset"] == "v2/accounting/od/avg_interest_rates"
    assert evidence[0].metadata["value_label"] == "Average Interest Rate"


def test_bls_adapter_loads_public_api_observations(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "status": "REQUEST_SUCCEEDED",
            "Results": {
                "series": [
                    {
                        "seriesID": "LNS14000000",
                        "data": [
                            {"year": "2026", "period": "M03", "periodName": "March", "value": "4.2"},
                            {"year": "2026", "period": "M02", "periodName": "February", "value": "4.1"},
                            {"year": "2026", "period": "M01", "periodName": "January", "value": "."},
                            {"year": "2025", "period": "M12", "periodName": "December", "value": "4.0"},
                        ],
                    }
                ]
            },
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    observations = source_adapters.load_bls_observations(
        "LNS14000000",
        limit=1,
        since="2026-01-01",
        start_year=2026,
        end_year=2026,
        api_base_url="https://bls.test/publicAPI/v2/timeseries/data",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "bls observations"
    assert parsed.netloc == "bls.test"
    assert parsed.path.endswith("/LNS14000000")
    assert params["startyear"] == ["2026"]
    assert params["endyear"] == ["2026"]
    assert len(observations) == 1
    assert observations[0].series_id == "LNS14000000"
    assert observations[0].observation_date == "2026-03-01"
    assert observations[0].published_at == "2026-03-01T00:00:00Z"
    assert observations[0].period == "M03"
    assert observations[0].value == 4.2


def test_forecast_cli_bls_import_captures_observations_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_bls_observations(series_id: str, **kwargs):
        captured["series_id"] = series_id
        captured["kwargs"] = kwargs
        return [
            BlsObservation(
                series_id="LNS14000000",
                observation_date="2026-03-01",
                period="M03",
                period_name="March",
                value=4.2,
                published_at="2026-03-01T00:00:00Z",
                source_url=None,
                source_name="BLS",
                entry_id="LNS14000000:2026:M03",
                raw={"year": "2026", "period": "M03", "value": "4.2"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_bls_observations", fake_load_bls_observations)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will BLS evidence import work?",
            "--resolution-criteria",
            "Resolved yes if BLS evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "bls",
            "LNS14000000",
            "--question",
            question_id,
            "--since",
            "2026-01-01",
            "--start-year",
            "2026",
            "--end-year",
            "2026",
            "--limit",
            "3",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.95",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 bls evidence item(s)" in output
    assert captured["series_id"] == "LNS14000000"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-01-01"
    assert captured["kwargs"]["start_year"] == 2026
    assert captured["kwargs"]["end_year"] == 2026
    assert evidence[0].claim == "LNS14000000 2026-03-01: 4.2"
    assert evidence[0].summary == "BLS observation for LNS14000000 period M03 on 2026-03-01: 4.2."
    assert evidence[0].source_name == "BLS"
    assert evidence[0].source_type == "adapter:bls"
    assert evidence[0].published_at == "2026-03-01T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.95
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["adapter"] == "bls"
    assert evidence[0].metadata["series_id"] == "LNS14000000"
    assert evidence[0].metadata["period"] == "M03"
    assert evidence[0].metadata["period_name"] == "March"
    assert evidence[0].metadata["value"] == 4.2


def test_worldbank_adapter_loads_indicator_observations(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return [
            {"page": 1, "pages": 1, "per_page": "100", "total": 3},
            [
                {
                    "country": {"id": "US", "value": "United States"},
                    "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
                    "date": "2025",
                    "value": "30000000000000",
                },
                {
                    "country": {"id": "US", "value": "United States"},
                    "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
                    "date": "2024",
                    "value": None,
                },
                {
                    "country": {"id": "US", "value": "United States"},
                    "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
                    "date": "2023",
                    "value": "28000000000000",
                },
            ],
        ]

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    observations = source_adapters.load_worldbank_observations(
        "USA/NY.GDP.MKTP.CD",
        limit=1,
        since="2023",
        api_base_url="https://worldbank.test/v2",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "worldbank observations"
    assert parsed.netloc == "worldbank.test"
    assert parsed.path.endswith("/country/USA/indicator/NY.GDP.MKTP.CD")
    assert params["format"] == ["json"]
    assert params["per_page"] == ["100"]
    assert len(observations) == 1
    assert observations[0].country == "US"
    assert observations[0].country_name == "United States"
    assert observations[0].indicator == "NY.GDP.MKTP.CD"
    assert observations[0].observation_date == "2025-12-31"
    assert observations[0].published_at == "2025-12-31T00:00:00Z"
    assert observations[0].value == 30000000000000.0


def test_forecast_cli_worldbank_import_captures_observations_as_evidence(
    tmp_path, capsys, monkeypatch
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_worldbank_observations(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            WorldBankObservation(
                country="US",
                country_name="United States",
                indicator="NY.GDP.MKTP.CD",
                indicator_name="GDP (current US$)",
                observation_date="2025-12-31",
                value=30000000000000.0,
                published_at="2025-12-31T00:00:00Z",
                source_url=None,
                source_name="World Bank",
                entry_id="US:NY.GDP.MKTP.CD:2025",
                raw={"date": "2025", "value": "30000000000000"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_worldbank_observations", fake_load_worldbank_observations)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will World Bank evidence import work?",
            "--resolution-criteria",
            "Resolved yes if World Bank evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "worldbank",
            "USA/NY.GDP.MKTP.CD",
            "--question",
            question_id,
            "--since",
            "2023",
            "--limit",
            "3",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.9",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 worldbank evidence item(s)" in output
    assert captured["source"] == "USA/NY.GDP.MKTP.CD"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2023"
    assert evidence[0].claim == "US/NY.GDP.MKTP.CD 2025-12-31: 30000000000000.0"
    assert evidence[0].summary == (
        "World Bank observation for United States GDP (current US$) "
        "on 2025-12-31: 30000000000000.0."
    )
    assert evidence[0].source_name == "World Bank"
    assert evidence[0].source_type == "adapter:worldbank"
    assert evidence[0].published_at == "2025-12-31T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.9
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["adapter"] == "worldbank"
    assert evidence[0].metadata["country"] == "US"
    assert evidence[0].metadata["country_name"] == "United States"
    assert evidence[0].metadata["indicator"] == "NY.GDP.MKTP.CD"
    assert evidence[0].metadata["indicator_name"] == "GDP (current US$)"
    assert evidence[0].metadata["value"] == 30000000000000.0


def test_imf_datamapper_adapter_loads_indicator_observations(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "values": {
                "NGDP_RPCH": {
                    "USA": {
                        "2023": 2.9,
                        "2024": None,
                        "2025": "1.8",
                    }
                }
            },
            "countries": {"USA": {"label": "United States"}},
            "indicators": {"NGDP_RPCH": {"label": "Real GDP growth"}},
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    observations = source_adapters.load_imf_datamapper_observations(
        "NGDP_RPCH/USA",
        limit=1,
        since="2023",
        api_base_url="https://imf.test/datamapper/api/v1",
    )
    parsed = urlparse(captured["endpoint"])

    assert captured["label"] == "imf datamapper observations"
    assert parsed.netloc == "imf.test"
    assert parsed.path.endswith("/datamapper/api/v1/NGDP_RPCH/USA")
    assert len(observations) == 1
    assert observations[0].indicator == "NGDP_RPCH"
    assert observations[0].indicator_name == "Real GDP growth"
    assert observations[0].country == "USA"
    assert observations[0].country_name == "United States"
    assert observations[0].observation_date == "2025-12-31"
    assert observations[0].published_at == "2025-12-31T00:00:00Z"
    assert observations[0].value == 1.8


def test_forecast_cli_imf_import_captures_observations_as_evidence(
    tmp_path, capsys, monkeypatch
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_imf_observations(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            ImfDataMapperObservation(
                indicator="NGDP_RPCH",
                indicator_name="Real GDP growth",
                country="USA",
                country_name="United States",
                observation_date="2025-12-31",
                value=1.8,
                published_at="2025-12-31T00:00:00Z",
                source_url="https://www.imf.org/external/datamapper/NGDP_RPCH@WEO/USA",
                source_name="IMF DataMapper",
                entry_id="NGDP_RPCH:USA:2025",
                raw={"year": "2025", "value": "1.8"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_imf_datamapper_observations", fake_load_imf_observations)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will IMF evidence import work?",
            "--resolution-criteria",
            "Resolved yes if IMF evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "imf",
            "NGDP_RPCH/USA",
            "--question",
            question_id,
            "--since",
            "2023",
            "--limit",
            "3",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.9",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 imf evidence item(s)" in output
    assert captured["source"] == "NGDP_RPCH/USA"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2023"
    assert evidence[0].claim == "NGDP_RPCH/USA 2025-12-31: 1.8"
    assert evidence[0].summary == (
        "IMF DataMapper observation for United States Real GDP growth "
        "on 2025-12-31: 1.8."
    )
    assert evidence[0].source_name == "IMF DataMapper"
    assert evidence[0].source_type == "adapter:imf"
    assert evidence[0].published_at == "2025-12-31T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.9
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["adapter"] == "imf"
    assert evidence[0].metadata["indicator"] == "NGDP_RPCH"
    assert evidence[0].metadata["indicator_name"] == "Real GDP growth"
    assert evidence[0].metadata["country"] == "USA"
    assert evidence[0].metadata["country_name"] == "United States"
    assert evidence[0].metadata["value"] == 1.8


def test_census_adapter_loads_api_rows(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return [
            ["NAME", "B01003_001E", "state"],
            ["California", "39100000", "06"],
            ["Texas", "30000000", "48"],
        ]

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)
    monkeypatch.setenv("CENSUS_API_KEY", "test-key")

    records = source_adapters.load_census_records(
        "2023/acs/acs5?get=NAME,B01003_001E&for=state:*",
        limit=1,
        since="2023-01-01",
        api_base_url="https://census.test/data",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "census data"
    assert parsed.netloc == "census.test"
    assert parsed.path == "/data/2023/acs/acs5"
    assert params["get"] == ["NAME,B01003_001E"]
    assert params["for"] == ["state:*"]
    assert params["key"] == ["test-key"]
    assert len(records) == 1
    assert records[0].dataset == "2023/acs/acs5"
    assert records[0].dataset_year == 2023
    assert records[0].observation_date == "2023-12-31"
    assert records[0].published_at == "2023-12-31T00:00:00Z"
    assert records[0].values == {"NAME": "California", "B01003_001E": 39100000.0}
    assert records[0].geography == {"state": "06"}
    assert "key=" not in (records[0].source_url or "")
    assert records[0].source_name == "U.S. Census Bureau"


def test_forecast_cli_census_import_captures_records_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_census_records(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            CensusRecord(
                dataset="2023/acs/acs5",
                dataset_year=2023,
                observation_date="2023-12-31",
                values={"NAME": "California", "B01003_001E": 39100000.0},
                geography={"state": "06"},
                published_at="2023-12-31T00:00:00Z",
                source_url="https://api.census.gov/data/2023/acs/acs5?get=NAME,B01003_001E&for=state:*",
                source_name="U.S. Census Bureau",
                entry_id="2023/acs/acs5:2023-12-31:0",
                raw={"row_index": 0},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_census_records", fake_load_census_records)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Census evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Census evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "census",
            "2023/acs/acs5?get=NAME,B01003_001E&for=state:*",
            "--question",
            question_id,
            "--since",
            "2023-01-01",
            "--limit",
            "3",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.95",
            "--relevance",
            "0.85",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 census evidence item(s)" in output
    assert captured["source"] == "2023/acs/acs5?get=NAME,B01003_001E&for=state:*"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2023-01-01"
    assert evidence[0].claim == "Census 2023/acs/acs5 state=06: NAME=California, B01003_001E=39100000.0"
    assert evidence[0].summary == (
        "U.S. Census Bureau record for 2023/acs/acs5 "
        "on 2023-12-31 (state=06): NAME=California, B01003_001E=39100000.0."
    )
    assert evidence[0].source_name == "U.S. Census Bureau"
    assert evidence[0].source_type == "adapter:census"
    assert evidence[0].published_at == "2023-12-31T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.95
    assert evidence[0].relevance_rating == 0.85
    assert evidence[0].metadata["adapter"] == "census"
    assert evidence[0].metadata["dataset"] == "2023/acs/acs5"
    assert evidence[0].metadata["dataset_year"] == 2023
    assert evidence[0].metadata["values"] == {"NAME": "California", "B01003_001E": 39100000.0}
    assert evidence[0].metadata["geography"] == {"state": "06"}


def test_socrata_adapter_loads_open_data_rows(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return [
            {
                ":id": "row-1",
                ":updated_at": "2026-05-21T11:00:00Z",
                "report_date": "2026-05-20",
                "county": "King",
                "cases": "42",
            }
        ]

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    records = source_adapters.load_socrata_records(
        "socrata:data.cdc.gov/abcd-1234?county=King",
        limit=2,
        since="2026-05-01T00:00:00Z",
        api_base_url="https://api.test/{domain}/resource/{dataset_id}.json",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "socrata records"
    assert parsed.netloc == "api.test"
    assert parsed.path == "/data.cdc.gov/resource/abcd-1234.json"
    assert params["county"] == ["King"]
    assert params["$limit"] == ["2"]
    assert records[0].domain == "data.cdc.gov"
    assert records[0].dataset_id == "abcd-1234"
    assert records[0].row_id == "row-1"
    assert records[0].updated_at == "2026-05-21T11:00:00Z"
    assert records[0].observation_time == "2026-05-20T00:00:00Z"
    assert records[0].values == {"report_date": "2026-05-20", "county": "King", "cases": "42"}
    assert records[0].source_url == "https://api.test/data.cdc.gov/resource/abcd-1234.json?county=King"


def test_forecast_cli_socrata_import_captures_records_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_socrata_records(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            SocrataRecord(
                domain="data.cdc.gov",
                dataset_id="abcd-1234",
                row_id="row-1",
                observation_time="2026-05-20T00:00:00Z",
                updated_at="2026-05-21T11:00:00Z",
                values={"report_date": "2026-05-20", "county": "King", "cases": "42"},
                source_url="https://data.cdc.gov/resource/abcd-1234.json?county=King",
                source_name="Socrata",
                entry_id="data.cdc.gov/abcd-1234:row-1",
                raw={"row_index": 0},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_socrata_records", fake_load_socrata_records)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Socrata evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Socrata evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "socrata",
            "data.cdc.gov/abcd-1234?county=King",
            "--question",
            question_id,
            "--since",
            "2026-05-01T00:00:00Z",
            "--limit",
            "3",
            "--api-base-url",
            "https://api.test/{domain}/resource/{dataset_id}.json",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.9",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 socrata evidence item(s)" in output
    assert captured["source"] == "data.cdc.gov/abcd-1234?county=King"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["api_base_url"] == "https://api.test/{domain}/resource/{dataset_id}.json"
    assert evidence[0].claim == "Socrata row: data.cdc.gov/abcd-1234 row-1"
    assert evidence[0].summary.startswith("Socrata record from data.cdc.gov/abcd-1234")
    assert evidence[0].source_name == "Socrata"
    assert evidence[0].source_type == "adapter:socrata"
    assert evidence[0].published_at == "2026-05-21T11:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.9
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["adapter"] == "socrata"
    assert evidence[0].metadata["domain"] == "data.cdc.gov"
    assert evidence[0].metadata["dataset_id"] == "abcd-1234"
    assert evidence[0].metadata["values"]["cases"] == "42"


def test_ckan_adapter_loads_open_data_package_metadata(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "success": True,
            "result": {
                "results": [
                    {
                        "id": "pkg-1",
                        "name": "electricity-demand",
                        "title": "Electricity demand",
                        "notes": "Hourly grid demand.",
                        "metadata_created": "2026-05-20T10:00:00",
                        "metadata_modified": "2026-05-22T11:30:00",
                        "license_title": "Creative Commons",
                        "organization": {"title": "Energy Department"},
                        "groups": [{"name": "energy"}],
                        "tags": [{"name": "grid"}, {"display_name": "demand"}],
                        "resources": [
                            {
                                "id": "res-1",
                                "name": "CSV",
                                "url": "https://example.test/demand.csv",
                                "format": "CSV",
                                "last_modified": "2026-05-22T11:00:00",
                            }
                        ],
                    }
                ]
            },
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    datasets = source_adapters.load_ckan_datasets(
        "ckan:data.gov/energy?fq=tags:energy",
        limit=1,
        since="2026-05-01T00:00:00Z",
        api_base_url="https://api.test/{domain}/api/3/action/package_search",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "ckan package search"
    assert parsed.netloc == "api.test"
    assert parsed.path == "/data.gov/api/3/action/package_search"
    assert params["q"] == ["energy"]
    assert params["rows"] == ["1"]
    assert params["sort"] == ["metadata_modified desc"]
    assert params["fq"] == ["tags:energy"]
    assert datasets[0].portal == "data.gov"
    assert datasets[0].package_id == "pkg-1"
    assert datasets[0].name == "electricity-demand"
    assert datasets[0].title == "Electricity demand"
    assert datasets[0].metadata_modified == "2026-05-22T11:30:00Z"
    assert datasets[0].organization == "Energy Department"
    assert datasets[0].tags == ["grid", "demand"]
    assert datasets[0].resources[0]["format"] == "CSV"
    assert datasets[0].source_url == "https://data.gov/dataset/electricity-demand"


def test_forecast_cli_ckan_import_captures_datasets_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_ckan_datasets(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            CkanDataset(
                portal="data.gov",
                package_id="pkg-1",
                name="electricity-demand",
                title="Electricity demand",
                notes="Hourly grid demand.",
                url="https://example.test/demand.csv",
                organization="Energy Department",
                groups=["energy"],
                tags=["grid", "demand"],
                license_title="Creative Commons",
                metadata_created="2026-05-20T10:00:00Z",
                metadata_modified="2026-05-22T11:30:00Z",
                resources=[{"id": "res-1", "name": "CSV", "format": "CSV"}],
                source_url="https://data.gov/dataset/electricity-demand",
                source_name="CKAN:data.gov",
                entry_id="data.gov:electricity-demand",
                raw={"row_index": 0},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_ckan_datasets", fake_load_ckan_datasets)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will CKAN evidence import work?",
            "--resolution-criteria",
            "Resolved yes if CKAN evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "ckan",
            "data.gov/energy",
            "--question",
            question_id,
            "--since",
            "2026-05-01T00:00:00Z",
            "--limit",
            "3",
            "--api-base-url",
            "https://api.test/{domain}/api/3/action/package_search",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.9",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 ckan evidence item(s)" in output
    assert captured["source"] == "data.gov/energy"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["api_base_url"] == "https://api.test/{domain}/api/3/action/package_search"
    assert evidence[0].claim == "CKAN dataset: data.gov Electricity demand"
    assert evidence[0].summary.startswith("CKAN dataset from data.gov")
    assert evidence[0].source_name == "CKAN:data.gov"
    assert evidence[0].source_type == "adapter:ckan"
    assert evidence[0].published_at == "2026-05-22T11:30:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.9
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["adapter"] == "ckan"
    assert evidence[0].metadata["portal"] == "data.gov"
    assert evidence[0].metadata["name"] == "electricity-demand"
    assert evidence[0].metadata["resource_count"] == 1
    assert evidence[0].metadata["tags"] == ["grid", "demand"]


def test_stooq_adapter_loads_recent_price_observations(monkeypatch):
    captured = {}

    def fake_read_text_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return "\n".join(
            [
                "Date,Open,High,Low,Close,Volume",
                "2026-05-20,195.00,197.00,194.50,196.25,60000000",
                "2026-05-21,196.50,198.00,195.25,197.10,61000000",
                "2026-05-22,197.20,199.00,196.80,198.40,62000000",
            ]
        )

    monkeypatch.setattr(source_adapters, "_read_text_endpoint", fake_read_text_endpoint)

    observations = source_adapters.load_stooq_prices(
        "AAPL.US",
        limit=1,
        since="2026-05-21",
        interval="d",
        api_base_url="https://stooq.test/q/d/l/",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "stooq prices"
    assert parsed.netloc == "stooq.test"
    assert params["s"] == ["aapl.us"]
    assert params["i"] == ["d"]
    assert len(observations) == 1
    assert observations[0].symbol == "AAPL.US"
    assert observations[0].interval == "d"
    assert observations[0].observation_date == "2026-05-22"
    assert observations[0].published_at == "2026-05-22T00:00:00Z"
    assert observations[0].close_price == 198.4
    assert observations[0].volume == 62000000


def test_yahoo_adapter_loads_chart_observations(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": "AAPL",
                            "currency": "USD",
                            "exchangeName": "NMS",
                        },
                        "timestamp": [1779408000, 1779494400],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [197.2, 198.0],
                                    "high": [199.0, 200.0],
                                    "low": [196.8, 197.5],
                                    "close": [198.4, 199.1],
                                    "volume": [62000000, 63000000],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    observations = source_adapters.load_yahoo_finance_prices(
        "AAPL",
        limit=1,
        since="2026-05-22T00:00:00Z",
        range_value="5d",
        interval="1d",
        api_base_url="https://query.yahoo.test/v8/finance/chart",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "yahoo finance chart"
    assert parsed.netloc == "query.yahoo.test"
    assert parsed.path == "/v8/finance/chart/AAPL"
    assert params["range"] == ["5d"]
    assert params["interval"] == ["1d"]
    assert len(observations) == 1
    assert observations[0].symbol == "AAPL"
    assert observations[0].interval == "1d"
    assert observations[0].observation_time == "2026-05-23T00:00:00Z"
    assert observations[0].published_at == "2026-05-23T00:00:00Z"
    assert observations[0].close_price == 199.1
    assert observations[0].volume == 63000000
    assert observations[0].currency == "USD"
    assert observations[0].exchange_name == "NMS"


def test_forecast_cli_stooq_import_captures_observations_as_evidence(
    tmp_path, capsys, monkeypatch
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_stooq_prices(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            StooqPriceObservation(
                symbol="AAPL.US",
                interval="d",
                observation_date="2026-05-22",
                open_price=197.2,
                high_price=199.0,
                low_price=196.8,
                close_price=198.4,
                volume=62000000,
                published_at="2026-05-22T00:00:00Z",
                source_url=None,
                source_name="Stooq",
                entry_id="AAPL.US:d:2026-05-22",
                raw={"Date": "2026-05-22", "Close": "198.40"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_stooq_prices", fake_load_stooq_prices)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Stooq evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Stooq evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "stooq",
            "AAPL.US",
            "--question",
            question_id,
            "--since",
            "2026-05-01",
            "--limit",
            "3",
            "--interval",
            "d",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.85",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 stooq evidence item(s)" in output
    assert captured["source"] == "AAPL.US"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-05-01"
    assert captured["kwargs"]["interval"] == "d"
    assert evidence[0].claim == "Stooq AAPL.US close 198.4 on 2026-05-22"
    assert evidence[0].summary == "Stooq market price observation for AAPL.US on 2026-05-22: close 198.4."
    assert evidence[0].source_name == "Stooq"
    assert evidence[0].source_type == "adapter:stooq"
    assert evidence[0].published_at == "2026-05-22T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.85
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["adapter"] == "stooq"
    assert evidence[0].metadata["symbol"] == "AAPL.US"
    assert evidence[0].metadata["close_price"] == 198.4
    assert evidence[0].metadata["volume"] == 62000000


def test_forecast_cli_yahoo_import_captures_observations_as_evidence(
    tmp_path, capsys, monkeypatch
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_yahoo_finance_prices(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            YahooFinancePriceObservation(
                symbol="AAPL",
                interval="1d",
                observation_time="2026-05-23T00:00:00Z",
                open_price=198.0,
                high_price=200.0,
                low_price=197.5,
                close_price=199.1,
                volume=63000000,
                published_at="2026-05-23T00:00:00Z",
                currency="USD",
                exchange_name="NMS",
                source_url="https://finance.yahoo.com/quote/AAPL",
                source_name="Yahoo Finance",
                entry_id="AAPL:1d:2026-05-23T00:00:00Z",
                raw={"symbol": "AAPL", "close": 199.1},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_yahoo_finance_prices", fake_load_yahoo_finance_prices)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Yahoo evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Yahoo Finance evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "yahoo",
            "AAPL",
            "--question",
            question_id,
            "--since",
            "2026-05-01T00:00:00Z",
            "--limit",
            "3",
            "--range",
            "5d",
            "--interval",
            "1d",
            "--api-base-url",
            "https://query.yahoo.test/v8/finance/chart",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.86",
            "--relevance",
            "0.81",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 yahoo evidence item(s)" in output
    assert captured["source"] == "AAPL"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-05-01T00:00:00Z"
    assert captured["kwargs"]["range_value"] == "5d"
    assert captured["kwargs"]["interval"] == "1d"
    assert captured["kwargs"]["api_base_url"] == "https://query.yahoo.test/v8/finance/chart"
    assert evidence[0].claim == "Yahoo Finance AAPL close 199.1 USD at 2026-05-23T00:00:00Z"
    assert evidence[0].summary == (
        "Yahoo Finance chart observation for AAPL at 2026-05-23T00:00:00Z: "
        "close 199.1 USD; open 198.0, high 200.0, low 197.5, volume 63000000."
    )
    assert evidence[0].source_name == "Yahoo Finance"
    assert evidence[0].source_type == "adapter:yahoo"
    assert evidence[0].published_at == "2026-05-23T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.86
    assert evidence[0].relevance_rating == 0.81
    assert evidence[0].metadata["adapter"] == "yahoo"
    assert evidence[0].metadata["symbol"] == "AAPL"
    assert evidence[0].metadata["range"] == "5d"
    assert evidence[0].metadata["close_price"] == 199.1
    assert evidence[0].metadata["currency"] == "USD"


def test_sec_adapter_loads_recent_company_filings(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "cik": "320193",
            "name": "Apple Inc.",
            "tickers": ["AAPL"],
            "filings": {
                "recent": {
                    "accessionNumber": ["0000320193-26-000010", "0000320193-25-000090"],
                    "filingDate": ["2026-02-01", "2025-11-01"],
                    "reportDate": ["2025-12-31", "2025-09-30"],
                    "acceptanceDateTime": ["2026-02-01T16:30:00.000Z", "2025-11-01T16:31:00.000Z"],
                    "form": ["10-Q", "10-K"],
                    "primaryDocument": ["aapl-20251231.htm", "aapl-20250930.htm"],
                    "primaryDocDescription": ["FORM 10-Q", "FORM 10-K"],
                }
            },
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    filings = source_adapters.load_sec_filings(
        "sec:320193",
        limit=1,
        since="2026-01-01T00:00:00Z",
        api_base_url="https://sec.test/submissions",
    )
    parsed = urlparse(captured["endpoint"])

    assert captured["label"] == "sec submissions"
    assert parsed.netloc == "sec.test"
    assert parsed.path.endswith("/CIK0000320193.json")
    assert len(filings) == 1
    assert filings[0].cik == "0000320193"
    assert filings[0].company_name == "Apple Inc."
    assert filings[0].ticker == "AAPL"
    assert filings[0].form == "10-Q"
    assert filings[0].published_at == "2026-02-01T16:30:00Z"
    assert filings[0].source_url.endswith("/aapl-20251231.htm")


def test_forecast_cli_sec_import_captures_filings_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_sec_filings(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            SecFiling(
                cik="0000320193",
                company_name="Apple Inc.",
                ticker="AAPL",
                form="10-Q",
                filing_date="2026-02-01",
                report_date="2025-12-31",
                acceptance_time="2026-02-01T16:30:00.000Z",
                published_at="2026-02-01T16:30:00Z",
                accession_number="0000320193-26-000010",
                primary_document="aapl-20251231.htm",
                description="FORM 10-Q",
                source_url=None,
                source_name="SEC EDGAR",
                entry_id="0000320193:0000320193-26-000010",
                raw={"form": "10-Q"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_sec_filings", fake_load_sec_filings)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will SEC evidence import work?",
            "--resolution-criteria",
            "Resolved yes if SEC evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "sec",
            "0000320193",
            "--question",
            question_id,
            "--since",
            "2026-01-01T00:00:00Z",
            "--limit",
            "3",
            "--claim-type",
            "fact",
            "--reliability",
            "0.98",
            "--relevance",
            "0.85",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 sec evidence item(s)" in output
    assert captured["source"] == "0000320193"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-01-01T00:00:00Z"
    assert evidence[0].claim == "Apple Inc. filed 10-Q on 2026-02-01"
    assert evidence[0].summary == "SEC EDGAR filing for Apple Inc.: 10-Q (FORM 10-Q), filed 2026-02-01."
    assert evidence[0].source_name == "SEC EDGAR"
    assert evidence[0].source_type == "adapter:sec"
    assert evidence[0].published_at == "2026-02-01T16:30:00Z"
    assert evidence[0].claim_type == "fact"
    assert evidence[0].reliability_rating == 0.98
    assert evidence[0].relevance_rating == 0.85
    assert evidence[0].metadata["adapter"] == "sec"
    assert evidence[0].metadata["cik"] == "0000320193"
    assert evidence[0].metadata["ticker"] == "AAPL"
    assert evidence[0].metadata["form"] == "10-Q"
    assert evidence[0].metadata["accession_number"] == "0000320193-26-000010"


def test_sec_company_facts_adapter_loads_xbrl_observations(monkeypatch):
    captured = {}

    def fake_read_json_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return {
            "cik": 320193,
            "entityName": "Apple Inc.",
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "label": "Revenues",
                        "description": "Revenue from contract with customer.",
                        "units": {
                            "USD": [
                                {
                                    "end": "2024-09-28",
                                    "val": 383285000000,
                                    "accn": "0000320193-24-000123",
                                    "fy": 2024,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2024-11-01",
                                    "frame": "CY2024",
                                },
                                {
                                    "end": "2025-09-27",
                                    "val": 391035000000,
                                    "accn": "0000320193-25-000079",
                                    "fy": 2025,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2025-10-31",
                                    "frame": "CY2025",
                                },
                            ]
                        },
                    }
                }
            },
        }

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read_json_endpoint)

    facts = source_adapters.load_sec_company_facts(
        "secfacts:320193/Revenues",
        limit=1,
        since="2025-01-01T00:00:00Z",
        api_base_url="https://sec.test/companyfacts",
    )
    parsed = urlparse(captured["endpoint"])

    assert captured["label"] == "sec company facts"
    assert parsed.netloc == "sec.test"
    assert parsed.path.endswith("/CIK0000320193.json")
    assert len(facts) == 1
    assert facts[0].cik == "0000320193"
    assert facts[0].company_name == "Apple Inc."
    assert facts[0].taxonomy == "us-gaap"
    assert facts[0].concept == "Revenues"
    assert facts[0].label == "Revenues"
    assert facts[0].unit == "USD"
    assert facts[0].observation_date == "2025-09-27"
    assert facts[0].value == 391035000000
    assert facts[0].filed_at == "2025-10-31T00:00:00Z"
    assert facts[0].published_at == "2025-10-31T00:00:00Z"
    assert facts[0].form == "10-K"
    assert facts[0].fiscal_year == 2025
    assert facts[0].source_name == "SEC Company Facts"


def test_forecast_cli_secfacts_import_captures_observations_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_sec_company_facts(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
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
                value=391035000000,
                filed_at="2025-10-31T00:00:00Z",
                published_at="2025-10-31T00:00:00Z",
                form="10-K",
                fiscal_year=2025,
                fiscal_period="FY",
                accession_number="0000320193-25-000079",
                frame="CY2025",
                source_url="https://sec.test/companyfacts/CIK0000320193.json",
                source_name="SEC Company Facts",
                entry_id="0000320193:us-gaap:Revenues:USD:2025-09-27:0000320193-25-000079",
                raw={"row": {"val": 391035000000}},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_sec_company_facts", fake_load_sec_company_facts)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will SEC facts evidence import work?",
            "--resolution-criteria",
            "Resolved yes if SEC facts evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "secfacts",
            "0000320193/Revenues",
            "--question",
            question_id,
            "--since",
            "2025-01-01T00:00:00Z",
            "--limit",
            "2",
            "--taxonomy",
            "us-gaap",
            "--unit",
            "USD",
            "--api-base-url",
            "https://sec.test/companyfacts",
            "--reliability",
            "0.97",
            "--relevance",
            "0.84",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 secfacts evidence item(s)" in output
    assert captured["source"] == "0000320193/Revenues"
    assert captured["kwargs"]["limit"] == 2
    assert captured["kwargs"]["since"] == "2025-01-01T00:00:00Z"
    assert captured["kwargs"]["concept"] is None
    assert captured["kwargs"]["taxonomy"] == "us-gaap"
    assert captured["kwargs"]["unit"] == "USD"
    assert captured["kwargs"]["api_base_url"] == "https://sec.test/companyfacts"
    assert evidence[0].claim == (
        "Apple Inc. reported Revenues of 391035000000 USD for period ending 2025-09-27"
    )
    assert evidence[0].summary == (
        "SEC Company Facts for Apple Inc.: us-gaap:Revenues was 391035000000 USD "
        "for period ending 2025-09-27, filed 2025-10-31T00:00:00Z."
    )
    assert evidence[0].source_name == "SEC Company Facts"
    assert evidence[0].source_type == "adapter:secfacts"
    assert evidence[0].published_at == "2025-10-31T00:00:00Z"
    assert evidence[0].claim_type == "fact"
    assert evidence[0].reliability_rating == 0.97
    assert evidence[0].relevance_rating == 0.84
    assert evidence[0].metadata["adapter"] == "secfacts"
    assert evidence[0].metadata["cik"] == "0000320193"
    assert evidence[0].metadata["concept"] == "Revenues"
    assert evidence[0].metadata["unit"] == "USD"
    assert evidence[0].metadata["value"] == 391035000000


def test_arxiv_adapter_loads_atom_papers(monkeypatch):
    captured = {}

    def fake_read_text_endpoint(endpoint: str, label: str):
        captured["endpoint"] = endpoint
        captured["label"] = label
        return """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2605.12345v1</id>
    <updated>2026-05-21T12:00:00Z</updated>
    <published>2026-05-20T12:00:00Z</published>
    <title> Forecasting with calibrated agents </title>
    <summary> A paper about probabilistic forecasting systems. </summary>
    <author><name>Ada Forecaster</name></author>
    <category term="cs.AI" />
    <category term="stat.ML" />
    <link href="http://arxiv.org/abs/2605.12345v1" rel="alternate" type="text/html" />
    <link title="pdf" href="http://arxiv.org/pdf/2605.12345v1" rel="related" type="application/pdf" />
  </entry>
</feed>"""

    monkeypatch.setattr(source_adapters, "_read_text_endpoint", fake_read_text_endpoint)

    papers = source_adapters.load_arxiv_papers(
        "cat:cs.AI AND forecasting",
        limit=2,
        since="2026-05-01T00:00:00Z",
        api_base_url="https://arxiv.test/api/query",
    )
    parsed = urlparse(captured["endpoint"])
    params = parse_qs(parsed.query)

    assert captured["label"] == "arxiv papers"
    assert parsed.netloc == "arxiv.test"
    assert params["search_query"] == ["cat:cs.AI AND forecasting"]
    assert params["max_results"] == ["2"]
    assert params["sortBy"] == ["submittedDate"]
    assert papers[0].arxiv_id == "2605.12345v1"
    assert papers[0].title == "Forecasting with calibrated agents"
    assert papers[0].published_at == "2026-05-20T12:00:00Z"
    assert papers[0].pdf_url == "http://arxiv.org/pdf/2605.12345v1"
    assert papers[0].authors == ["Ada Forecaster"]
    assert papers[0].categories == ["cs.AI", "stat.ML"]


def test_forecast_cli_arxiv_import_captures_papers_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_arxiv_papers(query: str, **kwargs):
        captured["query"] = query
        captured["kwargs"] = kwargs
        return [
            ArxivPaper(
                arxiv_id="2605.12345v1",
                title="Forecasting with calibrated agents",
                abstract="A paper about probabilistic forecasting systems.",
                url="http://arxiv.org/abs/2605.12345v1",
                pdf_url="http://arxiv.org/pdf/2605.12345v1",
                published_at="2026-05-20T12:00:00Z",
                updated_at="2026-05-21T12:00:00Z",
                authors=["Ada Forecaster"],
                categories=["cs.AI", "stat.ML"],
                source_name="arXiv",
                entry_id="http://arxiv.org/abs/2605.12345v1",
                raw={"id": "http://arxiv.org/abs/2605.12345v1"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_arxiv_papers", fake_load_arxiv_papers)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will arXiv evidence import work?",
            "--resolution-criteria",
            "Resolved yes if arXiv evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "arxiv",
            "cat:cs.AI AND forecasting",
            "--question",
            question_id,
            "--limit",
            "3",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 arxiv evidence item(s)" in output
    assert captured["query"] == "cat:cs.AI AND forecasting"
    assert captured["kwargs"]["limit"] == 3
    assert evidence[0].claim == "arXiv paper: Forecasting with calibrated agents"
    assert evidence[0].summary == "A paper about probabilistic forecasting systems."
    assert evidence[0].source_name == "arXiv"
    assert evidence[0].source_type == "adapter:arxiv"
    assert evidence[0].published_at == "2026-05-20T12:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "arxiv"
    assert evidence[0].metadata["arxiv_query"] == "cat:cs.AI AND forecasting"
    assert evidence[0].metadata["arxiv_id"] == "2605.12345v1"
    assert evidence[0].metadata["authors"] == ["Ada Forecaster"]
    assert evidence[0].metadata["categories"] == ["cs.AI", "stat.ML"]


def test_openalex_loader_parses_works_from_api():
    payload = {
        "results": [
            {
                "id": "https://openalex.org/W123",
                "doi": "https://doi.org/10.1234/forecasting",
                "display_name": "Forecasting with scholarly priors",
                "abstract_inverted_index": {
                    "Forecasting": [0],
                    "systems": [2],
                    "calibrate": [1],
                    "beliefs": [3],
                },
                "publication_date": "2026-05-20",
                "updated_date": "2026-05-21T12:00:00Z",
                "primary_location": {
                    "landing_page_url": "https://doi.org/10.1234/forecasting",
                    "source": {"display_name": "Journal of Forecasting"},
                },
                "authorships": [{"author": {"display_name": "Ada Forecaster"}}],
                "concepts": [{"display_name": "Forecasting"}, {"display_name": "Decision theory"}],
            }
        ]
    }
    server = _serve_import_payload(json.dumps(payload))
    try:
        url = f"http://127.0.0.1:{server.server_port}/works"
        works = source_adapters.load_openalex_works(
            "forecasting calibration",
            limit=2,
            since="2026-05-01",
            api_base_url=url,
        )
        params = parse_qs(urlparse(_ImportPayloadHandler.last_path).query)
    finally:
        server.shutdown()

    assert params["search"] == ["forecasting calibration"]
    assert params["per-page"] == ["2"]
    assert params["sort"] == ["publication_date:desc"]
    assert params["filter"] == ["from_publication_date:2026-05-01"]
    assert works[0].work_id == "https://openalex.org/W123"
    assert works[0].title == "Forecasting with scholarly priors"
    assert works[0].abstract == "Forecasting calibrate systems beliefs"
    assert works[0].source_name == "Journal of Forecasting"
    assert works[0].published_at == "2026-05-20T00:00:00Z"
    assert works[0].authors == ["Ada Forecaster"]
    assert works[0].concepts == ["Forecasting", "Decision theory"]


def test_forecast_cli_openalex_import_captures_works_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_openalex_works(query: str, **kwargs):
        captured["query"] = query
        captured["kwargs"] = kwargs
        return [
            OpenAlexWork(
                work_id="https://openalex.org/W123",
                title="Forecasting with scholarly priors",
                abstract="A scholarly work about probabilistic forecasting systems.",
                url="https://doi.org/10.1234/forecasting",
                doi="https://doi.org/10.1234/forecasting",
                published_at="2026-05-20T00:00:00Z",
                updated_at="2026-05-21T12:00:00Z",
                authors=["Ada Forecaster"],
                concepts=["Forecasting", "Decision theory"],
                source_name="Journal of Forecasting",
                entry_id="https://openalex.org/W123",
                raw={"id": "https://openalex.org/W123"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_openalex_works", fake_load_openalex_works)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will OpenAlex evidence import work?",
            "--resolution-criteria",
            "Resolved yes if OpenAlex evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "openalex",
            "forecasting calibration",
            "--question",
            question_id,
            "--limit",
            "3",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 openalex evidence item(s)" in output
    assert captured["query"] == "forecasting calibration"
    assert captured["kwargs"]["limit"] == 3
    assert evidence[0].claim == "OpenAlex work: Forecasting with scholarly priors"
    assert evidence[0].summary == "A scholarly work about probabilistic forecasting systems."
    assert evidence[0].source_name == "Journal of Forecasting"
    assert evidence[0].source_type == "adapter:openalex"
    assert evidence[0].published_at == "2026-05-20T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "openalex"
    assert evidence[0].metadata["openalex_query"] == "forecasting calibration"
    assert evidence[0].metadata["openalex_work_id"] == "https://openalex.org/W123"
    assert evidence[0].metadata["doi"] == "https://doi.org/10.1234/forecasting"
    assert evidence[0].metadata["authors"] == ["Ada Forecaster"]
    assert evidence[0].metadata["concepts"] == ["Forecasting", "Decision theory"]


def test_crossref_loader_parses_works_from_api():
    payload = {
        "message": {
            "items": [
                {
                    "DOI": "10.1234/forecasting",
                    "title": ["Forecasting with DOI priors"],
                    "abstract": " A Crossref-indexed work about calibrated beliefs. ",
                    "URL": "https://doi.org/10.1234/forecasting",
                    "published-online": {"date-parts": [[2026, 5, 20]]},
                    "deposited": {"date-time": "2026-05-21T12:00:00Z"},
                    "author": [{"given": "Ada", "family": "Forecaster"}],
                    "subject": ["Forecasting", "Decision theory"],
                    "container-title": ["Journal of Forecasting"],
                    "publisher": "Forecasting Society",
                    "type": "journal-article",
                    "reference-count": 12,
                    "is-referenced-by-count": 7,
                }
            ]
        }
    }
    server = _serve_import_payload(json.dumps(payload))
    try:
        url = f"http://127.0.0.1:{server.server_port}/works"
        works = source_adapters.load_crossref_works(
            "forecasting calibration",
            limit=2,
            since="2026-05-01",
            api_base_url=url,
        )
        params = parse_qs(urlparse(_ImportPayloadHandler.last_path).query)
    finally:
        server.shutdown()

    assert params["query.bibliographic"] == ["forecasting calibration"]
    assert params["rows"] == ["2"]
    assert params["sort"] == ["published"]
    assert params["order"] == ["desc"]
    assert params["filter"] == ["from-pub-date:2026-05-01"]
    assert works[0].doi == "10.1234/forecasting"
    assert works[0].title == "Forecasting with DOI priors"
    assert works[0].abstract == "A Crossref-indexed work about calibrated beliefs."
    assert works[0].source_name == "Journal of Forecasting"
    assert works[0].published_at == "2026-05-20T00:00:00Z"
    assert works[0].updated_at == "2026-05-21T12:00:00Z"
    assert works[0].authors == ["Ada Forecaster"]
    assert works[0].subjects == ["Forecasting", "Decision theory"]
    assert works[0].reference_count == 12
    assert works[0].cited_by_count == 7


def test_forecast_cli_crossref_import_captures_works_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_crossref_works(query: str, **kwargs):
        captured["query"] = query
        captured["kwargs"] = kwargs
        return [
            CrossrefWork(
                doi="10.1234/forecasting",
                title="Forecasting with DOI priors",
                abstract="A Crossref-indexed work about probabilistic forecasting.",
                url="https://doi.org/10.1234/forecasting",
                published_at="2026-05-20T00:00:00Z",
                updated_at="2026-05-21T12:00:00Z",
                authors=["Ada Forecaster"],
                subjects=["Forecasting", "Decision theory"],
                container_title="Journal of Forecasting",
                publisher="Forecasting Society",
                work_type="journal-article",
                reference_count=12,
                cited_by_count=7,
                source_name="Journal of Forecasting",
                entry_id="10.1234/forecasting",
                raw={"DOI": "10.1234/forecasting"},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_crossref_works", fake_load_crossref_works)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Crossref evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Crossref evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "crossref",
            "forecasting calibration",
            "--question",
            question_id,
            "--limit",
            "3",
            "--api-base-url",
            "https://api.crossref.test/works",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.8",
            "--relevance",
            "0.9",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 crossref evidence item(s)" in output
    assert captured["query"] == "forecasting calibration"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["api_base_url"] == "https://api.crossref.test/works"
    assert evidence[0].claim == "Crossref work: Forecasting with DOI priors"
    assert evidence[0].summary == "A Crossref-indexed work about probabilistic forecasting."
    assert evidence[0].source_name == "Journal of Forecasting"
    assert evidence[0].source_type == "adapter:crossref"
    assert evidence[0].published_at == "2026-05-20T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.8
    assert evidence[0].relevance_rating == 0.9
    assert evidence[0].metadata["adapter"] == "crossref"
    assert evidence[0].metadata["crossref_query"] == "forecasting calibration"
    assert evidence[0].metadata["doi"] == "10.1234/forecasting"
    assert evidence[0].metadata["authors"] == ["Ada Forecaster"]
    assert evidence[0].metadata["subjects"] == ["Forecasting", "Decision theory"]
    assert evidence[0].metadata["cited_by_count"] == 7


def test_wikipedia_loader_parses_mediawiki_search_results():
    payload = {
        "query": {
            "pages": {
                "123": {
                    "pageid": 123,
                    "index": 1,
                    "title": "Forecasting",
                    "extract": " Forecasting is the process of making predictions. ",
                    "fullurl": "https://en.wikipedia.org/wiki/Forecasting",
                    "revisions": [{"timestamp": "2026-05-21T12:00:00Z"}],
                }
            }
        }
    }
    server = _serve_import_payload(json.dumps(payload))
    try:
        url = f"http://127.0.0.1:{server.server_port}/w/api.php"
        pages = source_adapters.load_wikipedia_pages(
            "forecasting",
            limit=2,
            since="2026-05-01T00:00:00Z",
            api_base_url=url,
        )
        params = parse_qs(urlparse(_ImportPayloadHandler.last_path).query)
    finally:
        server.shutdown()

    assert params["action"] == ["query"]
    assert params["generator"] == ["search"]
    assert params["gsrsearch"] == ["forecasting"]
    assert params["gsrlimit"] == ["2"]
    assert params["prop"] == ["extracts|info|revisions"]
    assert pages[0].page_id == "123"
    assert pages[0].title == "Forecasting"
    assert pages[0].extract == "Forecasting is the process of making predictions."
    assert pages[0].url == "https://en.wikipedia.org/wiki/Forecasting"
    assert pages[0].updated_at == "2026-05-21T12:00:00Z"


def test_forecast_cli_wikipedia_import_captures_pages_as_evidence(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_wikipedia_pages(query: str, **kwargs):
        captured["query"] = query
        captured["kwargs"] = kwargs
        return [
            WikipediaPage(
                page_id="123",
                title="Forecasting",
                extract="Forecasting is the process of making predictions with uncertainty.",
                url="https://en.wikipedia.org/wiki/Forecasting",
                updated_at="2026-05-21T12:00:00Z",
                source_name="Wikipedia",
                entry_id="123",
                raw={"pageid": 123},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_wikipedia_pages", fake_load_wikipedia_pages)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will Wikipedia evidence import work?",
            "--resolution-criteria",
            "Resolved yes if Wikipedia evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "wikipedia",
            "forecasting",
            "--question",
            question_id,
            "--limit",
            "3",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.7",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 wikipedia evidence item(s)" in output
    assert captured["query"] == "forecasting"
    assert captured["kwargs"]["limit"] == 3
    assert evidence[0].claim == "Wikipedia page: Forecasting"
    assert evidence[0].summary == "Forecasting is the process of making predictions with uncertainty."
    assert evidence[0].source_name == "Wikipedia"
    assert evidence[0].source_type == "adapter:wikipedia"
    assert evidence[0].published_at == "2026-05-21T12:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.7
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["adapter"] == "wikipedia"
    assert evidence[0].metadata["wikipedia_query"] == "forecasting"
    assert evidence[0].metadata["page_id"] == "123"


def test_wikimedia_pageviews_loader_parses_daily_observations(monkeypatch):
    from datetime import date

    payload = {
        "items": [
            {
                "project": "en.wikipedia.org",
                "article": "Artificial_intelligence",
                "granularity": "daily",
                "timestamp": "2026043000",
                "access": "all-access",
                "agent": "user",
                "views": 900,
            },
            {
                "project": "en.wikipedia.org",
                "article": "Artificial_intelligence",
                "granularity": "daily",
                "timestamp": "2026050100",
                "access": "all-access",
                "agent": "user",
                "views": 1234,
            },
        ]
    }
    monkeypatch.setattr(source_adapters, "_wikimedia_today_utc", lambda: date(2026, 5, 22))
    server = _serve_import_payload(json.dumps(payload))
    try:
        url = f"http://127.0.0.1:{server.server_port}/metrics/pageviews/per-article"
        observations = source_adapters.load_wikimedia_pageviews(
            "en.wikipedia.org/Artificial intelligence",
            limit=5,
            since="2026-05-01T00:00:00Z",
            api_base_url=url,
        )
        path = urlparse(_ImportPayloadHandler.last_path).path
    finally:
        server.shutdown()

    assert "/en.wikipedia.org/all-access/user/Artificial_intelligence/daily/2026050100/" in path
    assert len(observations) == 1
    assert observations[0].project == "en.wikipedia.org"
    assert observations[0].article == "Artificial_intelligence"
    assert observations[0].observation_date == "2026-05-01"
    assert observations[0].published_at == "2026-05-01T00:00:00Z"
    assert observations[0].views == 1234
    assert observations[0].entry_id == "en.wikipedia.org:Artificial_intelligence:2026-05-01"


def test_forecast_cli_wikimedia_pageviews_import_captures_observations_as_evidence(
    tmp_path,
    capsys,
    monkeypatch,
):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    captured = {}

    def fake_load_wikimedia_pageviews(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            WikimediaPageviewObservation(
                project="en.wikipedia.org",
                article="Artificial_intelligence",
                access="all-access",
                agent="user",
                granularity="daily",
                observation_date="2026-05-01",
                views=1234,
                published_at="2026-05-01T00:00:00Z",
                source_url="https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia.org/all-access/user/Artificial_intelligence/daily/2026050100/2026052200",
                source_name="Wikimedia Pageviews",
                entry_id="en.wikipedia.org:Artificial_intelligence:2026-05-01",
                raw={"views": 1234},
            )
        ]

    monkeypatch.setattr("forecasting.cli.load_wikimedia_pageviews", fake_load_wikimedia_pageviews)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will public attention evidence import work?",
            "--resolution-criteria",
            "Resolved yes if pageview evidence is imported.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "wikipediapageviews",
            "en.wikipedia.org/Artificial_intelligence",
            "--question",
            question_id,
            "--limit",
            "3",
            "--since",
            "2026-05-01T00:00:00Z",
            "--claim-type",
            "estimate",
            "--reliability",
            "0.7",
            "--relevance",
            "0.8",
        ],
    )
    output = capsys.readouterr().out
    evidence = ForecastLedger(db_path).list_evidence(question_id)

    assert "captured 1 wikipediapageviews evidence item(s)" in output
    assert captured["source"] == "en.wikipedia.org/Artificial_intelligence"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["since"] == "2026-05-01T00:00:00Z"
    assert evidence[0].claim == "Wikimedia pageviews en.wikipedia.org/Artificial_intelligence 2026-05-01: 1234"
    assert evidence[0].source_name == "Wikimedia Pageviews"
    assert evidence[0].source_type == "adapter:wikipediapageviews"
    assert evidence[0].published_at == "2026-05-01T00:00:00Z"
    assert evidence[0].claim_type == "estimate"
    assert evidence[0].reliability_rating == 0.7
    assert evidence[0].relevance_rating == 0.8
    assert evidence[0].metadata["adapter"] == "wikipediapageviews"
    assert evidence[0].metadata["project"] == "en.wikipedia.org"
    assert evidence[0].metadata["article"] == "Artificial_intelligence"
    assert evidence[0].metadata["views"] == 1234


def test_forecast_cli_lists_extension_points(capsys):
    parser = _parser()

    _run(parser, ["forecast", "plugins", "--kind", "importer"])
    output = capsys.readouterr().out

    assert "benchmark-json" in output
    assert "generic-url" in output
    assert "metaculus-question" in output
    assert "metaculus-resolved-benchmark" in output
    assert "kalshi-resolved-benchmark" in output
    assert "rss-atom-news" in output
    assert "generic-data" in output
    assert "tournament-export" in output
    assert "gdelt-doc-news" in output
    assert "github-releases" in output
    assert "github-repository-metadata" in output
    assert "github-issues" in output
    assert "github-commits" in output
    assert "coingecko-market-data" in output
    assert "federal-register-documents" in output
    assert "courtlistener-search" in output
    assert "nvd-cves" in output
    assert "openmeteo-daily-forecast" in output
    assert "openmeteo-air-quality" in output
    assert "openmeteo-historical-weather" in output
    assert "usgs-earthquakes" in output
    assert "nasa-eonet-events" in output
    assert "nws-alerts" in output
    assert "openfda-drug-applications" in output
    assert "pubmed-articles" in output
    assert "pypi-releases" in output
    assert "npm-package-versions" in output
    assert "owid-grapher" in output
    assert "who-gho-indicators" in output
    assert "fred-economic-data" in output
    assert "eia-energy-data" in output
    assert "treasury-fiscal-data" in output
    assert "bls-economic-data" in output
    assert "worldbank-indicators" in output
    assert "imf-datamapper" in output
    assert "census-data" in output
    assert "yahoo-finance-chart" in output
    assert "sec-edgar-filings" in output
    assert "sec-company-facts" in output
    assert "arxiv-papers" in output
    assert "openalex-works" in output
    assert "crossref-works" in output
    assert "reliefweb-reports" in output
    assert "wikipedia-pages" in output
    assert "wikimedia-pageviews" in output
    assert "cisa-kev" in output
    assert "hackernews-search" in output
    assert "reddit-search" in output

    _run(parser, ["forecast", "plugins", "--kind", "market"])
    market_output = capsys.readouterr().out
    assert "prediction-market" in market_output
    assert "polymarket" in market_output
    assert "kalshi" in market_output


def test_forecast_cli_sources_lists_import_commands(capsys):
    parser = _parser()

    _run(parser, ["forecast", "sources"])
    output = capsys.readouterr().out

    assert "Name" in output
    assert 'gdelt' in output
    assert 'forecast import gdelt "<query>" --question <id>' in output
    assert "fivethirtyeight:<dataset-or-url>" in output
    assert "owid:<grapher-slug>" in output
    assert "whogho:<indicator-code>" in output
    assert "fema:<state|disaster-number|query>" in output
    assert "eia:<series-id-or-api-url>" in output
    assert "treasury:<dataset-path-or-api-url>" in output
    assert "imf:<indicator>/<country>" in output
    assert "census:<dataset-path?get=...&for=...>" in output
    assert "socrata:<domain>/<dataset-id>" in output
    assert "ckan:<domain>/<query>" in output
    assert "stooq:<symbol-or-csv-url>" in output
    assert "yahoo:<symbol>" in output
    assert "coingecko:<coin-id>" in output
    assert "secfacts:<cik>/<concept>" in output
    assert "openmeteo:<lat,lon>" in output
    assert "airquality:<lat,lon>" in output
    assert "weatherhistory:<lat,lon>?start=<date>&end=<date>" in output
    assert "usgs:<query>" in output
    assert "eonet:<query-or-category>" in output
    assert "nws:<area-or-point-or-query>" in output
    assert "clinicaltrials:<query-or-NCT-id>" in output
    assert "openfda:<query-or-application-number>" in output
    assert "pubmed:<query-or-PMID>" in output
    assert "crossref:<query-or-DOI>" in output
    assert "pypi:<package>" in output
    assert "npm:<package>" in output
    assert "wikipediapageviews:<project>/<article>" in output
    assert "githubrepo:<owner/repo>" in output
    assert "githubissues:<owner/repo>" in output
    assert "githubcommits:<owner/repo>" in output
    assert "githubactions:<owner/repo>" in output
    assert "hackernews:<query>" in output
    assert "reddit:<query>" in output
    assert "bluesky:<query>" in output
    assert "mastodon:<tag-or-instance/tag>" in output
    assert "reliefweb:<query>" in output
    assert "nvd:<keyword-or-CVE>" in output
    assert "cisakev:<keyword-or-CVE-or-all>" in output
    assert "federalregister:<query>" in output
    assert "courtlistener:<query>" in output
    assert "<market>:<market-id-or-url>" in output


def test_forecast_cli_sources_json_lists_import_commands(capsys):
    parser = _parser()

    _run(parser, ["forecast", "sources", "--json"])
    payload = json.loads(capsys.readouterr().out)

    names = {source["name"] for source in payload["sources"]}
    assert {"gdelt", "fivethirtyeight", "owid", "whogho", "fema", "eia", "treasury", "imf", "census", "socrata", "ckan", "stooq", "yahoo", "coingecko", "secfacts", "openmeteo", "airquality", "weatherhistory", "usgs", "eonet", "nws", "clinicaltrials", "openfda", "pubmed", "crossref", "pypi", "npm", "wikipediapageviews", "githubrepo", "githubissues", "githubcommits", "githubactions", "hackernews", "reddit", "bluesky", "mastodon", "reliefweb", "nvd", "cisakev", "federalregister", "courtlistener", "markets"} <= names
    assert any(source["watch_prefix"] == "fivethirtyeight:<dataset-or-url>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "owid:<grapher-slug>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "whogho:<indicator-code>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "fema:<state|disaster-number|query>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "treasury:<dataset-path-or-api-url>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "imf:<indicator>/<country>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "census:<dataset-path?get=...&for=...>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "socrata:<domain>/<dataset-id>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "ckan:<domain>/<query>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "stooq:<symbol-or-csv-url>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "yahoo:<symbol>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "coingecko:<coin-id>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "secfacts:<cik>/<concept>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "airquality:<lat,lon>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "weatherhistory:<lat,lon>?start=<date>&end=<date>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "clinicaltrials:<query-or-NCT-id>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "openfda:<query-or-application-number>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "pubmed:<query-or-PMID>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "crossref:<query-or-DOI>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "pypi:<package>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "npm:<package>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "githubrepo:<owner/repo>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "githubissues:<owner/repo>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "githubcommits:<owner/repo>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "githubactions:<owner/repo>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "hackernews:<query>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "reddit:<query>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "bluesky:<query>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "mastodon:<tag-or-instance/tag>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "reliefweb:<query>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "cisakev:<keyword-or-CVE-or-all>" for source in payload["sources"])
    assert any(source["watch_prefix"] == "courtlistener:<query>" for source in payload["sources"])


def test_forecast_cli_about_exposes_fork_identity(capsys):
    parser = _parser()

    _run(parser, ["forecast", "about"])
    output = capsys.readouterr().out

    assert "Superforecasting Agent" in output
    assert "superforecasting-agent" in output
    assert "core_primitive: forecast" in output
    assert "forecasting desk that compounds judgment" in output
    assert "gateway-first messaging" in output


def test_forecast_cli_status_summarizes_operational_desk(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will operational status summarize the desk?",
            "--resolution-criteria",
            "Resolved yes if status reports core forecast-desk state.",
            "--review-cadence",
            "7d",
            "--next-review-at",
            "2026-01-02T00:00:00Z",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    ledger = ForecastLedger(db_path)
    ledger.add_assumption(question_id=question_id, text="Status should count active assumptions.")
    ledger.add_assumption(
        question_id=question_id,
        text="Status should count stale assumptions.",
        status="stale",
    )
    ledger.add_watched_source(
        scope_type="question",
        scope_ref=question_id,
        source="Manual watch note",
        source_type="manual",
    )
    ledger.create_alert(
        severity="info",
        scope_type="question",
        scope_ref=question_id,
        reason="test_status_alert",
        recommended_action=f"forecast update {question_id} --preview",
    )

    _run(parser, ["forecast", "--db", db, "status"])
    output = capsys.readouterr().out

    assert "Superforecasting Agent" in output
    assert "questions: active=1" in output
    assert "assumptions: active=1  stale=1" in output
    assert "reviews: queued=1" in output
    assert "alerts: open=1" in output
    assert "schedules=1/1" in output
    assert "learning_schedules=0" in output
    assert "watches=1/1" in output
    assert "benchmarks: builtin=4" in output

    _run(parser, ["forecast", "--db", db, "status", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["product"] == "Superforecasting Agent"
    assert payload["slug"] == "superforecasting-agent"
    assert payload["question_counts"]["active"] == 1
    assert payload["active_assumption_count"] == 1
    assert payload["stale_assumption_count"] == 1
    assert payload["review_queue_count"] == 1
    assert payload["open_alert_count"] == 1
    assert payload["enabled_scheduled_review_count"] == 1
    assert payload["scheduled_review_count"] == 1
    assert payload["learning_scheduled_review_count"] == 0
    assert payload["active_watched_source_count"] == 1
    assert payload["watched_source_count"] == 1
    assert payload["builtin_benchmark_count"] >= 4


def test_standalone_forecast_entrypoint_exposes_product_surface(capsys):
    forecast_main(["about"])
    output = capsys.readouterr().out

    assert "Superforecasting Agent" in output
    assert "primary_surface: forecast" in output


def test_forecast_cli_export_all(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will all exports include this?",
            "--resolution-criteria",
            "Resolved yes if all export includes this.",
        ],
    )
    capsys.readouterr()

    _run(parser, ["forecast", "--db", db, "export", "all", "--format", "json"])
    packet = json.loads(capsys.readouterr().out)

    assert packet["product"]["product_name"] == "Superforecasting Agent"
    assert packet["questions"][0]["question"]["title"] == "Will all exports include this?"


def test_forecast_cli_pilot_report_outputs_exit_checks(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    ledger = ForecastLedger(db)
    question = ledger.create_question(
        title="Will CLI pilot report see one loop?",
        resolution_criteria="Resolved yes if the pilot report can see the loop.",
        domain="macro",
    )
    evidence = ledger.add_evidence(
        question_id=question.id,
        source_or_note="FRED observation.",
        source_type="fred",
        available_at="2026-05-23T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.6,
        rationale="Evidence supports a modest yes probability.",
        evidence_refs=[evidence.id],
    )
    ledger.schedule_review(
        scope_type="question",
        scope_ref=question.id,
        cadence="1d",
        next_run_at="2026-05-24T09:00:00Z",
    )

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "pilot-report",
            "--min-questions",
            "1",
            "--min-structured-source-questions",
            "1",
            "--min-scores",
            "0",
            "--min-postmortems",
            "0",
            "--min-scheduled-reviews",
            "1",
        ],
    )
    output = capsys.readouterr().out

    assert "pilot pilot_exit_ready: 7/7 checks passed" in output
    assert "structured_sources=1" in output
    assert "source_types:" in output
    assert "fred: 1" in output

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "pilot-report",
            "--min-questions",
            "2",
            "--json",
        ],
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["pilot_status"] == "collecting_pilot_evidence"
    assert payload["checks"][0]["id"] == "questions_created"
    assert payload["checks"][0]["observed"] == 1
    assert payload["checks"][0]["required"] == 2
    assert payload["next_actions"]


def test_forecast_cli_pilot_cohort_seeds_live_questions(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    manifest = tmp_path / "pilot_cohort.csv"
    manifest.write_text(
        "\n".join(
            [
                "title,resolution_criteria,probability,rationale,domain,topics,watch_source,close_time",
                "Will pilot cohort A resolve yes?,Resolved yes if pilot cohort A outcome is confirmed.,0.62,Initial outside-view estimate.,macro,inflation;rates,manual cohort source,2026-06-01T00:00:00Z",
            ]
        ),
        encoding="utf-8",
    )

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "pilot-cohort",
            str(manifest),
            "--schedule-cadence",
            "1d",
            "--schedule-next-run-at",
            "2026-05-25T00:00:00Z",
        ],
    )
    output = capsys.readouterr().out
    ledger = ForecastLedger(db_path)
    questions = ledger.list_questions()
    question = questions[0]
    snapshot = ledger.get_current_snapshot(question.id)
    schedules = ledger.list_scheduled_reviews()
    watches = ledger.list_watched_sources(scope_type="question", scope_ref=question.id, status=None)

    assert "pilot_cohort seeded 1 live question(s)" in output
    assert question.title == "Will pilot cohort A resolve yes?"
    assert question.domain == "macro"
    assert question.topics == ["inflation", "rates"]
    assert question.metadata["pilot_cohort"] is True
    assert question.metadata["prospective_live_evidence"] is True
    assert snapshot is not None
    assert snapshot.forecast_origin == "live"
    assert snapshot.probability_or_distribution == 0.62
    assert snapshot.rationale == "Initial outside-view estimate."
    assert schedules[0]["scope_ref"] == question.id
    assert schedules[0]["trigger_reason"] == "pilot_cohort_review"
    assert watches[0]["source"] == "manual cohort source"
    assert watches[0]["source_type"] == "manual"


def test_forecast_cli_pilot_cohort_dry_run_json_does_not_mutate(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    manifest = tmp_path / "pilot_cohort.json"
    manifest.write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "title": "Will dry-run cohort question resolve yes?",
                        "resolution_criteria": "Resolved yes if the dry-run outcome is confirmed.",
                        "domain": "ai",
                        "topics": ["benchmarks"],
                        "probability": 0.55,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    _run(
        parser,
        [
            "forecast",
            "--db",
            str(db_path),
            "pilot-cohort",
            str(manifest),
            "--dry-run",
            "--json",
        ],
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["dry_run"] is True
    assert payload["question_count"] == 1
    assert payload["questions"][0]["title"] == "Will dry-run cohort question resolve yes?"
    assert not db_path.exists()


def test_forecast_cli_pilot_cohort_example_manifest_dry_run(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    manifest = Path(__file__).resolve().parents[2] / "examples/forecasting/live-cohort.example.csv"

    _run(
        parser,
        [
            "forecast",
            "--db",
            str(db_path),
            "pilot-cohort",
            str(manifest),
            "--dry-run",
            "--json",
        ],
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["dry_run"] is True
    assert payload["question_count"] == 5
    assert payload["initial_probability_count"] == 5
    assert not db_path.exists()
    assert {question["domain"] for question in payload["questions"]} >= {
        "software",
        "macro",
        "crypto",
        "security",
    }
    assert any(
        "githubactions:teddyjfpender/superforecasting-agent" in question["watch_sources"]
        for question in payload["questions"]
    )


def test_forecast_cli_pilot_bundle_outputs_handoff_packet(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "tester-bundle.db"
    db = str(db_path)
    ledger = ForecastLedger(db_path)
    question = ledger.create_question(
        title="Will tester bundle include this live loop?",
        resolution_criteria="Resolved yes if the bundle includes pilot and readiness evidence.",
        domain="software",
    )
    evidence = ledger.add_evidence(
        question_id=question.id,
        source_or_note="GitHub Actions run completed.",
        source_type="github_actions",
        available_at="2026-05-23T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.64,
        rationale="Structured software evidence supports yes.",
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
        summary="Bundle fixture completed one live loop.",
        lesson="Keep pilot handoff artifacts bundled.",
    )

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "pilot-bundle",
            "--min-questions",
            "1",
            "--min-structured-source-questions",
            "1",
            "--min-scores",
            "1",
            "--min-postmortems",
            "1",
            "--min-scheduled-reviews",
            "1",
            "--min-live-scores",
            "1",
            "--min-agent-protocol-cases",
            "0",
            "--include-export",
        ],
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["product"]["purpose"] == "tester_pilot_handoff_bundle"
    assert payload["pilot_report"]["pilot_status"] == "pilot_exit_ready"
    assert payload["readiness"]["evidence_status"]["score_counts"]["live"] == 1
    assert payload["export_included"] is True
    assert payload["export_packet"]["questions"][0]["question"]["id"] == question.id
    assert "not, by themselves, proof" in payload["claim_note"]

    output_path = tmp_path / ".pilot" / "pilot-bundle.json"
    _run(parser, ["forecast", "--db", db, "pilot-bundle", "--output", str(output_path)])
    output = capsys.readouterr().out
    written = json.loads(output_path.read_text(encoding="utf-8"))

    assert f"pilot_bundle wrote {output_path}" in output
    assert written["export_included"] is False
    assert written["export_packet"] is None


def test_forecast_cli_pilot_aggregate_summarizes_export_packets(tmp_path, capsys):
    parser = _parser()
    ledger = ForecastLedger(tmp_path / "tester-a.db")
    question = ledger.create_question(
        title="Will tester export aggregation count this score?",
        resolution_criteria="Resolved yes if aggregation counts the live score.",
        domain="macro",
    )
    evidence = ledger.add_evidence(
        question_id=question.id,
        source_or_note="FRED observation.",
        source_type="fred",
        available_at="2026-05-23T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.7,
        rationale="Structured evidence supports yes.",
        evidence_refs=[evidence.id],
    )
    ledger.resolve_question(
        question_id=question.id,
        outcome="yes",
        resolution_source="https://example.com/resolution",
    )
    ledger.score_question(question.id)
    ledger.create_postmortem(
        question_id=question.id,
        summary="Aggregation fixture completed one loop.",
        lesson="Keep tester export packets machine-readable.",
    )
    export_path = tmp_path / "tester-a-export.json"
    export_path.write_text(ledger.export_all(fmt="json"), encoding="utf-8")

    _run(parser, ["forecast", "pilot-aggregate", str(export_path), "--min-live-scores", "1"])
    output = capsys.readouterr().out

    assert "pilot_exports live_evidence_floor_met: 1/1 live scores" in output
    assert "questions=1" in output
    assert "structured_evidence=1" in output
    assert "fred: 1" in output
    assert "macro: 1" in output

    _run(parser, ["forecast", "pilot-aggregate", str(export_path), "--min-live-scores", "2", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["aggregate_status"] == "collecting_live_evidence"
    assert payload["summary"]["live_score_count"] == 1
    assert payload["checks"][0]["required"] == 2
    assert payload["next_actions"]
    assert "not, by themselves, proof" in payload["claim_note"]

    with pytest.raises(SystemExit):
        _run(
            parser,
            [
                "forecast",
                "pilot-aggregate",
                str(export_path),
                "--min-live-scores",
                "2",
                "--require-live-scores",
            ],
        )


def test_forecast_cli_self_check_and_alerts(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will the question need review?",
            "--resolution-criteria",
            "Resolved yes if review is due.",
            "--next-review-at",
            "2026-01-01T00:00:00Z",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(parser, ["forecast", "--db", db, "self-check", "--question", question_id])
    self_check_output = capsys.readouterr().out

    assert "created" in self_check_output
    assert "review_due" in self_check_output or "no_forecast_snapshot" in self_check_output

    _run(parser, ["forecast", "--db", db, "alerts"])
    alerts_output = capsys.readouterr().out

    assert question_id in alerts_output
    alert_id = re.search(r"(al_[a-f0-9]+)", alerts_output).group(1)

    _run(parser, ["forecast", "--db", db, "alerts", "--ack", alert_id])
    assert "acknowledged alert" in capsys.readouterr().out


def test_forecast_cli_self_check_can_scope_to_portfolio(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will alpha portfolio be reviewed?",
            "--resolution-criteria",
            "Resolved yes if alpha is reviewed.",
            "--tag",
            "portfolio:alpha",
            "--next-review-at",
            "2026-01-01T00:00:00Z",
        ],
    )
    alpha_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will beta portfolio be ignored?",
            "--resolution-criteria",
            "Resolved yes if beta is ignored.",
            "--tag",
            "portfolio:beta",
            "--next-review-at",
            "2026-01-01T00:00:00Z",
        ],
    )
    beta_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(parser, ["forecast", "--db", db, "self-check", "--portfolio", "alpha"])
    output = capsys.readouterr().out
    alert_refs = {alert.scope_ref for alert in ForecastLedger(db_path).list_alerts()}

    assert "created" in output
    assert alpha_id in alert_refs
    assert beta_id not in alert_refs


def test_forecast_cli_base_rate_model_postmortem_and_backtest(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will the application be approved?",
            "--resolution-criteria",
            "Resolved yes if the application is approved.",
            "--domain",
            "biotech",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "base-rate",
            question_id,
            "--name",
            "Comparable approvals",
            "--inclusion-criteria",
            "Same indication.",
            "--base-rate",
            "0.61",
        ],
    )
    assert "reference_class:" in capsys.readouterr().out

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "model",
            question_id,
            "--type",
            "bayesian_update",
            "--status",
            "failure",
            "--output-json",
            '{"posterior":0.7}',
        ],
    )
    model_output = capsys.readouterr().out
    assert "model_run:" in model_output
    assert "status: failure" in model_output

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "update",
            question_id,
            "--probability",
            "0.9",
            "--rationale",
            "Strong trial result.",
        ],
    )
    capsys.readouterr()
    _run(parser, ["forecast", "--db", db, "resolve", question_id, "--outcome", "no"])
    capsys.readouterr()
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "postmortem",
            question_id,
            "--lesson",
            "Check regulatory delay before high-confidence biotech forecasts.",
        ],
    )
    assert "postmortem:" in capsys.readouterr().out
    lesson_id = ForecastLedger(db).list_calibration_lessons(scope_type="domain", scope_ref="biotech")[0]["id"]

    _run(parser, ["forecast", "--db", db, "lesson", "list", "--scope-type", "domain", "--scope-ref", "biotech"])
    assert lesson_id in capsys.readouterr().out

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "lesson",
            "status",
            lesson_id,
            "--status",
            "active",
            "--confidence",
            "0.75",
        ],
    )
    lesson_output = capsys.readouterr().out
    assert "status: active" in lesson_output

    dataset = tmp_path / "cases.json"
    dataset.write_text(
        """
        {
          "cases": [
            {
              "title": "Will Y happen?",
              "resolution_criteria": "Resolved yes if Y happens.",
              "as_of": "2026-01-10T00:00:00Z",
              "probability": 0.6,
              "outcome": "yes",
              "evidence": [
                {"note": "before", "available_at": "2026-01-05T00:00:00Z"},
                {"note": "after", "available_at": "2026-01-20T00:00:00Z"}
              ],
              "baselines": [
                {"source": "crowd", "baseline_type": "crowd", "probability": 0.55}
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    _run(parser, ["forecast", "--db", db, "backtest", str(dataset)])
    backtest_output = capsys.readouterr().out

    assert "backtest_run:" in backtest_output
    assert "leakage_checks_passed: True" in backtest_output
    run_id = re.search(r"backtest_run: (bt_[a-f0-9]+)", backtest_output).group(1)
    _run(parser, ["forecast", "--db", db, "backtest", "--list"])
    assert run_id in capsys.readouterr().out
    _run(parser, ["forecast", "--db", db, "backtest", "--show", run_id])
    show_output = capsys.readouterr().out
    assert "probability_sources: dataset" in show_output
    assert "cases: 1" in show_output
    assert "agent_mean_brier: 0.160000 n=1" in show_output
    assert "crowd:crowd" in show_output
    assert "brier_improvement=0.042500" in show_output
    assert "paired_brier agent=0.160000 baseline=0.202500 edge=+0.042 ci95=- wins=1/0/0" in show_output
    assert "agent_by_domain:" in show_output
    assert "unknown mean_brier=0.160000 n=1" in show_output
    assert "agent_by_horizon:" in show_output
    _run(parser, ["forecast", "--db", db, "calibration", "--origin", "imported_baseline", "--all"])
    baseline_calibration = capsys.readouterr().out
    assert "count: 1" in baseline_calibration
    assert "mean_brier: 0.202500" in baseline_calibration
    _run(parser, ["forecast", "--db", db, "calibration", "--by-origin", "--all"])
    by_origin = capsys.readouterr().out
    assert re.search(r"origin: combined\ncount: 3", by_origin)
    assert re.search(r"origin: live\ncount: 1", by_origin)
    assert re.search(r"origin: backtest\ncount: 1", by_origin)
    assert re.search(r"origin: imported_baseline\ncount: 1", by_origin)


def test_forecast_cli_runs_builtin_benchmark_dataset(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")

    _run(parser, ["forecast", "--db", db, "backtest", "--benchmarks"])
    benchmarks_output = capsys.readouterr().out
    assert "builtin:mini-binary" in benchmarks_output
    assert "Five resolved binary replay cases" in benchmarks_output
    assert "builtin:synthetic-100-binary" in benchmarks_output
    assert "builtin:heldout-120-binary" in benchmarks_output
    assert "builtin:manifold-public-120-binary" in benchmarks_output

    _run(parser, ["forecast", "--db", db, "backtest", "builtin:mini-binary"])
    run_output = capsys.readouterr().out
    assert "cases: 5" in run_output
    assert "scored_cases: 5" in run_output
    run_id = re.search(r"backtest_run: (bt_[a-f0-9]+)", run_output).group(1)

    _run(parser, ["forecast", "--db", db, "backtest", "--show", run_id])
    show_output = capsys.readouterr().out
    assert "dataset: builtin:mini-binary" in show_output
    assert "agent_by_domain:" in show_output
    assert "agent_by_horizon:" in show_output

    _run(parser, ["forecast", "--db", db, "backtest", "builtin:synthetic-100-binary"])
    scale_output = capsys.readouterr().out
    assert "cases: 100" in scale_output
    assert "scored_cases: 100" in scale_output

    _run(parser, ["forecast", "--db", db, "backtest", "builtin:heldout-120-binary"])
    heldout_output = capsys.readouterr().out
    assert "cases: 120" in heldout_output
    assert "scored_cases: 120" in heldout_output


def test_forecast_cli_runs_builtin_benchmark_suite(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting_suite.db")
    benchmark_names = [
        "mini-binary",
        "synthetic-100-binary",
        "heldout-120-binary",
        "manifold-public-120-binary",
    ]

    monkeypatch.setattr(
        "forecasting.cli.list_builtin_benchmarks",
        lambda: [
            {"name": name, "case_count": 1, "description": f"{name} fixture"}
            for name in benchmark_names
        ],
    )

    def fake_backtest_cases(dataset: str, *, ledger=None):
        return [
            {
                "title": f"Will {dataset} replay?",
                "resolution_criteria": "Resolved yes for the all-benchmarks fixture.",
                "as_of": "2026-01-01T00:00:00Z",
                "probability": 0.6,
                "outcome": "yes",
            }
        ]

    monkeypatch.setattr("forecasting.cli._load_backtest_cases", fake_backtest_cases)

    _run(parser, ["forecast", "--db", db, "backtest", "--all-benchmarks", "--probability-source", "naive"])
    output = capsys.readouterr().out

    assert "benchmark_suite: builtin" in output
    assert "probability_source: naive" in output
    assert "builtin:mini-binary" in output
    assert "builtin:synthetic-100-binary" in output
    assert "builtin:heldout-120-binary" in output
    assert "builtin:manifold-public-120-binary" in output
    assert output.count("backtest_run=") == 4


def test_forecast_cli_runs_public_manifold_benchmark_dataset(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")

    _run(parser, ["forecast", "--db", db, "backtest", "builtin:manifold-public-120-binary"])
    manifold_output = capsys.readouterr().out
    assert "cases: 120" in manifold_output
    assert "scored_cases: 120" in manifold_output
    manifold_run_id = re.search(r"backtest_run: (bt_[a-f0-9]+)", manifold_output).group(1)

    _run(parser, ["forecast", "--db", db, "backtest", "--show", manifold_run_id])
    manifold_show_output = capsys.readouterr().out
    assert "dataset: builtin:manifold-public-120-binary" in manifold_show_output
    assert "market:manifold" in manifold_show_output
    assert "naive_0_5:auto mean_brier=0.250000 n=120 paired=120 brier_improvement=0.172650" in manifold_show_output


def test_forecast_cli_performance_summarizes_backtest_edges(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    dataset = tmp_path / "performance_cases.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "title": "Will performance case one resolve yes?",
                        "resolution_criteria": "Resolved yes for the fixture.",
                        "as_of": "2026-01-10T00:00:00Z",
                        "close_time": "2026-01-20T00:00:00Z",
                        "domain": "macro",
                        "probability": 0.7,
                        "outcome": "yes",
                        "baselines": [
                            {"source": "fixture-market", "baseline_type": "market", "probability": 0.6}
                        ],
                    },
                    {
                        "title": "Will performance case two resolve yes?",
                        "resolution_criteria": "Resolved no for the fixture.",
                        "as_of": "2026-01-10T00:00:00Z",
                        "close_time": "2026-01-20T00:00:00Z",
                        "domain": "macro",
                        "probability": 0.2,
                        "outcome": "no",
                        "baselines": [
                            {"source": "fixture-market", "baseline_type": "market", "probability": 0.4}
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    _run(parser, ["forecast", "--db", db, "backtest", str(dataset)])
    run_output = capsys.readouterr().out
    run_id = re.search(r"backtest_run: (bt_[a-f0-9]+)", run_output).group(1)

    _run(parser, ["forecast", "--db", db, "performance", "--last", "5"])
    output = capsys.readouterr().out

    assert run_id in output
    assert "AgentBrier" in output
    assert "0.065000" in output
    assert "market:fixture-market" in output
    assert "AgentEdge" in output
    assert "+0.095" in output
    assert (
        "baseline market:fixture-market brier=0.160000 paired=2 agent_edge=+0.095 "
        "paired_brier_agent=0.065000 paired_brier_baseline=0.160000 "
        "paired_edge=+0.095 ci95=[+0.046,+0.144] wins=2/0/0"
    ) in output
    assert "wins=2/0/0" in output
    assert "domains macro=0.065000 n=2" in output
    assert "horizons 8-30d=0.065000 n=2" in output
    assert "claim benchmark_replay_only: Benchmark replay evidence only" in output
    assert "evidence insufficient_live_evidence: live_scored=0 agent_protocol_scored=0" in output
    assert "gap live_scored_forecasts: 0/100" in output

    _run(parser, ["forecast", "--db", db, "performance", "--last", "5", "--json"])
    payload = json.loads(capsys.readouterr().out)
    run_summary = payload["runs"][0]
    best_baseline = run_summary["best_baseline"]
    baseline_summary = run_summary["baselines"][0]
    assert payload["run_count"] == 1
    assert run_summary["id"] == run_id
    assert best_baseline["baseline_type"] == "market"
    assert best_baseline["source"] == "fixture-market"
    assert best_baseline["agent_edge_mean_brier"] == pytest.approx(0.095)
    assert best_baseline["paired_agent_edge_ci95_low"] == pytest.approx(0.046)
    assert best_baseline["paired_agent_edge_ci95_high"] == pytest.approx(0.144)
    assert baseline_summary["paired_agent_wins"] == 2
    assert run_summary["agent_by_domain"]["macro"]["mean_brier"] == pytest.approx(0.065)
    assert run_summary["agent_by_horizon"]["8-30d"]["count"] == 2
    assert run_summary["claim_status"]["verdict"] == "benchmark_replay_only"
    assert run_summary["claim_status"]["can_claim_live_superforecasting"] is False
    assert run_summary["claim_status"]["scored_count"] == 2
    assert payload["evidence_status"]["verdict"] == "insufficient_live_evidence"
    assert payload["evidence_status"]["can_claim_live_superforecasting"] is False
    assert payload["evidence_status"]["backtests"]["positive_best_baseline_edge_run_count"] == 0
    assert payload["evidence_status"]["score_counts"]["backtest"] == 2

    _run(parser, ["forecast", "--db", db, "readiness", "--last", "5"])
    readiness_output = capsys.readouterr().out
    assert "readiness insufficient_live_evidence:" in readiness_output
    assert "claim_live_superforecasting: False" in readiness_output
    assert "evidence insufficient_live_evidence: live_scored=0 agent_protocol_scored=0" in readiness_output
    assert "ok leakage_free_backtest_runs: 1/1" in readiness_output
    assert "gap live_scored_forecasts: 0/100" in readiness_output
    assert "gap distinct_backtest_datasets: 1/2" in readiness_output
    assert "next_actions:" in readiness_output
    assert "forecast backtest <cases.json> --probability-source agent-protocol" in readiness_output

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "readiness",
            "--last",
            "5",
            "--min-live-scores",
            "7",
            "--min-agent-protocol-cases",
            "9",
            "--json",
        ],
    )
    readiness_payload = json.loads(capsys.readouterr().out)
    readiness_requirements = {
        row["id"]: row for row in readiness_payload["evidence_status"]["requirements"]
    }
    assert readiness_payload["run_count"] == 1
    assert readiness_payload["inspected_backtest_run_ids"] == [run_id]
    assert readiness_requirements["live_scored_forecasts"]["required"] == 7
    assert readiness_requirements["agent_protocol_scored_cases"]["required"] == 9
    assert "forecast postmortem <id>" in readiness_requirements["live_scored_forecasts"]["recommended_action"]
    assert readiness_payload["evidence_status"]["next_actions"][0]["requirement_id"] == "live_scored_forecasts"

    with pytest.raises(SystemExit) as exc:
        _run(parser, ["forecast", "--db", db, "readiness", "--last", "5", "--require-evidence"])
    require_output = capsys.readouterr().out
    assert exc.value.code == 1
    assert "readiness insufficient_live_evidence:" in require_output
    assert "gap live_scored_forecasts: 0/100" in require_output
    assert "next_actions:" in require_output

    _run(parser, ["forecast", "--db", db, "backtest", "--show", run_id])
    show_output = capsys.readouterr().out
    assert "paired_brier agent=0.065000 baseline=0.160000 edge=+0.095 ci95=[+0.046,+0.144] wins=2/0/0" in show_output


def test_forecast_cli_readiness_require_evidence_passes_when_evidence_gate_is_met(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    for index in (1, 2):
        dataset = tmp_path / f"readiness_gate_{index}.json"
        dataset.write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "title": f"Will readiness gate fixture {index} resolve yes?",
                            "resolution_criteria": "Resolved yes for the fixture.",
                            "as_of": "2026-01-10T00:00:00Z",
                            "close_time": "2026-01-20T00:00:00Z",
                            "domain": "macro",
                            "outcome": "yes",
                            "baselines": [
                                {"source": "fixture-market", "baseline_type": "market", "probability": 0.6}
                            ],
                            "evidence": [
                                {
                                    "note": "Pre-cutoff signal points toward yes.",
                                    "available_at": "2026-01-09T00:00:00Z",
                                    "stance": "increases",
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        _run(
            parser,
            [
                "forecast",
                "--db",
                db,
                "backtest",
                str(dataset),
                "--probability-source",
                "forecast-engine",
            ],
        )
        capsys.readouterr()

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "readiness",
            "--last",
            "5",
            "--min-live-scores",
            "0",
            "--min-agent-protocol-cases",
            "0",
            "--require-evidence",
        ],
    )
    output = capsys.readouterr().out

    assert "readiness benchmark_evidence_ready_live_claim_unproven:" in output
    assert "claim_live_superforecasting: False" in output
    assert "ok leakage_free_backtest_runs: 2/1" in output
    assert "ok positive_best_baseline_edge_runs: 2/1" in output
    assert "ok distinct_backtest_datasets: 2/2" in output


def test_baseline_ensemble_probability_source_replays_public_market_corpus():
    cases = _apply_backtest_probability_source(
        load_builtin_benchmark("builtin:manifold-public-120-binary"),
        "baseline-ensemble",
    )
    scores = [
        (case["probability"] - (1 if case["outcome"] == "yes" else 0)) ** 2
        for case in cases
    ]

    assert len(cases) == 120
    assert cases[0]["method"] == "baseline_ensemble"
    assert sum(scores) / len(scores) == pytest.approx(0.0885447)
    assert sum(scores) / len(scores) < 0.25


def test_forecast_engine_probability_source_extremizes_public_market_corpus():
    raw_cases = load_builtin_benchmark("builtin:manifold-public-120-binary")
    cases = _apply_backtest_probability_source(raw_cases, "forecast-engine")
    engine_scores = [
        (case["probability"] - (1 if case["outcome"] == "yes" else 0)) ** 2
        for case in cases
    ]
    market_scores = [
        (case["baselines"][0]["probability"] - (1 if case["outcome"] == "yes" else 0)) ** 2
        for case in raw_cases
    ]

    assert len(cases) == 120
    assert cases[0]["method"] == "forecast_engine_v0"
    assert cases[0]["component_forecasts"][0]["name"] == "market"
    assert sum(engine_scores) / len(engine_scores) == pytest.approx(0.0741509)
    assert sum(engine_scores) / len(engine_scores) < sum(market_scores) / len(market_scores)
    assert sum(engine_scores) / len(engine_scores) < 0.25


def test_agent_protocol_probability_source_uses_sanitized_case_context():
    raw_case = {
        "id": "agent-case-1",
        "title": "Will the captured agent forecast be used?",
        "resolution_criteria": "Resolved yes if the fixture says so.",
        "as_of": "2026-01-10T00:00:00Z",
        "probability": 0.99,
        "outcome": "no",
        "evidence": [
            {"note": "before cutoff", "available_at": "2026-01-05T00:00:00Z"},
            {"note": "after cutoff", "available_at": "2026-01-20T00:00:00Z"},
        ],
        "baselines": [
            {"source": "market", "baseline_type": "market", "probability": 0.6, "as_of": "2026-01-08T00:00:00Z"}
        ],
    }
    messages = build_backtest_agent_protocol_messages(raw_case)
    prompt = messages[1]["content"]
    captured_prompts = []

    def runner(messages, case, index):
        captured_prompts.append(messages[1]["content"])
        assert case["id"] == "agent-case-1"
        assert index == 0
        return {
            "probability": 0.2,
            "confidence": 0.7,
            "rationale": "Captured protocol forecast from pre-cutoff context.",
            "components": {"market": {"probability": 0.6, "weight": 1}},
            "agent_model": "fixture-model",
        }

    cases = _apply_backtest_probability_source(
        [raw_case],
        "agent-protocol",
        agent_runner=runner,
        agent_provider="fixture-provider",
    )

    assert '"probability": 0.99' not in prompt
    assert '"outcome": "no"' not in prompt
    assert "before cutoff" in prompt
    assert "after cutoff" not in prompt
    assert cases[0]["probability"] == pytest.approx(0.2)
    assert cases[0]["confidence"] == pytest.approx(0.7)
    assert cases[0]["method"] == "agent_protocol_v0"
    assert cases[0]["probability_source"] == "agent-protocol"
    assert cases[0]["agent_model"] == "fixture-model"
    assert cases[0]["ensemble_components"]["market"]["probability"] == pytest.approx(0.6)
    assert cases[0]["forecast_metadata"]["agent_provider"] == "fixture-provider"
    assert captured_prompts


def test_agent_protocol_response_parser_accepts_fenced_json():
    parsed = parse_agent_protocol_response(
        """
        Forecast:
        ```json
        {"probability": 0.42, "confidence": 0.55, "rationale": "Base rate plus evidence."}
        ```
        """
    )

    assert parsed["probability"] == pytest.approx(0.42)
    assert parsed["confidence"] == pytest.approx(0.55)
    assert parsed["rationale"] == "Base rate plus evidence."


def test_forecast_cli_backtest_can_replay_captured_agent_protocol_outputs(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    dataset = tmp_path / "agent_protocol_cases.json"
    responses = tmp_path / "agent_responses.jsonl"
    captured = tmp_path / "captured_responses.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "agent-captured-1",
                        "title": "Will captured agent replay avoid answer-side probability?",
                        "resolution_criteria": "Resolved no for this fixture.",
                        "as_of": "2026-01-10T00:00:00Z",
                        "close_time": "2026-01-20T00:00:00Z",
                        "probability": 0.95,
                        "outcome": "no",
                        "baselines": [
                            {"source": "fixture-market", "baseline_type": "market", "probability": 0.6}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    responses.write_text(
        json.dumps(
            {
                "case_id": "agent-captured-1",
                "response": {
                    "probability": 0.2,
                    "confidence": 0.8,
                    "rationale": "Captured agent forecast used only visible case data.",
                    "components": {"base_rate": {"probability": 0.25, "weight": 1}},
                    "agent_model": "fixture-agent",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "backtest",
            str(dataset),
            "--probability-source",
            "agent-protocol",
            "--agent-response-jsonl",
            str(responses),
            "--agent-output-jsonl",
            str(captured),
        ],
    )
    run_output = capsys.readouterr().out
    run_id = re.search(r"backtest_run: (bt_[a-f0-9]+)", run_output).group(1)

    ledger = ForecastLedger(db_path)
    run = ledger.get_backtest_run(run_id)
    case = ledger.list_backtest_cases(run_id)[0]
    snapshot = ledger.get_snapshot(case["generated_forecast_id"])

    assert run["result_summary"]["probability_sources"] == ["agent-protocol"]
    assert snapshot.probability_or_distribution == pytest.approx(0.2)
    assert snapshot.confidence == pytest.approx(0.8)
    assert snapshot.method == "agent_protocol_v0"
    assert snapshot.agent_model == "fixture-agent"
    assert snapshot.metadata["probability_source"] == "agent-protocol"
    assert snapshot.ensemble_components["base_rate"]["probability"] == pytest.approx(0.25)
    captured_rows = [json.loads(line) for line in captured.read_text(encoding="utf-8").splitlines()]
    assert captured_rows[0]["case_id"] == "agent-captured-1"
    assert captured_rows[0]["response"]["probability"] == pytest.approx(0.2)

    _run(parser, ["forecast", "--db", db, "backtest", "--show", run_id])
    show_output = capsys.readouterr().out
    assert "probability_sources: agent-protocol" in show_output
    assert "agent_mean_brier: 0.040000 n=1" in show_output
    assert "market:fixture-market" in show_output
    assert "source=agent-protocol method=agent_protocol_v0 model=fixture-agent" in show_output

    _run(parser, ["forecast", "--db", db, "performance", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["runs"][0]["claim_status"]["evidence_type"] == "agent_protocol_time_aware_backtest_replay"
    assert payload["runs"][0]["claim_status"]["probability_sources"] == ["agent-protocol"]
    assert payload["runs"][0]["claim_status"]["can_claim_live_superforecasting"] is False
    assert payload["evidence_status"]["backtests"]["agent_protocol_scored_count"] == 1
    assert "agent_protocol_scored_cases" in payload["evidence_status"]["gaps"]


def test_forecast_cli_imports_csv_benchmark_dataset_and_replays_it(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    dataset = tmp_path / "resolved_cases.csv"
    dataset.write_text(
        "\n".join(
            [
                (
                    "id,title,resolution_criteria,as_of,probability,outcome,"
                    "baseline_probability,baseline_type,baseline_source,evidence_note,evidence_available_at"
                ),
                (
                    "case-1,Will CSV benchmark import replay?,"
                    "Resolved yes if CSV benchmark import can be replayed.,"
                    "2026-01-10T00:00:00Z,0.7,yes,0.55,crowd,csv-crowd,"
                    "Evidence available before replay,2026-01-05T00:00:00Z"
                ),
            ]
        ),
        encoding="utf-8",
    )

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "benchmark",
            str(dataset),
            "--name",
            "resolved-fixture",
            "--description",
            "CSV resolved fixture.",
        ],
    )
    import_output = capsys.readouterr().out
    dataset_id = re.search(r"imported benchmark dataset (bd_[a-f0-9]+)", import_output).group(1)
    assert "cases: 1" in import_output

    _run(parser, ["forecast", "--db", db, "backtest", "--benchmarks"])
    benchmarks_output = capsys.readouterr().out
    assert f"imported:{dataset_id}" in benchmarks_output
    assert "CSV resolved fixture." in benchmarks_output

    _run(parser, ["forecast", "--db", db, "backtest", f"imported:{dataset_id}"])
    run_output = capsys.readouterr().out
    assert "cases: 1" in run_output
    assert "scored_cases: 1" in run_output
    run_id = re.search(r"backtest_run: (bt_[a-f0-9]+)", run_output).group(1)

    _run(parser, ["forecast", "--db", db, "backtest", "--show", run_id])
    show_output = capsys.readouterr().out
    assert f"dataset: imported:{dataset_id}" in show_output
    assert "crowd:csv-crowd" in show_output


def test_forecast_cli_imports_tournament_export_as_benchmark(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    dataset = tmp_path / "tournament_export.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "tournament-1",
                        "title": "Will generic tournament import replay?",
                        "resolution_criteria": "Resolved yes if tournament imports are replayable.",
                        "simulated_forecast_time": "2026-01-10T00:00:00Z",
                        "probability": 0.7,
                        "outcome": "yes",
                        "baselines": [
                            {
                                "source": "tournament-crowd",
                                "baseline_type": "crowd",
                                "probability": 0.6,
                                "as_of": "2026-01-10T00:00:00Z",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "import",
            "tournament",
            str(dataset),
            "--name",
            "generic-tournament",
            "--description",
            "Generic tournament export.",
        ],
    )
    import_output = capsys.readouterr().out
    dataset_id = re.search(r"imported tournament benchmark dataset (bd_[a-f0-9]+)", import_output).group(1)
    assert "cases: 1" in import_output

    ledger = ForecastLedger(db)
    imported = ledger.get_benchmark_dataset(f"imported:{dataset_id}")
    assert imported["metadata"]["adapter"] == "tournament"

    _run(parser, ["forecast", "--db", db, "backtest", f"imported:{dataset_id}"])
    run_output = capsys.readouterr().out
    assert "cases: 1" in run_output
    assert "scored_cases: 1" in run_output


def test_forecast_cli_backtest_replays_url_json_benchmark_dataset(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    server = _serve_import_payload(
        json.dumps(
            {
                "cases": [
                    {
                        "title": "Will URL benchmark replay?",
                        "resolution_criteria": "Resolved yes if URL benchmark replay works.",
                        "as_of": "2026-01-10T00:00:00Z",
                        "probability": 0.63,
                        "outcome": "yes",
                    }
                ]
            }
        )
    )
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/cases.json"
        _run(parser, ["forecast", "--db", db, "backtest", url])
    finally:
        server.shutdown()
    output = capsys.readouterr().out

    assert "cases: 1" in output
    assert "scored_cases: 1" in output


def test_forecast_cli_imports_manifold_resolved_benchmark_dataset(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    server = _serve_import_payload(
        json.dumps(
            [
                {
                    "id": "mkt-yes",
                    "slug": "will-fixture-one-resolve-yes",
                    "question": "Will fixture one resolve yes?",
                    "textDescription": "Resolves YES in this benchmark fixture.",
                    "url": "https://manifold.markets/test/will-fixture-one-resolve-yes",
                    "outcomeType": "BINARY",
                    "probability": 0.72,
                    "closeTime": 1777593600000,
                    "lastBetTime": 1777507200000,
                    "resolutionTime": 1777680000000,
                    "isResolved": True,
                    "resolution": "YES",
                },
                {
                    "id": "mkt-no",
                    "slug": "will-fixture-two-resolve-no",
                    "question": "Will fixture two resolve no?",
                    "textDescription": "Resolves NO in this benchmark fixture.",
                    "url": "https://manifold.markets/test/will-fixture-two-resolve-no",
                    "outcomeType": "BINARY",
                    "probability": 0.2,
                    "closeTime": 1777593600000,
                    "lastBetTime": 1777507200000,
                    "resolutionTime": 1777680000000,
                    "isResolved": True,
                    "resolution": "NO",
                },
                {
                    "id": "mkt-cancel",
                    "slug": "will-cancelled-market-be-skipped",
                    "question": "Will cancelled market be skipped?",
                    "outcomeType": "BINARY",
                    "probability": 0.5,
                    "lastBetTime": 1777507200000,
                    "isResolved": True,
                    "resolution": "CANCEL",
                },
            ]
        )
    )
    try:
        api_base = f"http://127.0.0.1:{server.server_address[1]}/v0"
        _run(
            parser,
            [
                "forecast",
                "--db",
                db,
                "import",
                "benchmark",
                "manifold:resolved",
                "--api-base-url",
                api_base,
                "--limit",
                "10",
                "--name",
                "manifold-fixture",
            ],
        )
    finally:
        server.shutdown()
    import_output = capsys.readouterr().out
    dataset_id = re.search(r"imported benchmark dataset (bd_[a-f0-9]+)", import_output).group(1)

    assert "name: manifold-fixture" in import_output
    assert "cases: 2" in import_output

    _run(parser, ["forecast", "--db", db, "backtest", f"imported:{dataset_id}"])
    run_output = capsys.readouterr().out
    run_id = re.search(r"backtest_run: (bt_[a-f0-9]+)", run_output).group(1)

    assert "cases: 2" in run_output
    assert "scored_cases: 0" in run_output
    assert "leakage_checks_passed: True" in run_output

    _run(parser, ["forecast", "--db", db, "backtest", "--show", run_id])
    show_output = capsys.readouterr().out

    assert "dataset: imported:" in show_output
    assert "agent_mean_brier: - n=0" in show_output
    assert "market:manifold mean_brier=0.059200 n=2" in show_output


def test_forecast_cli_imports_metaculus_resolved_benchmark_dataset(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    server = _serve_import_payload(
        json.dumps(
            {
                "results": [
                    {
                        "id": 1001,
                        "title": "Will Metaculus fixture one resolve yes?",
                        "description": "Resolves YES in this benchmark fixture.",
                        "resolution_criteria": "Resolved yes if Metaculus admins mark fixture one as yes.",
                        "type": "binary",
                        "community_prediction": {"full": {"q2": 0.7}},
                        "close_time": "2026-05-01T00:00:00Z",
                        "last_prediction_time": "2026-04-30T00:00:00Z",
                        "scheduled_resolve_time": "2026-05-02T00:00:00Z",
                        "resolution": "yes",
                        "status": "resolved",
                    },
                    {
                        "id": 1002,
                        "title": "Will Metaculus fixture two resolve no?",
                        "description": "Resolves NO in this benchmark fixture.",
                        "resolution_criteria": "Resolved yes if Metaculus admins mark fixture two as yes.",
                        "type": "binary",
                        "community_prediction": 0.25,
                        "close_time": "2026-05-01T00:00:00Z",
                        "last_prediction_time": "2026-04-30T00:00:00Z",
                        "scheduled_resolve_time": "2026-05-02T00:00:00Z",
                        "resolution": "no",
                        "status": "resolved",
                    },
                    {
                        "id": 1003,
                        "title": "Will ambiguous Metaculus fixture be skipped?",
                        "type": "binary",
                        "community_prediction": 0.5,
                        "last_prediction_time": "2026-04-30T00:00:00Z",
                        "resolution": "ambiguous",
                    },
                ]
            }
        )
    )
    try:
        api_base = f"http://127.0.0.1:{server.server_address[1]}/api"
        _run(
            parser,
            [
                "forecast",
                "--db",
                db,
                "import",
                "benchmark",
                "metaculus:resolved",
                "--api-base-url",
                api_base,
                "--limit",
                "10",
                "--name",
                "metaculus-fixture",
            ],
        )
    finally:
        server.shutdown()
    import_output = capsys.readouterr().out
    dataset_id = re.search(r"imported benchmark dataset (bd_[a-f0-9]+)", import_output).group(1)

    assert "name: metaculus-fixture" in import_output
    assert "cases: 2" in import_output

    _run(parser, ["forecast", "--db", db, "backtest", f"imported:{dataset_id}"])
    run_output = capsys.readouterr().out
    run_id = re.search(r"backtest_run: (bt_[a-f0-9]+)", run_output).group(1)

    assert "cases: 2" in run_output
    assert "scored_cases: 0" in run_output
    assert "leakage_checks_passed: True" in run_output

    _run(parser, ["forecast", "--db", db, "backtest", "--show", run_id])
    show_output = capsys.readouterr().out

    assert "dataset: imported:" in show_output
    assert "agent_mean_brier: - n=0" in show_output
    assert "crowd:metaculus mean_brier=0.076250 n=2" in show_output
    assert "paired=0" in show_output


def test_forecast_cli_imports_kalshi_resolved_benchmark_dataset(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    server = _serve_import_payload(
        json.dumps(
            {
                "markets": [
                    {
                        "ticker": "KXTESTYES",
                        "event_ticker": "KXTEST",
                        "title": "Will Kalshi fixture one resolve yes?",
                        "rules_primary": "Resolves YES in this benchmark fixture.",
                        "status": "settled",
                        "previous_price_dollars": "0.6400",
                        "close_time": "2026-05-01T00:00:00Z",
                        "settlement_ts": "2026-05-02T00:00:00Z",
                        "settlement_value_dollars": "1.0000",
                    },
                    {
                        "ticker": "KXTESTNO",
                        "event_ticker": "KXTEST",
                        "title": "Will Kalshi fixture two resolve no?",
                        "rules_primary": "Resolves NO in this benchmark fixture.",
                        "status": "settled",
                        "previous_yes_bid_dollars": "0.2800",
                        "previous_yes_ask_dollars": "0.3200",
                        "close_time": "2026-05-01T00:00:00Z",
                        "settlement_ts": "2026-05-02T00:00:00Z",
                        "settlement_value_dollars": "0.0000",
                    },
                    {
                        "ticker": "KXTESTSCALAR",
                        "event_ticker": "KXTEST",
                        "title": "Will scalar Kalshi fixture be skipped?",
                        "status": "settled",
                        "previous_price_dollars": "0.5000",
                        "close_time": "2026-05-01T00:00:00Z",
                        "settlement_ts": "2026-05-02T00:00:00Z",
                        "settlement_value_dollars": "0.5600",
                    },
                ]
            }
        )
    )
    try:
        api_base = f"http://127.0.0.1:{server.server_address[1]}/trade-api/v2"
        _run(
            parser,
            [
                "forecast",
                "--db",
                db,
                "import",
                "benchmark",
                "kalshi:resolved",
                "--api-base-url",
                api_base,
                "--limit",
                "10",
                "--name",
                "kalshi-fixture",
            ],
        )
    finally:
        server.shutdown()
    import_output = capsys.readouterr().out
    dataset_id = re.search(r"imported benchmark dataset (bd_[a-f0-9]+)", import_output).group(1)

    assert "name: kalshi-fixture" in import_output
    assert "cases: 2" in import_output

    _run(parser, ["forecast", "--db", db, "backtest", f"imported:{dataset_id}"])
    run_output = capsys.readouterr().out
    run_id = re.search(r"backtest_run: (bt_[a-f0-9]+)", run_output).group(1)

    assert "cases: 2" in run_output
    assert "scored_cases: 0" in run_output
    assert "leakage_checks_passed: True" in run_output

    _run(parser, ["forecast", "--db", db, "backtest", "--show", run_id])
    show_output = capsys.readouterr().out

    assert "dataset: imported:" in show_output
    assert "agent_mean_brier: - n=0" in show_output
    assert "market:kalshi mean_brier=0.109800 n=2" in show_output
    assert "paired=0" in show_output


def test_forecast_cli_errors_show_recommended_adjustments(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will errors show adjustments?",
            "--resolution-criteria",
            "Resolved yes if errors output includes adjustments.",
            "--domain",
            "macro",
            "--topic",
            "inflation",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "update",
            question_id,
            "--probability",
            "0.9",
            "--rationale",
            "High confidence forecast.",
        ],
    )
    capsys.readouterr()
    _run(parser, ["forecast", "--db", db, "resolve", question_id, "--outcome", "no"])
    capsys.readouterr()
    _run(parser, ["forecast", "--db", db, "score", question_id])
    capsys.readouterr()

    _run(parser, ["forecast", "--db", db, "errors", "--domain", "macro", "--topic", "inflation"])
    output = capsys.readouterr().out

    assert "elevated_mean_brier" in output
    assert "adjustments=Review postmortems before increasing confidence" in output
    assert "macro:inflation" in output


def test_forecast_cli_default_dashboard_and_schedule_run(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)

    _run(parser, ["forecast", "--db", db])
    dashboard_output = capsys.readouterr().out
    assert "SUPERFORECASTING DESK" in dashboard_output
    assert "ACTIVE FORECASTS" in dashboard_output

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will a review be due?",
            "--resolution-criteria",
            "Resolved yes if a review becomes due.",
            "--domain",
            "ops",
            "--next-review-at",
            "2026-01-01T00:00:00Z",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    ledger = ForecastLedger(db_path)
    ledger.create_snapshot(
        question_id=question_id,
        probability_or_distribution=0.5,
        confidence=0.7,
        rationale="Dashboard forecast.",
    )
    ledger.add_assumption(question_id=question_id, text="Review will remain due.")
    ledger.self_check(question_id=question_id, now="2026-01-03T00:00:00Z")

    _run(parser, ["forecast", "--db", db])
    refreshed_dashboard = capsys.readouterr().out
    assert "Conf" in refreshed_dashboard
    assert "Assump" in refreshed_dashboard
    assert "Alerts" in refreshed_dashboard
    assert "0.70" in refreshed_dashboard
    assert "review_due" in refreshed_dashboard

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "schedule",
            "add",
            "--question",
            question_id,
            "--cadence",
            "1d",
            "--next-run-at",
            "2026-01-02T00:00:00Z",
        ],
    )
    capsys.readouterr()

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "schedule",
            "run",
            "--now",
            "2026-01-03T00:00:00Z",
        ],
    )
    output = capsys.readouterr().out

    assert "ran 1 scheduled review(s)" in output
    assert "created" in output
    assert question_id in output
    assert "review_due" in output


def test_forecast_cli_new_with_review_cadence_creates_schedule(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will cadence create a schedule?",
            "--resolution-criteria",
            "Resolved yes if cadence creates a scheduled review.",
            "--review-cadence",
            "2d",
            "--next-review-at",
            "2026-01-02T00:00:00Z",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(parser, ["forecast", "--db", db, "schedule", "list"])
    output = capsys.readouterr().out

    assert question_id in output
    assert "2d" in output


def test_forecast_cli_watch_add_list_and_check(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    source = tmp_path / "source.txt"
    source.write_text("initial", encoding="utf-8")

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI source change?",
            "--resolution-criteria",
            "Resolved yes if watched CLI source changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            str(source),
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    _run(parser, ["forecast", "--db", db, "watch", "list", "--question", question_id])
    list_output = capsys.readouterr().out
    assert watch_id in list_output
    assert "question:" in list_output

    source.write_text("changed", encoding="utf-8")
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_rss_sources(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    feed = tmp_path / "feed.xml"
    feed.write_text(
        """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Forecast Feed</title>
<item><guid>item-1</guid><title>Initial item</title><pubDate>Fri, 01 May 2026 00:00:00 GMT</pubDate></item>
</channel></rss>
""",
        encoding="utf-8",
    )

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI feed change?",
            "--resolution-criteria",
            "Resolved yes if watched feed changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            f"rss:{feed}",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: rss" in add_output

    feed.write_text(
        """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Forecast Feed</title>
<item><guid>item-2</guid><title>New item</title><pubDate>Sat, 02 May 2026 00:00:00 GMT</pubDate></item>
</channel></rss>
""",
        encoding="utf-8",
    )
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_gdelt_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    titles = ["Initial GDELT article"]

    def fake_load_gdelt_articles(query: str, **kwargs):
        return [
            GdeltArticle(
                title=titles[0],
                summary="",
                url=None,
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI GDELT search change?",
            "--resolution-criteria",
            "Resolved yes if watched GDELT search changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "gdelt:policy bill",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: gdelt" in add_output

    titles[0] = "New GDELT article"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_githubissues_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    states = ["open"]

    def fake_load_github_issues(source: str, **kwargs):
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
                url=None,
                html_url=None,
                source_name="GitHub",
                entry_id="acme/desk#42",
                raw={"state": states[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_github_issues", fake_load_github_issues)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI GitHub issues change?",
            "--resolution-criteria",
            "Resolved yes if watched GitHub issues change.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "githubissues:acme/desk",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: githubissues" in add_output

    states[0] = "closed"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_githubrepo_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    stars = [1234]

    def fake_load_github_repository_snapshots(source: str, **kwargs):
        return [
            GitHubRepositorySnapshot(
                repo="acme/desk",
                repo_id="456",
                owner_login="acme",
                description="Forecasting desk repository.",
                language="Python",
                default_branch="main",
                visibility="public",
                license_spdx_id="MIT",
                topics=["forecasting", "agents"],
                archived=False,
                disabled=False,
                fork=False,
                stargazers_count=stars[0],
                watchers_count=stars[0],
                forks_count=56,
                open_issues_count=7,
                subscribers_count=89,
                network_count=60,
                created_at="2024-01-01T00:00:00Z",
                updated_at="2026-05-21T11:00:00Z",
                pushed_at="2026-05-20T10:00:00Z",
                url=None,
                html_url=None,
                source_name="GitHub",
                entry_id="R_456",
                raw={"stars": stars[0]},
            )
        ]

    monkeypatch.setattr(
        "forecasting.source_adapters.load_github_repository_snapshots",
        fake_load_github_repository_snapshots,
    )
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI GitHub repository metadata change?",
            "--resolution-criteria",
            "Resolved yes if watched GitHub repository metadata changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "githubrepo:acme/desk",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: githubrepo" in add_output

    stars[0] = 1235
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_githubcommits_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    messages = ["Initial forecast commit"]

    def fake_load_github_commits(source: str, **kwargs):
        return [
            GitHubCommit(
                repo="acme/desk",
                sha=f"{len(messages[0]):040x}",
                short_sha=f"{len(messages[0]):07x}",
                message=messages[0],
                author_name="Ada Analyst",
                author_login="ada",
                authored_at="2026-05-20T10:00:00Z",
                committed_at="2026-05-21T11:00:00Z",
                comments=0,
                url=None,
                html_url=None,
                source_name="GitHub",
                entry_id=f"acme/desk@{len(messages[0]):040x}",
                raw={"message": messages[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_github_commits", fake_load_github_commits)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI GitHub commits change?",
            "--resolution-criteria",
            "Resolved yes if watched GitHub commits change.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "githubcommits:acme/desk",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: githubcommits" in add_output

    messages[0] = "New forecast commit"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_githubactions_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    conclusions = ["success"]

    def fake_load_github_workflow_runs(source: str, **kwargs):
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
                workflow_url=None,
                actor_login="ada",
                triggering_actor_login="ci-bot",
                run_started_at="2026-05-21T10:30:00Z",
                created_at="2026-05-21T10:00:00Z",
                updated_at="2026-05-21T11:00:00Z",
                url=None,
                html_url=None,
                source_name="GitHub",
                entry_id="acme/desk/actions/runs/987",
                raw={"conclusion": conclusions[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_github_workflow_runs", fake_load_github_workflow_runs)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI GitHub Actions change?",
            "--resolution-criteria",
            "Resolved yes if watched GitHub Actions runs change.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "githubactions:acme/desk",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: githubactions" in add_output

    conclusions[0] = "failure"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_coingecko_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    prices = [109500]

    def fake_load_coingecko_snapshots(source: str, **kwargs):
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI CoinGecko data change?",
            "--resolution-criteria",
            "Resolved yes if watched CoinGecko snapshots change.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "coingecko:bitcoin",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: coingecko" in add_output

    prices[0] = 111000
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_usgs_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    magnitudes = [5.7]

    def fake_load_usgs_earthquakes(source: str, **kwargs):
        return [
            UsgsEarthquakeEvent(
                event_id="us7000abcd",
                title=f"M {magnitudes[0]} - Testville",
                url=None,
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI USGS search change?",
            "--resolution-criteria",
            "Resolved yes if watched USGS search changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "usgs:minmagnitude=5",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: usgs" in add_output

    magnitudes[0] = 6.1
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_eonet_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    titles = ["Wildfire near Test Ridge"]

    def fake_load_nasa_eonet_events(source: str, **kwargs):
        return [
            NasaEonetEvent(
                event_id="EONET_123",
                title=titles[0],
                description="A public hazard event.",
                url=None,
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI EONET search change?",
            "--resolution-criteria",
            "Resolved yes if watched EONET search changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "eonet:category=wildfires&status=open",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: eonet" in add_output

    titles[0] = "Updated wildfire near Test Ridge"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_nws_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    severities = ["Moderate"]

    def fake_load_nws_alerts(source: str, **kwargs):
        return [
            NwsAlert(
                alert_id="urn:oid:alert-1",
                event="Flood Warning",
                headline=f"Flood Warning severity {severities[0]}",
                description="Flooding is possible.",
                instruction="Avoid flooded roads.",
                url=None,
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI NWS alerts change?",
            "--resolution-criteria",
            "Resolved yes if watched NWS alerts change.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "nws:area=CA&event=Flood Warning",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: nws" in add_output

    severities[0] = "Severe"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_clinicaltrials_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    statuses = ["RECRUITING"]

    def fake_load_clinicaltrials_studies(source: str, **kwargs):
        return [
            ClinicalTrialStudy(
                nct_id="NCT01234567",
                brief_title=f"Trial status {statuses[0]}",
                official_title=None,
                url=None,
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI ClinicalTrials.gov studies change?",
            "--resolution-criteria",
            "Resolved yes if watched ClinicalTrials.gov studies change.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "clinicaltrials:NCT01234567",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: clinicaltrials" in add_output

    statuses[0] = "ACTIVE_NOT_RECRUITING"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_openfda_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    statuses = ["AP"]

    def fake_load_openfda_drug_applications(source: str, **kwargs):
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
                url=None,
                source_name="openFDA Drugs@FDA",
                entry_id="BLA125514",
                raw={"status": statuses[0]},
            )
        ]

    monkeypatch.setattr(
        "forecasting.source_adapters.load_openfda_drug_applications",
        fake_load_openfda_drug_applications,
    )
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI openFDA applications change?",
            "--resolution-criteria",
            "Resolved yes if watched openFDA application evidence changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "openfda:BLA125514",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: openfda" in add_output

    statuses[0] = "TA"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_pubmed_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    titles = ["Initial PubMed article"]

    def fake_load_pubmed_articles(source: str, **kwargs):
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI PubMed articles change?",
            "--resolution-criteria",
            "Resolved yes if watched PubMed article evidence changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "pubmed:forecasting calibration",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: pubmed" in add_output

    titles[0] = "New PubMed article"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_who_gho_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    values = [77.4]

    def fake_load_who_gho_observations(source: str, **kwargs):
        return [
            WhoGhoObservation(
                indicator=source,
                spatial_dim="USA",
                time_dim="2025",
                dim1="BTSX",
                dim2=None,
                dim3=None,
                value=values[0],
                numeric_value=values[0],
                low=75.0,
                high=79.0,
                published_at="2025-01-01T00:00:00Z",
                source_url=f"https://ghoapi.azureedge.net/api/{source}",
                source_name="WHO Global Health Observatory",
                entry_id=f"{source}:USA:2025",
                raw={"value": values[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_who_gho_observations", fake_load_who_gho_observations)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI WHO GHO observations change?",
            "--resolution-criteria",
            "Resolved yes if watched WHO GHO evidence changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "whogho:WHOSIS_000001",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: whogho" in add_output

    values[0] = 78.1
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_fema_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    disaster_numbers = [5001]

    def fake_load_fema_disaster_declarations(source: str, **kwargs):
        return [
            FemaDisasterDeclaration(
                disaster_number=disaster_numbers[0],
                declaration_string=f"DR-{disaster_numbers[0]}-CA",
                state="CA",
                declaration_type="DR",
                declaration_date="2025-01-03T00:00:00Z",
                fiscal_year=2025,
                incident_type="Fire",
                title="California Wildfires",
                designated_area="Los Angeles County",
                incident_begin_date="2025-01-01T00:00:00Z",
                incident_end_date=None,
                individual_assistance=True,
                public_assistance=False,
                hazard_mitigation=True,
                last_refresh="2025-01-04T00:00:00Z",
                source_url="https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries",
                source_name="FEMA Disaster Declarations Summaries",
                entry_id=f"declaration-{disaster_numbers[0]}",
                raw={"disasterNumber": disaster_numbers[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_fema_disaster_declarations", fake_load_fema_disaster_declarations)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI FEMA declarations change?",
            "--resolution-criteria",
            "Resolved yes if watched FEMA evidence changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "fema:state=CA&incidentType=Fire",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: fema" in add_output

    disaster_numbers[0] = 5002
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_pypi_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    versions = ["1.2.3"]

    def fake_load_pypi_releases(source: str, **kwargs):
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI PyPI releases change?",
            "--resolution-criteria",
            "Resolved yes if watched PyPI release evidence changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "pypi:forecast-desk",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: pypi" in add_output

    versions[0] = "1.2.4"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_npm_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    versions = ["2.0.0"]

    def fake_load_npm_versions(source: str, **kwargs):
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI npm versions change?",
            "--resolution-criteria",
            "Resolved yes if watched npm package evidence changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "npm:@forecast/desk",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: npm" in add_output

    versions[0] = "2.1.0"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_fred_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    values = [4.1]

    def fake_load_fred_observations(series_id: str, **kwargs):
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI FRED series change?",
            "--resolution-criteria",
            "Resolved yes if watched FRED series changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "fred:UNRATE",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: fred" in add_output

    values[0] = 4.2
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_wikimedia_pageview_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    views = [1234]

    def fake_load_wikimedia_pageviews(source: str, **kwargs):
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched pageviews change?",
            "--resolution-criteria",
            "Resolved yes if watched Wikimedia pageviews change.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "wikipediapageviews:en.wikipedia.org/Artificial_intelligence",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: wikipediapageviews" in add_output

    views[0] = 2345
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_bls_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    values = [4.1]

    def fake_load_bls_observations(series_id: str, **kwargs):
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI BLS series change?",
            "--resolution-criteria",
            "Resolved yes if watched BLS series changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "bls:LNS14000000",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: bls" in add_output

    values[0] = 4.2
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_worldbank_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    values = [28_000_000_000_000.0]

    def fake_load_worldbank_observations(source: str, **kwargs):
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI World Bank series change?",
            "--resolution-criteria",
            "Resolved yes if watched World Bank series changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "worldbank:USA/NY.GDP.MKTP.CD",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: worldbank" in add_output

    values[0] = 30_000_000_000_000.0
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_imf_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    values = [1.8]

    def fake_load_imf_observations(source: str, **kwargs):
        return [
            ImfDataMapperObservation(
                indicator="NGDP_RPCH",
                indicator_name="Real GDP growth",
                country="USA",
                country_name="United States",
                observation_date="2025-12-31",
                value=values[0],
                published_at="2025-12-31T00:00:00Z",
                source_url="https://www.imf.org/external/datamapper/NGDP_RPCH@WEO/USA",
                source_name="IMF DataMapper",
                entry_id="NGDP_RPCH:USA:2025",
                raw={"year": "2025", "value": str(values[0])},
            )
        ]

    monkeypatch.setattr(
        "forecasting.source_adapters.load_imf_datamapper_observations",
        fake_load_imf_observations,
    )
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI IMF series change?",
            "--resolution-criteria",
            "Resolved yes if watched IMF series changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "imf:NGDP_RPCH/USA",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: imf" in add_output

    values[0] = 2.1
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_census_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    values = [39_100_000.0]

    def fake_load_census_records(source: str, **kwargs):
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI Census series change?",
            "--resolution-criteria",
            "Resolved yes if watched Census records change.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "census:2023/acs/acs5?get=NAME,B01003_001E&for=state:*",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: census" in add_output

    values[0] = 39_200_000.0
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_socrata_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    cases = ["42"]

    def fake_load_socrata_records(source: str, **kwargs):
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI Socrata rows change?",
            "--resolution-criteria",
            "Resolved yes if watched Socrata records change.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "socrata:data.cdc.gov/abcd-1234?county=King",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: socrata" in add_output

    cases[0] = "43"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_ckan_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    modified_at = ["2026-05-22T11:30:00Z"]

    def fake_load_ckan_datasets(source: str, **kwargs):
        return [
            CkanDataset(
                portal="data.gov",
                package_id="pkg-1",
                name="electricity-demand",
                title="Electricity demand",
                notes="Hourly grid demand.",
                url=None,
                organization="Energy Department",
                groups=["energy"],
                tags=["grid"],
                license_title="Creative Commons",
                metadata_created="2026-05-20T10:00:00Z",
                metadata_modified=modified_at[0],
                resources=[{"id": "res-1", "format": "CSV"}],
                source_url="https://data.gov/dataset/electricity-demand",
                source_name="CKAN:data.gov",
                entry_id="data.gov:electricity-demand",
                raw={"metadata_modified": modified_at[0]},
            )
        ]

    monkeypatch.setattr("forecasting.source_adapters.load_ckan_datasets", fake_load_ckan_datasets)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI CKAN packages change?",
            "--resolution-criteria",
            "Resolved yes if watched CKAN packages change.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "ckan:data.gov/energy",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: ckan" in add_output

    modified_at[0] = "2026-05-23T11:30:00Z"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_accepts_current_source_type_choices(capsys, monkeypatch):
    parser = _parser()
    captured = {}

    class DummyLedger:
        def add_watched_source(self, **kwargs):
            captured.update(kwargs)
            return {
                "id": "ws_test",
                "scope_type": kwargs["scope_type"],
                "scope_ref": kwargs["scope_ref"],
                "source": kwargs["source"],
                "source_type": kwargs["source_type"],
                "status": "active",
            }

    monkeypatch.setattr("forecasting.cli._ledger", lambda args: DummyLedger())

    _run(
        parser,
        [
            "forecast",
            "watch",
            "add",
            "placeholder source",
            "--question",
            "fq_test",
            "--source-type",
            "ckan",
        ],
    )
    output = capsys.readouterr().out

    assert captured["source_type"] == "ckan"
    assert "source_type: ckan" in output


def test_forecast_cli_watch_add_supports_stooq_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    close_prices = [198.4]

    def fake_load_stooq_prices(source: str, **kwargs):
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI Stooq price change?",
            "--resolution-criteria",
            "Resolved yes if watched Stooq price changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "stooq:AAPL.US",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: stooq" in add_output

    close_prices[0] = 201.2
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_yahoo_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI Yahoo Finance price change?",
            "--resolution-criteria",
            "Resolved yes if watched Yahoo Finance price changes.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "yahoo:AAPL",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: yahoo" in add_output

    close_prices[0] = 201.2
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_sec_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    forms = ["10-Q"]

    def fake_load_sec_filings(source: str, **kwargs):
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI SEC filings change?",
            "--resolution-criteria",
            "Resolved yes if watched SEC filings change.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "sec:0000320193",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: sec" in add_output

    forms[0] = "8-K"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_watch_add_supports_arxiv_sources(tmp_path, capsys, monkeypatch):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")
    titles = ["Initial forecasting paper"]

    def fake_load_arxiv_papers(query: str, **kwargs):
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
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will watched CLI arXiv papers change?",
            "--resolution-criteria",
            "Resolved yes if watched arXiv papers change.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "watch",
            "add",
            "arxiv:cat:cs.AI AND forecasting",
            "--question",
            question_id,
        ],
    )
    add_output = capsys.readouterr().out
    watch_id = re.search(r"watched source (ws_[a-f0-9]+)", add_output).group(1)

    assert "source_type: arxiv" in add_output

    titles[0] = "New forecasting paper"
    _run(parser, ["forecast", "--db", db, "watch", "check", "--question", question_id])
    check_output = capsys.readouterr().out

    assert "created 1 alert(s)" in check_output
    assert f"watched_source_changed:{watch_id}" in check_output


def test_forecast_cli_schedule_add_accepts_domain_topic_scope(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will domain topic scope be checked?",
            "--resolution-criteria",
            "Resolved yes if scoped schedule creates an alert.",
            "--domain",
            "biotech",
            "--topic",
            "regulatory",
            "--next-review-at",
            "2026-01-01T00:00:00Z",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "schedule",
            "add",
            "--domain",
            "biotech",
            "--topic",
            "regulatory",
            "--cadence",
            "1d",
            "--next-run-at",
            "2026-01-02T00:00:00Z",
        ],
    )
    capsys.readouterr()
    _run(parser, ["forecast", "--db", db, "schedule", "list"])
    assert "domain:biotech/regulatory" in capsys.readouterr().out

    _run(parser, ["forecast", "--db", db, "schedule", "run", "--now", "2026-01-03T00:00:00Z"])
    output = capsys.readouterr().out
    assert question_id in output
    assert "review_due" in output
    assert question_id in {alert.scope_ref for alert in ForecastLedger(db_path).list_alerts()}


def test_forecast_cli_review_and_schedule_can_scope_by_horizon(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    ledger = ForecastLedger(db_path)
    short_horizon = ledger.create_question(
        title="Will CLI short horizon be reviewed?",
        resolution_criteria="Resolved yes if horizon filters include this.",
        close_time="2026-01-25T00:00:00Z",
    )
    long_horizon = ledger.create_question(
        title="Will CLI long horizon be ignored?",
        resolution_criteria="Resolved yes if horizon filters exclude this.",
        close_time="2026-06-01T00:00:00Z",
    )
    for question in (short_horizon, long_horizon):
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.5,
            rationale="Initial forecast.",
            as_of="2026-01-01T00:00:00Z",
        )

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "review",
            "--stale",
            "--last",
            "7",
            "--horizon",
            "30",
            "--now",
            "2026-01-10T00:00:00Z",
        ],
    )
    review_output = capsys.readouterr().out
    assert short_horizon.id in review_output
    assert long_horizon.id not in review_output

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "schedule",
            "add",
            "--horizon",
            "30",
            "--cadence",
            "1d",
            "--next-run-at",
            "2026-01-02T00:00:00Z",
            "--stale-days",
            "3",
        ],
    )
    capsys.readouterr()
    _run(parser, ["forecast", "--db", db, "schedule", "list"])
    assert "horizon:30" in capsys.readouterr().out
    assert ForecastLedger(db_path).list_scheduled_reviews()[0]["stale_days"] == 3


def test_forecast_cli_schedule_add_can_enable_scoped_learning(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will scoped scheduled learning work?",
            "--resolution-criteria",
            "Resolved yes if schedule run updates scoped learning records.",
            "--domain",
            "macro",
            "--topic",
            "inflation",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "update",
            question_id,
            "--probability",
            "0.9",
            "--rationale",
            "High-confidence forecast that should miss.",
        ],
    )
    capsys.readouterr()
    _run(parser, ["forecast", "--db", db, "resolve", question_id, "--outcome", "no"])
    capsys.readouterr()
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "schedule",
            "add",
            "--domain",
            "macro",
            "--topic",
            "inflation",
            "--cadence",
            "1d",
            "--next-run-at",
            "2026-01-02T00:00:00Z",
            "--auto-score",
            "--auto-postmortem",
        ],
    )
    capsys.readouterr()
    _run(parser, ["forecast", "--db", db, "schedule", "list"])
    schedule_output = capsys.readouterr().out
    assert "domain:macro/inflation" in schedule_output
    assert "score,postmortem" in schedule_output

    _run(parser, ["forecast", "--db", db, "schedule", "run", "--due", "--now", "2026-01-03T00:00:00Z"])
    run_output = capsys.readouterr().out

    assert "scores_created: 1" in run_output
    assert "postmortems_created: 1" in run_output
    assert "learning_reviews:" in run_output
    assert "score_created:" in run_output
    assert "postmortem_created:" in run_output
    ledger = ForecastLedger(db_path)
    assert ledger.list_calibration_lessons(scope_type="domain", scope_ref="macro")
    assert ledger.list_domain_error_profiles(domain="macro", topic="inflation")[0]["sample_count"] == 1


def test_forecast_cli_self_check_auto_scores_and_postmortems_resolved_question(tmp_path, capsys):
    parser = _parser()
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will auto-score work?",
            "--resolution-criteria",
            "Resolved yes if auto-score records a score.",
        ],
    )
    question_id = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "update",
            question_id,
            "--probability",
            "0.7",
            "--rationale",
            "Initial forecast.",
        ],
    )
    capsys.readouterr()
    _run(parser, ["forecast", "--db", db, "resolve", question_id, "--outcome", "yes"])
    capsys.readouterr()

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "self-check",
            "--question",
            question_id,
            "--auto-score",
            "--auto-postmortem",
        ],
    )
    output = capsys.readouterr().out

    assert "score_created:" in output
    assert "postmortem_created:" in output
    ledger = ForecastLedger(db_path)
    assert ledger.list_scores()[0].question_id == question_id
    assert ledger.list_postmortems(question_id=question_id)[0]["question_id"] == question_id


def test_forecast_cli_correction_and_resolver_policy(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "forecasting.db")

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "resolver",
            "trust",
            "--plugin",
            "official-results",
            "--plugin-version",
            "1.0.0",
            "--scope-type",
            "domain",
            "--scope-ref",
            "elections",
            "--enabled",
        ],
    )
    assert "trusted_resolver_policy:" in capsys.readouterr().out

    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "correction",
            "add",
            "--target-type",
            "calibration_lesson",
            "--target-id",
            "cl_manual",
            "--reason",
            "Lesson was too broad.",
            "--patch-json",
            '{"status":"retired"}',
        ],
    )
    output = capsys.readouterr().out

    assert "correction:" in output
    assert "affected_lessons: 1" in output
    _run(parser, ["forecast", "--db", db, "correction", "list", "--target-type", "calibration_lesson"])
    list_output = capsys.readouterr().out
    assert "calibration_lesson:cl_manual" in list_output


def test_forecast_cli_installs_no_agent_cron_bridge(tmp_path, capsys, monkeypatch):
    parser = _parser()
    hermes_home = tmp_path / "home"
    db_path = tmp_path / "pilot.db"
    token = set_hermes_home_override(hermes_home)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    sys.modules.pop("cron.jobs", None)
    try:
        _run(
            parser,
            [
                "forecast",
                "--db",
                str(db_path),
                "schedule",
                "install-cron",
                "--schedule",
                "every 1d",
                "--name",
                "Forecast checks",
                "--auto-score",
                "--auto-postmortem",
            ],
        )
    finally:
        reset_hermes_home_override(token)

    output = capsys.readouterr().out
    jobs = json.loads((hermes_home / "cron" / "jobs.json").read_text(encoding="utf-8"))["jobs"]

    assert "cron_job:" in output
    script = hermes_home / "scripts" / "forecast_self_check.py"
    assert script.exists()
    assert "--db" in script.read_text(encoding="utf-8")
    assert str(db_path) in script.read_text(encoding="utf-8")
    assert "--auto-score" in script.read_text(encoding="utf-8")
    assert "--auto-postmortem" in script.read_text(encoding="utf-8")
    assert jobs[0]["name"] == "Forecast checks"
    assert jobs[0]["script"] == "forecast_self_check.py"
    assert jobs[0]["no_agent"] is True
