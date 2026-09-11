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


def test_numeric_response_contract_rejects_aliases_strings_and_degenerate_sd():
    from forecasting.trial_contracts import validate_response, response_schema
    space = {'type': 'numeric', 'units': 'percent'}
    validate_response({'forecast': {'mean': 21, 'sd': 5}, 'rationale': 'Evidence e1'}, space)
    assert response_schema(space)['properties']['forecast']['additionalProperties'] is False
    for forecast in ({'mean': 21, 'stdev': 5, 'type': 'normal'}, {'mean': '21', 'sd': 5}, {'mean': 21, 'sd': 0}, 21):
        with pytest.raises(ValidationError, match='response schema'):
            validate_response({'forecast': forecast, 'rationale': 'Evidence e1'}, space)


def test_provider_pacing_is_shared_durable_and_does_not_reserve_rejected_calls(tmp_path):
    from forecasting.trial_provider import reserve_quota
    ledger = ForecastLedger(tmp_path/'ledger.db')
    config = {'provider': 'fixture', 'requests_per_minute': 6, 'input_tokens_per_minute': 5000}
    with ledger.transaction(immediate=True), ledger._connect() as conn:
        assert reserve_quota(conn, config, [], '2026-09-11T00:00:00Z') is None
        pause = reserve_quota(conn, config, [], '2026-09-11T00:00:01Z')
        assert pause['retry_after_seconds'] == 9
        assert reserve_quota(conn, config, [], '2026-09-11T00:00:10Z') is None
        assert reserve_quota(conn, config, [], '2026-09-11T00:00:20Z')['retry_after_seconds'] == 40
        assert conn.execute('SELECT count(*) FROM learning_provider_reservations').fetchone()[0] == 2
        assert reserve_quota(conn, config, ['x'*5000], '2026-09-11T00:02:00Z')['reason'] == 'request_exceeds_input_budget'
        assert reserve_quota(conn, config, [], '2026-09-11T00:02:00Z') is None
