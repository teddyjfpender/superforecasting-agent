"""Read-only cohort preparation: expose evidence and treatment gaps before calls."""
from collections import Counter

from forecasting.learning import active_lessons_for_question, _in_scope_lessons, lesson_applicability
from forecasting.trial_inputs import admissible_evidence, score_support_problem, settlement_ready
from forecasting.models import timestamp_to_datetime, utc_now_iso


def candidate_report(ledger):
    cutoff = utc_now_iso()
    now = timestamp_to_datetime(cutoff)
    candidates = []
    for q in ledger.list_questions(status='active'):
        if not q.close_time or timestamp_to_datetime(q.close_time) <= now:
            continue
        reasons = []
        if ledger.get_latest_resolution(q.id) or settlement_ready(ledger, q.id):
            reasons.append('resolution_already_known')
        if q.outcome_space.type not in ('binary', 'categorical', 'numeric', 'distribution') or (q.outcome_space.type == 'distribution' and q.outcome_space.choices):
            reasons.append('no_comparable_proper_trial_loss')
        evidence = admissible_evidence(ledger, q.id, cutoff)
        if not evidence:
            reasons.append('missing_pre_cutoff_evidence')
        lessons = active_lessons_for_question(ledger, q, context={'_fact_cutoff': cutoff})
        if not lessons:
            reasons.append('no_applicable_lesson')
        backed = []
        for lesson in lessons:
            refs = lesson.get('source_score_record_refs', [])
            scores = [ledger.get_score(ref) for ref in refs]
            if scores and all(not score_support_problem(s, cutoff, (q.id,)) for s in scores):
                backed.append(lesson['id'])
        if lessons and not backed:
            reasons.append('no_outcome_backed_lesson')
        candidates.append({'question_id': q.id, 'title': q.title, 'domain': q.domain,
            'close_time': q.close_time, 'outcome_type': q.outcome_space.type,
            'evidence_count': len(evidence), 'lesson_refs': [l['id'] for l in lessons],
            'outcome_backed_lesson_refs': backed,
            'lesson_conditions': [{'lesson_id': lesson['id'], 'decision': lesson_applicability(lesson, q, {'_fact_cutoff': cutoff}, ledger=ledger)[1]} for lesson in _in_scope_lessons(ledger, q)], 'readiness_gaps': reasons})
    return {'as_of': cutoff, 'future_questions': len(candidates),
        'ready_for_cluster_review': sum(not c['readiness_gaps'] for c in candidates),
        'gap_counts': dict(Counter(r for c in candidates for r in c['readiness_gaps'])),
        'candidates': candidates,
        'next_action': 'Research missing evidence and review genuinely applicable outcome-backed lessons, then assign independent event clusters explicitly. No independence is inferred from titles or domains.'}
