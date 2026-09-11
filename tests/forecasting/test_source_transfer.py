import base64
from copy import deepcopy
import hashlib
import json
import pytest
from forecasting import ForecastLedger
from forecasting.models import ValidationError
from forecasting.applicability_facts import evidence_facts
from forecasting.settlement_binding import bind_settlement
from tests.forecasting.test_settlement_binding import measurement


@pytest.fixture(autouse=True)
def frozen_resolution_clock(monkeypatch):
    for module in ('forecasting.settlement_binding', 'forecasting.ledger.resolutions', 'forecasting.source_transfer'):
        monkeypatch.setattr(module + '.utc_now_iso', lambda: '2026-09-11T12:00:00Z')


def packet_for(measurement):
    ledger, q, ev, archive, settings = measurement
    bind_settlement(ledger, q.id, **settings)
    ledger.resolve_question(question_id=q.id, outcome=23.5, resolution_source=ev.source_url, resolution_source_snapshot_ref=ev.id)
    return json.loads(ledger.export_question(q.id, fmt='json'))


def test_roundtrip_archives_without_foreign_file_access(measurement, tmp_path):
    packet = packet_for(measurement)
    source, q, ev, archive, _ = measurement
    archive.unlink()
    target = ForecastLedger(tmp_path/'other'/'db')
    target.import_packet(packet)
    assert target.get_latest_resolution(q.id).outcome == 23.5
    assert target.get_evidence(ev.id).snapshot_path is None
    assert evidence_facts(target,target.get_question(q.id))['temperature']['status'] == 'imported'
    exported = json.loads(target.export_question(q.id, fmt='json'))
    assert exported['source_transfer']['bindings'] == packet['source_transfer']['bindings']
    assert exported['source_transfer']['archives'] == packet['source_transfer']['archives']
    third = ForecastLedger(tmp_path/'third'/'db')
    third.import_packet(exported)
    assert third.get_latest_resolution(q.id).outcome == 23.5
    assert evidence_facts(third,third.get_question(q.id))['temperature']['status'] == 'imported'


@pytest.mark.parametrize('tamper', ['bytes','hash','entity','version','scope','duplicate'])
def test_invalid_transfer_rolls_back_every_record(measurement, tmp_path, tamper):
    packet = packet_for(measurement)
    transfer = packet['source_transfer']
    if tamper == 'bytes':
        transfer['archives'][0]['content_base64'] = base64.b64encode(b'{}').decode()
    elif tamper == 'hash':
        transfer['archives'][0]['sha256'] = '0'*64
    elif tamper == 'entity':
        contract = json.loads(transfer['bindings'][0]['source_contract']); contract['entity']='KLGA'
        transfer['bindings'][0]['source_contract']=json.dumps(contract)
    elif tamper == 'version':
        transfer['version']=999
    elif tamper == 'scope':
        transfer['bindings'][0]['question_id']='other'
    else:
        transfer['archives'].append(deepcopy(transfer['archives'][0]))
    target = ForecastLedger(tmp_path/'target'/'db')
    with pytest.raises(ValidationError):
        target.import_packet(packet)
    assert target.list_questions() == []
    with target._connect() as conn:
        assert conn.execute('SELECT count(*) FROM transferred_source_archives').fetchone()[0] == 0


def test_imported_resolution_still_rejects_wrong_measurement(measurement, tmp_path):
    packet = packet_for(measurement)
    packet['resolution']['outcome'] = 24
    target = ForecastLedger(tmp_path/'target'/'db')
    with pytest.raises(ValidationError, match='outcome'):
        target.import_packet(packet)


def test_reverification_requires_identical_canonical_bytes(measurement, tmp_path, monkeypatch):
    from forecasting.source_transfer import reverify_sources
    packet = packet_for(measurement)
    _, q, ev, archive, _ = measurement
    target = ForecastLedger(tmp_path/'target'/'db'); target.import_packet(packet)
    raw = b'{}'
    def fetch(**kw):
        path=tmp_path/(kw['evidence_id']+'.json'); path.write_bytes(raw)
        return dict(snapshot_path=str(path),status=200,sha256=hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(target,'_archive_url_evidence_snapshot',fetch)
    result=reverify_sources(target,q.id)
    assert result['archives'][0]['status']=='imported'
    raw=archive.read_bytes()
    result=reverify_sources(target,q.id)
    assert result['archives'][0]['status']=='locally_reverified'
    with target._connect() as conn:
        row=conn.execute('SELECT * FROM transferred_source_archives WHERE evidence_id=?',(ev.id,)).fetchone()
        assert row['verified_at'] is not None
        assert json.loads(row['provenance'])==packet['source_transfer']['archives'][0]['provenance']


def test_imported_forecast_cannot_acquire_calibration_authority(measurement, tmp_path):
    ledger, q, ev, archive, settings = measurement
    snapshot = ledger.create_snapshot(question_id=q.id,
        probability_or_distribution={'mean': 23, 'sd': 2}, rationale='Measured station forecast',
        as_of='2026-09-11T11:00:00Z', require_style=False)
    packet = packet_for(measurement)
    original_score = ledger.score_snapshot(snapshot.forecast_id)
    assert original_score.calibration_eligible
    packet = json.loads(ledger.export_question(q.id, fmt='json'))
    target = ForecastLedger(tmp_path / 'scoring' / 'db')
    target.import_packet(packet)
    imported = target.get_snapshot(snapshot.forecast_id)
    assert imported.forecast_origin == 'imported'
    assert not imported.calibration_eligible and imported.calibration_weight == 0
    with pytest.raises(ValidationError, match='local source verification'):
        target.score_snapshot(snapshot.forecast_id)
    # Even successful byte verification must not authenticate foreign forecast
    # timing. This isolates the scoring transition from the separately tested fetch.
    with target._connect() as conn:
        conn.execute("UPDATE transferred_source_archives SET verification_status='locally_reverified', verified_at='2026-09-11T12:00:00Z'")
    score = target.score_snapshot(snapshot.forecast_id)
    assert not score.calibration_eligible and score.calibration_weight == 0
    with target._connect() as conn:
        original = json.loads(conn.execute('SELECT original_records FROM source_transfer_history').fetchone()[0])
    assert original['forecast_history'][0]['forecast_origin'] == 'live'
