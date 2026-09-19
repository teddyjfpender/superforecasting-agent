"""Retries return the original acquisition without repeating network or writes."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from forecasting.application.market_imports import (
    MarketAcquisitionRequest,
    acquire_market_evidence,
)
from forecasting.ledger import ForecastLedger
from forecasting.models import LedgerNotFoundError
from tests.application.test_market_imports import market


@pytest.fixture
def context(tmp_path):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    question = ledger.create_question(
        title="Will it attach?",
        resolution_criteria="Resolved yes if evidence attaches.",
    )
    request = MarketAcquisitionRequest(
        question_id=question.id,
        source="KXTEST",
        provider="kalshi",
        api_base_url="https://mirror.example",
        request_id="retry-1",
    )
    return ledger, request


def fetch(*args, **kwargs):
    return market("kalshi")


def test_retry_does_not_acquire_again(context):
    ledger, request = context
    first = acquire_market_evidence(ledger, request, fetch=fetch)

    def unexpected(*args, **kwargs):
        pytest.fail("receipt replay fetched again")

    second = acquire_market_evidence(ledger, request, fetch=unexpected)
    assert first == second
    assert len(ledger.list_evidence(request.question_id)) == 1
    assert len(ledger.list_baseline_comparisons(request.question_id)) == 1


def test_changed_input_rejected_before_fetch(context):
    ledger, request = context
    acquire_market_evidence(ledger, request, fetch=fetch)
    with pytest.raises(ValueError, match="different input"):
        acquire_market_evidence(
            ledger, request.model_copy(update={"source": "OTHER"}), fetch=fetch
        )


def test_concurrent_acquisitions_commit_one_receipt(context):
    ledger, request = context
    barrier = Barrier(2)

    def concurrent(*args, **kwargs):
        barrier.wait(timeout=10)
        return fetch()

    def run():
        return acquire_market_evidence(
            ForecastLedger(ledger.db_path), request, fetch=concurrent
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: run(), range(2)))
    assert first == second
    assert len(ledger.list_evidence(request.question_id)) == 1
    assert len(ledger.list_baseline_comparisons(request.question_id)) == 1


def test_receipt_failure_rolls_back_both_records(context, monkeypatch):
    ledger, request = context

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("receipt interrupted")

    with monkeypatch.context() as patch:
        patch.setattr("forecasting.application.market_imports.write_receipt", fail)
        with pytest.raises(sqlite3.OperationalError, match="interrupted"):
            acquire_market_evidence(ledger, request, fetch=fetch)
    assert ledger.list_evidence(request.question_id) == []
    assert ledger.list_baseline_comparisons(request.question_id) == []
    assert acquire_market_evidence(ledger, request, fetch=fetch).comparison is not None


def test_evidence_only_receipt_schema_is_upgraded(context):
    ledger, request = context
    with ledger.transaction(immediate=True) as conn:
        conn.execute(
            "CREATE TABLE forecast_source_import_receipts (question_id TEXT, request_id TEXT, request_digest TEXT, evidence_ids TEXT, PRIMARY KEY(question_id,request_id))"
        )
        conn.execute(
            "INSERT INTO forecast_source_import_receipts VALUES (?,?,?,?)",
            (request.question_id, "historical", "frozen-digest", "[]"),
        )
    acquire_market_evidence(ledger, request, fetch=fetch)
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT request_digest,comparison_ids FROM forecast_source_import_receipts WHERE request_id='historical'"
        ).fetchone()
    assert tuple(row) == ("frozen-digest", "[]")


def test_missing_comparison_receipt_fails_closed(context):
    ledger, request = context
    result = acquire_market_evidence(ledger, request, fetch=fetch)
    with ledger.transaction(immediate=True) as conn:
        conn.execute(
            "DELETE FROM baseline_comparisons WHERE id=?", (result.comparison["id"],)
        )
    with pytest.raises(LedgerNotFoundError, match="baseline comparison not found"):
        acquire_market_evidence(ledger, request, fetch=fetch)
    assert len(ledger.list_evidence(request.question_id)) == 1


@pytest.mark.parametrize("provider", ["kalshi", "polymarket"])
def test_cli_replay_keeps_original_comparison(
    context, provider, monkeypatch, tmp_path, capsys
):
    from forecasting.cli import main

    ledger, request = context
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path / "profile"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profile"))
    calls = []

    def controlled(source, **kwargs):
        calls.append(source)
        return market(provider)

    monkeypatch.setattr(f"forecasting.cli.core.load_{provider}_market", controlled)
    argv = [
        "--db",
        str(ledger.db_path),
        "import",
        provider,
        "market-source",
        "--question",
        request.question_id,
        "--request-id",
        "cli-retry",
    ]
    main(argv)
    first_output = capsys.readouterr().out
    main(argv)
    assert capsys.readouterr().out == first_output
    assert calls == ["market-source"]
    assert len(ledger.list_evidence(request.question_id)) == 1
    assert len(ledger.list_baseline_comparisons(request.question_id)) == 1
    with pytest.raises(SystemExit) as failure:
        main([*argv, "--api-base-url", "https://different.example"])
    assert failure.value.code == 1
    assert "different input" in capsys.readouterr().err
    assert calls == ["market-source"]


def test_restart_after_commit_returns_receipt(context):
    import subprocess
    import sys

    ledger, request = context
    code = """
import os, sys
from forecasting.ledger import ForecastLedger, allow_ledger_writes
from forecasting.application.market_imports import MarketAcquisitionRequest, acquire_market_evidence
from forecasting.sources.kalshi_parsing import _kalshi_market_from_payload
request = MarketAcquisitionRequest.model_validate_json(sys.argv[2])
with allow_ledger_writes(reason="receipt-recovery-test"):
    acquire_market_evidence(ForecastLedger(sys.argv[1]), request,
        fetch=lambda *args, **kwargs: _kalshi_market_from_payload({"ticker":"KXTEST","title":"Question?","yes_bid":40}))
os._exit(0)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(ledger.db_path), request.model_dump_json()],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr

    def unexpected(*args, **kwargs):
        pytest.fail("post-crash replay acquired again")

    result = acquire_market_evidence(
        ForecastLedger(ledger.db_path), request, fetch=unexpected
    )
    assert result.comparison["probability_or_distribution"] == 0.4
    assert len(ledger.list_evidence(request.question_id)) == 1
