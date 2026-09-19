"""Adapter discrimination and pre-I/O admission across direct and shared paths."""

import pytest
from pydantic import ValidationError

from forecasting.sources.acquisition_requests import REQUEST_ADAPTER, acquisition_request
from forecasting.models import ValidationError as ForecastValidationError
from forecasting.sources import dispatch
from forecasting.sources.bls import load_bls_observations


@pytest.mark.parametrize("adapter", ["fred", "bls", "kalshi", "polymarket"])
def test_typed_contract_roundtrip_and_unknown_fields(adapter):
    request = REQUEST_ADAPTER.validate_python({"adapter": adapter, "source": "series"})
    assert REQUEST_ADAPTER.validate_json(request.model_dump_json()) == request
    with pytest.raises(ValidationError):
        REQUEST_ADAPTER.validate_python({"adapter": adapter, "source": "series", "unrecognized": True})


@pytest.mark.parametrize("values", [{"start_year": True}, {"end_year": "2025"}, {"start_year": 0}, {"end_year": 10000}, {"start_year": 2026, "end_year": 2025}, {"limit": False}])
def test_bls_invalid_inputs_reject_before_direct_or_dispatch_fetch(monkeypatch, values):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid request reached I/O")
    monkeypatch.setattr(dispatch, "load_bls_observations", forbidden)
    with pytest.raises(ValueError):
        dispatch.load_source_items("bls", "CUUR0000SA0", values)
    with pytest.raises(ForecastValidationError):
        load_bls_observations("CUUR0000SA0", _read_json_endpoint=forbidden, **values)


def test_bls_adapter_specific_years_are_forwarded(monkeypatch):
    calls = []
    monkeypatch.setattr(dispatch, "load_bls_observations", lambda source, **kwargs: calls.append((source, kwargs)) or [])
    dispatch.load_source_items("adapter:bls", "CUUR0000SA0", {"start_year": 2024, "end_year": 2025, "auto_watch": True})
    assert calls == [("CUUR0000SA0", {"limit": 10, "start_year": 2024, "end_year": 2025})]


@pytest.mark.parametrize("adapter", ["kalshi", "polymarket"])
def test_market_contract_does_not_accept_economic_options(adapter):
    with pytest.raises(ValidationError):
        REQUEST_ADAPTER.validate_python({"adapter": adapter, "source": "market", "start_year": 2025})


def test_validation_error_does_not_echo_endpoint_secrets():
    with pytest.raises(ValueError) as caught:
        acquisition_request("bls", "x", {"api_base_url": "secret://user:password@example.org"})
    assert "api_base_url" in str(caught.value)
    assert "password" not in str(caught.value)
