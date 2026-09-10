"""Market records for evidence source adapters."""

from __future__ import annotations

from dataclasses import dataclass

from forecasting.models import OutcomeSpace


@dataclass(frozen=True)
class CoinGeckoMarketSnapshot:
    coin_id: str
    symbol: str | None
    name: str | None
    vs_currency: str
    current_price: float | str | None
    market_cap: float | int | str | None
    market_cap_rank: int | None
    total_volume: float | int | str | None
    price_change_percentage_24h: float | str | None
    last_updated: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class ManifoldMarketImport:
    market_id: str | None
    slug: str | None
    question: str
    description: str
    url: str | None
    outcome_space: OutcomeSpace
    probability: float | None
    distribution: dict[str, float] | None
    close_time: str | None
    resolution_time: str | None
    resolution: str | None
    is_resolved: bool
    as_of: str | None
    raw: dict

    @property
    def baseline_source(self) -> str:
        return f"manifold:{self.slug or self.market_id or 'market'}"

    @property
    def resolution_criteria(self) -> str:
        if self.description:
            return self.description
        return "Resolved according to the linked Manifold market and its creator's resolution rules."

    def baseline_payload(self) -> dict[str, object] | None:
        value = self.distribution if self.distribution is not None else self.probability
        if value is None:
            return None
        return {
            "source": self.baseline_source,
            "baseline_type": "market",
            "probability_or_distribution": value,
            "as_of": self.as_of,
        }


@dataclass(frozen=True)
class MetaculusQuestionImport:
    question_id: str | None
    title: str
    description: str
    resolution_criteria_text: str
    url: str | None
    outcome_space: OutcomeSpace
    probability: float | None
    distribution: dict[str, float] | None
    close_time: str | None
    resolution_time: str | None
    resolution: str | None
    status: str | None
    as_of: str | None
    raw: dict

    @property
    def baseline_source(self) -> str:
        return f"metaculus:{self.question_id or 'question'}"

    @property
    def resolution_criteria(self) -> str:
        if self.resolution_criteria_text:
            return self.resolution_criteria_text
        return "Resolved according to the linked Metaculus question and its resolution criteria."

    def baseline_payload(self) -> dict[str, object] | None:
        value = self.distribution if self.distribution is not None else self.probability
        if value is None:
            return None
        return {
            "source": self.baseline_source,
            "baseline_type": "crowd",
            "probability_or_distribution": value,
            "as_of": self.as_of,
        }


@dataclass(frozen=True)
class PolymarketMarketImport:
    market_id: str | None
    slug: str | None
    question: str
    description: str
    url: str | None
    outcome_space: OutcomeSpace
    probability: float | None
    distribution: dict[str, float] | None
    close_time: str | None
    resolution_time: str | None
    as_of: str | None
    raw: dict

    @property
    def baseline_source(self) -> str:
        return f"polymarket:{self.slug or self.market_id or 'market'}"

    @property
    def resolution_criteria(self) -> str:
        if self.description:
            return self.description
        return "Resolved according to the linked Polymarket market and its settlement rules."

    def baseline_payload(self) -> dict[str, object] | None:
        value = self.distribution if self.distribution is not None else self.probability
        if value is None:
            return None
        return {
            "source": self.baseline_source,
            "baseline_type": "market",
            "probability_or_distribution": value,
            "as_of": self.as_of,
        }


@dataclass(frozen=True)
class KalshiMarketImport:
    ticker: str | None
    event_ticker: str | None
    question: str
    description: str
    url: str | None
    outcome_space: OutcomeSpace
    probability: float | None
    close_time: str | None
    resolution_time: str | None
    status: str | None
    result: str | None
    as_of: str | None
    raw: dict

    @property
    def baseline_source(self) -> str:
        return f"kalshi:{self.ticker or 'market'}"

    @property
    def resolution_criteria(self) -> str:
        if self.description:
            return self.description
        return "Resolved according to the linked Kalshi market and its settlement rules."

    def baseline_payload(self) -> dict[str, object] | None:
        if self.probability is None:
            return None
        return {
            "source": self.baseline_source,
            "baseline_type": "market",
            "probability_or_distribution": self.probability,
            "as_of": self.as_of,
        }
