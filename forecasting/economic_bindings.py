"""Economic observation contracts. Dates of observations never imply release dates.

FRED output_type=4 is the provider's initial-release-only series. Vintage mode
pins the real-time date. Its units=lin is a transformation, not a unit label;
physical units and entity identity come from an independently archived series
metadata response. BLS's current API is deliberately not first-release proof.
"""
from datetime import date, datetime, time, timedelta, timezone
import math
import re
from urllib.parse import urlencode
from forecasting.models import ValidationError, timestamp_to_datetime

ADAPTERS = ('bls_observation_v1', 'fred_observation_v1')
# Explicit reviewed series identities; arbitrary BLS series need a reviewed
# unit mapping, not a caller-supplied unit assertion. See data.bls.gov/timeseries.
BLS_UNITS = {'LNS14000000': 'Percent', 'CES0000000001': 'Thousands of persons',
             'CUSR0000SA0': 'Index 1982-1984=100'}


def validate_options(adapter, entity, options):
    allowed = {'units', 'revision_policy', 'observation_date', 'vintage_date', 'metadata_evidence_id'}
    if set(options) - allowed:
        raise ValidationError('unknown economic contract fields')
    for key in ('units', 'revision_policy', 'observation_date'):
        if not isinstance(options.get(key), str) or not options[key].strip():
            raise ValidationError('economic contract requires ' + key)
    try:
        if date.fromisoformat(options['observation_date']).isoformat() != options['observation_date']:
            raise ValueError()
    except ValueError as exc:
        raise ValidationError('observation_date must be an ISO date') from exc
    policy = options['revision_policy']
    if adapter == 'bls_observation_v1':
        if BLS_UNITS.get(entity) != options['units']:
            raise ValidationError('unsupported BLS series or mismatched units')
        if policy != 'as_captured':
            raise ValidationError('BLS current-series API cannot prove first release or a historical vintage')
        if options.get('vintage_date') or options.get('metadata_evidence_id'):
            raise ValidationError('BLS contract does not accept FRED vintage metadata')
    else:
        if policy not in ('first_release', 'vintage'):
            raise ValidationError('FRED requires first_release or vintage revision policy')
        if not isinstance(options.get('metadata_evidence_id'), str) or not re.fullmatch(r'ev_[a-zA-Z0-9]+', options['metadata_evidence_id']):
            raise ValidationError('FRED requires archived series metadata evidence')
        if policy == 'vintage':
            try:
                date.fromisoformat(options.get('vintage_date', ''))
            except (TypeError, ValueError) as exc:
                raise ValidationError('vintage policy requires an ISO vintage_date') from exc
        elif options.get('vintage_date'):
            raise ValidationError('first release must not select an arbitrary vintage')
    return options


def fred_metadata_url(contract):
    return 'https://api.stlouisfed.org/fred/series?' + urlencode(
        {'series_id': contract['entity'], 'file_type': 'json'})


def binding_spec(contract):
    if contract['adapter'] == 'bls_observation_v1':
        url = f"https://api.bls.gov/publicAPI/v2/timeseries/data/{contract['entity']}"
        return dict(source_url=url, value_pointer='/Results/series/0/data/0/value', observed_at_pointer='/source_capture/captured_at')
    params = dict(series_id=contract['entity'], file_type='json', units='lin',
                  observation_start=contract['observation_date'], observation_end=contract['observation_date'])
    if contract['revision_policy'] == 'first_release':
        params.update(output_type='4', realtime_start='1776-07-04', realtime_end='9999-12-31')
    else:
        params.update(output_type='1', realtime_start=contract['vintage_date'], realtime_end=contract['vintage_date'])
    return dict(source_url='https://api.stlouisfed.org/fred/series/observations?' + urlencode(params),
                value_pointer='/observations/0/value', observed_at_pointer='/observations/0/realtime_start')


def extract(document, contract, captured_at, *, metadata_document=None):
    if not isinstance(document, dict):
        raise ValidationError('economic source must be an object')
    capture = timestamp_to_datetime(captured_at)
    observation = date.fromisoformat(contract['observation_date'])
    start, end = (timestamp_to_datetime(contract[k]) for k in ('window_start', 'window_end'))
    event = datetime.combine(observation, time.min, timezone.utc)
    if start != event or end <= event or end > capture:
        raise ValidationError('economic observation period must start exactly at observation_date and be complete')
    published = None
    if contract['adapter'] == 'bls_observation_v1':
        if document.get('status') != 'REQUEST_SUCCEEDED':
            raise ValidationError('BLS request did not succeed')
        results = document.get('Results')
        series = results.get('series') if isinstance(results, dict) else None
        if not isinstance(series, list) or len(series) != 1 or not isinstance(series[0], dict):
            raise ValidationError('BLS requires exactly one series')
        series = series[0]
        if series.get('seriesID') != contract['entity']:
            raise ValidationError('source_entity_mismatch')
        # This adapter deliberately supports monthly observations only. Annual
        # averages and quarter totals require different period contracts.
        next_month = date(observation.year + (observation.month == 12), observation.month % 12 + 1, 1)
        if observation.day != 1 or end != datetime.combine(next_month, time.min, timezone.utc):
            raise ValidationError('BLS monthly period mismatch')
        rows = series.get('data')
        if not isinstance(rows, list):
            raise ValidationError('BLS data missing')
        matches = [r for r in rows if isinstance(r, dict) and r.get('year') == str(observation.year)
                   and r.get('period') == f'M{observation.month:02d}']
        observed = captured_at  # receipt time, explicitly not publication
        meaning = {'publication_status': 'unknown', 'revision_status': 'current_at_capture'}
    else:
        meta = metadata_document.get('seriess') if isinstance(metadata_document, dict) else None
        if not isinstance(meta, list) or len(meta) != 1 or not isinstance(meta[0], dict):
            raise ValidationError('FRED series metadata missing')
        meta = meta[0]
        if meta.get('id') != contract['entity'] or meta.get('units') != contract['units']:
            raise ValidationError('FRED series entity or units mismatch')
        # Weekly FRED dates can denote week endings; do not infer a start.
        frequencies = {'D': timedelta(days=1)}
        frequency = meta.get('frequency_short')
        if frequency in frequencies:
            expected_end = event + frequencies[frequency]
        elif frequency in ('M', 'Q', 'A'):
            months = {'M': 1, 'Q': 3, 'A': 12}[frequency]
            if observation.day != 1 or (frequency == 'Q' and observation.month not in (1, 4, 7, 10)) or (frequency == 'A' and observation.month != 1):
                raise ValidationError('FRED period start mismatch')
            month = observation.month - 1 + months
            expected_end = event.replace(year=observation.year + month // 12, month=month % 12 + 1)
        else:
            raise ValidationError('unsupported FRED observation frequency')
        if end != expected_end:
            raise ValidationError('FRED observation period mismatch')
        expected_type = 4 if contract['revision_policy'] == 'first_release' else 1
        if document.get('units') != 'lin' or type(document.get('output_type')) is not int or document.get('output_type') != expected_type:
            raise ValidationError('FRED transformation or revision policy mismatch')
        if type(document.get('count')) is not int or type(document.get('offset')) is not int or document.get('count') != 1 or document.get('offset') != 0:
            raise ValidationError('FRED incomplete or ambiguous response')
        matches = document.get('observations')
        if not isinstance(matches, list) or len(matches) != 1 or not isinstance(matches[0], dict):
            raise ValidationError('FRED requires one exact observation')
        row = matches[0]
        if row.get('date') != contract['observation_date']:
            raise ValidationError('FRED observation date mismatch')
        try:
            vintage = date.fromisoformat(row['realtime_start'])
            vintage_end = date.fromisoformat(row['realtime_end'])
            if vintage_end < vintage or datetime.combine(vintage, time.min, timezone.utc) > capture:
                raise ValueError('invalid real-time interval')
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError('FRED real-time date missing') from exc
        if contract['revision_policy'] == 'vintage':
            if any(document.get(k) != contract['vintage_date'] for k in ('realtime_start', 'realtime_end')) or row.get('realtime_start') != contract['vintage_date'] or row.get('realtime_end') != contract['vintage_date']:
                raise ValidationError('FRED vintage mismatch')
            observed = captured_at
            meaning = {'publication_status': 'unknown', 'revision_status': 'pinned_vintage'}
        else:
            # Provider gives day precision only: conservatively available after
            # that complete day, never invent midnight release availability.
            published = datetime.combine(vintage + timedelta(days=1), time.min, timezone.utc).isoformat()
            observed = published
            if timestamp_to_datetime(published) > capture or timestamp_to_datetime(published) < end or vintage < observation:
                raise ValidationError('FRED release time invalid or not fully observed')
            meaning = {'publication_status': 'day_precision_upper_bound', 'revision_status': 'initial_release'}
    if not matches or any(r != matches[0] for r in matches):
        raise ValidationError('missing measurement or conflicting revisions')
    raw = matches[0].get('value')
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        raise ValidationError('economic measurement must be numeric')
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValidationError('economic measurement missing or nonnumeric') from exc
    if not math.isfinite(value):
        raise ValidationError('economic measurement must be finite')
    return value, observed, {**meaning, 'published_at': published, 'entity': contract['entity'],
        'units': contract['units'], 'measurement': 'economic_series_observation',
        'observation_period': contract['observation_date'], 'revision_policy': contract['revision_policy'],
        'window_start': contract['window_start'], 'window_end': contract['window_end'],
        'adapter': contract['adapter'], 'independence_group': 'economic_series:' + contract['entity']}


def authenticated_url(source_url):
    """Add the FRED credential only at fetch time; never put it in the ledger."""
    import os
    from urllib.parse import urlsplit, parse_qsl, urlunsplit
    parts = urlsplit(source_url)
    if parts.scheme != 'https' or parts.netloc != 'api.stlouisfed.org' or parts.path not in ('/fred/series', '/fred/series/observations'):
        return source_url
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    if 'api_key' not in params and os.environ.get('FRED_API_KEY'):
        params['api_key'] = os.environ['FRED_API_KEY']
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))
