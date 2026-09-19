"""Durable source-batch retries retain exact input/result associations."""

from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from forecasting.application import source_batches
from forecasting.application.source_batches import commit_source_payloads
from forecasting.ledger import ForecastLedger


@pytest.fixture
def desk(tmp_path):
    ledger = ForecastLedger(tmp_path / 'forecast.db')
    question = ledger.create_question(title='Retry receipts', resolution_criteria='Resolves yes if the example agency publishes the January observation by 2027-02-01.')
    return ledger, question.id


def rows():
    return [
        {'source_or_note': 'anonymous observation'},
        {'source_or_note': 'identified', 'source_type': 'adapter:example', 'metadata': {'entry_id': 'one'}},
        {'source_or_note': 'identified', 'source_type': 'adapter:example', 'metadata': {'entry_id': 'one'}},
    ]


def test_replay_retains_original_indices_and_unidentified_evidence(desk):
    ledger, qid = desk
    first = commit_source_payloads(ledger, qid, rows(), request_id='retry')
    again = commit_source_payloads(ledger, qid, rows(), request_id='retry')
    assert first == again
    assert [row.index for row in again.imported] == [0, 1]
    assert again.duplicate_indices == (2,)
    assert len(ledger.list_evidence(qid)) == 2
    with pytest.raises(ValueError, match='reused for different input'):
        commit_source_payloads(ledger, qid, rows()[::-1], request_id='retry')
    with pytest.raises(ValueError, match='reused for different input'):
        commit_source_payloads(ledger, qid, rows(), request_id='retry', dedupe=False)
    assert len(ledger.list_evidence(qid)) == 2


def test_receipt_failure_rolls_back_evidence_and_retry(desk, monkeypatch):
    ledger, qid = desk
    write = source_batches.write_receipt
    def fail(*args, **kwargs):
        write(*args, **kwargs)
        raise OSError('after receipt insert')
    monkeypatch.setattr(source_batches, 'write_receipt', fail)
    with pytest.raises(OSError):
        commit_source_payloads(ledger, qid, rows(), request_id='retry')
    assert ledger.list_evidence(qid) == []
    monkeypatch.setattr(source_batches, 'write_receipt', write)
    assert len(commit_source_payloads(ledger, qid, rows(), request_id='retry').imported) == 2


def test_concurrent_receipt_commit_returns_one_identical_result(desk):
    ledger, qid = desk
    ready = threading.Barrier(2)
    def import_one(_):
        ready.wait(5)
        return commit_source_payloads(ledger, qid, rows(), request_id='concurrent')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(import_one, range(2)))
    assert first == second
    assert len(ledger.list_evidence(qid)) == 2


@pytest.mark.parametrize('indices', [
    {'version': True, 'imported': [0, 1], 'duplicates': [2]},
    {'version': 1, 'imported': [0, 0], 'duplicates': [2]},
    {'version': 1, 'imported': [0, 2], 'duplicates': [3]},
    {'version': 1, 'imported': [0], 'duplicates': [1, 2]},
])
def test_corrupt_receipt_mapping_fails_closed(desk, indices):
    ledger, qid = desk
    commit_source_payloads(ledger, qid, rows(), request_id='retry')
    with ledger.transaction(immediate=True) as conn:
        conn.execute('UPDATE forecast_source_import_receipts SET batch_indices=?', (json.dumps(indices),))
    with pytest.raises(ValueError, match='receipt'):
        commit_source_payloads(ledger, qid, rows(), request_id='retry')
    assert len(ledger.list_evidence(qid)) == 2


@pytest.mark.parametrize('surface', ['single', 'batch'])
def test_tool_retry_does_not_duplicate_anonymous_source_records(desk, monkeypatch, surface):
    from tools import forecasting_tool as tool
    from tools.forecast_actions.evidence import import_source_evidence
    ledger, qid = desk
    monkeypatch.setattr(tool, '_load_source_adapter_items', lambda *args: [{'title': 'No entry ID'}])
    request = {'question_id': qid, 'request_id': 'retry', 'source_type': 'rss', 'source': 'https://example.test/feed'}
    def run():
        if surface == 'single':
            return json.loads(import_source_evidence(request, ledger))
        return json.loads(tool._import_source_evidence_batch_payload(ledger, {
            'question_id': qid, 'request_id': 'retry', 'sources': [
                {'source_type': 'rss', 'source': 'https://example.test/feed'},
                {'source_type': 'rss', 'source': 'https://example.test/second'},
            ],
        }))
    first = run()
    ids = [item.id for item in ledger.list_evidence(qid)]
    second = run()
    assert first['imported_count'] == second['imported_count']
    assert [item.id for item in ledger.list_evidence(qid)] == ids
    assert len(ids) == (1 if surface == 'single' else 2)
