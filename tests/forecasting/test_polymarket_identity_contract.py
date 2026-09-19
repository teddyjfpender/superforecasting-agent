"""Single-forecast imports cannot substitute another Gamma market or event."""

import pytest

from forecasting import source_adapters as sa
from forecasting.models import ValidationError


def market(identifier="123", slug="target", **extra):
    return {
        "id": identifier,
        "slug": slug,
        "question": "Will it happen?",
        "outcomes": ["Yes", "No"],
        "outcomePrices": ["0.3", "0.7"],
        **extra,
    }


def event(children, **extra):
    return {"id": "42", "slug": "event-target", "markets": children, **extra}


@pytest.mark.parametrize(
    "source", ["123", "slug:target", "https://gamma-api.polymarket.com/markets/123"]
)
def test_matching_market_selected_independent_of_order(source, monkeypatch):
    monkeypatch.setattr(
        sa, "_read_json_endpoint", lambda *a: [market("999", "other"), market()]
    )
    assert sa.load_polymarket_market(source).market_id == "123"


@pytest.mark.parametrize(
    "payload",
    [[market("999", "other")], [market(), market()], {"question": "No ID"}, [None]],
)
def test_invalid_identity_cannot_trigger_event_fallback(payload, monkeypatch):
    calls = []

    def fetch(endpoint, label):
        calls.append(endpoint)
        return payload

    monkeypatch.setattr(sa, "_read_json_endpoint", fetch)
    with pytest.raises(ValidationError, match="polymarket"):
        sa.load_polymarket_market("123")
    assert len(calls) == 1


def test_multimarket_event_requires_child_selection(monkeypatch):
    monkeypatch.setattr(
        sa,
        "_read_json_endpoint",
        lambda endpoint, label: (
            [] if "/markets?" in endpoint else event([market(), market("456", "other")])
        ),
    )
    with pytest.raises(ValidationError, match="explicit single market"):
        sa.load_polymarket_market("event-target")
    selected = sa.load_polymarket_market(
        "https://polymarket.com/event/event-target/target"
    )
    assert selected.market_id == "123"


@pytest.mark.parametrize(
    "returned",
    [
        event([market()], slug="wrong"),
        event([market("999", "wrong")]),
        event([market(), market()]),
    ],
)
def test_child_url_cannot_select_wrong_parent_or_child(returned, monkeypatch):
    monkeypatch.setattr(
        sa,
        "_read_json_endpoint",
        lambda endpoint, label: [] if "/markets?" in endpoint else returned,
    )
    with pytest.raises(ValidationError, match="polymarket"):
        sa.load_polymarket_market("https://polymarket.com/event/event-target/target")


def test_condition_hash_mismatch_is_not_treated_as_closed_market_miss(monkeypatch):
    calls = []

    def fetch(endpoint, label):
        calls.append(endpoint)
        return [market(conditionId="0xbb")]

    monkeypatch.setattr(sa, "_read_json_endpoint", fetch)
    with pytest.raises(ValidationError, match="matching"):
        sa.load_polymarket_market("0xaa")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://gamma-api.polymarket.com/markets?id=123&id=456",
        "https://gamma-api.polymarket.com/markets/123?id=456",
        "https://gamma-api.polymarket.com/markets?condition_ids=0xaa,0xbb",
        "https://gamma-api.polymarket.com/markets?slug=",
    ],
)
def test_conflicting_request_rejected_before_io(endpoint, monkeypatch):
    def fetch(*args):
        pytest.fail("invalid selector reached acquisition")

    monkeypatch.setattr(sa, "_read_json_endpoint", fetch)
    with pytest.raises(ValidationError, match="polymarket"):
        sa.load_polymarket_market(endpoint)


def test_unfiltered_mirror_must_supply_one_market(monkeypatch):
    monkeypatch.setattr(
        sa, "_read_json_endpoint", lambda *a: [market(), market("456", "other")]
    )
    with pytest.raises(ValidationError, match="exactly one"):
        sa.load_polymarket_market("https://mirror.example/fixture.json")


def test_lookalike_domain_not_rewritten():
    source = "https://notpolymarket.com/event/target"
    assert sa._polymarket_endpoint_candidates(
        source, api_base_url="https://api.example"
    ) == [source]


def test_market_endpoint_cannot_hide_wrong_event_by_flattening(monkeypatch):
    monkeypatch.setattr(sa, "_read_json_endpoint", lambda *a: event([market()]))
    with pytest.raises(ValidationError, match="returned an event"):
        sa.load_polymarket_market("123")


def test_cli_ambiguous_event_leaves_ledger_unchanged(tmp_path, monkeypatch, capsys):
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
        sa,
        "_read_json_endpoint",
        lambda endpoint, label: (
            [] if "/markets?" in endpoint else event([market(), market("456", "other")])
        ),
    )
    with pytest.raises(SystemExit) as failure:
        main([
            "--db",
            str(ledger.db_path),
            "import",
            "polymarket",
            "event-target",
            "--question",
            question.id,
        ])
    assert failure.value.code == 1
    assert "explicit single market" in capsys.readouterr().err
    assert ledger.list_evidence(question.id) == []
    assert ledger.list_baseline_comparisons(question.id) == []
    assert ledger.get_question(question.id).current_forecast_id is None
