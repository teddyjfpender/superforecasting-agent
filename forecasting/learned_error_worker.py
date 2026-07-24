"""Bounded, auditable reviews of learned domain-error alerts."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Callable

from forecasting.learning import is_learned_error_review_reason, learned_error_profile_id
from forecasting.models import ValidationError, json_dumps


SYSTEM_PROMPT = """You review learned error profiles against one current forecast.
Return one JSON object and no prose with: assessment (at least 20 characters) and
decision (reviewed_no_change or update_required). Compare the profile's recurring
errors and adjustments to the forecast's current reasoning. Do not edit the ledger
or invent evidence. Choose update_required when the profile exposes a concrete
reason the current forecast must be refreshed; otherwise explain why no change is
warranted."""


def run_learned_error_reviews(
    ledger,
    *,
    owner: str,
    reviewer: Callable[[dict[str, Any]], dict[str, Any]],
    limit: int = 2,
    now: str | None = None,
) -> list[dict[str, Any]]:
    """Review oldest unique questions and persist reasoning before closing alerts."""
    if not callable(reviewer):
        raise ValidationError("a learned-error reviewer callback is required")
    alerts = sorted(
        (
            alert
            for alert in ledger.list_alerts(unresolved_only=True)
            if alert.scope_type == "question"
            and is_learned_error_review_reason(alert.reason)
        ),
        key=lambda alert: (alert.created_at, alert.id),
    )
    question_ids = list(dict.fromkeys(alert.scope_ref for alert in alerts))[: max(int(limit), 0)]
    results: list[dict[str, Any]] = []
    for question_id in question_ids:
        try:
            question = ledger.get_question(question_id)
            current = ledger.get_current_snapshot(question_id)
            if current is None:
                raise ValidationError("learned-error review requires a current forecast")
            question_alerts = [alert for alert in alerts if alert.scope_ref == question_id]
            profile_ids = list(
                dict.fromkeys(
                    profile_id
                    for alert in question_alerts
                    if (profile_id := learned_error_profile_id(alert.reason)) is not None
                )
            )
            payload = {
                "question": asdict(question),
                "current_forecast": asdict(current),
                "alerts": [asdict(alert) for alert in question_alerts],
                "profiles": [ledger.get_domain_error_profile(profile_id) for profile_id in profile_ids],
                "reference_classes": ledger.list_reference_classes(question_id),
            }
            review = reviewer(payload)
            if not isinstance(review, dict):
                raise ValidationError("learned-error reviewer must return an object")
            persisted = ledger.review_learned_error_alerts(
                question_id,
                reviewed_by=owner,
                assessment=str(review.get("assessment") or ""),
                decision=str(review.get("decision") or "reviewed_no_change"),
                now=now,
            )
            results.append({"question_id": question_id, "status": "reviewed", "result": persisted})
        except Exception as exc:
            results.append({"question_id": question_id, "status": "failed", "error": str(exc)})
    return results


def build_agent_learned_error_reviewer(
    *,
    model: str | None = None,
    provider: str | None = None,
    max_iterations: int = 8,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build the hosted reviewer while preserving the configured model."""
    if not model:
        from forecasting.quorum_autorun import resolve_active_model_id
        from hermes_cli.config import load_config

        model = resolve_active_model_id(load_config().get("model"))
    if not model:
        raise ValidationError("no active model configured for learned-error review")

    def review(payload: dict[str, Any]) -> dict[str, Any]:
        from agent.agent_factory import build_agent

        agent = build_agent(
            model=model,
            requested_provider=provider,
            enabled_toolsets=[],
            max_iterations=max(int(max_iterations), 1),
            quiet_mode=True,
            skip_memory=True,
            skip_context_files=True,
            load_soul_identity=False,
            platform="cron",
        )
        result = agent.run_conversation(
            "Review this exact persisted forecast and learned-error context:\n\n"
            + json_dumps(payload),
            system_message=SYSTEM_PROMPT,
        )
        result_dict = result if isinstance(result, dict) else {}
        if not isinstance(result, dict) or result.get("failed") or result.get("error"):
            raise RuntimeError(str(result_dict.get("error") or "learned-error review failed"))
        text = str(result.get("final_response") or "").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise ValidationError("learned-error review did not contain a JSON object")
            parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValidationError("learned-error review must be a JSON object")
        return parsed

    return review
