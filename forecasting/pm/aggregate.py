"""Collapse a venue event into a discretised distribution (headline + sub-rows).

De-vig uses the same multiplicative normalisation family as
``bayes_toolkit.normalize_categorical_market``: divide each YES mid by the sum
of YES mids so the mutually-exclusive outcomes sum to ~1, and report the removed
overround honestly. Binary (single-market) events pass through untouched.
Zero-liquidity outcomes get probability 0 and rank last.
"""

from __future__ import annotations

from forecasting.pm.model import PMDistribution, PMEvent, PMMarket, PMOutcome


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


# The sane-book band for earned normalisation: a true partition with vig sums
# near 1 (typically 1.00-1.10); far below means missing outcomes, far above a
# malformed book. Outside the band we render raw prices with an honest note.
_NORMALIZE_SUM_LO = 0.85
_NORMALIZE_SUM_HI = 1.25


def devig_yes_mids(mids: dict[str, float]) -> tuple[dict[str, float], float]:
    """Multiplicative de-vig over YES mids → (normalised probs, overround).

    ``overround`` is ``sum(mids) - 1`` (the vig/overround the book carried).
    Mids that are None/≤0 are treated as zero-liquidity and excluded from the
    normalising sum; they surface as probability 0.
    """
    positive = {k: v for k, v in mids.items() if v is not None and v > 0.0}
    total = sum(positive.values())
    if total <= 0.0:
        return {k: 0.0 for k in mids}, 0.0
    normalised = {k: (positive.get(k, 0.0) / total) for k in mids}
    return normalised, total - 1.0


def build_distribution(event: PMEvent) -> PMDistribution:
    """Turn a :class:`PMEvent` into a :class:`PMDistribution`."""
    markets = list(event.markets)
    # Venues carry dead DUPLICATE outcome markets (e.g. two "Robert F.
    # Kennedy Jr." rows — one live, one an untraded placeholder): keep the
    # most liquid market per label so an outcome appears exactly once.
    by_label: dict[str, PMMarket] = {}
    for m in markets:
        key = (m.label or "").strip().lower()
        cur = by_label.get(key)
        if cur is None:
            by_label[key] = m
            continue
        def _liq(x: PMMarket) -> tuple[int, float]:
            return (1 if x.yes_mid is not None else 0, x.volume or 0.0)
        if _liq(m) > _liq(cur):
            by_label[key] = m
    if len(by_label) < len(markets):
        markets = list(by_label.values())
    total_volume = sum((m.volume or 0.0) for m in markets)

    if len(markets) <= 1:
        return _binary_distribution(event, markets[0] if markets else None, total_volume)

    raw_mids: dict[str, float | None] = {}
    for idx, m in enumerate(markets):
        raw_mids[_row_key(m, idx)] = m.yes_mid
    mids_clean = {k: (v if v is not None else 0.0) for k, v in raw_mids.items()}
    book_sum = sum(v for v in mids_clean.values() if v > 0.0)

    # Normalisation must be EARNED. De-vig to sum-to-1 is only valid over a
    # COMPLETE mutually-exclusive partition: an open-ended event (no partition
    # guarantee) or a book whose sum falls outside a sane band (missing/illiquid
    # outcomes, or a truncated listing) rendered to 1.0 would overstate every
    # listed outcome. Outside those conditions we show RAW prices and say so.
    partition_ok = event.mutually_exclusive and _NORMALIZE_SUM_LO <= book_sum <= _NORMALIZE_SUM_HI
    if partition_ok:
        probs, overround = devig_yes_mids(mids_clean)
    else:
        probs = {k: _clamp01(v) for k, v in mids_clean.items()}
        overround = book_sum - 1.0

    outcomes: list[PMOutcome] = []
    for idx, m in enumerate(markets):
        key = _row_key(m, idx)
        mid = m.yes_mid
        liquid = mid is not None and mid > 0.0
        outcomes.append(
            PMOutcome(
                label=m.label,
                prob=_clamp01(probs.get(key, 0.0)),
                raw_prob=_clamp01(mid if mid is not None else 0.0),
                market_id=m.market_id,
                yes_bid=m.yes_bid,
                yes_ask=m.yes_ask,
                volume=m.volume,
                liquid=liquid,
            )
        )
    # Rank by de-vigged probability; illiquid (prob 0) fall to the bottom, and
    # ties break on raw mid then volume for a stable, honest ordering.
    outcomes.sort(key=lambda o: (o.liquid, o.prob, o.raw_prob, o.volume or 0.0), reverse=True)

    notes: list[str] = []
    if any(not o.liquid for o in outcomes):
        notes.append("some outcomes have no live quote (ranked last, prob 0)")
    if partition_ok:
        if abs(overround) > 0.02:
            notes.append(f"removed {overround * 100:+.1f} pts of overround (vig)")
    elif not event.mutually_exclusive:
        notes.append(
            f"outcome list is not a guaranteed partition — raw prices shown (book sums to {book_sum:.2f})"
        )
    else:
        notes.append(
            f"book sums to {book_sum:.2f} — outcome list looks incomplete; raw prices shown"
        )

    return PMDistribution(
        venue=event.venue,
        event_id=event.event_id,
        title=event.title,
        outcomes=tuple(outcomes),
        binary=False,
        overround=overround,
        total_volume=total_volume,
        close_time=event.close_time,
        url=event.url,
        notes=tuple(notes),
        normalized=partition_ok,
    )


def _binary_distribution(
    event: PMEvent, market: PMMarket | None, total_volume: float
) -> PMDistribution:
    if market is None:
        return PMDistribution(
            venue=event.venue,
            event_id=event.event_id,
            title=event.title,
            outcomes=(),
            binary=True,
            total_volume=total_volume,
            close_time=event.close_time,
            url=event.url,
            notes=("event has no markets",),
        )
    mid = market.yes_mid
    prob = _clamp01(mid) if mid is not None else 0.0
    outcome = PMOutcome(
        label=market.label or "Yes",
        prob=prob,
        raw_prob=prob,
        market_id=market.market_id,
        yes_bid=market.yes_bid,
        yes_ask=market.yes_ask,
        volume=market.volume,
        liquid=mid is not None,
    )
    return PMDistribution(
        venue=event.venue,
        event_id=event.event_id,
        title=event.title,
        outcomes=(outcome,),
        binary=True,
        overround=0.0,
        total_volume=total_volume,
        close_time=event.close_time or market.close_time,
        url=event.url or market.url,
    )


def _row_key(market: PMMarket, idx: int) -> str:
    # Labels can repeat/blank across a venue; index-qualify to keep rows distinct.
    return f"{idx}:{market.market_id or market.label}"


__all__ = ["devig_yes_mids", "build_distribution"]
