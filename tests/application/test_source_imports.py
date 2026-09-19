"""Shared imports preserve admission and atomic ledger behavior across consumers."""

from dataclasses import replace

import pytest

from forecasting.application.source_imports import (
    FredImportRequest,
    import_fred_evidence,
)
from forecasting.ledger import ForecastLedger
from forecasting.sources.economic_records import FredObservation
from forecasting.sources.requests import CommonSourceOptions


@pytest.fixture
def desk(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecast.db")
    question = ledger.create_question(
        title="Evidence import",
        resolution_criteria="Resolved yes if FRED evidence is imported.",
    )
    request = FredImportRequest(
        source="UNRATE",
        question_id=question.id,
        options=CommonSourceOptions(),
        as_of="2026-09-01T00:00:00Z",
    )
    return ledger, request


def row(**changes):
    return replace(
        FredObservation(
            "UNRATE",
            "2026-01-01",
            4.2,
            None,
            None,
            "FRED",
            "UNRATE:2026-01-01",
            {"value": "4.2"},
        ),
        **changes,
    )


def test_identical_rows_collapse_without_fabricating_publication(desk):
    ledger, request = desk
    evidence = import_fred_evidence(
        ledger, request, fetch=lambda *a, **kw: [row(), row()]
    )
    assert len(evidence) == 1
    assert evidence[0].published_at is None
    assert evidence[0].available_at == request.as_of
    assert ledger.get_question(request.question_id).current_forecast_id is None


@pytest.mark.parametrize(
    "invalid",
    [
        row(series_id="CPIAUCSL"),
        row(value=float("nan")),
        row(value="4.2"),
        row(value=True),
        row(value=4.3),
    ],
)
def test_invalid_or_conflicting_batch_writes_nothing(desk, invalid):
    ledger, request = desk
    with pytest.raises(ValueError):
        import_fred_evidence(ledger, request, fetch=lambda *a, **kw: [row(), invalid])
    assert ledger.list_evidence(request.question_id) == []


def test_mid_batch_storage_failure_rolls_back_every_row(desk, monkeypatch):
    ledger, request = desk
    add = ledger.add_evidence
    calls = 0

    def interrupted(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("storage interrupted")
        return add(**kwargs)

    monkeypatch.setattr(ledger, "add_evidence", interrupted)
    rows = [row(), row(entry_id="UNRATE:2026-02-01", observation_date="2026-02-01")]
    with pytest.raises(RuntimeError, match="storage interrupted"):
        import_fred_evidence(ledger, request, fetch=lambda *a, **kw: rows)
    assert ledger.list_evidence(request.question_id) == []
    monkeypatch.setattr(ledger, "add_evidence", add)
    assert len(import_fred_evidence(ledger, request, fetch=lambda *a, **kw: rows)) == 2


def test_fetch_uses_provider_defaults_outside_write_transaction(desk):
    ledger, request = desk

    def fetch(source, *, limit, since):
        assert ledger._transaction_connection.get() is None
        assert source == "UNRATE"
        assert limit == 10 and since is None
        return [row()]

    assert len(import_fred_evidence(ledger, request, fetch=fetch)) == 1


def test_acknowledged_retry_returns_original_evidence_without_refetch(desk):
    ledger, request = desk
    request = request.model_copy(update={"request_id": "delivery-1"})
    original = import_fred_evidence(ledger, request, fetch=lambda *a, **kw: [row()])

    def forbidden(*a, **kw):
        pytest.fail("acknowledged import was fetched again")

    assert import_fred_evidence(ledger, request, fetch=forbidden) == original
    assert len(ledger.list_evidence(request.question_id)) == 1
    changed = request.model_copy(update={"reliability": 0.5})
    with pytest.raises(ValueError, match="identifier reused"):
        import_fred_evidence(ledger, changed, fetch=forbidden)


def test_receipt_failure_rolls_back_evidence_and_retry_is_safe(desk, monkeypatch):
    from contextlib import contextmanager

    ledger, request = desk
    request = request.model_copy(update={"request_id": "delivery-1"})
    transaction = ledger.transaction

    class InterruptReceipt:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, params=()):
            if sql.startswith("INSERT INTO forecast_source_import_receipts"):
                raise RuntimeError("receipt interrupted")
            return self.conn.execute(sql, params)

    @contextmanager
    def interrupted(*a, **kw):
        with transaction(*a, **kw) as conn:
            yield InterruptReceipt(conn)

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "transaction", interrupted)
        with pytest.raises(RuntimeError, match="receipt interrupted"):
            import_fred_evidence(ledger, request, fetch=lambda *a, **kw: [row()])
    assert ledger.list_evidence(request.question_id) == []
    assert (
        len(import_fred_evidence(ledger, request, fetch=lambda *a, **kw: [row()])) == 1
    )


def test_concurrent_same_request_commits_only_one_batch(desk):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    ledger, request = desk
    request = request.model_copy(update={"request_id": "delivery-1"})
    barrier = Barrier(2)

    def fetch(*a, **kw):
        barrier.wait(timeout=5)
        return [row()]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(import_fred_evidence, ledger, request, fetch=fetch)
            for _ in range(2)
        ]
        results = [future.result(timeout=10) for future in futures]
    assert [item.id for item in results[0]] == [item.id for item in results[1]]
    assert len(ledger.list_evidence(request.question_id)) == 1


def test_committed_receipt_survives_process_exit(desk):
    import json
    import os
    import subprocess
    import sys

    ledger, request = desk
    request = request.model_copy(update={"request_id": "process-delivery"})
    with ledger._connect() as conn:
        path = conn.execute("PRAGMA database_list").fetchone()[2]
    program = """
import json, os, sys
from forecasting.application.source_imports import FredImportRequest, import_fred_evidence
from forecasting.ledger import ForecastLedger
from forecasting.sources.economic_records import FredObservation
request = FredImportRequest.model_validate_json(sys.argv[2])
def fetch(*args, **kwargs):
    return [FredObservation('UNRATE', '2026-01-01', 4.2, None, None, 'FRED', 'UNRATE:2026-01-01', {})]
items = import_fred_evidence(ForecastLedger(sys.argv[1]), request, fetch=fetch)
print(json.dumps([item.id for item in items]), flush=True)
os._exit(0)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, path, request.model_dump_json()],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
        env=os.environ.copy(),
    )

    def forbidden(*a, **kw):
        pytest.fail("durable retry refetched after process exit")

    replay = import_fred_evidence(ledger, request, fetch=forbidden)
    assert [item.id for item in replay] == json.loads(result.stdout)
    assert len(ledger.list_evidence(request.question_id)) == 1
