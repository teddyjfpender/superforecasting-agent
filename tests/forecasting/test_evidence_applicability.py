import hashlib
import json
from pathlib import Path
import pytest
from forecasting import ForecastLedger
from forecasting.applicability_facts import bind_fact, evidence_facts
from forecasting.learning import lesson_applicability


@pytest.fixture
def facts_setup(tmp_path, monkeypatch):
    now=['2026-09-01T12:00:00Z']
    monkeypatch.setattr('forecasting.applicability_facts.utc_now_iso',lambda:now[0])
    monkeypatch.setattr('forecasting.ledger.evidence.utc_now_iso',lambda:now[0])
    monkeypatch.setattr('forecasting.ledger.snapshots.utc_now_iso',lambda:now[0])
    ledger=ForecastLedger(tmp_path/'db')
    q=ledger.create_question(title='Will the station report a hot day?',resolution_criteria='YES if the official station daily high exceeds 30 degrees.',domain='weather')
    source='https://weather.example/station/daily.json'
    raw=json.dumps({'properties':{'complete':True,'timestamp':now[0],'temperature':{'value':31.5}}}).encode()
    archive=tmp_path/'capture.json';archive.write_bytes(raw)
    monkeypatch.setattr(ledger,'_archive_url_evidence_snapshot',lambda **kw: {
        'snapshot_path':str(archive),'sha256':hashlib.sha256(raw).hexdigest(),'url':source,'status':200})
    ev=ledger.add_evidence(question_id=q.id,source_or_note=source,claim='Official daily report.')
    bind_fact(ledger,question_id=q.id,key='weather.report_complete',source_url=source,
        value_pointer='/properties/complete',observed_at_pointer='/properties/timestamp',value_type='boolean',max_age_seconds=3600)
    lesson=ledger.create_calibration_lesson(scope_type='domain',scope_ref='weather',lesson='Use completed daily reports.',status='active',
        recommended_adjustment={'applicability':{'evidence_equals':{'weather.report_complete':True}}})
    return ledger,q,lesson,ev,archive,now


def test_fact_is_source_bound_and_snapshot_freezes_proof(facts_setup):
    ledger,q,lesson,ev,archive,now=facts_setup
    assert lesson_applicability(lesson,q,ledger=ledger)==(True,'conditions_met')
    snapshot=ledger.create_snapshot(question_id=q.id,probability_or_distribution=.7,rationale='Official report inspected',
        metadata={'evidence_facts':{'forged':True}})
    proof=snapshot.metadata['evidence_facts']['weather.report_complete']
    assert proof['evidence_id']==ev.id and proof['value'] is True
    assert proof['sha256']==hashlib.sha256(archive.read_bytes()).hexdigest()
    now[0]='2026-09-01T14:00:00Z'
    assert not lesson_applicability(lesson,q,ledger=ledger)[0]
    assert ledger.get_snapshot(snapshot.forecast_id).metadata['evidence_facts']==snapshot.metadata['evidence_facts']


def test_tampered_archive_or_agent_metadata_cannot_satisfy_condition(facts_setup):
    ledger,q,lesson,ev,archive,now=facts_setup
    archive.write_text('{"properties":{"complete":true}}')
    assert evidence_facts(ledger,q)['weather.report_complete']['reason']=='archive_hash_mismatch'
    assert not lesson_applicability(lesson,q,context={'weather':{'report_complete':True},'evidence_facts':{'weather.report_complete':{'status':'verified','value':True}}},ledger=ledger)[0]


def test_manual_file_cannot_impersonate_a_fetched_source(facts_setup):
    ledger,q,lesson,ev,archive,now=facts_setup
    now[0]='2026-09-01T12:01:00Z'
    ledger.add_evidence(question_id=q.id,source_or_note='manually supplied',source_url=ev.source_url,
        snapshot_path=str(archive),metadata={'source_capture':{'url':ev.source_url,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'method':'https_fetch'}})
    fact=evidence_facts(ledger,q)['weather.report_complete']
    assert fact['status']=='unknown' and fact['reason']=='source_capture_unverified'


def test_future_capture_is_not_available_to_past_forecast(facts_setup):
    ledger,q,lesson,ev,archive,now=facts_setup
    assert evidence_facts(ledger,q,cutoff='2026-09-01T11:59:00Z')=={}


def test_packet_import_cannot_forge_a_local_fetch_receipt(facts_setup, tmp_path):
    ledger, q, _, _, _, _ = facts_setup
    packet = json.loads(ledger.export_question(q.id, fmt='json'))
    restored = ForecastLedger(tmp_path/'restored.db')
    restored.import_packet(packet)
    evidence = restored.list_evidence(q.id)[0]
    assert 'source_capture' not in evidence.metadata
    assert evidence.metadata['imported_source_capture']['method'] == 'https_fetch'
