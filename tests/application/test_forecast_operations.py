"""Product adapters agree on durable forecast operations and errors."""
from __future__ import annotations

import builtins
from dataclasses import asdict

import pytest

from forecasting.application.resolution import resolve_forecast
from forecasting.application.reviews import review_forecasts
from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    # Narrative generation is an optional provider integration, not settlement.
    monkeypatch.setattr("forecasting.writeup.write_retrospective", lambda *a, **kw: None)
    ledger = ForecastLedger()
    question = ledger.create_question(title="Will the fixture finish?", resolution_criteria="Resolves YES if the official fixture completion record confirms completion by 2026-09-11; otherwise NO.")
    ledger.create_snapshot(question_id=question.id, probability_or_distribution=0.7, rationale="Baseline.")
    return ledger, question


def rpc(method, params):
    from tui_gateway import forecast_operations_rpc, server
    forecast_operations_rpc.register(server)
    return server.handle_request({"jsonrpc": "2.0", "id": "test", "method": method, "params": params})


def test_structured_review_and_resolution_do_not_import_cli(desk, monkeypatch):
    ledger, question = desk
    # Import the host first: its remaining legacy startup edges are a separate
    # migration. Once hosted, these operations must not execute/import the CLI.
    from tui_gateway import server  # noqa: F401
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "cli" or name == "forecasting.cli" or name.startswith("forecasting.cli."):
            raise AssertionError(f"Application operation imported presentation: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    review = rpc("forecast.review", {})
    assert question.id in [row["question"]["id"] for row in review["result"]["rows"]]
    values = {"question_id": question.id, "outcome": True, "resolution_source": "Fixture completion"}
    result = rpc("forecast.resolve", values)["result"]
    assert result["resolution"]["question_id"] == question.id
    assert ledger.get_question(question.id).status == "resolved"
    assert result["score"] is not None
    retry = resolve_forecast(ledger, values)
    assert asdict(retry.resolution) == result["resolution"]
    assert retry.score.id == result["score"]["id"]


def test_invalid_resolution_has_same_error_and_no_write(desk):
    ledger, question = desk
    values = {"question_id": question.id, "outcome": True, "criteria_satisfied": "false"}
    with pytest.raises(ValidationError) as failure:
        resolve_forecast(ledger, values)
    response = rpc("forecast.resolve", values)
    assert response["error"]["code"] == 4003
    assert response["error"]["message"] == str(failure.value)
    assert ledger.get_latest_resolution(question.id) is None
    assert ledger.get_question(question.id).status == "active"


def test_review_rejects_unknown_parameters_and_wrong_boolean_types(desk):
    ledger, _ = desk
    for values in ({"stale": "false"}, {"confidence_abov": 0.5}, {"last_days": -1}):
        with pytest.raises(ValidationError) as failure:
            review_forecasts(ledger, **values)
        assert rpc("forecast.review", values)["error"]["message"] == str(failure.value)


def test_cli_and_rpc_resolution_share_retry_identity(desk, capsys):
    ledger, question = desk
    from forecasting.cli import main
    main(["resolve", question.id, "--outcome", "true", "--source", "Fixture completion"])
    resolution = ledger.get_latest_resolution(question.id)
    assert resolution.id in capsys.readouterr().out
    response = rpc("forecast.resolve", {"question_id": question.id, "outcome": True,
                                        "resolution_source": "Fixture completion"})
    assert response["result"]["resolution"]["id"] == resolution.id


def test_terminal_operation_uses_shared_flags_without_cli_or_stdout(desk, monkeypatch, capsys):
    ledger, question = desk
    from tui_gateway import server  # noqa: F401
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "cli" or name == "forecasting.cli" or name.startswith("forecasting.cli."):
            raise AssertionError(f"Command operation imported CLI: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    review = rpc("forecast.operation", {"operation": "review", "arg": "--last 7d"})["result"]
    assert question.title in review["output"]
    result = rpc("forecast.operation", {"operation": "resolve", "argv": [question.id, "--outcome", "true",
                               "--source", "Fixture completion"]})["result"]
    assert result["code"] == 0
    assert result["data"]["resolution"]["id"] == ledger.get_latest_resolution(question.id).id
    assert "auto_score:" in result["output"]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize('operation', ['review', 'resolve'])
def test_terminal_operation_help_and_parse_failure_do_not_write(desk, operation, capsys):
    ledger, question = desk
    help_result = rpc("forecast.operation", {"operation": operation, "arg": "--help"})["result"]
    assert help_result["code"] == 0
    assert f"forecast {operation}" in help_result["output"]
    rejected = rpc("forecast.operation", {"operation": operation, "arg": "--unknown"})["result"]
    assert rejected["code"] == 2
    assert ledger.get_latest_resolution(question.id) is None
    assert capsys.readouterr().out == ""
