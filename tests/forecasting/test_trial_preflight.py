import pytest
from forecasting import ForecastLedger
from forecasting.models import ValidationError
from forecasting.trial_provider import preflight, require_preflight, response_json


def receipt(*_, reason='stop'):
    return {'model': 'fixture', 'endpoint': 'https://fixture.invalid/v1',
        'finish_reason': reason, 'content': '{"forecast":0.5,"rationale":"A fair coin."}'}


def test_readiness_is_bound_to_budget_and_retains_truncation(tmp_path):
    ledger = ForecastLedger(tmp_path/'ledger.db')
    config = {'provider': 'fixture', 'model': 'fixture', 'max_tokens': 8192}
    probe = preflight(ledger, config, runner=receipt)
    assert require_preflight(ledger, {**config, 'preflight_id': probe['preflight_id']})['model'] == 'fixture'
    with pytest.raises(ValidationError, match='exact model'):
        require_preflight(ledger, {**config, 'max_tokens': 128, 'preflight_id': probe['preflight_id']})
    failed = preflight(ledger, config, runner=lambda *_: receipt(reason='length'))
    assert failed['status'] == 'failed' and failed['receipt']['finish_reason'] == 'length'
    with pytest.raises(ValidationError, match='incomplete'):
        response_json(receipt(reason='length'))
