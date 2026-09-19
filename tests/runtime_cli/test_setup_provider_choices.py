"""Setup presentation must not change credential compatibility or plugin identity."""

from superforecasting_agent.configuration.provider_catalog import (
    CANONICAL_PROVIDERS,
    PROVIDER_LABELS,
    SETUP_PROVIDERS,
)


def test_setup_order_and_legacy_compatibility():
    slugs = [entry.slug for entry in SETUP_PROVIDERS]
    assert slugs[:3] == ["anthropic", "openai-api", "openai-codex"]
    assert "nous" not in slugs
    assert len(slugs) == len(set(slugs))
    remainder = [entry.label.casefold() for entry in SETUP_PROVIDERS[3:]]
    assert remainder == sorted(remainder)
    assert {p.slug for p in CANONICAL_PROVIDERS} - set(slugs) == {"nous"}
    assert PROVIDER_LABELS["nous"] == "Nous Portal"
