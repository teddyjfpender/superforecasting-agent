"""Wire enforcement preserves domain failures and never logs secret values."""

from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from protocol.rpc.commands import CommandDispatchResponse
from protocol.validation import ContractViolation, contract_handler


def test_unknown_field_is_rejected_before_effects():
    handler = Mock()
    result = contract_handler("paste.collapse", handler)(
        1, {"text": "x", "typo": "secret"}
    )
    assert result["error"]["code"] == 4000
    assert "secret" not in str(result)
    handler.assert_not_called()


def test_domain_failure_is_returned_unchanged():
    failure = {
        "jsonrpc": "2.0",
        "id": 2,
        "error": {"code": 4004, "message": "empty paste"},
    }
    handler = Mock(return_value=failure)
    assert contract_handler("paste.collapse", handler)(2, {}) is failure


def test_successful_invalid_result_fails_contract_without_exposing_payload():
    handler = Mock(return_value={"result": {"path": "private-secret"}})
    with pytest.raises(ContractViolation) as exc:
        contract_handler("paste.collapse", handler)(1, {"text": "secret-input"})
    assert "private-secret" not in str(exc.value) and "secret-input" not in str(
        exc.value
    )


def test_invalid_parameter_types_are_rejected_before_side_effects():
    handler = Mock()
    result = contract_handler("paste.collapse", handler)(1, {"text": []})
    assert result["error"]["code"] == 4000
    handler.assert_not_called()


def test_command_outcomes_require_their_own_fields():
    assert (
        CommandDispatchResponse.model_validate({
            "type": "alias",
            "target": "help",
        }).root.target
        == "help"
    )
    with pytest.raises(ValidationError):
        CommandDispatchResponse.model_validate({"type": "alias", "output": "help"})


def test_bundled_gateway_methods_all_have_one_contract():
    from protocol import RPC_BY_METHOD, RPC_SPECS
    from tui_gateway import server

    assert len(RPC_BY_METHOD) == len(RPC_SPECS), "duplicate method declarations"
    assert set(server._methods) <= RPC_BY_METHOD.keys()


def test_contract_violation_fails_closed_outside_pytest_mode(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    handler = Mock(return_value={"result": {"path": "only one field"}})
    result = contract_handler("paste.collapse", handler)(1, {"text": "x"})
    assert result["error"]["code"] == -32603
    assert "result" not in result


@pytest.mark.parametrize("params", [{"stale": "false"}, {"typo": True}])
def test_shared_domain_validator_cannot_silently_accept_invalid_input(params):
    handler = Mock(return_value={"result": {"rows": []}})
    with pytest.raises(ContractViolation):
        contract_handler("forecast.review", handler)(1, params)
