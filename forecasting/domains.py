"""Semantic question domains, independent of acquisition and scoring origins."""
from forecasting.models import ValidationError, json_dumps, utc_now_iso

ACQUISITION_DOMAINS = frozenset({'market_nightly', 'forecastbench', 'imported_baseline', 'backtest'})
# Only explicit source categories are mapped. Titles are not a classification API.
SOURCE_DOMAINS = {
    'politics': 'politics', 'elections': 'politics', 'weather': 'weather',
    'climate': 'climate', 'economics': 'economics', 'economy': 'economics',
    'finance': 'finance', 'financials': 'finance', 'sports': 'sports',
    'science': 'science', 'technology': 'technology', 'crypto': 'crypto',
}


def semantic_domain(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError('domain must be a non-empty semantic label')
    value = value.strip().lower()
    if value in ACQUISITION_DOMAINS:
        raise ValidationError('acquisition origin is not a semantic domain')
    return value


def market_domain(market, explicit=None):
    if explicit and explicit not in ACQUISITION_DOMAINS:
        return semantic_domain(explicit), 'operator'
    value = market.get('domain') or market.get('category')
    if isinstance(value, str) and value.strip().lower() in SOURCE_DOMAINS:
        return SOURCE_DOMAINS[value.strip().lower()], 'source_category'
    return None, 'unknown_source_category'


def set_question_domain(ledger, question_id, *, domain, expected_domain, reason):
    """Correct an active question explicitly, preserving snapshots and score history."""
    from forecasting.ledger.core import _enforce_write_gate
    _enforce_write_gate('set_question_domain')
    domain = semantic_domain(domain)
    if not domain or not isinstance(reason, str) or not reason.strip():
        raise ValidationError('domain correction requires a semantic domain and reason')
    with ledger.transaction(immediate=True):
        q = ledger.get_question(question_id)
        if q.domain != expected_domain:
            raise ValidationError('question domain changed since review; inspect it again')
        if q.status != 'active':
            raise ValidationError('domain correction requires an active question')
        if q.domain == domain:
            return q
        metadata = dict(q.metadata)
        history = list(metadata.get('domain_history', []))
        history.append({'from': q.domain, 'to': domain, 'reason': reason.strip(), 'changed_at': utc_now_iso()})
        metadata['domain_history'] = history
        if q.domain in ACQUISITION_DOMAINS:
            metadata.setdefault('acquisition_origin', q.domain)
        with ledger._connect() as conn:
            conn.execute('UPDATE forecast_questions SET domain=?,metadata=? WHERE id=?',
                         (domain, json_dumps(metadata), q.id))
    return ledger.get_question(q.id)
