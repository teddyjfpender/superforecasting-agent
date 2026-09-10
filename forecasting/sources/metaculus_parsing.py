"""Pure question metadata and prediction parsing for Metaculus."""

from __future__ import annotations
from .market_records import MetaculusQuestionImport

from forecasting.sources.dates import _optional_prediction_timestamp

from urllib.parse import quote, urlparse
from forecasting.models import OutcomeSpace, ValidationError
from .values import _first_present, _optional_float, _optional_str

def _metaculus_endpoint_for_source(source: str, *, api_base_url: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        if parsed.netloc.endswith("metaculus.com"):
            if parsed.path.startswith(("/api/", "/api2/")):
                return source
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[0] == "questions":
                return f"{api_base_url.rstrip('/')}/questions/{quote(parts[1])}/"
            raise ValidationError("metaculus URL must include a question id")
        return source
    question_id = source.removeprefix("id:").strip()
    if not question_id:
        raise ValidationError("metaculus question id is empty")
    return f"{api_base_url.rstrip('/')}/questions/{quote(question_id)}/"


def _metaculus_choices(payload: dict) -> list[str]:
    for key in ("possibilities", "options", "choices"):
        value = payload.get(key)
        if isinstance(value, dict):
            choices = [str(item).strip() for item in value.values() if str(item).strip()]
            if choices:
                return choices
        if isinstance(value, list):
            choices: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    text = _first_present(item.get("label"), item.get("name"), item.get("title"), item.get("text"))
                else:
                    text = item
                if text is not None and str(text).strip():
                    choices.append(str(text).strip())
            if choices:
                return choices
    return []


def _metaculus_forecast_value(payload: dict, choices: list[str]) -> float | dict[str, float] | None:
    candidates: list[object] = [
        payload.get("community_prediction"),
        payload.get("community_prediction_stats"),
        payload.get("prediction"),
    ]
    aggregations = payload.get("aggregations")
    if isinstance(aggregations, dict):
        for key in ("recency_weighted", "community", "unweighted", "metaculus_prediction"):
            candidates.append(aggregations.get(key))
    for candidate in candidates:
        value = _metaculus_extract_prediction_value(candidate, choices)
        if value is not None:
            return value
    return None


def _metaculus_extract_prediction_value(value: object, choices: list[str]) -> float | dict[str, float] | None:
    probability = _optional_float(value)
    if probability is not None and 0 <= probability <= 1:
        return probability
    if isinstance(value, list):
        probabilities = [_optional_float(item) for item in value]
        if len(probabilities) == 1 and probabilities[0] is not None and 0 <= probabilities[0] <= 1:
            return probabilities[0]
        if choices and len(probabilities) >= len(choices):
            selected = probabilities[:len(choices)]
            if all(item is not None for item in selected):
                return dict(zip(choices, selected))
        return None
    if not isinstance(value, dict):
        return None
    for key in ("latest", "full", "center", "centers", "forecast_values"):
        if key in value:
            extracted = _metaculus_extract_prediction_value(value.get(key), choices)
            if extracted is not None:
                return extracted
    for key in ("probability", "probability_yes", "median", "q2", "mean", "value", "prediction"):
        if key in value:
            number = _optional_float(value.get(key))
            if number is not None and 0 <= number <= 1:
                return number
    if choices:
        distribution: dict[str, float] = {}
        lowered = {choice.lower(): choice for choice in choices}
        for key, raw_probability in value.items():
            match = lowered.get(str(key).strip().lower())
            number = _optional_float(raw_probability)
            if match and number is not None:
                distribution[match] = number
        if distribution:
            return distribution
    return None


def _metaculus_outcome_space(
    payload: dict,
    choices: list[str],
    probability: float | None,
    distribution: dict[str, float] | None,
) -> OutcomeSpace:
    raw_type = str(_first_present(payload.get("type"), payload.get("question_type")) or "").lower()
    if "binary" in raw_type or probability is not None:
        return OutcomeSpace(type="binary")
    if "multiple" in raw_type or "choice" in raw_type or distribution:
        return OutcomeSpace(type="categorical", choices=choices or list((distribution or {}).keys()))
    if "numeric" in raw_type or "date" in raw_type or "continuous" in raw_type:
        scaling = payload.get("scaling") if isinstance(payload.get("scaling"), dict) else {}
        bounds = [
            bound
            for bound in (
                _optional_float(scaling.get("range_min")),
                _optional_float(scaling.get("range_max")),
            )
            if bound is not None
        ]
        return OutcomeSpace(type="numeric", bounds=bounds, units=_optional_str(scaling.get("unit")))
    return OutcomeSpace(type="distribution", choices=choices)


def _metaculus_description(question_payload: dict, root_payload: dict) -> str:
    value = _first_present(
        question_payload.get("description"),
        question_payload.get("body"),
        question_payload.get("text"),
        root_payload.get("description"),
    )
    return str(value or "").strip()


def _metaculus_public_url(question_payload: dict, root_payload: dict, source: str) -> str | None:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc.endswith("metaculus.com") and not parsed.path.startswith(("/api/", "/api2/")):
        return source
    question_id = _optional_str(_first_present(question_payload.get("id"), root_payload.get("id")))
    return f"https://www.metaculus.com/questions/{question_id}/" if question_id else None


def _metaculus_timestamp(value: object) -> str | None:
    return _optional_prediction_timestamp(value, field_name="metaculus timestamp")


def _metaculus_resolution_to_outcome(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"yes", "true", "1", "1.0", "resolved_yes"}:
        return "yes"
    if normalized in {"no", "false", "0", "0.0", "resolved_no"}:
        return "no"
    return None


def _metaculus_question_from_payload(payload: dict, source: str) -> MetaculusQuestionImport:
    question_payload = payload.get("question") if isinstance(payload.get("question"), dict) else payload
    title = str(
        _first_present(
            question_payload.get("title"),
            question_payload.get("question"),
            payload.get("title"),
        )
        or ""
    ).strip()
    if not title:
        raise ValidationError("metaculus question response is missing title")
    choices = _metaculus_choices(question_payload)
    forecast_value = _metaculus_forecast_value(question_payload, choices)
    probability = forecast_value if isinstance(forecast_value, float) else None
    distribution = forecast_value if isinstance(forecast_value, dict) else None
    outcome_space = _metaculus_outcome_space(question_payload, choices, probability, distribution)

    return MetaculusQuestionImport(
        question_id=_optional_str(_first_present(question_payload.get("id"), payload.get("id"))),
        title=title,
        description=_metaculus_description(question_payload, payload),
        resolution_criteria_text=str(
            _first_present(
                question_payload.get("resolution_criteria"),
                question_payload.get("fine_print"),
                question_payload.get("resolution"),
                payload.get("resolution_criteria"),
            )
            or ""
        ).strip(),
        url=_optional_str(payload.get("url")) or _metaculus_public_url(question_payload, payload, source),
        outcome_space=outcome_space,
        probability=probability if outcome_space.type == "binary" else None,
        distribution=distribution if outcome_space.type != "binary" else None,
        close_time=_metaculus_timestamp(
            _first_present(
                question_payload.get("close_time"),
                question_payload.get("scheduled_close_time"),
                question_payload.get("closes_at"),
            )
        ),
        resolution_time=_metaculus_timestamp(
            _first_present(
                question_payload.get("resolve_time"),
                question_payload.get("scheduled_resolve_time"),
                question_payload.get("resolved_at"),
                question_payload.get("actual_resolve_time"),
            )
        ),
        resolution=_optional_str(
            _first_present(
                question_payload.get("resolution"),
                question_payload.get("resolve_value"),
                question_payload.get("actual_resolution"),
            )
        ),
        status=_optional_str(question_payload.get("status")),
        as_of=_metaculus_timestamp(
            _first_present(
                question_payload.get("last_prediction_time"),
                question_payload.get("publish_time"),
                question_payload.get("created_time"),
                payload.get("published_at"),
            )
        ),
        raw=payload,
    )


def _metaculus_question_to_benchmark_case(question: MetaculusQuestionImport) -> dict[str, object] | None:
    if question.outcome_space.type != "binary":
        return None
    outcome = _metaculus_resolution_to_outcome(question.resolution)
    if outcome is None:
        return None
    baseline = question.baseline_payload()
    if baseline is None:
        return None
    as_of = question.as_of or question.close_time
    if not as_of:
        return None
    return {
        "id": f"metaculus:{question.question_id or question.title}",
        "title": question.title,
        "description": question.description,
        "resolution_criteria": question.resolution_criteria,
        "resolution_source": question.url,
        "as_of": as_of,
        "simulated_forecast_time": as_of,
        "evidence_cutoff": as_of,
        "close_time": question.close_time,
        "resolution_time": question.resolution_time,
        "outcome": outcome,
        "domain": "forecasting_platforms",
        "topics": ["metaculus"],
        "evidence": [
            {
                "source": question.url or question.baseline_source,
                "source_name": "Metaculus",
                "source_type": "adapter:metaculus",
                "url": question.url,
                "claim": question.title,
                "summary": question.description,
                "available_at": as_of,
                "claim_type": "estimate",
                "stance": "context",
            }
        ],
        "baselines": [
            {
                "source": "metaculus",
                "baseline_type": baseline["baseline_type"],
                "probability": baseline["probability_or_distribution"],
                "as_of": as_of,
            }
        ],
        "notes": (
            "Metaculus resolved-question benchmark case. Crowd probability is "
            "stored as an external baseline, not as an agent forecast."
        ),
    }
