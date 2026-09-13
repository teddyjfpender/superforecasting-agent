import hashlib
import json
import pytest
from forecasting import ForecastLedger
from forecasting.models import OutcomeSpace, ValidationError
from forecasting.applicability_facts import bind_fact
from forecasting.source_bindings import source_contract, binding_spec
from forecasting.settlement_binding import bind_settlement


@pytest.fixture
def measurement(tmp_path, monkeypatch):
    stamp = '2026-09-11T12:00:00Z'
    monkeypatch.setattr('forecasting.applicability_facts.utc_now_iso', lambda:stamp)
    monkeypatch.setattr('forecasting.ledger.evidence.utc_now_iso', lambda:stamp)
    ledger = ForecastLedger(tmp_path/'db')
    q = ledger.create_question(title='Station temperature observation?',
        resolution_criteria='Resolve to the verified station temperature at the declared observation time.',
        outcome_space=OutcomeSpace(type='numeric', choices=[], units='wmoUnit:degC'))
    contract = source_contract(adapter='nws_temperature_v1', entity='KJFK',
        window_start='2026-09-11T11:59:00Z', window_end='2026-09-11T12:01:00Z')
    spec = binding_spec(contract)
    raw = json.dumps({'type':'Feature','properties':{'station':'https://api.weather.gov/stations/KJFK',
        'timestamp':stamp,'temperature':{'value':23.5,'unitCode':'wmoUnit:degC','qualityControl':'V'}}}).encode()
    archive = tmp_path/'source.json';archive.write_bytes(raw)
    monkeypatch.setattr(ledger, '_archive_url_evidence_snapshot', lambda **kw:{
        'snapshot_path':str(archive), 'sha256':hashlib.sha256(raw).hexdigest(), 'status':200})
    ev = ledger.add_evidence(question_id=q.id, source_or_note=spec['source_url'])
    bind_fact(ledger, question_id=q.id, key='temperature', **spec, value_type='number', source_contract=contract)
    settings = dict(fact_key='temperature', entity='KJFK', units='wmoUnit:degC',
        measurement='instantaneous_air_temperature', window_start=contract['window_start'],
        window_end=contract['window_end'], reason='Exact station and instantaneous observation reviewed.')
    return ledger, q, ev, archive, settings


def test_exact_binding_rejects_wrong_value_source_and_unarchived_resolution(measurement):
    ledger,q,ev,archive,settings = measurement
    bind_settlement(ledger, q.id, **settings)
    good = dict(question_id=q.id, outcome=23.5, resolution_source=ev.source_url, resolution_source_snapshot_ref=ev.id)
    for patch in ({'outcome':24}, {'resolution_source':'https://example.org'}, {'resolution_source_snapshot_ref':None}):
        with pytest.raises(ValidationError):
            ledger.resolve_question(**{**good, **patch})
        assert ledger.get_latest_resolution(q.id) is None
    assert ledger.resolve_question(**good).outcome == 23.5


def test_instantaneous_observation_cannot_be_bound_as_daily_maximum(measurement):
    ledger,q,_,_,settings = measurement
    with pytest.raises(ValidationError, match='measurement'):
        bind_settlement(ledger, q.id, **{**settings, 'measurement':'daily_maximum_temperature'})
    assert 'settlement_binding' not in ledger.get_question(q.id).metadata


def test_tampered_source_blocks_bound_settlement(measurement):
    ledger,q,ev,archive,settings = measurement
    bind_settlement(ledger, q.id, **settings)
    archive.write_text('{}')
    with pytest.raises(ValidationError, match='verified'):
        ledger.resolve_question(question_id=q.id, outcome=23.5, resolution_source=ev.source_url, resolution_source_snapshot_ref=ev.id)
    assert ledger.get_latest_resolution(q.id) is None
