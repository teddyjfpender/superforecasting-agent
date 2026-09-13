from copy import deepcopy
import hashlib
import json
import pytest
from forecasting import ForecastLedger
from forecasting.models import OutcomeSpace, ValidationError
from forecasting.source_bindings import source_contract, binding_spec, extract_measurement
from forecasting.applicability_facts import bind_fact
from forecasting.settlement_binding import bind_settlement
from forecasting.economic_bindings import fred_metadata_url

STAMP = '2026-09-11T12:00:00+00:00'


def fred_contract(**changes):
    return source_contract(**{**dict(adapter='fred_observation_v1', entity='UNRATE', units='Percent',
        window_start='2026-08-01T00:00:00Z', window_end='2026-09-01T00:00:00Z',
        observation_date='2026-08-01', revision_policy='first_release', metadata_evidence_id='ev_metadata'), **changes})


def fred_documents():
    return ({'units': 'lin', 'output_type': 4, 'count': 1, 'offset': 0,
             'observations': [{'date': '2026-08-01', 'realtime_start': '2026-09-04',
                               'realtime_end': '9999-12-31', 'value': '4.2'}]},
            {'seriess': [{'id': 'UNRATE', 'units': 'Percent', 'frequency_short': 'M'}]})


def test_first_release_and_vintage_are_distinct():
    doc, meta = fred_documents()
    value, observed, meaning = extract_measurement(doc, fred_contract(), captured_at=STAMP, metadata_document=meta)
    assert value == 4.2 and observed == '2026-09-05T00:00:00+00:00'
    assert meaning['publication_status'] == 'day_precision_upper_bound'
    vintage = fred_contract(revision_policy='vintage', vintage_date='2026-09-10')
    with pytest.raises(ValidationError, match='revision policy'):
        extract_measurement(doc, vintage, captured_at=STAMP, metadata_document=meta)
    doc.update(output_type=1, realtime_start='2026-09-10', realtime_end='2026-09-10')
    doc['observations'][0].update(realtime_start='2026-09-10', realtime_end='2026-09-10', value='4.3')
    value, _, meaning = extract_measurement(doc, vintage, captured_at=STAMP, metadata_document=meta)
    assert value == 4.3 and meaning['published_at'] is None


@pytest.mark.parametrize('target,key,value', [
    ('meta', 'id', 'PAYEMS'), ('meta', 'units', 'Thousands of Persons'),
    ('meta', 'frequency_short', 'Q'), ('doc', 'units', 'pch'),
    ('doc', 'output_type', 1), ('doc', 'count', True), ('doc', 'offset', False), ('doc', 'count', 2), ('doc', 'offset', 1),
    ('row', 'date', '2026-07-01'), ('row', 'value', '.'), ('row', 'value', True),
    ('meta', 'frequency_short', 'W'), ('row', 'realtime_end', '2026-09-01'),
    ('row', 'value', 'NaN'), ('row', 'realtime_start', '2026-09-12')])
def test_plausible_wrong_measurements_cannot_settle(tmp_path, monkeypatch, target, key, value):
    monkeypatch.setattr('forecasting.applicability_facts.utc_now_iso', lambda: STAMP)
    monkeypatch.setattr('forecasting.ledger.evidence.utc_now_iso', lambda: STAMP)
    ledger = ForecastLedger(tmp_path/'db')
    q = ledger.create_question(title='August unemployment rate?', resolution_criteria='Initial UNRATE release for August.',
                               outcome_space=OutcomeSpace(type='numeric', choices=[], units='Percent'))
    doc, meta = fred_documents()
    def archive(**kw):
        raw = json.dumps(meta if '/series?' in kw['source_url'] else doc).encode()
        path = tmp_path/(kw['evidence_id']+'.json'); path.write_bytes(raw)
        return dict(snapshot_path=str(path),sha256=hashlib.sha256(raw).hexdigest(),status=200)
    monkeypatch.setattr(ledger, '_archive_url_evidence_snapshot', archive)
    meta_ev = ledger.add_evidence(question_id=q.id, source_or_note=fred_metadata_url(fred_contract()))
    contract = fred_contract(metadata_evidence_id=meta_ev.id)
    spec = binding_spec(contract)
    ev = ledger.add_evidence(question_id=q.id, source_or_note=spec['source_url'])
    bind_fact(ledger, question_id=q.id, key='rate', **spec, value_type='number', source_contract=contract, max_age_seconds=31536000)
    bind_settlement(ledger, q.id, fact_key='rate', entity='UNRATE', units='Percent', measurement='economic_series_observation',
                    window_start=contract['window_start'], window_end=contract['window_end'], reason='Exact first release')
    {'doc': doc, 'meta': meta['seriess'][0], 'row': doc['observations'][0]}[target][key] = value
    # A fresh real-boundary receipt, not mere archive tampering: bad semantic
    # content must fail even with a matching HTTPS receipt and digest.
    bad = ledger.add_evidence(question_id=q.id, source_or_note=meta_ev.source_url if target == 'meta' else ev.source_url,
                              available_at=STAMP)
    # Preserve deterministic ordering when timestamps tie.
    with ledger._connect() as conn:
        conn.execute('UPDATE evidence_items SET captured_at=? WHERE id=?', ('2026-09-11T11:59:59+00:00', meta_ev.id if target == 'meta' else ev.id))
    if target == 'meta':
        # The metadata archive identity is pinned by the source contract.
        contract['metadata_evidence_id'] = bad.id
        with ledger._connect() as conn:
            conn.execute('UPDATE applicability_bindings SET source_contract=? WHERE question_id=?', (json.dumps(contract),q.id))
    with pytest.raises(ValidationError):
        ledger.resolve_question(question_id=q.id, outcome=4.2, resolution_source=ev.source_url, resolution_source_snapshot_ref=ev.id)
    assert ledger.get_latest_resolution(q.id) is None


def test_bls_never_fabricates_first_release_or_units():
    kwargs = dict(adapter='bls_observation_v1', entity='LNS14000000', units='Percent',
                  window_start='2026-08-01T00:00:00Z',window_end='2026-09-01T00:00:00Z', observation_date='2026-08-01')
    with pytest.raises(ValidationError, match='first release'):
        source_contract(**kwargs, revision_policy='first_release')
    with pytest.raises(ValidationError, match='units'):
        source_contract(**{**kwargs,'units':'fraction'}, revision_policy='as_captured')
    contract = source_contract(**kwargs, revision_policy='as_captured')
    doc = {'status':'REQUEST_SUCCEEDED','Results':{'series':[{'seriesID':'LNS14000000','data':[
        {'year':'2026','period':'M08','value':'0'}]}]}}
    value, _, meaning = extract_measurement(doc, contract, captured_at=STAMP)
    assert value == 0 and meaning['published_at'] is None
    doc['Results']['series'][0]['data'].append({'year':'2026','period':'M08','value':'4.2'})
    with pytest.raises(ValidationError, match='conflicting'):
        extract_measurement(doc, contract, captured_at=STAMP)


def test_fred_key_is_only_added_at_fetch_boundary(monkeypatch):
    from forecasting.economic_bindings import authenticated_url
    monkeypatch.setenv('FRED_API_KEY', 'test-private-key')
    canonical = binding_spec(fred_contract())['source_url']
    assert 'test-private-key' not in canonical
    assert 'api_key=test-private-key' in authenticated_url(canonical)
    assert authenticated_url('https://example.org/fred/series') == 'https://example.org/fred/series'
