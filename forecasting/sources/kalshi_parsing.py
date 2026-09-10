"""Pure Kalshi endpoint, price, and metadata parsing."""
from __future__ import annotations
from .market_records import KalshiMarketImport
from forecasting.models import OutcomeSpace
from urllib.parse import quote, urlparse
from forecasting.models import ValidationError
from .dates import _optional_prediction_timestamp
from .values import _first_present, _optional_float, _optional_str

def _kalshi_endpoint_for_source(source: str, *, api_base_url: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        if parsed.netloc == "external-api.kalshi.com":
            return source
        if parsed.netloc.endswith("kalshi.com"):
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[0].lower() == "markets":
                ticker = parts[-1].upper()
                return f"{api_base_url.rstrip('/')}/markets/{quote(ticker)}"
            raise ValidationError("kalshi market URL must include a market ticker")
        return source
    ticker = source.removeprefix("ticker:").strip().upper()
    if not ticker:
        raise ValidationError("kalshi market ticker is empty")
    return f"{api_base_url.rstrip('/')}/markets/{quote(ticker)}"


def _kalshi_yes_probability(payload: dict) -> float | None:
    bid = _kalshi_price(
        _first_present(
            payload.get("yes_bid"),
            payload.get("yes_bid_cents"),
            payload.get("yes_bid_dollars"),
        )
    )
    ask = _kalshi_price(
        _first_present(
            payload.get("yes_ask"),
            payload.get("yes_ask_cents"),
            payload.get("yes_ask_dollars"),
        )
    )
    if bid is not None and ask is not None:
        return (bid + ask) / 2
    last = _kalshi_price(
        _first_present(
            payload.get("last_price"),
            payload.get("last_price_cents"),
            payload.get("last_price_dollars"),
        )
    )
    if last is not None:
        return last
    if bid is not None:
        return bid
    return ask


def _kalshi_previous_yes_probability(payload: dict) -> float | None:
    previous = _kalshi_price(
        _first_present(
            payload.get("previous_price"),
            payload.get("previous_price_cents"),
            payload.get("previous_price_dollars"),
        )
    )
    if previous is not None:
        return previous
    previous_bid = _kalshi_price(
        _first_present(
            payload.get("previous_yes_bid"),
            payload.get("previous_yes_bid_cents"),
            payload.get("previous_yes_bid_dollars"),
        )
    )
    previous_ask = _kalshi_price(
        _first_present(
            payload.get("previous_yes_ask"),
            payload.get("previous_yes_ask_cents"),
            payload.get("previous_yes_ask_dollars"),
        )
    )
    if previous_bid is not None and previous_ask is not None:
        return (previous_bid + previous_ask) / 2
    if previous_bid is not None:
        return previous_bid
    return previous_ask


def _kalshi_price(value: object) -> float | None:
    number = _optional_float(value)
    if number is None:
        return None
    if number > 1:
        number = number / 100
    return max(0.0, min(1.0, number))


def _kalshi_description(payload: dict) -> str:
    parts = [
        _optional_str(payload.get("rules_primary")),
        _optional_str(payload.get("rules_secondary")),
        _optional_str(payload.get("settlement_sources")),
        _optional_str(payload.get("subtitle")),
    ]
    return "\n\n".join(part for part in parts if part)


def _kalshi_public_url(payload: dict) -> str | None:
    ticker = _optional_str(payload.get("ticker"))
    return f"https://kalshi.com/markets/{ticker.lower()}" if ticker else None


def _kalshi_timestamp(value: object) -> str | None:
    return _optional_prediction_timestamp(value, field_name="kalshi timestamp")


def _kalshi_resolution_to_outcome(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"yes", "true"}:
        return "yes"
    if normalized in {"no", "false"}:
        return "no"
    numeric = _optional_float(normalized)
    if numeric is None:
        return None
    if numeric >= 0.999:
        return "yes"
    if numeric <= 0.001:
        return "no"
    return None


def _kalshi_market_from_payload(payload: dict) -> KalshiMarketImport:
    question = str(payload.get("title") or payload.get("question") or "").strip()
    if not question:
        raise ValidationError("kalshi market response is missing title")
    ticker = _optional_str(payload.get("ticker"))
    probability = _kalshi_yes_probability(payload)
    return KalshiMarketImport(
        ticker=ticker,
        event_ticker=_optional_str(payload.get("event_ticker")),
        question=question,
        description=_kalshi_description(payload),
        url=_optional_str(payload.get("url")) or _kalshi_public_url(payload),
        outcome_space=OutcomeSpace(type="binary"),
        probability=probability,
        close_time=_kalshi_timestamp(
            _first_present(
                payload.get("close_time"),
                payload.get("expiration_time"),
                payload.get("expected_expiration_time"),
            )
        ),
        resolution_time=_kalshi_timestamp(
            _first_present(
                payload.get("settlement_time"),
                payload.get("expiration_time"),
                payload.get("expected_expiration_time"),
                payload.get("latest_expiration_time"),
            )
        ),
        status=_optional_str(payload.get("status")),
        result=_optional_str(
            _first_present(
                payload.get("result"),
                payload.get("settlement_value"),
                payload.get("settlement_value_dollars"),
                payload.get("yes_settlement_value_dollars"),
            )
        ),
        as_of=_kalshi_timestamp(
            _first_present(
                payload.get("updated_time"),
                payload.get("last_update_time"),
                payload.get("last_update_ts"),
            )
        ),
        raw=payload,
    )


def _kalshi_market_to_benchmark_case(market: KalshiMarketImport) -> dict[str, object] | None:
    if market.outcome_space.type != "binary":
        return None
    outcome = _kalshi_resolution_to_outcome(market.result)
    if outcome is None:
        return None
    probability = _kalshi_previous_yes_probability(market.raw)
    if probability is None:
        probability = market.probability
    if probability is None:
        return None
    as_of = (
        _kalshi_timestamp(
            _first_present(
                market.raw.get("last_trade_time"),
                market.raw.get("last_trade_ts"),
                market.raw.get("last_price_time"),
            )
        )
        or market.close_time
        or market.as_of
    )
    if not as_of:
        return None
    return {
        "id": f"kalshi:{market.ticker or market.question}",
        "title": market.question,
        "description": market.description,
        "resolution_criteria": market.resolution_criteria,
        "resolution_source": market.url,
        "as_of": as_of,
        "simulated_forecast_time": as_of,
        "evidence_cutoff": as_of,
        "close_time": market.close_time,
        "resolution_time": market.resolution_time,
        "outcome": outcome,
        "domain": "prediction_markets",
        "topics": ["kalshi"],
        "evidence": [
            {
                "source": market.url or market.baseline_source,
                "source_name": "Kalshi",
                "source_type": "adapter:kalshi",
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
                "source": "kalshi",
                "baseline_type": "market",
                "probability": probability,
                "as_of": as_of,
            }
        ],
        "notes": (
            "Kalshi settled-market benchmark case. Market probability is "
            "stored as an external baseline, not as an agent forecast."
        ),
    }
