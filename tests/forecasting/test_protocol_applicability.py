from forecasting import ForecastLedger
from forecasting.protocol import build_protocol_messages


def test_update_prompt_renders_conditional_lessons_and_unknown_source_facts(tmp_path):
    ledger = ForecastLedger(tmp_path/'db')
    q = ledger.create_question(title='Will the station exceed the threshold?',
        resolution_criteria='Resolves yes if the official daily station maximum exceeds 30 degrees.', domain='weather')
    lesson = ledger.create_calibration_lesson(scope_type='domain', scope_ref='weather',
        lesson='Use the completed daily report only after its source is verified.', status='active',
        recommended_adjustment={'applicability':{'evidence_equals':{'weather.complete':True}}})
    messages = build_protocol_messages(ledger, q.id, stage='update')
    prompt = '\n'.join(m.content for m in messages)
    assert lesson['id'] in prompt
    assert 'Applicability evidence' in prompt
    assert 'evidence_unknown:weather.complete:binding_missing' in prompt
    assert 'forecast facts show '+q.id in prompt
