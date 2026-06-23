"""Typed watched-source roles: the desk must distinguish resolution-critical
sources (resolver/consensus/official_primary) from background RSS, so a lazy
prompter's broad feeds don't get treated like the source that actually resolves
or anchors the question (feedback item #8)."""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger, WATCH_SOURCE_ROLES
from forecasting.models import ValidationError

CRIT = "Resolves yes if the reported value exceeds the stated threshold at the close date."


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "src.db"))
    lg.initialize_schema()
    return lg


def test_watched_source_persists_role(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the metric exceed target by close?", resolution_criteria=CRIT)
    w = lg.add_watched_source(
        scope_type="question", scope_ref=q.id, source="https://example.com/feed.rss",
        source_type="rss", role="resolver",
    )
    assert w["role"] == "resolver"
    listed = lg.list_watched_sources(scope_type="question", scope_ref=q.id)
    assert any(x["role"] == "resolver" for x in listed)


def test_role_is_optional_and_defaults_none(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the indicator cross by close?", resolution_criteria=CRIT)
    w = lg.add_watched_source(scope_type="question", scope_ref=q.id, source="https://x/feed.rss", source_type="rss")
    assert w["role"] is None


def test_invalid_role_is_rejected(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will it cross by close?", resolution_criteria=CRIT)
    with pytest.raises(ValidationError, match="role must be one of"):
        lg.add_watched_source(
            scope_type="question", scope_ref=q.id, source="https://x/2.rss", source_type="rss", role="bogus",
        )


def test_role_taxonomy_covers_the_feedback_roles(tmp_path):
    # The roles the feedback called for must all be accepted.
    for role in ("resolver", "consensus", "official_primary", "leading_indicator", "market_price", "background_context"):
        assert role in WATCH_SOURCE_ROLES
