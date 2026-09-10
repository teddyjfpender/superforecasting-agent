"""Pure Manifold endpoint, outcome, and description parsing."""
from __future__ import annotations
from .market_records import ManifoldMarketImport
from .values import _optional_str
from datetime import timezone
from urllib.parse import quote, urlparse
from forecasting.models import OutcomeSpace, ValidationError
from .values import _optional_float

def _manifold_endpoint_for_source(source: str, *, api_base_url: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        if parsed.netloc == "api.manifold.markets":
            return source
        if parsed.netloc.endswith("manifold.markets"):
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2:
                slug = parts[-1]
                return f"{api_base_url.rstrip('/')}/slug/{quote(slug)}"
            raise ValidationError("manifold market URL must include a market slug")
        return source
    if source.startswith("id:"):
        market_id = source.split(":", 1)[1].strip()
        if not market_id:
            raise ValidationError("manifold market id is empty")
        return f"{api_base_url.rstrip('/')}/market/{quote(market_id)}"
    if source.startswith("slug:"):
        slug = source.split(":", 1)[1].strip()
    else:
        slug = source
    if not slug:
        raise ValidationError("manifold market slug is empty")
    return f"{api_base_url.rstrip('/')}/slug/{quote(slug)}"


def _manifold_distribution(payload: dict) -> dict[str, float] | None:
    answers = payload.get("answers")
    if not isinstance(answers, list):
        return None
    distribution: dict[str, float] = {}
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        probability = _optional_float(answer.get("probability"))
        text = str(answer.get("text") or answer.get("number") or answer.get("id") or "").strip()
        if text and probability is not None:
            distribution[text] = probability
    return distribution or None


def _manifold_outcome_space(
    outcome_type: str,
    distribution: dict[str, float] | None,
    payload: dict,
) -> OutcomeSpace:
    if outcome_type == "BINARY":
        return OutcomeSpace(type="binary")
    if distribution:
        return OutcomeSpace(type="categorical", choices=list(distribution.keys()))
    if outcome_type in {"PSEUDO_NUMERIC", "NUMERIC"}:
        return OutcomeSpace(
            type="numeric",
            units="manifold_value",
            bounds=(
                [_optional_float(payload.get("min")), _optional_float(payload.get("max"))]
                if payload.get("min") is not None and payload.get("max") is not None
                else []
            ),
        )
    return OutcomeSpace(type="distribution", choices=[])


def _manifold_description(payload: dict) -> str:
    text_description = payload.get("textDescription")
    if isinstance(text_description, str) and text_description.strip():
        return text_description.strip()
    description = payload.get("description")
    if isinstance(description, str):
        return description.strip()
    if isinstance(description, dict):
        text = " ".join(_extract_rich_text(description))
        return " ".join(text.split())
    return ""


def _extract_rich_text(node: object) -> list[str]:
    if isinstance(node, dict):
        parts: list[str] = []
        text = node.get("text")
        if isinstance(text, str):
            parts.append(text)
        content = node.get("content")
        if isinstance(content, list):
            for child in content:
                parts.extend(_extract_rich_text(child))
        return parts
    if isinstance(node, list):
        parts = []
        for child in node:
            parts.extend(_extract_rich_text(child))
        return parts
    return []


def _manifold_ms_to_iso(value: object) -> str | None:
    number = _optional_float(value)
    if number is None:
        return None
    from datetime import datetime

    try:
        return datetime.fromtimestamp(number / 1000, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return None


def _manifold_market_from_payload(payload: dict, source: str) -> ManifoldMarketImport:
    question = str(payload.get("question") or "").strip()
    if not question:
        raise ValidationError("manifold market response is missing question")
    outcome_type = str(payload.get("outcomeType") or "BINARY").upper()
    probability = _optional_float(payload.get("probability"))
    distribution = _manifold_distribution(payload)
    outcome_space = _manifold_outcome_space(outcome_type, distribution, payload)
    return ManifoldMarketImport(
        market_id=_optional_str(payload.get("id")),
        slug=_optional_str(payload.get("slug")),
        question=question,
        description=_manifold_description(payload),
        url=_optional_str(payload.get("url")) or source,
        outcome_space=outcome_space,
        probability=probability if outcome_space.type == "binary" else None,
        distribution=distribution,
        close_time=_manifold_ms_to_iso(payload.get("closeTime")),
        resolution_time=_manifold_ms_to_iso(payload.get("resolutionTime")),
        resolution=_optional_str(payload.get("resolution")),
        is_resolved=bool(payload.get("isResolved")),
        as_of=_manifold_ms_to_iso(
            payload.get("lastUpdatedTime")
            or payload.get("lastBetTime")
            or payload.get("closeTime")
            or payload.get("createdTime")
        ),
        raw=payload,
    )


def _manifold_market_to_benchmark_case(market: ManifoldMarketImport) -> dict[str, object] | None:
    if market.outcome_space.type != "binary" or not market.is_resolved:
        return None
    resolution = (market.resolution or "").upper()
    if resolution not in {"YES", "NO"}:
        return None
    baseline = market.baseline_payload()
    if baseline is None:
        return None
    as_of = _manifold_ms_to_iso(market.raw.get("lastBetTime")) or market.close_time or market.as_of
    if not as_of:
        return None
    return {
        "id": f"manifold:{market.market_id or market.slug or market.question}",
        "title": market.question,
        "description": market.description,
        "resolution_criteria": market.resolution_criteria,
        "resolution_source": market.url,
        "as_of": as_of,
        "simulated_forecast_time": as_of,
        "evidence_cutoff": as_of,
        "close_time": market.close_time,
        "resolution_time": market.resolution_time,
        "outcome": "yes" if resolution == "YES" else "no",
        "domain": "prediction_markets",
        "topics": ["manifold"],
        "evidence": [
            {
                "source": market.url or market.baseline_source,
                "source_name": "Manifold",
                "source_type": "adapter:manifold",
                "url": market.url,
                "claim": market.question,
                "summary": market.description,
                "available_at": as_of,
                "claim_type": "estimate",
                "stance": "context",
            }
        ],
        "baselines": [
            {
                "source": "manifold",
                "baseline_type": baseline["baseline_type"],
                "probability": baseline["probability_or_distribution"],
                "as_of": as_of,
            }
        ],
        "notes": (
            "Manifold resolved-market benchmark case. Market probability is "
            "stored as an external baseline, not as an agent forecast."
        ),
    }
