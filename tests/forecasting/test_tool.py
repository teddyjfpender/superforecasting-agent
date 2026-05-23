from __future__ import annotations

import json
from pathlib import Path

import pytest

from forecasting import ForecastLedger
from forecasting.source_adapters import (
    CisaKevVulnerability,
    ClinicalTrialStudy,
    EiaObservation,
    HackerNewsItem,
    GitHubIssue,
    NasaEonetEvent,
    NwsAlert,
    OpenFdaDrugApplication,
    RedditPost,
    StooqPriceObservation,
    TreasuryRecord,
    UsgsEarthquakeEvent,
    WikimediaPageviewObservation,
)
from hermes_cli.tools_config import _get_platform_tools
from model_tools import get_tool_definitions
from tools.forecasting_tool import FORECAST_LEDGER_SCHEMA, forecast_ledger_tool
from tools.registry import discover_builtin_tools, registry
from toolsets import get_toolset, resolve_toolset, validate_toolset


def test_forecasting_toolset_is_discoverable():
    discover_builtin_tools()

    assert registry.get_entry("forecast_ledger") is not None
    assert "forecast_ledger" in resolve_toolset("forecasting")


def test_cli_default_toolsets_are_forecast_desk_scoped():
    enabled = _get_platform_tools({}, "cli", include_default_mcp_servers=False)

    assert "forecasting" in enabled
    assert "web" in enabled
    assert "browser" in enabled
    assert "terminal" in enabled
    assert "file" in enabled
    assert "code_execution" in enabled
    assert "cronjob" in enabled
    assert "memory" not in enabled
    assert "skills" not in enabled
    assert "image_gen" not in enabled
    assert "delegation" not in enabled

    tool_names = {
        tool["function"]["name"]
        for tool in get_tool_definitions(enabled_toolsets=sorted(enabled), quiet_mode=True)
    }
    assert "forecast_ledger" in tool_names
    assert "memory" not in tool_names
    assert "skill_manage" not in tool_names
    assert "image_generate" not in tool_names
    assert "delegate_task" not in tool_names


def test_fork_native_toolset_aliases_resolve_inherited_presets():
    alias_pairs = {
        "forecast-cli": "hermes-cli",
        "forecast-acp": "hermes-acp",
        "forecast-api-server": "hermes-api-server",
        "forecast-cron": "hermes-cron",
        "forecast-gateway": "hermes-gateway",
    }

    for alias, inherited in alias_pairs.items():
        assert validate_toolset(alias)
        assert get_toolset(alias) is not None
        assert resolve_toolset(alias) == resolve_toolset(inherited)


def test_forecast_ledger_tool_watch_source_type_schema_is_current():
    source_types = set(
        FORECAST_LEDGER_SCHEMA["parameters"]["properties"]["source_type"]["enum"]
    )

    assert {"github", "githubissues", "hackernews", "reddit", "federalregister", "nvd", "cisakev", "openmeteo", "usgs", "eonet", "nws", "clinicaltrials", "openfda", "owid", "eia", "treasury", "stooq", "wikipedia", "wikipediapageviews"} <= source_types


def test_forecast_ledger_tool_lifecycle(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool lifecycle work?",
                "resolution_criteria": "Resolved yes if the tool can score a forecast.",
            }
        )
    )
    question_id = created["question"]["id"]
    evidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_evidence",
                "question_id": question_id,
                "source_or_note": "Initial evidence note.",
                "available_at": "2026-01-01T00:00:00Z",
            }
        )
    )
    updated = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_forecast",
                "question_id": question_id,
                "probability": 0.7,
                "rationale": "Evidence supports yes.",
                "as_of": "2026-01-02T00:00:00Z",
                "evidence_refs": [evidence["evidence"]["id"]],
            }
        )
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "resolve",
            "question_id": question_id,
            "outcome": "yes",
        }
    )
    score = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "score",
                "question_id": question_id,
            }
        )
    )

    assert updated["forecast_snapshot"]["forecast_id"]
    assert score["score"]["brier_score"] == 0.09000000000000002
    assert ForecastLedger(db).get_question(question_id).current_forecast_id == updated["forecast_snapshot"]["forecast_id"]


def test_forecast_ledger_tool_can_require_update_citations(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool citation policy work?",
                "resolution_criteria": "Resolved yes if the agent tool can enforce citations.",
            }
        )
    )
    question_id = created["question"]["id"]
    uncited = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_forecast",
                "question_id": question_id,
                "probability": 0.5,
                "rationale": "Uncited factual claim.",
                "require_citations": True,
            }
        )
    )
    evidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_evidence",
                "question_id": question_id,
                "source_or_note": "Tool-cited evidence.",
                "available_at": "2026-01-01T00:00:00Z",
            }
        )
    )
    cited = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_forecast",
                "question_id": question_id,
                "probability": 0.55,
                "rationale": "Tool-cited evidence supports the update.",
                "as_of": "2026-01-02T00:00:00Z",
                "evidence_refs": [evidence["evidence"]["id"]],
                "require_citations": True,
            }
        )
    )

    assert uncited["success"] is False
    assert "requires citations" in uncited["error"]
    assert cited["forecast_snapshot"]["evidence_refs"] == [evidence["evidence"]["id"]]
    assert cited["forecast_snapshot"]["metadata"]["citation_policy"] == "required"


def test_forecast_ledger_tool_stores_resolution_provenance(tmp_path):
    db = str(tmp_path / "forecasting.db")
    source = tmp_path / "resolution.txt"
    source.write_text("official result: no", encoding="utf-8")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool resolution provenance persist?",
                "resolution_criteria": "Resolved no if provenance fields are stored.",
            }
        )
    )
    question_id = created["question"]["id"]

    resolved = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "resolve",
                "question_id": question_id,
                "outcome": "no",
                "resolution_source": str(source),
                "resolver_type": "source_adapter",
                "resolution_status": "confirmed",
                "criteria_satisfied": True,
                "confidence": 0.82,
                "confirmed_by": "official-results-adapter",
                "resolver_notes": "Matched the published outcome.",
                "scoreable": False,
            }
        )
    )

    resolution = resolved["resolution"]
    assert resolution["outcome"] == "no"
    assert resolution["resolution_source"] == str(source)
    assert resolution["resolution_source_snapshot_ref"]
    assert Path(resolution["resolution_source_snapshot_ref"]).exists()
    assert resolution["resolver_type"] == "source_adapter"
    assert resolution["resolution_status"] == "confirmed"
    assert resolution["criteria_satisfied"] is True
    assert resolution["confidence"] == pytest.approx(0.82)
    assert resolution["confirmed_by"] == "official-results-adapter"
    assert resolution["resolver_notes"] == "Matched the published outcome."
    assert resolution["scoreable"] is False


def test_forecast_ledger_tool_records_structured_postmortem_learning(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool postmortems preserve learning fields?",
                "resolution_criteria": "Resolved no if structured postmortems are persisted.",
                "domain": "macro",
            }
        )
    )
    question_id = created["question"]["id"]
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.82,
            "rationale": "Inside-view signal looked strong.",
        }
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "resolve",
            "question_id": question_id,
            "outcome": "no",
        }
    )

    result = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "postmortem",
                "question_id": question_id,
                "summary": "Overweighted a policy signal.",
                "what_happened": "The policy did not pass.",
                "what_was_expected": "Expected a high chance of passage.",
                "missed_evidence": "Committee calendar delays.",
                "overweighted_evidence": "Sponsor statements.",
                "base_rate_error": "Ignored prior committee failure rates.",
                "inside_view_error": "Treated rhetoric as commitment.",
                "resolution_error": "No resolution ambiguity.",
                "lesson": "Discount sponsor rhetoric when calendar evidence is weak.",
                "calibration_adjustment": {"probability_delta": -0.04},
            }
        )
    )

    postmortem = result["postmortem"]
    lessons = ForecastLedger(db).list_calibration_lessons(scope_type="domain", scope_ref="macro")
    assert postmortem["summary"] == "Overweighted a policy signal."
    assert postmortem["what_happened"] == "The policy did not pass."
    assert postmortem["what_was_expected"] == "Expected a high chance of passage."
    assert postmortem["missed_evidence"] == "Committee calendar delays."
    assert postmortem["overweighted_evidence"] == "Sponsor statements."
    assert postmortem["base_rate_error"] == "Ignored prior committee failure rates."
    assert postmortem["inside_view_error"] == "Treated rhetoric as commitment."
    assert postmortem["resolution_error"] == "No resolution ambiguity."
    assert postmortem["lesson"] == "Discount sponsor rhetoric when calendar evidence is weak."
    assert postmortem["calibration_adjustment"] == {"probability_delta": -0.04}
    assert lessons[0]["source_postmortem_refs"] == [postmortem["id"]]
    assert lessons[0]["recommended_adjustment"] == {"probability_delta": -0.04}


def test_forecast_ledger_tool_creates_questions_with_forecast_metadata(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool metadata persist?",
                "description": "Question metadata should survive tool creation.",
                "resolution_criteria": "Resolved yes if metadata is stored.",
                "resolution_source": "official filing",
                "domain": "macro",
                "topics": ["rates", "inflation"],
                "tags": ["portfolio:global-macro"],
                "owner": "research",
                "impact": "high",
                "outcome_type": "numeric",
                "choices": [],
                "units": "percent",
                "bounds": [0, 10],
                "close_time": "2026-06-01T00:00:00Z",
                "resolution_time": "2026-07-01T00:00:00Z",
                "review_cadence": "3d",
                "next_review_at": "2026-05-01T00:00:00Z",
            }
        )
    )

    ledger = ForecastLedger(db)
    question = ledger.get_question(created["question"]["id"])
    schedules = ledger.list_scheduled_reviews()

    assert question.description == "Question metadata should survive tool creation."
    assert question.resolution_source == "official filing"
    assert question.domain == "macro"
    assert question.topics == ["rates", "inflation"]
    assert question.tags == ["portfolio:global-macro"]
    assert question.owner == "research"
    assert question.impact == "high"
    assert question.outcome_space.type == "numeric"
    assert question.outcome_space.units == "percent"
    assert question.outcome_space.bounds == [0, 10]
    assert question.close_time == "2026-06-01T00:00:00Z"
    assert question.resolution_time == "2026-07-01T00:00:00Z"
    assert schedules[0]["scope_ref"] == question.id
    assert schedules[0]["cadence"] == "3d"


def test_forecast_ledger_tool_show_question_returns_research_context(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will show question include context?",
                "resolution_criteria": "Resolved yes if agent context includes research artifacts.",
                "domain": "macro",
            }
        )
    )
    question_id = created["question"]["id"]
    evidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_evidence",
                "question_id": question_id,
                "source_or_note": "Context evidence.",
            }
        )
    )["evidence"]
    assumption = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_assumption",
                "question_id": question_id,
                "text": "Indicator remains comparable.",
            }
        )
    )["assumption"]
    reference = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_reference_class",
                "question_id": question_id,
                "name": "Comparable macro releases",
                "inclusion_criteria": "Same country and indicator family.",
                "base_rate": 0.48,
            }
        )
    )["reference_class"]
    model = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "record_model_run",
                "question_id": question_id,
                "model_type": "sensitivity",
                "output": {"probability": 0.57},
            }
        )
    )["model_run"]
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.57,
            "rationale": "Context update.",
            "evidence_refs": [evidence["id"]],
            "assumption_refs": [assumption["id"]],
            "reference_class_refs": [reference["id"]],
            "model_run_refs": [model["id"]],
        }
    )
    forecast_ledger_tool({"db": db, "action": "resolve", "question_id": question_id, "outcome": "yes"})
    score = json.loads(forecast_ledger_tool({"db": db, "action": "score", "question_id": question_id}))["score"]
    postmortem = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "postmortem",
                "question_id": question_id,
                "summary": "Context postmortem.",
            }
        )
    )["postmortem"]

    shown = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "show_question",
                "question_id": question_id,
            }
        )
    )

    assert shown["question"]["id"] == question_id
    assert shown["current_forecast"]["evidence_refs"] == [evidence["id"]]
    assert shown["forecast_history"][0]["forecast_id"] == shown["current_forecast"]["forecast_id"]
    assert shown["evidence"][0]["id"] == evidence["id"]
    assert shown["assumptions"][0]["id"] == assumption["id"]
    assert shown["reference_classes"][0]["id"] == reference["id"]
    assert model["id"] in {row["id"] for row in shown["model_runs"]}
    assert shown["scores"][0]["id"] == score["id"]
    assert shown["postmortems"][0]["id"] == postmortem["id"]


def test_forecast_ledger_tool_manages_baseline_comparisons(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool baselines be comparable?",
                "resolution_criteria": "Resolved yes if agent baselines are stored.",
            }
        )
    )
    question_id = created["question"]["id"]
    added = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_baseline_comparison",
                "question_id": question_id,
                "source": "market-fixture",
                "baseline_type": "market",
                "probability_or_distribution": 0.63,
                "as_of": "2026-01-01T00:00:00Z",
                "metadata": {"market_id": "fixture-1"},
            }
        )
    )
    listed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_baseline_comparisons",
                "question_id": question_id,
            }
        )
    )
    shown = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "show_question",
                "question_id": question_id,
            }
        )
    )

    assert added["baseline_comparison"]["baseline_type"] == "market"
    assert listed["baseline_comparisons"][0]["source"] == "market-fixture"
    assert listed["baseline_comparisons"][0]["probability_or_distribution"] == pytest.approx(0.63)
    assert listed["baseline_comparisons"][0]["metadata"] == {"market_id": "fixture-1"}
    assert shown["baseline_comparisons"][0]["id"] == added["baseline_comparison"]["id"]


def test_forecast_ledger_tool_adds_strict_evidence_metadata(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool evidence metadata persist?",
                "resolution_criteria": "Resolved yes if strict source metadata is stored.",
            }
        )
    )
    question_id = created["question"]["id"]

    result = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_evidence",
                "question_id": question_id,
                "source_or_note": "https://example.com/report",
                "source_url": "https://example.com/report",
                "source_name": "Example Research",
                "source_type": "url",
                "published_at": "2026-01-01T12:00:00Z",
                "available_at": "2026-01-02T00:00:00Z",
                "claim": "The report supports the forecast.",
                "claim_type": "estimate",
                "summary": "A timestamped source summary.",
                "reliability_rating": 0.83,
                "relevance_rating": 0.76,
                "stance": "supports",
                "admissible_for_backtests": False,
                "metadata": {"source_snapshot_id": "snap-1"},
            }
        )
    )

    evidence = result["evidence"]
    assert evidence["source_url"] == "https://example.com/report"
    assert evidence["source_name"] == "Example Research"
    assert evidence["source_type"] == "url"
    assert evidence["published_at"] == "2026-01-01T12:00:00Z"
    assert evidence["available_at"] == "2026-01-02T00:00:00Z"
    assert evidence["claim_type"] == "estimate"
    assert evidence["reliability_rating"] == pytest.approx(0.83)
    assert evidence["relevance_rating"] == pytest.approx(0.76)
    assert evidence["stance"] == "supports"
    assert evidence["admissible_for_backtests"] is False
    assert evidence["metadata"]["source_snapshot_id"] == "snap-1"


def test_forecast_ledger_tool_manages_assumptions(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool assumptions persist?",
                "resolution_criteria": "Resolved yes if assumptions can be managed.",
            }
        )
    )
    question_id = created["question"]["id"]
    evidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_evidence",
                "question_id": question_id,
                "source_or_note": "Assumption source.",
            }
        )
    )
    added = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_assumption",
                "question_id": question_id,
                "text": "Policy conditions remain unchanged.",
                "check_cadence": "7d",
                "evidence_refs": [evidence["evidence"]["id"]],
                "notes": "Initial assumption.",
            }
        )
    )
    assumption_id = added["assumption"]["id"]
    listed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_assumptions",
                "question_id": question_id,
            }
        )
    )
    updated = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_assumption",
                "assumption_id": assumption_id,
                "status": "invalidated",
                "last_checked_at": "2026-01-05T00:00:00Z",
                "notes": "Policy changed.",
            }
        )
    )

    assert listed["assumptions"][0]["id"] == assumption_id
    assert listed["assumptions"][0]["check_cadence"] == "7d"
    assert listed["assumptions"][0]["evidence_refs"] == [evidence["evidence"]["id"]]
    assert updated["assumption"]["status"] == "invalidated"
    assert updated["assumption"]["last_checked_at"] == "2026-01-05T00:00:00Z"
    assert updated["assumption"]["invalidated_at"] is not None
    assert updated["assumption"]["notes"] == "Policy changed."


def test_forecast_ledger_tool_checks_watched_sources(tmp_path):
    db = str(tmp_path / "forecasting.db")
    source = tmp_path / "source.txt"
    source.write_text("initial", encoding="utf-8")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool watches detect changes?",
                "resolution_criteria": "Resolved yes if tool watch alerts are created.",
            }
        )
    )
    question_id = created["question"]["id"]
    watch = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_watched_source",
                "question_id": question_id,
                "source": str(source),
            }
        )
    )

    source.write_text("changed", encoding="utf-8")
    checked = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "check_watched_sources",
                "scope_type": "question",
                "scope_ref": question_id,
            }
        )
    )

    assert watch["watched_source"]["source_type"] == "file"
    assert checked["alerts"][0]["reason"] == f"watched_source_changed:{watch['watched_source']['id']}"


def test_forecast_ledger_tool_can_save_ensemble_components(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool ensemble updates work?",
                "resolution_criteria": "Resolved yes if tool ensemble components are stored.",
            }
        )
    )
    question_id = created["question"]["id"]

    updated = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_forecast",
                "question_id": question_id,
                "components": {
                    "base_rate": {"probability": 0.4, "weight": 2},
                    "inside_view": {"probability": 0.7, "weight": 1},
                },
                "rationale": "Tool-saved ensemble update.",
                "method": "weighted_ensemble",
            }
        )
    )

    snapshot = ForecastLedger(db).get_snapshot(updated["forecast_snapshot"]["forecast_id"])
    assert snapshot.probability_or_distribution == 0.5
    assert snapshot.ensemble_components["base_rate"]["weight"] == 2
    assert snapshot.method == "weighted_ensemble"


def test_forecast_ledger_tool_records_model_run_provenance(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool model provenance persist?",
                "resolution_criteria": "Resolved yes if model run provenance is stored.",
            }
        )
    )
    question_id = created["question"]["id"]

    result = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "record_model_run",
                "question_id": question_id,
                "model_type": "bayesian_update",
                "inputs": {"prior": 0.45},
                "parameters": {"likelihood_ratio": 1.4},
                "output": {"posterior": 0.53},
                "diagnostics": {"sensitivity": "medium"},
                "code_ref": "models/bayes.py@abc123",
                "artifact_paths": ["artifacts/run-1.json"],
                "model_version": "bayes-v2",
                "prompt_version": "decomp-v1",
                "data_version": "evidence-cut-2026-01-01",
                "evidence_cutoff": "2026-01-01T00:00:00Z",
            }
        )
    )

    model_run = result["model_run"]
    assert model_run["model_type"] == "bayesian_update"
    assert model_run["inputs"] == {"prior": 0.45}
    assert model_run["parameters"] == {"likelihood_ratio": 1.4}
    assert model_run["output"] == {"posterior": 0.53}
    assert model_run["diagnostics"] == {"sensitivity": "medium"}
    assert model_run["code_ref"] == "models/bayes.py@abc123"
    assert model_run["artifact_paths"] == ["artifacts/run-1.json"]
    assert model_run["model_version"] == "bayes-v2"
    assert model_run["prompt_version"] == "decomp-v1"
    assert model_run["data_version"] == "evidence-cut-2026-01-01"
    assert model_run["evidence_cutoff"] == "2026-01-01T00:00:00Z"


def test_forecast_ledger_tool_lists_model_runs_and_postmortems(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool learning artifacts be inspectable?",
                "resolution_criteria": "Resolved no if model runs and postmortems can be listed.",
            }
        )
    )
    question_id = created["question"]["id"]
    forecast_ledger_tool(
        {
            "db": db,
            "action": "record_model_run",
            "question_id": question_id,
            "model_type": "reference_class",
            "output": {"base_rate": 0.4},
        }
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.7,
            "rationale": "Model run pushed probability higher.",
        }
    )
    forecast_ledger_tool({"db": db, "action": "resolve", "question_id": question_id, "outcome": "no"})
    created_postmortem = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "postmortem",
                "question_id": question_id,
                "summary": "The base-rate comparison was too loose.",
                "lesson": "Tighten reference classes before moving above 0.6.",
            }
        )
    )["postmortem"]

    model_runs = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_model_runs",
                "question_id": question_id,
            }
        )
    )
    postmortems = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_postmortems",
                "question_id": question_id,
            }
        )
    )

    assert model_runs["model_runs"][0]["model_type"] == "reference_class"
    assert model_runs["model_runs"][0]["output"] == {"base_rate": 0.4}
    assert postmortems["postmortems"][0]["id"] == created_postmortem["id"]
    assert postmortems["postmortems"][0]["summary"] == "The base-rate comparison was too loose."
    assert postmortems["postmortems"][0]["lesson"] == "Tighten reference classes before moving above 0.6."


def test_forecast_ledger_tool_exports_audit_packets(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool exports include audit data?",
                "resolution_criteria": "Resolved yes if export packets are available to agents.",
                "domain": "macro",
            }
        )
    )
    question_id = created["question"]["id"]
    evidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_evidence",
                "question_id": question_id,
                "source_or_note": "Export evidence note.",
                "claim": "A relevant indicator moved.",
            }
        )
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.61,
            "rationale": "Evidence nudged the forecast.",
            "evidence_refs": [evidence["evidence"]["id"]],
        }
    )

    question_packet = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "export_question",
                "question_id": question_id,
                "format": "json",
            }
        )
    )
    markdown_packet = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "export_question",
                "question_id": question_id,
                "format": "markdown",
            }
        )
    )
    portfolio_packet = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "export_all",
                "format": "json",
            }
        )
    )

    assert question_packet["packet"]["question"]["id"] == question_id
    assert question_packet["packet"]["forecast_history"][0]["evidence_refs"] == [evidence["evidence"]["id"]]
    assert question_packet["packet"]["evidence"][0]["claim"] == "A relevant indicator moved."
    assert markdown_packet["export"].startswith("# Forecast Packet:")
    assert portfolio_packet["packet"]["questions"][0]["question"]["id"] == question_id


def test_forecast_ledger_tool_returns_pilot_report(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool pilot report summarize artifacts?",
                "resolution_criteria": "Resolved yes if tool reports pilot checks.",
                "domain": "macro",
            }
        )
    )
    question_id = created["question"]["id"]
    evidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_evidence",
                "question_id": question_id,
                "source_or_note": "Structured source row.",
                "source_type": "fred",
            }
        )
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.55,
            "rationale": "Structured evidence is enough for the pilot report.",
            "evidence_refs": [evidence["evidence"]["id"]],
        }
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "schedule_review",
            "question_id": question_id,
            "cadence": "1d",
            "next_run_at": "2026-05-24T09:00:00Z",
        }
    )

    report = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "pilot_report",
                "min_questions": 1,
                "min_structured_source_questions": 1,
                "min_scores": 0,
                "min_postmortems": 0,
                "min_scheduled_reviews": 1,
            }
        )
    )

    assert report["pilot_report"]["pilot_status"] == "pilot_exit_ready"
    assert report["pilot_report"]["summary"]["questions_with_structured_sources"] == 1
    assert report["pilot_report"]["source_types"]["fred"] == 1


def test_forecast_ledger_tool_records_corrections_and_invalidates_learning(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool corrections invalidate learning?",
                "resolution_criteria": "Resolved no if applied corrections mark dependent learning invalid.",
                "domain": "policy",
            }
        )
    )
    question_id = created["question"]["id"]
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.8,
            "rationale": "Wrong source was trusted.",
        }
    )
    forecast_ledger_tool({"db": db, "action": "resolve", "question_id": question_id, "outcome": "no"})
    score = json.loads(forecast_ledger_tool({"db": db, "action": "score", "question_id": question_id}))["score"]
    postmortem = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "postmortem",
                "question_id": question_id,
                "summary": "The source was later corrected.",
                "lesson": "Discount this source class.",
            }
        )
    )["postmortem"]
    lesson = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_calibration_lessons",
                "scope_type": "domain",
                "scope_ref": "policy",
            }
        )
    )["calibration_lessons"][0]

    created_correction = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_correction",
                "target_type": "score_record",
                "target_id": score["id"],
                "reason": "Resolution source was corrected after scoring.",
                "created_by": "forecast-agent",
                "old_value": {"outcome": "no"},
                "new_value": {"outcome": "yes"},
                "patch": {"resolution": "corrected"},
                "status": "applied",
            }
        )
    )["correction"]
    listed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_corrections",
                "target_type": "score_record",
                "target_id": score["id"],
            }
        )
    )
    ledger = ForecastLedger(db)

    assert listed["corrections"][0]["id"] == created_correction["id"]
    assert created_correction["affected_score_record_refs"] == [score["id"]]
    assert created_correction["affected_postmortem_refs"] == [postmortem["id"]]
    assert created_correction["affected_calibration_lesson_refs"] == [lesson["id"]]
    assert ledger.get_score(score["id"]).invalidated_by_correction_id == created_correction["id"]
    assert ledger.get_postmortem(postmortem["id"])["invalidated_by_correction_id"] == created_correction["id"]
    assert ledger.get_calibration_lesson(lesson["id"])["invalidated_by_correction_id"] == created_correction["id"]


def test_forecast_ledger_tool_lists_scores_for_calibration_review(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool score listing support calibration review?",
                "resolution_criteria": "Resolved yes if score records can be filtered.",
                "domain": "macro",
            }
        )
    )
    question_id = created["question"]["id"]
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.72,
            "rationale": "Macro forecast for score listing.",
            "forecast_origin": "live",
        }
    )
    forecast_ledger_tool({"db": db, "action": "resolve", "question_id": question_id, "outcome": "yes"})
    score = json.loads(forecast_ledger_tool({"db": db, "action": "score", "question_id": question_id}))["score"]

    listed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_scores",
                "domain": "macro",
                "forecast_origin": "live",
                "bucket": score["calibration_bucket"],
                "calibration_eligible": True,
            }
        )
    )

    assert listed["scores"][0]["id"] == score["id"]
    assert listed["scores"][0]["domain"] == "macro"
    assert listed["scores"][0]["forecast_origin"] == "live"
    assert listed["scores"][0]["calibration_bucket"] == score["calibration_bucket"]


def test_forecast_ledger_tool_manages_trusted_resolver_policies(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_trusted_resolver_policy",
                "resolver_plugin": "official-results",
                "plugin_version": "1.2.0",
                "scope_type": "source",
                "scope_ref": "official-election-board",
                "enabled": True,
                "approved_by": "research-lead",
                "audit_log_ref": "audit://resolver-policy/1",
            }
        )
    )
    policy = created["trusted_resolver_policy"]
    listed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_trusted_resolver_policies",
                "resolver_plugin": "official-results",
                "scope_type": "source",
                "enabled": True,
            }
        )
    )
    question = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will trusted resolver usage be audited?",
                "resolution_criteria": "Resolved yes if trusted resolver policy usage updates last_used_at.",
            }
        )
    )["question"]
    resolved = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "resolve",
                "question_id": question["id"],
                "outcome": "yes",
                "resolver_type": "source_adapter",
                "trusted_policy_id": policy["id"],
            }
        )
    )
    stored_policy = ForecastLedger(db).get_trusted_resolver_policy(policy["id"])

    assert listed["trusted_resolver_policies"][0]["id"] == policy["id"]
    assert listed["trusted_resolver_policies"][0]["enabled"] is True
    assert resolved["resolution"]["trusted_policy_id"] == policy["id"]
    assert stored_policy["last_used_at"] is not None


def test_forecast_ledger_tool_manages_reference_class_review_state(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool reference classes be reviewable?",
                "resolution_criteria": "Resolved yes if reference classes can be checked and invalidated.",
            }
        )
    )
    question_id = created["question"]["id"]
    added = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_reference_class",
                "question_id": question_id,
                "name": "Comparable policy votes",
                "inclusion_criteria": "Recent committee votes with similar sponsors.",
                "exclusion_criteria": "Unrelated floor votes.",
                "base_rate": 0.42,
                "uncertainty": 0.08,
                "check_cadence": "14d",
                "notes": "Initial base-rate book.",
            }
        )
    )
    reference_class_id = added["reference_class"]["id"]
    listed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_reference_classes",
                "question_id": question_id,
            }
        )
    )
    updated = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_reference_class",
                "reference_class_id": reference_class_id,
                "status": "invalidated",
                "last_checked_at": "2026-01-07T00:00:00Z",
                "notes": "Reference class no longer comparable.",
            }
        )
    )

    assert listed["reference_classes"][0]["id"] == reference_class_id
    assert listed["reference_classes"][0]["check_cadence"] == "14d"
    assert listed["reference_classes"][0]["notes"] == "Initial base-rate book."
    assert updated["reference_class"]["status"] == "invalidated"
    assert updated["reference_class"]["last_checked_at"] == "2026-01-07T00:00:00Z"
    assert updated["reference_class"]["invalidated_at"] is not None
    assert updated["reference_class"]["notes"] == "Reference class no longer comparable."


def test_forecast_ledger_tool_stores_snapshot_audit_metadata(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool snapshot metadata persist?",
                "resolution_criteria": "Resolved yes if snapshot metadata is auditable.",
            }
        )
    )
    question_id = created["question"]["id"]
    updated = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_forecast",
                "question_id": question_id,
                "probability": 0.62,
                "rationale": "Store tool audit metadata.",
                "as_of": "2026-01-01T00:00:00Z",
                "method": "structured_judgment",
                "key_assumptions": ["Policy signal remains valid."],
                "forecast_origin": "live",
                "agent_model": "test-model",
                "prompt_version": "prompt-v1",
                "forecasting_protocol_version": "protocol-v1",
                "toolset_version": "forecast-tool-v1",
                "source_snapshot_refs": ["src_snap_1"],
                "evidence_cutoff": "2026-01-01T00:00:00Z",
                "calibration_eligible": False,
                "calibration_weight": 0.25,
                "metadata": {"created_by": "forecast_ledger_tool"},
            }
        )
    )

    snapshot = ForecastLedger(db).get_snapshot(updated["forecast_snapshot"]["forecast_id"])
    assert snapshot.method == "structured_judgment"
    assert snapshot.key_assumptions == ["Policy signal remains valid."]
    assert snapshot.forecast_origin == "live"
    assert snapshot.agent_model == "test-model"
    assert snapshot.prompt_version == "prompt-v1"
    assert snapshot.forecasting_protocol_version == "protocol-v1"
    assert snapshot.toolset_version == "forecast-tool-v1"
    assert snapshot.source_snapshot_refs == ["src_snap_1"]
    assert snapshot.evidence_cutoff == "2026-01-01T00:00:00Z"
    assert snapshot.calibration_eligible is False
    assert snapshot.calibration_weight == pytest.approx(0.25)
    assert snapshot.metadata["created_by"] == "forecast_ledger_tool"


def test_forecast_ledger_tool_can_apply_active_calibration_lessons(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool learning adjust forecasts?",
                "resolution_criteria": "Resolved yes if the tool applies active lessons.",
                "domain": "macro",
            }
        )
    )
    question_id = created["question"]["id"]
    ledger = ForecastLedger(db)
    lesson = ledger.create_calibration_lesson(
        scope_type="domain",
        scope_ref="macro",
        lesson="Macro tool updates should discount policy-shock overconfidence.",
        status="active",
        recommended_adjustment={"probability_delta": -0.06},
    )

    updated = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_forecast",
                "question_id": question_id,
                "probability": 0.7,
                "rationale": "Tool applies active lesson.",
                "use_active_lessons": True,
            }
        )
    )

    snapshot = ledger.get_snapshot(updated["forecast_snapshot"]["forecast_id"])
    assert snapshot.probability_or_distribution == pytest.approx(0.64)
    assert snapshot.calibration_lesson_refs == [lesson["id"]]
    assert snapshot.calibration_adjustment["raw_probability"] == pytest.approx(0.7)
    assert snapshot.calibration_adjustment["applied_probability_delta"] == pytest.approx(-0.06)


def test_forecast_ledger_tool_manages_scheduled_reviews(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool schedules run?",
                "resolution_criteria": "Resolved yes if scheduled reviews run through the tool.",
            }
        )
    )
    question_id = created["question"]["id"]

    scheduled = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "schedule_review",
                "question_id": question_id,
                "cadence": "1d",
                "next_run_at": "2026-01-01T00:00:00Z",
                "auto_score": True,
                "auto_postmortem": True,
            }
        )
    )
    review_id = scheduled["scheduled_review"]["id"]
    listed = json.loads(
        forecast_ledger_tool({"db": db, "action": "list_scheduled_reviews"})
    )
    ran = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "run_scheduled_reviews",
                "now": "2026-01-02T00:00:00Z",
            }
        )
    )

    assert listed["scheduled_reviews"][0]["id"] == review_id
    assert listed["scheduled_reviews"][0]["scope_ref"] == question_id
    assert bool(listed["scheduled_reviews"][0]["auto_score"]) is True
    assert bool(listed["scheduled_reviews"][0]["auto_postmortem"]) is True
    assert ran["scheduled_review_results"][0]["review"]["id"] == review_id
    assert ran["scheduled_review_results"][0]["review"]["last_run_at"] == "2026-01-02T00:00:00Z"
    assert ran["scheduled_review_results"][0]["alerts"][0]["reason"] == "no_forecast_snapshot"


def test_forecast_ledger_tool_reviews_and_schedules_by_horizon(tmp_path):
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    ledger = ForecastLedger(db_path)
    short_horizon = ledger.create_question(
        title="Will tool short horizon be reviewed?",
        resolution_criteria="Resolved yes if horizon review includes this.",
        close_time="2026-01-25T00:00:00Z",
    )
    long_horizon = ledger.create_question(
        title="Will tool long horizon be ignored?",
        resolution_criteria="Resolved yes if horizon review excludes this.",
        close_time="2026-06-01T00:00:00Z",
    )
    for question in (short_horizon, long_horizon):
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.5,
            rationale="Initial forecast.",
            as_of="2026-01-01T00:00:00Z",
        )

    reviewed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "review",
                "stale": True,
                "last_days": 7,
                "horizon": "30",
                "now": "2026-01-10T00:00:00Z",
            }
        )
    )
    scheduled = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "schedule_review",
                "horizon": "30",
                "cadence": "1d",
                "next_run_at": "2026-01-02T00:00:00Z",
                "stale_days": 3,
            }
        )
    )

    assert [row["question"]["id"] for row in reviewed["review"]] == [short_horizon.id]
    assert scheduled["scheduled_review"]["scope_type"] == "horizon"
    assert scheduled["scheduled_review"]["scope_ref"] == "30"
    assert scheduled["scheduled_review"]["stale_days"] == 3


def test_forecast_ledger_tool_can_list_and_acknowledge_alerts(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool alert lifecycle work?",
                "resolution_criteria": "Resolved yes if alerts can be reviewed.",
            }
        )
    )
    question_id = created["question"]["id"]
    checked = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "self_check",
                "question_id": question_id,
            }
        )
    )
    alert_id = checked["alerts"][0]["id"]

    listed = json.loads(forecast_ledger_tool({"db": db, "action": "list_alerts"}))
    acknowledged = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "acknowledge_alert",
                "alert_id": alert_id,
                "acknowledged_at": "2026-01-03T00:00:00Z",
            }
        )
    )
    open_after_ack = json.loads(forecast_ledger_tool({"db": db, "action": "list_alerts"}))
    all_after_ack = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_alerts",
                "unresolved_only": False,
            }
        )
    )

    assert listed["alerts"][0]["id"] == alert_id
    assert acknowledged["alert"]["acknowledged_at"] == "2026-01-03T00:00:00Z"
    assert open_after_ack["alerts"] == []
    assert all_after_ack["alerts"][0]["id"] == alert_id


def test_forecast_ledger_tool_reviews_focused_books(tmp_path):
    db = str(tmp_path / "forecasting.db")
    low_confidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will focused election review appear?",
                "resolution_criteria": "Resolved yes if low-confidence election forecasts can be filtered.",
                "domain": "geopolitics",
                "topics": ["election"],
            }
        )
    )["question"]
    high_confidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will rates review stay separate?",
                "resolution_criteria": "Resolved yes if topic filters exclude this question.",
                "domain": "geopolitics",
                "topics": ["rates"],
            }
        )
    )["question"]
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": low_confidence["id"],
            "probability": 0.55,
            "confidence": 0.3,
            "rationale": "Low-confidence election update.",
        }
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": high_confidence["id"],
            "probability": 0.65,
            "confidence": 0.8,
            "rationale": "High-confidence rates update.",
        }
    )

    focused = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "review",
                "domain": "geopolitics",
                "topic": "election",
                "confidence_below": 0.5,
                "now": "2026-01-10T00:00:00Z",
            }
        )
    )

    assert [row["question"]["id"] for row in focused["review"]] == [low_confidence["id"]]


def test_forecast_ledger_tool_reads_calibration_and_error_memory(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool calibration memory be readable?",
                "resolution_criteria": "Resolved yes if calibration memory is readable.",
                "domain": "macro",
            }
        )
    )
    question_id = created["question"]["id"]
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.9,
            "rationale": "Overconfident macro forecast.",
        }
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "resolve",
            "question_id": question_id,
            "outcome": "no",
        }
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "postmortem",
            "question_id": question_id,
            "summary": "The macro event did not happen.",
            "lesson": "Discount overconfident macro calls after misses.",
        }
    )

    calibration = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "calibration_summary",
                "domain": "macro",
            }
        )
    )
    profiles = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_domain_error_profiles",
                "domain": "macro",
            }
        )
    )

    assert calibration["calibration"]["count"] == 1
    assert calibration["calibration"]["mean_brier"] == pytest.approx(0.81)
    assert profiles["domain_error_profiles"][0]["domain"] == "macro"
    assert profiles["domain_error_profiles"][0]["sample_count"] == 1
    assert "elevated_mean_brier" in profiles["domain_error_profiles"][0]["recurring_errors"]


def test_forecast_ledger_tool_runs_and_reports_backtests(tmp_path):
    db = str(tmp_path / "forecasting.db")
    actions = set(FORECAST_LEDGER_SCHEMA["parameters"]["properties"]["action"]["enum"])
    assert "evidence_readiness" in actions

    run = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "run_backtest_dataset",
                "dataset": "tool-fixture",
                "cases": [
                    {
                        "title": "Will tool backtest case resolve yes?",
                        "resolution_criteria": "Resolved yes for the fixture.",
                        "as_of": "2026-01-01T00:00:00Z",
                        "probability": 0.7,
                        "outcome": "yes",
                        "baselines": [
                            {
                                "source": "fixture-market",
                                "baseline_type": "market",
                                "probability": 0.6,
                            }
                        ],
                    }
                ],
            }
        )
    )
    run_id = run["backtest_run"]["id"]
    listed = json.loads(forecast_ledger_tool({"db": db, "action": "list_backtest_runs"}))
    report = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "backtest_performance_report",
                "run_id": run_id,
            }
        )
    )
    readiness = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "evidence_readiness",
                "last": 5,
                "min_live_scores": 3,
                "min_agent_protocol_cases": 4,
            }
        )
    )

    assert listed["backtest_runs"][0]["id"] == run_id
    assert report["backtest_performance"]["case_count"] == 1
    assert report["backtest_performance"]["agent"]["mean_brier"] == pytest.approx(0.09)
    assert report["backtest_performance"]["baselines"][0]["baseline_type"] == "market"
    assert report["backtest_performance"]["baselines"][0]["mean_brier"] == pytest.approx(0.16)
    assert report["backtest_performance"]["baselines"][0]["paired_agent_wins"] == 1
    assert readiness["inspected_backtest_run_ids"] == [run_id]
    assert readiness["backtest_summaries"][0]["id"] == run_id
    assert readiness["evidence_status"]["score_counts"]["backtest"] == 1
    assert readiness["evidence_status"]["backtests"]["leakage_free_run_count"] == 1
    requirements = {
        row["id"]: row
        for row in readiness["evidence_status"]["requirements"]
    }
    assert requirements["live_scored_forecasts"]["required"] == 3
    assert requirements["agent_protocol_scored_cases"]["required"] == 4
    assert readiness["evidence_status"]["next_actions"][0]["requirement_id"] == "live_scored_forecasts"
    assert "forecast backtest <cases.json>" in readiness["evidence_status"]["next_actions"][1]["action"]


def test_forecast_ledger_tool_imports_structured_source_evidence(tmp_path, monkeypatch):
    db = str(tmp_path / "forecasting.db")
    actions = set(FORECAST_LEDGER_SCHEMA["parameters"]["properties"]["action"]["enum"])
    assert "import_source_evidence" in actions

    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will structured adapter evidence import?",
                "resolution_criteria": "Resolved yes if adapter evidence is imported through the tool.",
            }
        )
    )
    question_id = created["question"]["id"]

    def fake_pageviews(source, **kwargs):
        assert source == "en.wikipedia.org/Artificial_intelligence"
        assert kwargs["limit"] == 2
        assert kwargs["since"] == "2026-01-01"
        assert kwargs["access"] == "desktop"
        assert kwargs["agent"] == "user"
        assert kwargs["api_base_url"] == "https://example.test/pageviews"
        return [
            WikimediaPageviewObservation(
                project="en.wikipedia.org",
                article="Artificial_intelligence",
                access="desktop",
                agent="user",
                granularity="daily",
                observation_date="2026-01-02",
                views=1234,
                published_at="2026-01-02T00:00:00Z",
                source_url="https://example.test/pageviews/en.wikipedia.org/Artificial_intelligence",
                source_name="Wikimedia Pageviews",
                entry_id="en.wikipedia.org:Artificial_intelligence:2026-01-02",
                raw={"views": 1234},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_wikimedia_pageviews", fake_pageviews)
    imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "wikipediapageviews",
                "source": "en.wikipedia.org/Artificial_intelligence",
                "limit": 2,
                "since": "2026-01-01",
                "access": "desktop",
                "agent": "user",
                "api_base_url": "https://example.test/pageviews",
                "reliability_rating": 0.8,
                "relevance_rating": 0.7,
                "snapshot_path": "adapter-snapshot.json",
            }
        )
    )

    assert imported["imported_count"] == 1
    row = imported["imported"][0]
    evidence = row["evidence"]
    assert evidence["question_id"] == question_id
    assert evidence["source_type"] == "adapter:wikipediapageviews"
    assert evidence["source_name"] == "Wikimedia Pageviews"
    assert evidence["snapshot_path"] == "adapter-snapshot.json"
    assert evidence["claim"] == "Wikimedia pageviews for Artificial_intelligence were 1234 on 2026-01-02"
    assert evidence["reliability_rating"] == pytest.approx(0.8)
    assert evidence["relevance_rating"] == pytest.approx(0.7)
    assert evidence["metadata"]["adapter"] == "wikipediapageviews"
    assert evidence["metadata"]["adapter_item"]["views"] == 1234
    assert row["adapter_item"]["entry_id"] == "en.wikipedia.org:Artificial_intelligence:2026-01-02"

    def fake_eia(source, **kwargs):
        assert source == "PET.RWTC.M"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-01-01"
        assert kwargs["api_base_url"] == "https://example.test/eia"
        return [
            EiaObservation(
                series_id="PET.RWTC.M",
                series_name="WTI crude oil spot price",
                observation_period="2026-03",
                value=72.5,
                unit="dollars per barrel",
                published_at="2026-03-01T00:00:00Z",
                source_url="https://example.test/eia?series_id=PET.RWTC.M",
                source_name="EIA",
                entry_id="PET.RWTC.M:2026-03",
                raw={"period": "2026-03", "value": "72.5"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_eia_observations", fake_eia)
    eia_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "eia",
                "source": "PET.RWTC.M",
                "limit": 1,
                "since": "2026-01-01",
                "api_base_url": "https://example.test/eia",
            }
        )
    )

    assert eia_imported["imported_count"] == 1
    eia_evidence = eia_imported["imported"][0]["evidence"]
    assert eia_evidence["source_type"] == "adapter:eia"
    assert eia_evidence["source_name"] == "EIA"
    assert eia_evidence["claim"] == "EIA PET.RWTC.M was 72.5 dollars per barrel for 2026-03"
    assert eia_evidence["published_at"] == "2026-03-01T00:00:00Z"
    assert eia_evidence["metadata"]["adapter"] == "eia"
    assert eia_evidence["metadata"]["adapter_item"]["unit"] == "dollars per barrel"

    def fake_treasury(source, **kwargs):
        assert source == "v2/accounting/od/avg_interest_rates"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-01-01"
        assert kwargs["date_field"] == "record_date"
        assert kwargs["value_field"] == "avg_interest_rate_amt"
        assert kwargs["api_base_url"] == "https://example.test/treasury"
        return [
            TreasuryRecord(
                dataset="v2/accounting/od/avg_interest_rates",
                record_date="2026-04-01",
                value=4.4,
                value_field="avg_interest_rate_amt",
                value_label="Average Interest Rate",
                published_at="2026-04-01T00:00:00Z",
                source_url="https://example.test/treasury/v2/accounting/od/avg_interest_rates",
                source_name="U.S. Treasury Fiscal Data",
                entry_id="v2/accounting/od/avg_interest_rates:2026-04-01:0",
                raw={"record_date": "2026-04-01", "avg_interest_rate_amt": "4.40"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_treasury_records", fake_treasury)
    treasury_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "treasury",
                "source": "v2/accounting/od/avg_interest_rates",
                "limit": 1,
                "since": "2026-01-01",
                "date_field": "record_date",
                "value_field": "avg_interest_rate_amt",
                "api_base_url": "https://example.test/treasury",
            }
        )
    )

    assert treasury_imported["imported_count"] == 1
    treasury_evidence = treasury_imported["imported"][0]["evidence"]
    assert treasury_evidence["source_type"] == "adapter:treasury"
    assert treasury_evidence["source_name"] == "U.S. Treasury Fiscal Data"
    assert (
        treasury_evidence["claim"]
        == "Treasury v2/accounting/od/avg_interest_rates 2026-04-01: avg_interest_rate_amt=4.4"
    )
    assert treasury_evidence["published_at"] == "2026-04-01T00:00:00Z"
    assert treasury_evidence["metadata"]["adapter"] == "treasury"
    assert treasury_evidence["metadata"]["adapter_item"]["value_label"] == "Average Interest Rate"

    def fake_githubissues(source, **kwargs):
        assert source == "acme/desk"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["state"] == "all"
        assert kwargs["api_base_url"] == "https://example.test/github"
        return [
            GitHubIssue(
                repo="acme/desk",
                issue_number=42,
                title="Ship forecast ledger",
                state="open",
                is_pull_request=False,
                author="analyst",
                labels=["forecasting"],
                created_at="2026-05-20T10:00:00Z",
                updated_at="2026-05-21T11:00:00Z",
                closed_at=None,
                comments=2,
                url="https://api.github.test/repos/acme/desk/issues/42",
                html_url="https://github.com/acme/desk/issues/42",
                source_name="GitHub",
                entry_id="acme/desk#42",
                raw={"number": 42},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_github_issues", fake_githubissues)
    githubissues_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "githubissues",
                "source": "acme/desk",
                "limit": 1,
                "since": "2026-05-01",
                "state": "all",
                "api_base_url": "https://example.test/github",
            }
        )
    )

    assert githubissues_imported["imported_count"] == 1
    githubissues_evidence = githubissues_imported["imported"][0]["evidence"]
    assert githubissues_evidence["source_type"] == "adapter:githubissues"
    assert githubissues_evidence["source_name"] == "GitHub"
    assert githubissues_evidence["claim"] == "GitHub issue acme/desk #42: Ship forecast ledger"
    assert githubissues_evidence["published_at"] == "2026-05-21T11:00:00Z"
    assert githubissues_evidence["metadata"]["adapter"] == "githubissues"
    assert githubissues_evidence["metadata"]["adapter_item"]["labels"] == ["forecasting"]

    def fake_hackernews(source, **kwargs):
        assert source == "forecast desk"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/hackernews"
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

    monkeypatch.setattr("tools.forecasting_tool.load_hackernews_items", fake_hackernews)
    hackernews_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "hackernews",
                "source": "forecast desk",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/hackernews",
            }
        )
    )

    assert hackernews_imported["imported_count"] == 1
    hackernews_evidence = hackernews_imported["imported"][0]["evidence"]
    assert hackernews_evidence["source_type"] == "adapter:hackernews"
    assert hackernews_evidence["source_name"] == "Hacker News"
    assert hackernews_evidence["claim"] == "Hacker News: Forecast Desk launches public beta"
    assert hackernews_evidence["published_at"] == "2026-05-21T14:30:00Z"
    assert hackernews_evidence["metadata"]["adapter"] == "hackernews"
    assert hackernews_evidence["metadata"]["adapter_item"]["points"] == 128

    def fake_reddit(source, **kwargs):
        assert source == "forecast desk"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/reddit/search.json"
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

    monkeypatch.setattr("tools.forecasting_tool.load_reddit_posts", fake_reddit)
    reddit_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "reddit",
                "source": "forecast desk",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/reddit/search.json",
            }
        )
    )

    assert reddit_imported["imported_count"] == 1
    reddit_evidence = reddit_imported["imported"][0]["evidence"]
    assert reddit_evidence["source_type"] == "adapter:reddit"
    assert reddit_evidence["source_name"] == "Reddit r/forecasting"
    assert reddit_evidence["claim"] == "Reddit: Forecast Desk launches public beta"
    assert reddit_evidence["published_at"] == "2026-05-21T14:30:00Z"
    assert reddit_evidence["metadata"]["adapter"] == "reddit"
    assert reddit_evidence["metadata"]["adapter_item"]["score"] == 128

    def fake_cisakev(source, **kwargs):
        assert source == "ForecastSoft"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/cisa-kev.json"
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
                source_url="https://example.test/cisa-kev.json",
                source_name="CISA Known Exploited Vulnerabilities",
                entry_id="CVE-2026-23456",
                raw={"cveID": "CVE-2026-23456"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_cisa_kev_vulnerabilities", fake_cisakev)
    cisakev_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "cisakev",
                "source": "ForecastSoft",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/cisa-kev.json",
            }
        )
    )

    assert cisakev_imported["imported_count"] == 1
    cisakev_evidence = cisakev_imported["imported"][0]["evidence"]
    assert cisakev_evidence["source_type"] == "adapter:cisakev"
    assert cisakev_evidence["source_name"] == "CISA Known Exploited Vulnerabilities"
    assert cisakev_evidence["claim"] == "CISA KEV CVE-2026-23456: ForecastSoft Forecast Server"
    assert cisakev_evidence["published_at"] == "2026-05-20T00:00:00Z"
    assert cisakev_evidence["metadata"]["adapter"] == "cisakev"
    assert cisakev_evidence["metadata"]["adapter_item"]["ransomware_use"] == "Known"

    def fake_stooq(source, **kwargs):
        assert source == "AAPL.US"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["interval"] == "d"
        assert kwargs["api_base_url"] == "https://example.test/stooq"
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
                source_url="https://example.test/stooq?s=aapl.us&i=d",
                source_name="Stooq",
                entry_id="AAPL.US:d:2026-05-22",
                raw={"Date": "2026-05-22", "Close": "198.40"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_stooq_prices", fake_stooq)
    stooq_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "stooq",
                "source": "AAPL.US",
                "limit": 1,
                "since": "2026-05-01",
                "interval": "d",
                "api_base_url": "https://example.test/stooq",
            }
        )
    )

    assert stooq_imported["imported_count"] == 1
    stooq_evidence = stooq_imported["imported"][0]["evidence"]
    assert stooq_evidence["source_type"] == "adapter:stooq"
    assert stooq_evidence["source_name"] == "Stooq"
    assert stooq_evidence["claim"] == "Stooq AAPL.US close was 198.4 on 2026-05-22"
    assert stooq_evidence["published_at"] == "2026-05-22T00:00:00Z"
    assert stooq_evidence["metadata"]["adapter"] == "stooq"
    assert stooq_evidence["metadata"]["adapter_item"]["close_price"] == 198.4

    def fake_clinicaltrials(source, **kwargs):
        assert source == "NCT01234567"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/clinicaltrials"
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
                completion_date=None,
                last_update_submitted_at="2026-05-20T00:00:00Z",
                last_update_posted_at="2026-05-21T00:00:00Z",
                has_results=False,
                source_name="ClinicalTrials.gov",
                entry_id="NCT01234567",
                raw={"nctId": "NCT01234567"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_clinicaltrials_studies", fake_clinicaltrials)
    clinicaltrials_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "clinicaltrials",
                "source": "NCT01234567",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/clinicaltrials",
            }
        )
    )

    assert clinicaltrials_imported["imported_count"] == 1
    clinicaltrials_evidence = clinicaltrials_imported["imported"][0]["evidence"]
    assert clinicaltrials_evidence["source_type"] == "adapter:clinicaltrials"
    assert clinicaltrials_evidence["source_name"] == "ClinicalTrials.gov"
    assert clinicaltrials_evidence["claim"] == (
        "ClinicalTrials.gov NCT01234567: RECRUITING - Test oncology trial"
    )
    assert clinicaltrials_evidence["published_at"] == "2026-05-21T00:00:00Z"
    assert clinicaltrials_evidence["metadata"]["adapter"] == "clinicaltrials"
    assert clinicaltrials_evidence["metadata"]["adapter_item"]["phases"] == ["PHASE2"]

    def fake_openfda(source, **kwargs):
        assert source == "BLA125514"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/openfda"
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

    monkeypatch.setattr("tools.forecasting_tool.load_openfda_drug_applications", fake_openfda)
    openfda_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "openfda",
                "source": "BLA125514",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/openfda",
            }
        )
    )

    assert openfda_imported["imported_count"] == 1
    openfda_evidence = openfda_imported["imported"][0]["evidence"]
    assert openfda_evidence["source_type"] == "adapter:openfda"
    assert openfda_evidence["source_name"] == "openFDA Drugs@FDA"
    assert openfda_evidence["claim"] == "openFDA BLA125514: AP - TESTMAB"
    assert openfda_evidence["published_at"] == "2026-05-21T00:00:00Z"
    assert openfda_evidence["metadata"]["adapter"] == "openfda"
    assert openfda_evidence["metadata"]["adapter_item"]["brand_names"] == ["TESTMAB"]

    def fake_usgs(source, **kwargs):
        assert source == "minmagnitude=5"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-20"
        assert kwargs["api_base_url"] == "https://example.test/usgs"
        return [
            UsgsEarthquakeEvent(
                event_id="us7000abcd",
                title="M 5.7 - Testville",
                url="https://earthquake.usgs.gov/earthquakes/eventpage/us7000abcd",
                time="2026-05-20T00:00:00Z",
                updated_at="2026-05-20T01:00:00Z",
                magnitude=5.7,
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
                raw={"id": "us7000abcd"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_usgs_earthquakes", fake_usgs)
    usgs_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "usgs",
                "source": "minmagnitude=5",
                "limit": 1,
                "since": "2026-05-20",
                "api_base_url": "https://example.test/usgs",
            }
        )
    )

    assert usgs_imported["imported_count"] == 1
    usgs_evidence = usgs_imported["imported"][0]["evidence"]
    assert usgs_evidence["source_type"] == "adapter:usgs"
    assert usgs_evidence["source_name"] == "USGS Earthquake Catalog"
    assert usgs_evidence["claim"] == "USGS earthquake M5.7: Testville"
    assert usgs_evidence["published_at"] == "2026-05-20T00:00:00Z"
    assert usgs_evidence["metadata"]["adapter"] == "usgs"
    assert usgs_evidence["metadata"]["adapter_item"]["event_id"] == "us7000abcd"

    def fake_eonet(source, **kwargs):
        assert source == "category=wildfires&status=open"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-19"
        assert kwargs["api_base_url"] == "https://example.test/eonet"
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
                source_urls=[],
                longitude=-121.2,
                latitude=38.5,
                source_name="NASA EONET",
                entry_id="EONET_123",
                raw={"id": "EONET_123"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_nasa_eonet_events", fake_eonet)
    eonet_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "eonet",
                "source": "category=wildfires&status=open",
                "limit": 1,
                "since": "2026-05-19",
                "api_base_url": "https://example.test/eonet",
            }
        )
    )

    assert eonet_imported["imported_count"] == 1
    eonet_evidence = eonet_imported["imported"][0]["evidence"]
    assert eonet_evidence["source_type"] == "adapter:eonet"
    assert eonet_evidence["source_name"] == "NASA EONET"
    assert eonet_evidence["claim"] == "NASA EONET Wildfires: Wildfire near Test Ridge"
    assert eonet_evidence["published_at"] == "2026-05-20T00:00:00Z"
    assert eonet_evidence["metadata"]["adapter"] == "eonet"
    assert eonet_evidence["metadata"]["adapter_item"]["event_id"] == "EONET_123"

    def fake_nws(source, **kwargs):
        assert source == "area=CA&event=Flood Warning"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-20"
        assert kwargs["api_base_url"] == "https://example.test/nws"
        return [
            NwsAlert(
                alert_id="urn:oid:alert-1",
                event="Flood Warning",
                headline="Flood Warning issued for Test County",
                description="Flooding is possible.",
                instruction="Avoid flooded roads.",
                url="https://api.weather.gov/alerts/urn:oid:alert-1",
                area_desc="Test County",
                severity="Severe",
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
                raw={"id": "urn:oid:alert-1"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_nws_alerts", fake_nws)
    nws_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "nws",
                "source": "area=CA&event=Flood Warning",
                "limit": 1,
                "since": "2026-05-20",
                "api_base_url": "https://example.test/nws",
            }
        )
    )

    assert nws_imported["imported_count"] == 1
    nws_evidence = nws_imported["imported"][0]["evidence"]
    assert nws_evidence["source_type"] == "adapter:nws"
    assert nws_evidence["source_name"] == "National Weather Service"
    assert nws_evidence["claim"] == "NWS Flood Warning: Flood Warning issued for Test County"
    assert nws_evidence["published_at"] == "2026-05-20T12:00:00Z"
    assert nws_evidence["metadata"]["adapter"] == "nws"
    assert nws_evidence["metadata"]["adapter_item"]["alert_id"] == "urn:oid:alert-1"


def test_forecast_ledger_tool_records_reference_classes_and_model_runs(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool base rates work?",
                "resolution_criteria": "Resolved yes if tool base rates are recorded.",
            }
        )
    )
    question_id = created["question"]["id"]

    reference = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_reference_class",
                "question_id": question_id,
                "name": "Similar cases",
                "inclusion_criteria": "Same domain and horizon.",
                "base_rate": 0.42,
            }
        )
    )
    model = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "record_model_run",
                "question_id": question_id,
                "model_type": "bayesian_update",
                "inputs": {"prior": 0.42},
                "output": {"posterior": 0.55},
            }
        )
    )

    ledger = ForecastLedger(db)
    assert reference["reference_class"]["base_rate"] == 0.42
    assert reference["model_run"]["model_type"] == "base_rate"
    assert model["model_run"]["output"]["posterior"] == 0.55
    assert len(ledger.list_model_runs(question_id)) == 2
