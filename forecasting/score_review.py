"""Outcome-space-aware baselines for review prompts, not calibration claims."""
from forecasting.models import LedgerNotFoundError


def uninformative_brier(ledger, score):
    """Match the ledger's scalar binary vs summed categorical Brier convention."""
    try:
        snapshot = ledger.get_snapshot(score.forecast_id)
        question = ledger.get_question(score.question_id)
    except LedgerNotFoundError:
        return None
    payload = snapshot.probability_or_distribution
    if isinstance(payload, dict):
        labels = {str(k).lower() for k in payload}
        labels.update(str(k).lower() for k in question.outcome_space.choices)
        return 1 - 1 / len(labels) if len(labels) >= 2 else None
    return .25 if question.outcome_space.type == 'binary' else None
