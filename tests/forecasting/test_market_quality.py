"""Market-liquidity stratification: a thin or stale market price gets an
advisory pooling discount so it can't inflate a tail at full weight."""

from __future__ import annotations

from forecasting.market_quality import (
    MarketReading,
    age_days_from_timestamp,
    classify_market,
    reading_from_evidence,
    recommended_market_weight,
)


class TestClassify:
    def test_liquid_market_keeps_full_weight(self):
        q = classify_market(MarketReading("polymarket:x", volume=120_000, age_days=0.5))
        assert q.tier == "liquid"
        assert q.weight == 1.0

    def test_thin_market_is_discounted(self):
        q = classify_market(MarketReading("manifold:y", volume=300, age_days=1))
        assert q.tier == "thin"
        assert q.weight < 0.5

    def test_placeholder_market_is_near_zero(self):
        q = classify_market(MarketReading("manifold:z", volume=20, age_days=1))
        assert q.tier == "placeholder"
        assert q.weight <= 0.1

    def test_staleness_dominates_depth(self):
        # Deep but not traded in 3 weeks → stale, not liquid.
        q = classify_market(MarketReading("kalshi:w", volume=80_000, age_days=20))
        assert q.tier == "stale"
        assert q.weight <= 0.25

    def test_binding_constraint_wins(self):
        # Thin AND stale → the lower (stale=0.25 vs thin=0.35) binds via tier order.
        q = classify_market(MarketReading("m", volume=300, age_days=30))
        assert q.tier == "stale"

    def test_unknown_volume_and_recency_default_moderate(self):
        q = classify_market(MarketReading("m"))
        assert q.tier == "moderate"
        assert 0 < q.weight < 1

    def test_recommended_weight_helper(self):
        assert recommended_market_weight(MarketReading("m", volume=120_000, age_days=0.1)) == 1.0


class TestTimestampAge:
    def test_age_days_from_timestamp(self):
        age = age_days_from_timestamp("2026-06-01T00:00:00Z", now="2026-06-08T00:00:00Z")
        assert age == 7.0

    def test_missing_timestamp_is_none(self):
        assert age_days_from_timestamp(None) is None
        assert age_days_from_timestamp("not-a-date") is None


class TestReadingFromEvidence:
    def test_reads_volume_and_recency_from_row(self):
        row = {
            "source": "polymarket:slug",
            "probability": 0.43,
            "volume": 90_000,
            "updated_at": "2026-06-01T00:00:00Z",
        }
        reading = reading_from_evidence(row, now="2026-06-02T00:00:00Z")
        assert reading.source == "polymarket:slug"
        assert reading.volume == 90_000
        assert reading.age_days == 1.0
        assert classify_market(reading).tier == "liquid"

    def test_falls_back_to_total_volume(self):
        reading = reading_from_evidence({"source": "m", "total_volume": 7000})
        assert reading.volume == 7000
