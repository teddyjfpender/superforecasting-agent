"""Shared command syntax and text presentation for CLI and Ink RPC adapters.

This module adapts inputs/results; application services own all business behavior.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Any, NoReturn

from forecasting.application.resolution import ResolutionResult, resolve_forecast
from forecasting.application.reviews import review_forecasts
from forecasting.application.scoring import ScoringResult, score_forecast
from forecasting.argv import split_forecast_cli_args
from forecasting.learning import is_learned_error_review_reason
from forecasting.ledger import ForecastLedger
from forecasting.models import ForecastingError, ValidationError


def _format_probability(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, int):
        return f"{float(value):.3f}"
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _review_next_action(question_id: str, reasons: list[str]) -> str:
    if any(reason.startswith("new_evidence:") for reason in reasons):
        return f"forecast research {question_id}; forecast update {question_id} --preview ..."
    if any(is_learned_error_review_reason(reason) for reason in reasons):
        return (
            f"forecast show {question_id}; forecast update {question_id} --preview ..."
        )
    if "no_forecast_snapshot" in reasons:
        return f"forecast update {question_id} --preview ..."
    if any(
        reason in {"resolution_check_due", "close_time_passed"}
        or reason.startswith("close_time_within_")
        for reason in reasons
    ):
        return f"forecast resolve {question_id} --outcome <value>"
    if "no_evidence" in reasons or any(
        reason.startswith("evidence_stale_") for reason in reasons
    ):
        return f"forecast research {question_id}"
    if any(
        reason.startswith(("assumption_", "reference_class_")) for reason in reasons
    ):
        return f"forecast protocol {question_id} --stage self_check"
    if "review_due" in reasons or any(
        reason.startswith("last_update_") for reason in reasons
    ):
        return f"forecast research {question_id}; forecast update {question_id} --preview ..."
    return f"forecast show {question_id}"


def _format_metric(value: float | None) -> str:
    return "-" if value is None else f"{value:.6f}"


def _parse_day_count(value: str) -> int:
    raw = str(value).strip().lower()
    if raw.endswith("d"):
        raw = raw[:-1]
    days = int(raw)
    if days < 0:
        raise argparse.ArgumentTypeError("day count must be non-negative")
    return days


def add_scoring_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("id")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--baselines",
        action="store_true",
        help="Also score imported market/crowd/baseline comparisons without changing the current forecast",
    )


def format_scoring(result: ScoringResult) -> str:
    score = result.score
    lines = [
        f"score: {score.id}",
        f"brier_score: {_format_metric(score.brier_score)}",
        f"log_score: {_format_metric(score.log_score)}",
        f"proper_score: {_format_metric(score.proper_score)}",
        f"score_rule: {score.score_rule or '-'}",
        f"bucket: {score.calibration_bucket or '-'}",
        f"origin: {score.forecast_origin}",
    ]
    if result.baselines is not None:
        lines.append(f"baseline_scores: {len(result.baselines) or 'none'}")
        for baseline in result.baselines:
            value = baseline["score"]
            name = f"{baseline['baseline_type']}:{baseline['source']}"
            lines.append(
                f"  {baseline['id']} {name} "
                f"brier={_format_metric(value.brier_score)} "
                f"log={_format_metric(value.log_score)} origin={value.forecast_origin}"
            )
    return "\n".join(lines)


def add_resolution_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("id")
    parser.add_argument("--outcome", required=True)
    parser.add_argument("--source", "--resolution-source", dest="resolution_source")
    parser.add_argument("--source-snapshot-ref", dest="resolution_source_snapshot_ref")
    parser.add_argument(
        "--resolver-type",
        choices=["manual", "source_adapter", "scheduled_check"],
        default="manual",
    )
    parser.add_argument(
        "--status",
        dest="resolution_status",
        choices=["proposed", "confirmed", "disputed", "corrected"],
        default="confirmed",
    )
    parser.add_argument(
        "--confirmed",
        dest="resolution_status",
        action="store_const",
        const="confirmed",
        help="Alias for --status confirmed",
    )
    parser.add_argument(
        "--criteria-satisfied",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--confidence", type=float)
    parser.add_argument("--confirmed-by")
    parser.add_argument("--notes", dest="resolver_notes")
    parser.add_argument("--correction-ref")
    parser.add_argument("--trusted-policy")
    parser.add_argument("--not-scoreable", action="store_true")
    parser.add_argument(
        "--auto-score",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Automatically score the current live snapshot on a confirmed, criteria-satisfied resolution (default on; --no-auto-score to defer).",
    )


def add_review_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--stale", action="store_true")
    parser.add_argument("--last", dest="last_days", type=_parse_day_count, default=7)
    parser.add_argument("--domain")
    parser.add_argument("--topic")
    parser.add_argument(
        "--horizon", help="Filter by forecast horizon in days, e.g. 30 or 30-90"
    )
    parser.add_argument("--confidence-below", type=float)
    parser.add_argument("--confidence-above", type=float)
    parser.add_argument("--large-delta-threshold", type=float)
    parser.add_argument("--now")


def format_review(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No forecasts need review."
    lines = [
        "ID             P(now)    As of                 Close                Priority  Reasons              Title"
    ]
    for row in rows:
        question, snapshot = row["question"], row["current_snapshot"]
        probability = (
            _format_probability(snapshot.probability_or_distribution)
            if snapshot
            else "-"
        )
        as_of = snapshot.as_of if snapshot else "-"
        close = question.close_time or "-"
        reasons = ",".join(row["reasons"]) or "active"
        lines.append(
            f"{question.id:<14} {probability:<9} {as_of:<20} {close:<20} "
            f"{row.get('priority', 9):<9} {reasons:<20} {question.title}"
        )
        lines.append(f"  next: {_review_next_action(question.id, row['reasons'])}")
    return "\n".join(lines)


def format_resolution(result: ResolutionResult) -> str:
    resolution, score = result.resolution, result.score
    lines = [
        f"recorded resolution {resolution.id}",
        f"status: {resolution.resolution_status}",
        f"criteria_satisfied: {resolution.criteria_satisfied}",
    ]
    if score is not None:
        lines.append(
            f"auto_score: brier={_format_metric(score.brier_score)} "
            f"log={_format_metric(score.log_score)} origin={score.forecast_origin}"
        )
    if result.retrospective:
        headline = result.retrospective.get("headline") or result.retrospective.get(
            "body", ""
        )
        if headline:
            lines.append(f"retrospective: {headline[:80]}")
    return "\n".join(lines)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValidationError(message)


def execute_operation(
    ledger: ForecastLedger, operation: str, arg: str | list[str]
) -> dict[str, Any]:
    """Parse a terminal command without process-global stdout/exit side effects."""
    if operation not in {"review", "resolve", "score"}:
        raise ValidationError("operation must be review, resolve or score")
    parser = _Parser(prog=f"forecast {operation}", add_help=False)
    {
        "review": add_review_arguments,
        "resolve": add_resolution_arguments,
        "score": add_scoring_arguments,
    }[operation](parser)
    try:
        argv = list(arg) if isinstance(arg, list) else split_forecast_cli_args(arg)
        if argv in (["--help"], ["-h"]):
            return {"code": 0, "output": parser.format_help(), "data": None}
        values = vars(parser.parse_args(argv))
        if operation == "review":
            rows = review_forecasts(ledger, **values)
            data = [
                {
                    **row,
                    "question": asdict(row["question"]),
                    "current_snapshot": asdict(row["current_snapshot"])
                    if row["current_snapshot"]
                    else None,
                }
                for row in rows
            ]
            return {"code": 0, "output": format_review(rows), "data": {"rows": data}}
        values["question_id"] = values.pop("id")
        if operation == "score":
            scored = score_forecast(ledger, values)
            return {"code": 0, "output": format_scoring(scored), "data": asdict(scored)}
        values["scoreable"] = not values.pop("not_scoreable")
        values["trusted_policy_id"] = values.pop("trusted_policy")
        result = resolve_forecast(ledger, values)
        return {"code": 0, "output": format_resolution(result), "data": asdict(result)}
    except (ForecastingError, ValueError) as exc:
        return {"code": 2, "output": str(exc), "data": None}
