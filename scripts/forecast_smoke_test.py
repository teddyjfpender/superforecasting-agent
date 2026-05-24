#!/usr/bin/env python3
"""Run a local Superforecasting Agent forecast-lifecycle smoke test."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


QUESTION_RE = re.compile(r"created forecast question (fq_[a-f0-9]+)")
EVIDENCE_RE = re.compile(r"added evidence (ev_[a-f0-9]+)")
REFERENCE_CLASS_RE = re.compile(r"reference_class: (rc_[a-f0-9]+)")
MODEL_RUN_RE = re.compile(r"model_run: (mr_[a-f0-9]+)")
BACKTEST_RE = re.compile(r"backtest_run: (bt_[a-f0-9]+)")
EXPECTED_SOURCE_ADAPTERS = {
    "news",
    "gdelt",
    "fivethirtyeight",
    "data",
    "owid",
    "whogho",
    "fema",
    "openmeteo",
    "airquality",
    "weatherhistory",
    "usgs",
    "eonet",
    "nws",
    "clinicaltrials",
    "openfda",
    "pubmed",
    "fred",
    "eia",
    "treasury",
    "bls",
    "worldbank",
    "imf",
    "census",
    "socrata",
    "ckan",
    "stooq",
    "yahoo",
    "sec",
    "secfacts",
    "federalregister",
    "courtlistener",
    "nvd",
    "cisakev",
    "arxiv",
    "openalex",
    "crossref",
    "wikipedia",
    "wikipediapageviews",
    "github",
    "githubissues",
    "githubcommits",
    "githubactions",
    "coingecko",
    "pypi",
    "npm",
    "hackernews",
    "reddit",
    "bluesky",
    "mastodon",
    "reliefweb",
    "markets",
}
EXPECTED_BENCHMARKS = {
    "builtin:mini-binary",
    "builtin:synthetic-100-binary",
    "builtin:heldout-120-binary",
    "builtin:manifold-public-120-binary",
}


class SmokeError(RuntimeError):
    """Raised when a smoke-test assertion fails."""


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Exercise the local forecast ledger, scoring, backtesting, and "
            "scheduled self-check paths without external APIs or model calls."
        )
    )
    parser.add_argument("--db", help="Forecast ledger path to use. Defaults to a temporary database.")
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="Keep the temporary database and print its path when --db is not supplied.",
    )
    parser.add_argument(
        "--skip-backtest",
        action="store_true",
        help="Skip the built-in benchmark replay portion.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every command and its stdout.",
    )
    return parser.parse_args(argv)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_forecast(
    args: list[str],
    *,
    db_path: Path,
    repo_root: Path,
    verbose: bool,
) -> str:
    command = [
        sys.executable,
        "-m",
        "superforecasting_agent",
        "--db",
        str(db_path),
        *args,
    ]
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    result = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if verbose or result.returncode != 0:
        print(f"$ {shlex.join(command)}")
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode != 0:
        raise SmokeError(f"command failed with exit {result.returncode}: {shlex.join(command)}")
    return result.stdout


def _extract(pattern: re.Pattern[str], output: str, label: str) -> str:
    match = pattern.search(output)
    if not match:
        raise SmokeError(f"could not parse {label} from output:\n{output}")
    return match.group(1)


def _json_output(output: str, label: str) -> dict:
    try:
        loaded = json.loads(output)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"{label} did not return JSON:\n{output}") from exc
    if not isinstance(loaded, dict):
        raise SmokeError(f"{label} returned non-object JSON:\n{output}")
    return loaded


def _print_step(message: str) -> None:
    print(f"[forecast-smoke] {message}")


def _verify_source_catalog(repo_root: Path, db_path: Path, *, verbose: bool) -> None:
    output = _run_forecast(["sources", "--json"], db_path=db_path, repo_root=repo_root, verbose=verbose)
    catalog = _json_output(output, "sources")
    sources = catalog.get("sources")
    if not isinstance(sources, list):
        raise SmokeError(f"sources returned malformed catalog:\n{output}")
    names = {str(item.get("name")) for item in sources if isinstance(item, dict)}
    missing = sorted(EXPECTED_SOURCE_ADAPTERS - names)
    if missing:
        raise SmokeError(f"source catalog missing expected adapter(s): {', '.join(missing)}")
    _print_step(f"source_adapters: {len(names)}")


def _verify_benchmark_catalog(repo_root: Path, db_path: Path, *, verbose: bool) -> None:
    output = _run_forecast(["backtest", "--benchmarks"], db_path=db_path, repo_root=repo_root, verbose=verbose)
    missing = sorted(name for name in EXPECTED_BENCHMARKS if name not in output)
    if missing:
        raise SmokeError(f"benchmark catalog missing expected dataset(s): {', '.join(missing)}")
    _print_step(f"benchmark_datasets: {len(EXPECTED_BENCHMARKS)}")


def _write_agent_protocol_fixture(db_path: Path) -> tuple[Path, Path]:
    dataset_path = db_path.with_name("forecast-smoke-agent-protocol-cases.json")
    responses_path = db_path.with_name("forecast-smoke-agent-protocol-responses.jsonl")
    cases = {
        "cases": [
            {
                "id": "smoke-agent-protocol-yes",
                "title": "Will the captured smoke agent-protocol yes case resolve yes?",
                "resolution_criteria": "Resolved yes for the local smoke fixture.",
                "as_of": "2026-01-10T00:00:00Z",
                "close_time": "2026-01-20T00:00:00Z",
                "domain": "tester",
                "probability": 0.99,
                "outcome": "yes",
                "baselines": [
                    {
                        "source": "fixture-market",
                        "baseline_type": "market",
                        "probability": 0.55,
                        "as_of": "2026-01-09T00:00:00Z",
                    }
                ],
                "evidence": [
                    {
                        "note": "Pre-cutoff smoke evidence supports yes.",
                        "available_at": "2026-01-09T00:00:00Z",
                        "stance": "increases",
                    }
                ],
            },
            {
                "id": "smoke-agent-protocol-no",
                "title": "Will the captured smoke agent-protocol no case resolve yes?",
                "resolution_criteria": "Resolved no for the local smoke fixture.",
                "as_of": "2026-01-10T00:00:00Z",
                "close_time": "2026-01-20T00:00:00Z",
                "domain": "tester",
                "probability": 0.01,
                "outcome": "no",
                "baselines": [
                    {
                        "source": "fixture-market",
                        "baseline_type": "market",
                        "probability": 0.45,
                        "as_of": "2026-01-09T00:00:00Z",
                    }
                ],
                "evidence": [
                    {
                        "note": "Pre-cutoff smoke evidence supports no.",
                        "available_at": "2026-01-09T00:00:00Z",
                        "stance": "decreases",
                    }
                ],
            },
        ]
    }
    responses = [
        {
            "case_id": "smoke-agent-protocol-yes",
            "response": {
                "probability": 0.8,
                "confidence": 0.75,
                "rationale": "Captured smoke protocol forecast from visible pre-cutoff evidence.",
                "components": {"market": {"probability": 0.55, "weight": 0.4}},
                "agent_model": "smoke-captured-agent",
            },
        },
        {
            "case_id": "smoke-agent-protocol-no",
            "response": {
                "probability": 0.2,
                "confidence": 0.75,
                "rationale": "Captured smoke protocol forecast from visible pre-cutoff evidence.",
                "components": {"market": {"probability": 0.45, "weight": 0.4}},
                "agent_model": "smoke-captured-agent",
            },
        },
    ]
    dataset_path.write_text(json.dumps(cases, indent=2, sort_keys=True), encoding="utf-8")
    responses_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in responses),
        encoding="utf-8",
    )
    return dataset_path, responses_path


def _exercise_lifecycle(repo_root: Path, db_path: Path, *, skip_backtest: bool, verbose: bool) -> None:
    status = _json_output(
        _run_forecast(["status", "--json"], db_path=db_path, repo_root=repo_root, verbose=verbose),
        "status",
    )
    if status.get("product") != "Superforecasting Agent":
        raise SmokeError(f"unexpected product identity: {status.get('product')!r}")
    _print_step(f"ledger: {status.get('ledger_path')}")

    _verify_source_catalog(repo_root, db_path, verbose=verbose)
    _verify_benchmark_catalog(repo_root, db_path, verbose=verbose)

    question_output = _run_forecast(
        [
            "new",
            "Will the local tester smoke workflow resolve yes?",
            "--resolution-criteria",
            "Resolved yes if the local tester smoke workflow completes all ledger steps.",
            "--close-time",
            "2026-05-23T00:00:00Z",
            "--resolution-time",
            "2026-05-23T01:00:00Z",
            "--domain",
            "tester",
            "--topic",
            "smoke",
        ],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    question_id = _extract(QUESTION_RE, question_output, "question id")
    _print_step(f"question_id: {question_id}")

    evidence_output = _run_forecast(
        [
            "evidence",
            "add",
            question_id,
            "local smoke evidence",
            "--claim",
            "The local smoke workflow is exercising the forecast ledger.",
            "--summary",
            "Deterministic local evidence for tester verification.",
            "--source-type",
            "data",
            "--available-at",
            "2026-05-22T00:00:00Z",
            "--reliability",
            "0.9",
            "--relevance",
            "0.8",
            "--stance",
            "increases",
        ],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    evidence_id = _extract(EVIDENCE_RE, evidence_output, "evidence id")
    _print_step(f"evidence_id: {evidence_id}")

    base_rate_output = _run_forecast(
        [
            "base-rate",
            question_id,
            "--name",
            "local deterministic smoke runs",
            "--inclusion-criteria",
            "Smoke workflows run in this checkout",
            "--exclusion-criteria",
            "External API and model-provider calls",
            "--base-rate",
            "0.55",
            "--uncertainty",
            "0.10",
            "--source-ref",
            evidence_id,
            "--check-cadence",
            "7d",
            "--notes",
            "Synthetic base rate for a local tester smoke run.",
        ],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    reference_class_id = _extract(REFERENCE_CLASS_RE, base_rate_output, "reference class id")
    _print_step(f"reference_class_id: {reference_class_id}")

    model_output = _run_forecast(
        [
            "model",
            question_id,
            "--type",
            "bayesian_update",
            "--prior",
            "0.55",
            "--likelihood-if-true",
            "0.8",
            "--likelihood-if-false",
            "0.4",
            "--model-version",
            "smoke-v1",
            "--evidence-cutoff",
            "2026-05-22T00:00:00Z",
        ],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    model_run_id = _extract(MODEL_RUN_RE, model_output, "model run id")
    _print_step(f"model_run_id: {model_run_id}")

    update_output = _run_forecast(
        [
            "update",
            question_id,
            "--probability",
            "0.67",
            "--confidence",
            "0.72",
            "--method",
            "smoke-test-ensemble",
            "--rationale",
            "Base rate, evidence, and local Bayesian update support a high probability.",
            "--as-of",
            "2026-05-22T00:00:00Z",
            "--evidence-ref",
            evidence_id,
            "--reference-class-ref",
            reference_class_id,
            "--model-run-ref",
            model_run_id,
            "--ack-stale-evidence",
        ],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    if "created forecast snapshot" not in update_output:
        raise SmokeError(f"forecast update did not create a snapshot:\n{update_output}")

    show_output = _run_forecast(
        ["show", question_id],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    if "current_forecast:" not in show_output or "evidence_count: 1" not in show_output:
        raise SmokeError(f"forecast show did not include expected ledger state:\n{show_output}")

    _run_forecast(
        [
            "resolve",
            question_id,
            "--outcome",
            "yes",
            "--source",
            "local tester smoke workflow",
            "--notes",
            "The smoke workflow completed the forecast lifecycle.",
        ],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    score_output = _run_forecast(
        ["score", question_id],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    if "brier_score:" not in score_output or "origin: live" not in score_output:
        raise SmokeError(f"score output was missing live score fields:\n{score_output}")

    postmortem_output = _run_forecast(
        [
            "postmortem",
            question_id,
            "--summary",
            "The local smoke workflow resolved yes.",
            "--what-happened",
            "All local ledger lifecycle commands completed.",
            "--what-was-expected",
            "The forecast desk would record evidence, models, a forecast, a resolution, a score, and a learning record.",
            "--lesson",
            "Tester smoke runs should exercise append-only forecast, scoring, and learning paths before external API testing.",
        ],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    if "calibration_lesson: created" not in postmortem_output:
        raise SmokeError(f"postmortem did not create a calibration lesson:\n{postmortem_output}")

    stale_question_output = _run_forecast(
        [
            "new",
            "Will the local tester stale self-check produce an alert?",
            "--resolution-criteria",
            "Resolved yes if the self-check path creates an alert for stale tester work.",
            "--close-time",
            "2026-06-01T00:00:00Z",
            "--domain",
            "tester",
            "--topic",
            "stale",
        ],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    stale_question_id = _extract(QUESTION_RE, stale_question_output, "stale question id")
    _run_forecast(
        [
            "update",
            stale_question_id,
            "--probability",
            "0.5",
            "--confidence",
            "0.5",
            "--method",
            "smoke-stale-check",
            "--rationale",
            "Initial placeholder forecast for the self-check smoke path.",
            "--as-of",
            "2026-05-01T00:00:00Z",
        ],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    self_check_output = _run_forecast(
        [
            "self-check",
            "--question",
            stale_question_id,
            "--stale-days",
            "0",
            "--now",
            "2026-05-24T00:00:00Z",
        ],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    if "created" not in self_check_output or "alert(s)" not in self_check_output:
        raise SmokeError(f"self-check did not create a stale-work alert:\n{self_check_output}")

    _run_forecast(
        [
            "schedule",
            "add",
            "--question",
            stale_question_id,
            "--cadence",
            "1d",
            "--next-run-at",
            "2026-05-22T00:00:00Z",
            "--stale-days",
            "0",
            "--auto-score",
            "--auto-postmortem",
        ],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    schedule_output = _run_forecast(
        [
            "schedule",
            "run",
            "--now",
            "2026-05-24T00:00:00Z",
            "--auto-score",
            "--auto-postmortem",
        ],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    if "ran 1 scheduled review(s)" not in schedule_output or "alert(s)" not in schedule_output:
        raise SmokeError(f"scheduled review did not run:\n{schedule_output}")
    _print_step(f"scheduled_self_check_question_id: {stale_question_id}")

    _run_forecast(
        ["calibration", "--by-origin", "--all"],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    cohort_path = db_path.with_name("forecast-smoke-cohort.json")
    cohort_path.write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "title": "Will the prospective smoke cohort resolve yes?",
                        "resolution_criteria": "Resolved yes if a future smoke cohort tester confirms success.",
                        "domain": "tester",
                        "topics": ["smoke"],
                        "probability": 0.6,
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    pilot_cohort = _json_output(
        _run_forecast(
            ["pilot-cohort", str(cohort_path), "--dry-run", "--json"],
            db_path=db_path,
            repo_root=repo_root,
            verbose=verbose,
        ),
        "pilot-cohort",
    )
    if not pilot_cohort.get("dry_run") or pilot_cohort.get("question_count") != 1:
        raise SmokeError(f"pilot cohort dry-run did not validate:\n{json.dumps(pilot_cohort, indent=2)}")
    _print_step(f"pilot_cohort_dry_run_questions: {pilot_cohort.get('question_count')}")

    example_cohort_path = repo_root / "examples/forecasting/live-cohort.example.csv"
    example_cohort = _json_output(
        _run_forecast(
            ["pilot-cohort", str(example_cohort_path), "--dry-run", "--json"],
            db_path=db_path,
            repo_root=repo_root,
            verbose=verbose,
        ),
        "example pilot-cohort",
    )
    if (
        not example_cohort.get("dry_run")
        or example_cohort.get("question_count") != 5
        or example_cohort.get("initial_probability_count") != 5
    ):
        raise SmokeError(
            "example pilot cohort manifest did not validate:\n"
            f"{json.dumps(example_cohort, indent=2)}"
        )
    _print_step(f"pilot_cohort_example_questions: {example_cohort.get('question_count')}")

    pilot_report = _json_output(
        _run_forecast(
            [
                "pilot-report",
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
                "--json",
            ],
            db_path=db_path,
            repo_root=repo_root,
            verbose=verbose,
        ),
        "pilot-report",
    )
    if pilot_report.get("pilot_status") != "pilot_exit_ready":
        raise SmokeError(f"pilot report did not pass tester exit checks:\n{json.dumps(pilot_report, indent=2)}")
    _print_step(
        "pilot_report_checks: "
        f"{pilot_report.get('passed_checks')}/{pilot_report.get('total_checks')}"
    )
    export_path = db_path.with_name("forecast-smoke-export.json")
    _run_forecast(
        ["export", "all", "--format", "json", "--output", str(export_path)],
        db_path=db_path,
        repo_root=repo_root,
        verbose=verbose,
    )
    pilot_aggregate = _json_output(
        _run_forecast(
            [
                "pilot-aggregate",
                str(export_path),
                "--min-live-scores",
                "1",
                "--json",
            ],
            db_path=db_path,
            repo_root=repo_root,
            verbose=verbose,
        ),
        "pilot-aggregate",
    )
    if pilot_aggregate.get("aggregate_status") != "live_evidence_floor_met":
        raise SmokeError(
            "pilot aggregate did not count the smoke export live score:\n"
            f"{json.dumps(pilot_aggregate, indent=2)}"
        )
    _print_step(
        "pilot_aggregate_live_scores: "
        f"{pilot_aggregate.get('summary', {}).get('live_score_count')}"
    )

    if not skip_backtest:
        backtest_output = _run_forecast(
            ["backtest", "builtin:mini-binary", "--probability-source", "forecast-engine"],
            db_path=db_path,
            repo_root=repo_root,
            verbose=verbose,
        )
        backtest_id = _extract(BACKTEST_RE, backtest_output, "backtest run id")
        if "scored_cases: 5" not in backtest_output or "leakage_checks_passed: True" not in backtest_output:
            raise SmokeError(f"backtest output was missing expected fields:\n{backtest_output}")
        _print_step(f"backtest_run_id: {backtest_id}")

        agent_dataset, agent_responses = _write_agent_protocol_fixture(db_path)
        agent_protocol_output = _run_forecast(
            [
                "backtest",
                str(agent_dataset),
                "--probability-source",
                "agent-protocol",
                "--agent-response-jsonl",
                str(agent_responses),
            ],
            db_path=db_path,
            repo_root=repo_root,
            verbose=verbose,
        )
        agent_protocol_id = _extract(BACKTEST_RE, agent_protocol_output, "agent-protocol backtest run id")
        if "scored_cases: 2" not in agent_protocol_output or "leakage_checks_passed: True" not in agent_protocol_output:
            raise SmokeError(f"agent-protocol backtest output was missing expected fields:\n{agent_protocol_output}")
        _print_step(f"agent_protocol_backtest_run_id: {agent_protocol_id}")

    performance = _json_output(
        _run_forecast(["performance", "--last", "3", "--json"], db_path=db_path, repo_root=repo_root, verbose=verbose),
        "performance",
    )
    readiness = _json_output(
        _run_forecast(["readiness", "--last", "3", "--json"], db_path=db_path, repo_root=repo_root, verbose=verbose),
        "readiness",
    )
    evidence_status = readiness.get("evidence_status") or {}
    if evidence_status.get("can_claim_live_superforecasting") is not False:
        raise SmokeError("smoke readiness should not allow a live superforecasting claim")
    gaps = evidence_status.get("gaps") or []
    if not gaps:
        raise SmokeError("smoke readiness should still list evidence gaps for tester handoff")
    pilot_bundle = _json_output(
        _run_forecast(
            [
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
            db_path=db_path,
            repo_root=repo_root,
            verbose=verbose,
        ),
        "pilot-bundle",
    )
    if pilot_bundle.get("pilot_report", {}).get("pilot_status") != "pilot_exit_ready":
        raise SmokeError(f"pilot bundle did not include a passing pilot report:\n{json.dumps(pilot_bundle, indent=2)}")
    if pilot_bundle.get("readiness", {}).get("evidence_status", {}).get("score_counts", {}).get("live", 0) < 1:
        raise SmokeError(f"pilot bundle did not include live-score readiness data:\n{json.dumps(pilot_bundle, indent=2)}")
    if not pilot_bundle.get("export_included") or not pilot_bundle.get("export_packet", {}).get("questions"):
        raise SmokeError(f"pilot bundle did not include export data:\n{json.dumps(pilot_bundle, indent=2)}")
    _print_step(f"performance_runs: {performance.get('run_count')}")
    _print_step(f"readiness_verdict: {evidence_status.get('verdict')}")
    _print_step(f"readiness_gaps: {len(gaps)}")
    _print_step("pilot_bundle_export_included: true")


def _main(argv: list[str]) -> int:
    args = _parse_args(argv)
    repo_root = _repo_root()
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    db_path: Path
    if args.db:
        db_path = Path(args.db).expanduser().resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        if args.keep_db:
            temp_root = Path(tempfile.mkdtemp(prefix="superforecasting-agent-smoke-"))
            db_path = temp_root / "forecasting-smoke.db"
        else:
            temp_dir = tempfile.TemporaryDirectory(prefix="superforecasting-agent-smoke-")
            db_path = Path(temp_dir.name) / "forecasting-smoke.db"

    try:
        _exercise_lifecycle(
            repo_root,
            db_path,
            skip_backtest=args.skip_backtest,
            verbose=args.verbose,
        )
    except SmokeError as exc:
        print(f"[forecast-smoke] failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    if args.keep_db or args.db:
        _print_step(f"kept_db: {db_path}")
    _print_step("forecast smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
