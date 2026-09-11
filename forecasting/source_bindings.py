"""Verified measurement contracts for NWS observations and USGS event details.

Schema authorities: weather.gov/documentation/services-web-api and
 earthquake.usgs.gov/earthquakes/feed/v1.0/geojson_detail.php.
These contracts identify observations; neither establishes a completed daily
maximum, an independent corroborating source, or a final settlement by itself.
"""
from datetime import datetime, timezone
import re

from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime


def source_contract(*, adapter, entity, window_start, window_end, magnitude_type=None):
    if adapter not in ('nws_temperature_v1', 'usgs_magnitude_v1'):
        raise ValidationError('unsupported source binding adapter')
    if not isinstance(entity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{2,40}', entity):
        raise ValidationError('invalid source entity identifier')
    start = parse_timestamp(window_start, field_name='measurement window start')
    end = parse_timestamp(window_end, field_name='measurement window end')
    if not start or not end or timestamp_to_datetime(start) >= timestamp_to_datetime(end):
        raise ValidationError('measurement window must have an ordered start and end')
    if adapter == 'usgs_magnitude_v1' and magnitude_type not in ('mb', 'md', 'mh', 'ml', 'ms', 'mw', 'mwb', 'mwc', 'mwr', 'mww'):
        raise ValidationError('an explicit supported USGS magnitude type is required')
    return dict(adapter=adapter, entity=entity, window_start=start, window_end=end, magnitude_type=magnitude_type)


def binding_spec(contract):
    if contract['adapter'] == 'nws_temperature_v1':
        return dict(source_url=f"https://api.weather.gov/stations/{contract['entity']}/observations/latest",
            value_pointer='/properties/temperature/value', observed_at_pointer='/properties/timestamp')
    return dict(source_url=f"https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/{contract['entity']}.geojson",
        value_pointer='/properties/mag', observed_at_pointer='/properties/updated')


def _epoch_ms(value):
    if type(value) is not int:
        raise ValidationError('USGS timestamps must be integer epoch milliseconds')
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()


def extract_measurement(document, contract, *, captured_at):
    """Return value, revision/observation time, and explicit measurement meaning."""
    if not isinstance(document, dict) or document.get('type') != 'Feature' or not isinstance(document.get('properties'), dict):
        raise ValidationError('source_schema_mismatch')
    p = document['properties']
    if contract['adapter'] == 'nws_temperature_v1':
        station = f"https://api.weather.gov/stations/{contract['entity']}"
        if p.get('station') != station or p.get('stationId', contract['entity']) != contract['entity']:
            raise ValidationError('source_entity_mismatch')
        measure = p.get('temperature')
        if not isinstance(measure, dict):
            raise ValidationError('source_schema_mismatch')
        if measure.get('unitCode') != 'wmoUnit:degC':
            raise ValidationError('source_units_mismatch')
        if measure.get('qualityControl') != 'V':
            raise ValidationError('source_quality_unverified')
        value, observed = measure['value'], parse_timestamp(p['timestamp'], field_name='NWS observation time')
        event_time = observed
        meaning = dict(measurement='instantaneous_air_temperature', units='wmoUnit:degC',
            observation_period='instant', entity=contract['entity'], daily_maximum_complete=False)
    else:
        if document.get('id') != contract['entity'] or p.get('type') != 'earthquake':
            raise ValidationError('source_entity_mismatch')
        if p.get('magType') != contract['magnitude_type']:
            raise ValidationError('source_magnitude_scale_mismatch')
        if p.get('status') not in ('automatic', 'reviewed'):
            raise ValidationError('source_review_status_unknown')
        value, observed = p['mag'], _epoch_ms(p['updated'])
        event_time = _epoch_ms(p['time'])
        meaning = dict(measurement='earthquake_magnitude', units='magnitude:'+contract['magnitude_type'],
            observation_period='event', entity=contract['entity'], review_status=p['status'], event_time=event_time)
    if not observed or not event_time:
        raise ValidationError('observation_time_missing')
    event_at, observed_at = timestamp_to_datetime(event_time), timestamp_to_datetime(observed)
    if not timestamp_to_datetime(contract['window_start']) <= event_at < timestamp_to_datetime(contract['window_end']):
        raise ValidationError('source_measurement_window_mismatch')
    if event_at > observed_at or observed_at > timestamp_to_datetime(captured_at):
        raise ValidationError('source_timestamp_order_invalid')
    return value, observed, {**meaning, 'window_start': contract['window_start'], 'window_end': contract['window_end'],
        'adapter': contract['adapter'], 'independence_group': f"{contract['adapter']}:{contract['entity']}"}
