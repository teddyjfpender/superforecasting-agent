"""Admission invariants for captured BLS responses, independent of HTTP."""
import pytest
from forecasting.models import ValidationError
from forecasting.sources.bls_parsing import parse_bls_observations


def payload(value=0, *, series='TEST', extra=None):
    row = {'year': '2026', 'period': 'M03', 'value': value}
    return {'Results': {'series': [{'seriesID': series, 'data': [row] + (extra or [])}]}}


def test_zero_is_an_observation_and_period_is_not_publication():
    rows = parse_bls_observations(payload(), 'TEST')
    assert rows[0].value == 0
    assert rows[0].published_at is None
    assert rows[0].observation_date == '2026-03-01'


@pytest.mark.parametrize('value', [True, 'NaN', 'inf', 'not measured'])
def test_invalid_measurement_is_not_imported_as_text(value):
    with pytest.raises(ValidationError):
        parse_bls_observations(payload(value), 'TEST')


def test_series_identity_and_revision_ambiguity():
    with pytest.raises(ValidationError, match='identity'):
        parse_bls_observations(payload(series='OTHER'), 'TEST')
    duplicate = {'year': '2026', 'period': 'M03', 'value': 0}
    assert len(parse_bls_observations(payload(extra=[duplicate]), 'TEST')) == 1
    with pytest.raises(ValidationError, match='conflicting revisions'):
        parse_bls_observations(payload(extra=[{**duplicate, 'value': 1}]), 'TEST')


@pytest.mark.parametrize('raw', [b'{"value":1,"value":2}', b'{"value":NaN}', b'{"value":1e999}'])
def test_source_fetch_rejects_ambiguous_or_nonfinite_json(monkeypatch, raw):
    import io
    from forecasting import source_adapters
    monkeypatch.setattr(source_adapters, 'urlopen', lambda *a, **kw: io.BytesIO(raw))
    with pytest.raises(ValidationError):
        source_adapters._read_json_endpoint('https://example.org/measurement', 'fixture')
