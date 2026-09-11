"""Outcome-backed learning audit, without confusing compliance with skill.

One earliest eligible pre-close live forecast per question prevents selecting
winning updates after seeing the outcome. Cohorts remain observational: lesson
exposure is not randomized, and close time alone cannot prove outcome ignorance.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import math
import statistics


def learning_effectiveness(ledger):
    with ledger._connect() as conn:
        snapshots = [dict(r) for r in conn.execute("""
            SELECT f.*, q.domain, q.close_time, q.outcome_space
            FROM forecast_snapshots f JOIN forecast_questions q ON q.id=f.question_id
            WHERE f.forecast_origin='live' AND f.calibration_eligible=1
            ORDER BY julianday(f.created_at), f.rowid
        """)]
        resolutions = {r['question_id']: dict(r) for r in conn.execute("""
            SELECT * FROM resolutions WHERE resolution_status='confirmed'
              AND criteria_satisfied=1 AND scoreable=1 ORDER BY julianday(resolved_at), rowid
        """)}
        scores = {r['id']: dict(r) for r in conn.execute('SELECT * FROM score_records')}
    from forecasting.models import timestamp_to_datetime, ValidationError

    def before(a, b):
        return bool(a and b and timestamp_to_datetime(a) < timestamp_to_datetime(b))

    counts = Counter()
    exclusions = Counter()
    cohorts = defaultdict(list)
    scores_by_pair = defaultdict(list)
    for score in scores.values():
        scores_by_pair[(score['forecast_id'], score['resolution_id'])].append(score)
    selected = set()
    pairs = []
    records = []
    update_gains = defaultdict(list)
    latest_by_question = {}
    for candidate in snapshots:
        resolved = resolutions.get(candidate["question_id"])
        if resolved:
            cutoff = min((x for x in [candidate["close_time"], resolved["resolved_at"]] if x), key=timestamp_to_datetime)
            if before(candidate["created_at"], cutoff) and before(candidate["as_of"], cutoff):
                latest_by_question[candidate["question_id"]] = candidate
    for row in snapshots:
        counts['eligible_live_snapshots'] += 1
        metadata = json.loads(row['metadata'] or '{}')
        decisions = metadata.get('lesson_decisions')
        counts['verified_decision_snapshots' if isinstance(decisions, list) else 'historical_unverified_snapshots'] += 1
        resolution = resolutions.get(row['question_id'])
        if not resolution:
            exclusions['unresolved'] += 1
            continue
        # Require BOTH claimed evidence time and durable insertion time before
        # the cutoff. Historical imports cannot masquerade as prospective calls.
        cutoff = min((x for x in [row['close_time'], resolution['resolved_at']] if x), key=timestamp_to_datetime)
        if not before(row['created_at'], cutoff) or not before(row['as_of'], cutoff):
            exclusions['not_recorded_before_cutoff'] += 1
            continue
        if row['question_id'] in selected:
            exclusions['repeat_question_snapshot'] += 1
            continue
        selected.add(row['question_id'])
        valid = [s for s in scores_by_pair[(row['forecast_id'], resolution['id'])]
                 if not s['invalidated_by_correction_id'] and not s['audit_quarantine_reason']]
        legacy = bool(valid and valid[-1]['score_rule'] in ('crps_discrete_cdf', 'crps_discrete_pmf'))
        if not valid or legacy:
            if not valid and scores_by_pair[(row['forecast_id'], resolution['id'])]:
                exclusions['invalidated_or_quarantined_score'] += 1
                continue
            # Score the PRESELECTED frozen input with the existing proper-score
            # kernel, read-only. Never fall back to a later, better-looking call.
            try:
                from forecasting.models import OutcomeSpace
                computed = ledger._score_forecast_payload(
                    json.loads(row['probability_or_distribution']), json.loads(resolution['outcome']),
                    OutcomeSpace(**json.loads(row['outcome_space'])),
                )
            except (ValueError, TypeError, KeyError, ValidationError):
                exclusions['selected_snapshot_unscoreable'] += 1
                continue
            score = {**computed, 'id': None}
            counts['scores_recomputed_read_only'] += 1
        else:
            score = valid[-1]
        refs = json.loads(row['calibration_lesson_refs'] or '[]')
        # Immutable source references, not the lesson's currently edited text.
        lineage = 'verified' if isinstance(decisions, list) else 'unknown'
        for decision in decisions or []:
            if not (decision.get('applied') or decision.get('consulted')):
                continue
            for sid in decision.get('source_score_record_refs', []):
                source = scores.get(sid)
                if not source or source['invalidated_by_correction_id'] or source['audit_quarantine_reason']:
                    lineage = 'invalid_source'
                elif source['question_id']==row['question_id'] or not before(source['scored_at'], row['created_at']) or not before(source['scored_at'], row['as_of']):
                    lineage = 'training_overlap_or_future_source'
        if score['score_rule'] == 'vector_mae_percentage_points':
            exclusions['accuracy_metric_not_proper_loss'] += 1
            continue
        counts['scored_distinct_questions'] += 1
        counts['lineage_'+lineage] += 1
        value = score['proper_score']
        if value is None:
            value = score['brier_score']
        space = json.loads(row['outcome_space'])
        key = (row['domain'] or 'unclassified', score['score_rule'] or 'brier', space.get('units') or space['type'], bool(refs))
        if value is not None and math.isfinite(value):
            cohorts[key].append(value)
        record = {'question_id': row['question_id'], 'forecast_id': row['forecast_id'],
                  'resolution_id': resolution['id'], 'score_id': score['id'],
                  'lesson_refs': refs, 'lineage': lineage, 'score_rule': score['score_rule'],
                  'score': value, 'created_at': row['created_at'], 'cutoff': cutoff}
        adjustment = json.loads(row['calibration_adjustment'] or '{}')
        raw = adjustment.get('raw_probability')
        probability = json.loads(row['probability_or_distribution'])
        outcome = json.loads(resolution['outcome'])
        if (isinstance(raw, (float, int)) and not isinstance(raw, bool) and 0 <= raw <= 1
            and isinstance(probability, (float, int)) and not isinstance(probability, bool)
            and score['brier_score'] is not None and outcome in ('yes', 'no', True, False, 0, 1)):
            observed = 1.0 if outcome in ('yes', True, 1) else 0.0
            delta = (raw-observed)**2 - (probability-observed)**2
            pairs.append(delta)
            record['self_reported_numeric_brier_gain'] = delta
        latest = latest_by_question.get(row['question_id'])
        if latest and latest['forecast_id'] != row['forecast_id'] and value is not None:
            try:
                from forecasting.models import OutcomeSpace
                latest_score = ledger._score_forecast_payload(json.loads(latest['probability_or_distribution']),
                    outcome, OutcomeSpace(**space))
                if latest_score['score_rule'] == score['score_rule'] and latest_score['proper_score'] is not None:
                    gain = value - latest_score['proper_score']
                    update_gains[key[:3]].append(gain)
                    record['later_preclose_forecast_id'] = latest['forecast_id']
                    record['update_score_gain'] = gain
            except (ValueError, TypeError, KeyError, ValidationError):
                pass
        records.append(record)
    return {
        'status': 'benefit_not_established',
        'selection': 'earliest eligible live snapshot durably recorded before close and resolution; one per question',
        'counts': dict(counts), 'exclusions': dict(exclusions),
        'observational_cohorts': [
            {'domain': d, 'score_rule': rule, 'units': units, 'lesson_refs_recorded': exposed,
             'questions': len(values), 'mean_score': statistics.mean(values)}
            for (d, rule, units, exposed), values in sorted(cohorts.items())
        ],
        'update_trajectory': [{'domain': d, 'score_rule': rule, 'units': units, 'questions': len(gains),
                               'mean_score_gain': statistics.mean(gains), 'attribution': 'later evidence and updates; not a lesson effect'}
                              for (d, rule, units), gains in sorted(update_gains.items())],
        'numeric_replay': {'pairs': len(pairs), 'mean_brier_gain': statistics.mean(pairs) if pairs else None,
                           'provenance': 'self-reported pre-adjustment probability; diagnostic only'},
        'interpretation': 'Rule compliance and lesson references are process evidence, not causal forecasting improvement. '
                          'Cohorts differ in difficulty and horizon. Numeric replay measures only the reported mechanical change, '
                          'not the effect of advice on reasoning. Weather post-maximum observations require separate cohorts.',
        'next_action': 'Pre-register a question-level learning/control comparison with identical evidence cutoffs, '
                       'freeze lesson versions before forecasting, and score every assigned question after resolution.',
        'records': records,
    }
