"""Ignored provider filters cannot silently substitute another market."""

import pytest

from forecasting import source_adapters
from forecasting.models import ValidationError
from forecasting.sources.kalshi_parsing import _kalshi_endpoint_for_source


def row(ticker):
    return {"ticker": ticker, "title": "Question?", "yes_bid": 1}


@pytest.mark.parametrize(
    "source",
    [
        "TARGET",
        "ticker:target",
        "https://kalshi.com/markets/target",
        "https://mirror.example/markets/TARGET",
        "https://mirror.example/markets?tickers=TARGET",
    ],
)
def test_selects_requested_identity_not_first_row(source, monkeypatch):
    monkeypatch.setattr(
        source_adapters,
        "_read_json_endpoint",
        lambda *a: {"markets": [row("OTHER"), row("TARGET")]},
    )
    market = source_adapters.load_kalshi_market(source)
    assert market.ticker == "TARGET"
    assert market.probability == 0.01


@pytest.mark.parametrize(
    "payload",
    [
        row("OTHER"),
        {"market": row("OTHER")},
        {"markets": [row("OTHER")]},
        {"markets": [row("TARGET"), row("TARGET")]},
        {"markets": []},
        {"market": None},
        {"markets": "invalid"},
        {"title": "No ID"},
        row(True),
        {"markets": [None]},
    ],
)
def test_unmatched_ambiguous_or_malformed_identity_fails(payload, monkeypatch):
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *a: payload)
    with pytest.raises(ValidationError, match="kalshi"):
        source_adapters.load_kalshi_market("TARGET")


def test_custom_mirror_requires_one_identified_market(monkeypatch):
    monkeypatch.setattr(
        source_adapters, "_read_json_endpoint", lambda *a: {"market": row("TARGET")}
    )
    assert (
        source_adapters.load_kalshi_market("https://mirror.example/fixture.json").ticker
        == "TARGET"
    )
    monkeypatch.setattr(
        source_adapters,
        "_read_json_endpoint",
        lambda *a: {"markets": [row("A"), row("B")]},
    )
    with pytest.raises(ValidationError, match="exactly one"):
        source_adapters.load_kalshi_market("https://mirror.example/fixture.json")


@pytest.mark.parametrize(
    "query", ["tickers=A,B", "ticker=", "ticker=A&ticker=B", "ticker=OTHER"]
)
def test_conflicting_selector_rejected_before_fetch(query, monkeypatch):
    def unexpected_fetch(*args):
        pytest.fail("invalid selector reached network")

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", unexpected_fetch)
    with pytest.raises(ValidationError, match="one ticker"):
        source_adapters.load_kalshi_market(
            f"https://mirror.example/markets/TARGET?{query}"
        )


def test_lookalike_domain_is_not_rewritten_to_kalshi():
    source = "https://notkalshi.com/markets/TARGET"
    assert (
        _kalshi_endpoint_for_source(source, api_base_url="https://api.example")
        == source
    )


@pytest.mark.parametrize(
    "host", ["api.elections.kalshi.com", "external-api.kalshi.com"]
)
def test_native_api_urls_preserve_single_market_identity(host, monkeypatch):
    source = f"https://{host}/trade-api/v2/markets/TARGET"
    calls = []

    def fetch(endpoint, label):
        calls.append(endpoint)
        return {"market": row("TARGET")}

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fetch)
    assert source_adapters.load_kalshi_market(source).ticker == "TARGET"
    assert calls == [source]


def test_raw_ticker_cannot_change_endpoint_path():
    assert _kalshi_endpoint_for_source(
        "A/markets/B", api_base_url="https://api.example"
    ) == ("https://api.example/markets/A%2FMARKETS%2FB")


def test_cli_identity_mismatch_cannot_write_evidence(tmp_path, monkeypatch, capsys):
    from forecasting.cli import main
    from forecasting.ledger import ForecastLedger

    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path / "profile"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profile"))
    ledger = ForecastLedger(tmp_path / "ledger.db")
    question = ledger.create_question(
        title="Will the correct market attach?",
        resolution_criteria="Resolved yes if the requested market attaches.",
    )
    monkeypatch.setattr(
        source_adapters, "_read_json_endpoint", lambda *a: {"market": row("OTHER")}
    )
    with pytest.raises(SystemExit) as failure:
        main([
            "--db",
            str(ledger.db_path),
            "import",
            "kalshi",
            "TARGET",
            "--question",
            question.id,
        ])
    assert failure.value.code == 1
    assert "matching market" in capsys.readouterr().err
    assert ledger.list_evidence(question.id) == []
    assert ledger.list_baseline_comparisons(question.id) == []
    assert ledger.get_question(question.id).current_forecast_id is None
