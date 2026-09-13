"""Audited conversion of pre-existing prose censoring, never forecast rewrites."""
import hashlib
import json

from forecasting.censoring import threshold_probability, validate_contract
from forecasting.models import OutcomeSpace, ValidationError, json_dumps, utc_now_iso


def policy_preview(ledger, question_id, *, contract, criteria_quote, reason):
    validate_contract(contract)
    q = ledger.get_question(question_id)
    if q.outcome_space.censoring is not None:
        raise ValidationError('question already has a typed censoring policy')
    if not isinstance(criteria_quote, str) or not criteria_quote.strip() or criteria_quote not in q.resolution_criteria:
        raise ValidationError('quote must exactly match the historical resolution criteria')
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError('conversion requires a substantive review reason')
    if ledger.get_latest_resolution(question_id) is not None:
        raise ValidationError('existing resolutions require the correction workflow')
    space = q.outcome_space.to_dict()
    OutcomeSpace.from_dict({**space, 'censoring': contract})
    snapshots = ledger.list_snapshots(question_id)
    manifest = [{'forecast_id': s.forecast_id, 'created_at': s.created_at,
                 'payload': s.probability_or_distribution} for s in snapshots]
    probabilities = [{'forecast_id': s.forecast_id,
                      'tail_probability': threshold_probability(s.probability_or_distribution, contract)} for s in snapshots]
    original = {'question_id': q.id, 'created_at': q.created_at,
                'resolution_criteria': q.resolution_criteria, 'outcome_space': space,
                'snapshots': manifest}
    encoded = json.dumps(original, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return {'original_sha256': hashlib.sha256(encoded).hexdigest(), 'original': original,
            'contract': contract, 'criteria_quote': criteria_quote, 'reason': reason.strip(),
            'probabilities': probabilities, 'retrospective_policy_review': True,
            'calibration_eligible': False,
            'warning': 'Threshold-event scores only. This review does not establish prospective scoring-policy provenance or full-distribution accuracy.'}


def convert_policy(ledger, question_id, *, expected_sha256, contract, criteria_quote, reason):
    from forecasting.ledger.gate import _enforce_write_gate
    _enforce_write_gate('convert_censoring_policy')
    with ledger.transaction(immediate=True):
        review = policy_preview(ledger, question_id, contract=contract, criteria_quote=criteria_quote, reason=reason)
        if review['original_sha256'] != expected_sha256:
            raise ValidationError('question or forecast history changed since policy review')
        q = ledger.get_question(question_id)
        metadata = dict(q.metadata)
        history = list(metadata.get('censoring_policy_reviews', []))
        history.append({**review, 'reviewed_at': utc_now_iso()})
        metadata['censoring_policy_reviews'] = history
        with ledger._connect() as conn:
            conn.execute('UPDATE forecast_questions SET outcome_space=?,metadata=? WHERE id=?',
                (json_dumps({**q.outcome_space.to_dict(), 'censoring': contract}), json_dumps(metadata), q.id))
    return {'question_id': q.id, 'review': history[-1]}
