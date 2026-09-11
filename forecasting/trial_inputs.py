"""Shared admission checks for readiness reports and newly frozen trials."""
from forecasting.models import timestamp_to_datetime


def admissible_evidence(ledger, question_id, cutoff):
    """Keep invalidated and backtest-excluded observations out of frozen packets."""
    at = timestamp_to_datetime(cutoff)
    return [e for e in ledger.list_evidence(question_id)
            if e.admissible_for_backtests
            and not any(e.metadata.get(key) for key in ('blocked', 'invalidated', 'superseded_by', 'stale'))
            and all(t and timestamp_to_datetime(t) <= at for t in (e.available_at, e.captured_at))]


def score_support_problem(score, cutoff, excluded_questions=()):
    if not score.calibration_eligible or score.calibration_weight <= 0:
        return 'ineligible_source_score'
    if score.invalidated_by_correction_id or score.audit_quarantine_reason:
        return 'invalidated_source_score'
    if score.question_id in excluded_questions:
        return 'overlapping_source_outcome'
    if timestamp_to_datetime(score.scored_at) > timestamp_to_datetime(cutoff):
        return 'post_cutoff_source_score'
    return None


def settlement_ready(ledger, question_id):
    """A future close date does not make an already-known outcome prospective."""
    with ledger._connect() as conn:
        row = conn.execute('SELECT state FROM settlement_reviews WHERE question_id=? ORDER BY rowid DESC LIMIT 1', (question_id,)).fetchone()
    return row is not None and row[0] in ('ready', 'no_historical_forecast')
