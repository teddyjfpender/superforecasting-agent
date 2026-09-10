"""An empty resolved-question page is a valid benchmark result."""
import pytest
from forecasting import source_adapters


@pytest.fixture(params=[
    ("metaculus", ("results", "questions", "data")),
    ("kalshi", ("markets", "results", "data")),
])
def source_config(request):
    venue, keys = request.param
    return getattr(source_adapters, f"load_{venue}_resolved_binary_cases"), keys


@pytest.mark.parametrize("position", [0, 1, 2])
def test_empty_envelope_is_valid(source_config, monkeypatch, position):
    loader, keys = source_config
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: {keys[position]: []})
    assert loader() == []


def test_empty_primary_does_not_fall_through(source_config, monkeypatch):
    loader, keys = source_config
    def unexpected(*args):
        raise AssertionError("A fallback row must not be decoded")
    venue = "metaculus" if keys[0] == "results" else "kalshi"
    parser = "_metaculus_question_from_payload" if venue == "metaculus" else "_kalshi_market_from_payload"
    monkeypatch.setattr(source_adapters, parser, unexpected)
    # A dictionary row would reach the parser if an empty primary is ignored.
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: {keys[0]: [], keys[1]: [{}]})
    assert loader() == []


def test_raw_empty_array_is_valid(source_config, monkeypatch):
    loader, _ = source_config
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: [])
    assert loader() == []
