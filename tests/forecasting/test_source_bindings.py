from copy import deepcopy
import pytest
from forecasting.models import ValidationError
from forecasting.source_bindings import source_contract, extract_measurement
from forecasting.applicability_facts import pointer_value


def test_nws_measurement_identity_units_and_window():
    # Fields from the captured KJFK observation at 2026-09-10T17:51Z.
    raw = {'type': 'Feature', 'properties': {'station': 'https://api.weather.gov/stations/KJFK',
        'stationId': 'KJFK', 'timestamp': '2026-09-10T17:51:00+00:00',
        'temperature': {'unitCode': 'wmoUnit:degC', 'value': 30.6, 'qualityControl': 'V'}}}
    contract = source_contract(adapter='nws_temperature_v1', entity='KJFK',
        window_start='2026-09-10T00:00:00Z', window_end='2026-09-11T00:00:00Z')
    value, _, meaning = extract_measurement(raw, contract, captured_at='2026-09-10T18:18:07Z')
    assert value == 30.6 and meaning['daily_maximum_complete'] is False
    for field, replacement, error in [('station', 'https://api.weather.gov/stations/KLGA', 'entity'),
            ('timestamp', '2026-09-09T17:51:00Z', 'window')]:
        bad = deepcopy(raw); bad['properties'][field] = replacement
        with pytest.raises(ValidationError, match=error):
            extract_measurement(bad, contract, captured_at='2026-09-10T18:18:07Z')
    raw['properties']['temperature']['unitCode'] = 'wmoUnit:degF'
    with pytest.raises(ValidationError, match='units'):
        extract_measurement(raw, contract, captured_at='2026-09-10T18:18:07Z')


def test_usgs_revision_time_is_distinct_from_event_time():
    raw = {'id': 'us1234', 'type': 'Feature', 'properties': {'type': 'earthquake',
        'time': 1789041600000, 'updated': 1789045200000, 'mag': 4.5, 'magType': 'mb', 'status': 'reviewed'}}
    contract = source_contract(adapter='usgs_magnitude_v1', entity='us1234', magnitude_type='mb',
        window_start='2026-09-10T00:00:00Z', window_end='2026-09-11T00:00:00Z')
    value, observed, meaning = extract_measurement(raw, contract, captured_at='2026-09-11T00:00:00Z')
    assert value == 4.5 and observed != meaning['event_time'] and meaning['units'] == 'magnitude:mb'
    raw['properties']['magType'] = 'ml'
    with pytest.raises(ValidationError, match='scale'):
        extract_measurement(raw, contract, captured_at='2026-09-11T00:00:00Z')


def test_json_pointer_cannot_select_last_array_item_with_negative_index():
    with pytest.raises(ValidationError, match='array index'):
        pointer_value({'records': [1, 2]}, '/records/-1')
