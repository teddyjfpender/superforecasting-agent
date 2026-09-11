"""Bind settlement to an existing source-specific measurement, with audit history."""
from forecasting.applicability_facts import evidence_facts
from forecasting.models import ValidationError, json_dumps, utc_now_iso


def bind_settlement(ledger, question_id, *, fact_key, entity, units, measurement,
                    window_start, window_end, reason):
    from forecasting.ledger.gate import _enforce_write_gate
    _enforce_write_gate('bind_settlement')
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError('settlement binding requires a review reason')
    with ledger.transaction(immediate=True):
        q = ledger.get_question(question_id)
        if ledger.get_latest_resolution(q.id):
            raise ValidationError('resolved questions require the correction workflow')
        if q.outcome_space.type not in ('numeric', 'distribution') or q.outcome_space.choices or q.outcome_space.censoring:
            raise ValidationError('measurement settlement requires an uncensored scalar outcome')
        if q.outcome_space.units != units:
            raise ValidationError('question units must exactly match the source measurement; implicit conversions are forbidden')
        fact = evidence_facts(ledger, q).get(fact_key, {})
        expected = dict(entity=entity, units=units, measurement=measurement,
                        window_start=window_start, window_end=window_end)
        _check_measurement(fact, expected)
        binding = {**expected, 'fact_key':fact_key, 'binding_id':fact['binding_id'],
                   'revision_policy':fact.get('revision_policy'), 'published_at':fact.get('published_at'),
                   'source_url':fact['source_url'], 'reason':reason.strip(), 'bound_at':utc_now_iso()}
        metadata = dict(q.metadata)
        history = list(metadata.get('settlement_binding_history', []))
        history.append(binding)
        metadata['settlement_binding_history'] = history
        metadata['settlement_binding'] = binding
        with ledger._connect() as conn:
            conn.execute('UPDATE forecast_questions SET metadata=? WHERE id=?', (json_dumps(metadata), q.id))
    return binding


def _check_measurement(fact, expected, *, historical_import=False):
    if fact.get('status') not in (('verified', 'imported') if historical_import else ('verified',)) or fact.get('adapter') not in ('nws_temperature_v1', 'usgs_magnitude_v1', 'bls_observation_v1', 'fred_observation_v1'):
        raise ValidationError('settlement requires a verified source-specific measurement')
    for key in ('entity', 'units', 'measurement', 'window_start', 'window_end'):
        if fact.get(key) != expected[key]:
            raise ValidationError('settlement measurement mismatch: ' + key)
    if 'revision_policy' in expected and fact.get('revision_policy') != expected['revision_policy']:
        raise ValidationError('settlement revision policy changed')
    if fact.get('adapter') == 'usgs_magnitude_v1' and fact.get('review_status') != 'reviewed':
        raise ValidationError('automatic earthquake estimates are not reviewed settlement evidence')


def verify_settlement(ledger, question, outcome, source, snapshot_ref, *, historical_import=False, cutoff=None):
    binding = question.metadata.get('settlement_binding')
    if not binding:
        return
    if question.outcome_space.units != binding['units']:
        raise ValidationError('question units changed since settlement binding review')
    fact = evidence_facts(ledger, question, cutoff=cutoff).get(binding['fact_key'], {})
    _check_measurement(fact, binding, historical_import=historical_import)
    if fact.get('binding_id') != binding['binding_id']:
        raise ValidationError('source fact binding changed; review settlement binding again')
    if source != binding['source_url'] or fact['source_url'] != source:
        raise ValidationError('resolution source differs from the bound canonical source')
    evidence = ledger.get_evidence(fact['evidence_id'])
    if snapshot_ref not in (fact['evidence_id'], evidence.snapshot_path):
        raise ValidationError('resolution must reference the verified source archive')
    if type(outcome) not in (int, float) or outcome != fact['value']:
        raise ValidationError('resolution outcome differs from the verified measurement')
