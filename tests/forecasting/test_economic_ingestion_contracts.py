"""Source changes must not invent temporal or measurement provenance."""
import pytest
from forecasting.models import ValidationError
from forecasting.sources.eia_parser import _eia_observations_from_payload, _eia_period_to_iso
from forecasting.sources.census import _census_records_from_payload
from forecasting.sources.macroeconomic import _imf_values_for, load_worldbank_observations
from forecasting.sources.treasury import _treasury_records_from_payload
from forecasting.source_bindings import source_contract


def eia(row):
    return _eia_observations_from_payload({'response': {'data': [row]}}, series_id='PET.RWTC.M', endpoint='https://api.eia.gov/series/?api_key=secret')


def test_eia_observation_date_is_not_publication_or_revision():
    row = eia({'period': '2026-03', 'value': 72, 'units': 'dollars per barrel'})[0]
    assert row.published_at is None
    assert row.observation_period == '2026-03'
    assert 'secret' not in row.source_url


@pytest.mark.parametrize('value', [True, False, float('inf'), float('nan'), 'unknown'])
def test_eia_invalid_measurements_are_rejected(value):
    with pytest.raises(ValidationError, match='finite numeric'):
        eia({'period': '2026-03', 'value': value})


def test_eia_wrong_series_is_not_relabelled():
    with pytest.raises(ValidationError, match='series'):
        eia({'series_id': 'OTHER', 'period': '2026-03', 'value': 72})


@pytest.mark.parametrize('period', ['202613', '2026-00', '0000', '2026-02-30'])
def test_eia_rejects_invalid_period(period):
    assert _eia_period_to_iso(period) is None


@pytest.mark.parametrize('payload', [[['state', 'state'], ['06', '01']], [['state', 'value'], ['06']]])
def test_census_changed_columns_fail_closed(payload):
    with pytest.raises(ValidationError):
        _census_records_from_payload(payload, dataset='2023/acs/acs5', endpoint='https://api.census.gov/data')


def test_imf_anonymous_mapping_cannot_borrow_requested_identity():
    with pytest.raises(ValidationError, match='indicator/country'):
        _imf_values_for({'values': {'2025': 3}}, indicator='NGDP_RPCH', country='USA')


def test_worldbank_wrong_country_rejected():
    payload = [{}, [{'date': '2025', 'value': 3, 'country': {'id': 'CA'}, 'countryiso3code': 'CAN', 'indicator': {'id': 'NY.GDP.MKTP.CD'}}]]
    with pytest.raises(ValidationError, match='country/indicator'):
        load_worldbank_observations('USA/NY.GDP.MKTP.CD', _read_json_endpoint=lambda *_: payload)


@pytest.mark.parametrize('row', [{'effective_date': '2026-03-01', 'amount': 3}, {'record_date': '2026-03-01', 'wrong_amount': 3}])
def test_treasury_requested_fields_cannot_fall_back(row):
    with pytest.raises(ValidationError, match='requested'):
        _treasury_records_from_payload({'data': [row]}, dataset='test', endpoint='https://example.test', date_field='record_date', value_field='amount')


@pytest.mark.parametrize('adapter', ['eia', 'treasury', 'census', 'worldbank', 'imf'])
def test_research_adapter_is_not_a_verified_settlement_contract(adapter):
    with pytest.raises(ValidationError, match='unsupported'):
        source_contract(adapter=adapter, entity='USA', window_start='2025-01-01', window_end='2026-01-01')


def test_treasury_never_selects_first_of_competing_numeric_fields():
    from forecasting.sources.treasury import _treasury_value
    with pytest.raises(ValidationError, match='ambiguous'):
        _treasury_value({'amount': 30, 'percentage': 3}, date_field='record_date', value_field=None)
