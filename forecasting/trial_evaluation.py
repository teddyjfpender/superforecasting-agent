"""Read-only evaluation of frozen paired trials; independent of provider transport."""
from collections import Counter, defaultdict
import json
import math
import random
import statistics

from forecasting.models import ValidationError, timestamp_to_datetime

def trial_report(ledger, trial_id):
    from forecasting.learning_trials import trial_records, contract, arm_messages
    from forecasting.trial_contracts import evaluation_compatible
    trial, cases, arms = trial_records(ledger, trial_id)
    config = json.loads(trial['config'])
    index = {(a['question_id'], a['arm']): a for a in arms}
    exclusions = Counter()
    comparisons = []
    cohorts = defaultdict(lambda: defaultdict(list))
    kernel_matches = evaluation_compatible(trial)
    for case in cases:
        pair = [index[(case['question_id'], a)] for a in ('control', 'learning')]
        q = ledger.get_question(case['question_id'])
        resolution = ledger.get_latest_resolution(q.id, confirmed_only=True)
        reason = None
        try:
            expected_requests = {a: arm_messages(case, a, config.get('prompt_version', 'paired-learning-v2')) for a in ('control', 'learning')}
        except (ValidationError, ValueError, TypeError, KeyError):
            exclusions['packet_integrity_mismatch'] += 1
            continue
        if any(a['status'] != 'completed' for a in pair):
            reason = 'incomplete_pair'
        elif not resolution or not resolution.criteria_satisfied or not resolution.scoreable:
            reason = 'awaiting_resolution'
        elif not kernel_matches:
            reason = 'scoring_version_changed'
        elif contract(q) != json.loads(case['packet'])['question']:
            reason = 'question_contract_changed'
        elif any(timestamp_to_datetime(a['finished_at']) >= min(timestamp_to_datetime(q.close_time), timestamp_to_datetime(resolution.resolved_at)) for a in pair):
            reason = 'forecast_not_completed_before_cutoff'
        elif any(json.loads(a['request']) != expected_requests[a['arm']] for a in pair):
            reason = 'request_integrity_mismatch'
        elif len({(json.loads(a['response']).get('model'), json.loads(a['response']).get('endpoint')) for a in pair}) != 1:
            reason = 'provider_model_mismatch'
        else:
            for lesson in json.loads(case['treatment'])['lessons']:
                for sid in lesson.get('source_score_record_refs', []):
                    score = ledger.get_score(sid)
                    if score.invalidated_by_correction_id or score.audit_quarantine_reason:
                        reason = 'lesson_source_invalidated'
        if reason:
            exclusions[reason] += 1
            continue
        try:
            # Reconstruct outputs from immutable provider receipts and frozen
            # treatment. Stored output edits must never become accuracy evidence.
            from forecasting.trial_contracts import response_json
            from forecasting.learning import apply_active_lesson_adjustments
            from forecasting.trial_contracts import validate_response
            for arm in pair:
                parsed = response_json(json.loads(arm['response']))
                if config.get('prompt_version') == 'paired-learning-v3':
                    validate_response(parsed, json.loads(case['packet'])['question']['outcome_space'])
                output = json.loads(arm['output'])
                forecast = ledger._validate_probability_payload(parsed['forecast'], q.outcome_space)
                adjustment = {}
                if arm['arm'] == 'learning':
                    forecast, _, adjustment = apply_active_lesson_adjustments(ledger=ledger, question=q,
                        payload=forecast, calibration_lesson_refs=[], calibration_adjustment={},
                        frozen_lessons=json.loads(case['treatment'])['lessons'])
                if output != {'forecast': forecast, 'raw_forecast': parsed['forecast'],
                              'rationale': parsed['rationale'], 'adjustment': adjustment}:
                    raise ValidationError('output integrity mismatch')
            scores = [ledger._score_forecast_payload(json.loads(a['output'])['forecast'], resolution.outcome, q.outcome_space) for a in pair]
            if scores[0]['score_rule'] != scores[1]['score_rule'] or scores[0]['score_rule'] == 'vector_mae_percentage_points':
                raise ValidationError('incomparable loss rules')
            values = [s['proper_score'] for s in scores]
            if any(v is None or not math.isfinite(v) for v in values):
                raise ValidationError('nonfinite loss')
            gain = values[0] - values[1]
            key = (scores[0]['score_rule'], q.outcome_space.units or q.outcome_space.type)
            cohorts[key][case['cluster_id']].append(gain)
            comparisons.append({'question_id': q.id, 'cluster_id': case['cluster_id'], 'resolution_id': resolution.id,
                'control_loss': values[0], 'learning_loss': values[1], 'gain': gain, 'rule': key[0], 'units': key[1]})
        except (ValueError, TypeError, KeyError, ValidationError):
            exclusions['unscoreable_pair'] += 1
    estimates = []
    for (rule, units), clusters in cohorts.items():
        values = [statistics.mean(v) for v in clusters.values()]
        rng = random.Random(trial_id+rule+units)
        boot = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(2000))
        low, high = boot[49], boot[1949]
        enough = len(values) >= config['min_clusters'] and len(comparisons) == len(cases) and len(cohorts) == 1
        estimates.append({'score_rule': rule, 'units': units, 'clusters': len(values), 'mean_gain': statistics.mean(values),
            'cluster_bootstrap_95_interval': [low, high] if len(values) >= 2 else None,
            'status': 'benefit_supported_in_this_trial' if enough and low > config['minimum_effect'] else 'benefit_not_established'})
    return {'trial_id': trial_id, 'created_at': trial['created_at'], 'config': config,
        'evaluation_compatible': kernel_matches,
        'assigned_questions': len(cases), 'assigned_clusters': len({c['cluster_id'] for c in cases}),
        'arm_status_counts': dict(Counter(a['status'] for a in arms)), 'exclusions': dict(exclusions),
        'treatment_coverage': {
            'questions_with_lessons': sum(bool(json.loads(c['treatment'])['lessons']) for c in cases),
            'questions_with_error_profiles': sum(bool(json.loads(c['treatment'])['error_profiles']) for c in cases)},
        'estimates': estimates, 'comparisons': comparisons,
        'arms': [{k: a[k] for k in ('question_id', 'arm', 'status', 'started_at', 'finished_at', 'error')} for a in arms],
        'interpretation': 'Paired closed-book lesson-context and numeric-adjustment comparison; no live probabilities changed. '
            'Cluster IDs are operator-declared. Missing pairs remain in the denominator. Evidence is limited to this frozen policy, '
            'model, budget and question cohort; bootstrap uncertainty does not establish general forecasting superiority.'}
