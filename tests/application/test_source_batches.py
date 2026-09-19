"""Source batches preserve rollback, duplicate decisions and consumer parity."""

from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from forecasting.application.source_batches import commit_source_payloads
from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError


@pytest.fixture
def desk(tmp_path):
    ledger = ForecastLedger(tmp_path / 'forecast.db')
    question = ledger.create_question(title='Source batch', resolution_criteria='Resolves yes if the observation is published.')
    return ledger, question.id


def payload(identity, **changes):
    return {'source_or_note': 'observation', 'source_type': 'adapter:fred',
            'metadata': {'entry_id': identity}, **changes}


def test_late_invalid_row_rolls_back_and_retry_deduplicates(desk):
    ledger, qid = desk
    rows = [payload('first'), payload('second', published_at='not-a-timestamp')]
    with pytest.raises(ValidationError):
        commit_source_payloads(ledger, qid, rows)
    assert ledger.list_evidence(qid) == []
    result = commit_source_payloads(ledger, qid, [payload('first'), payload('first'), payload('second')])
    assert [row.index for row in result.imported] == [0, 2]
    assert result.duplicate_indices == (1,)
    retry = commit_source_payloads(ledger, qid, [payload('second'), payload('first')])
    assert retry.imported == ()
    assert retry.duplicate_indices == (0, 1)
    assert len(ledger.list_evidence(qid)) == 2
    assert ledger.get_question(qid).current_forecast_id is None


def test_concurrent_importers_decide_duplicates_inside_write_transaction(desk):
    ledger, qid = desk
    barrier = threading.Barrier(2)
    def run(_):
        barrier.wait(timeout=5)
        return commit_source_payloads(ledger, qid, [payload('shared')])
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(run, range(2)))
    assert sorted(len(result.imported) for result in results) == [0, 1]
    assert len(ledger.list_evidence(qid)) == 1


@pytest.mark.parametrize('dedupe', ['false', 0, None])
def test_invalid_boolean_is_not_coerced(desk, dedupe):
    ledger, qid = desk
    with pytest.raises(ValueError, match='boolean'):
        commit_source_payloads(ledger, qid, [payload('one')], dedupe=dedupe)
    assert ledger.list_evidence(qid) == []


@pytest.mark.parametrize('action', ['import_source_evidence', 'import_source_evidence_batch'])
def test_tool_sources_fail_atomically_and_other_sources_can_complete(desk, monkeypatch, action):
    from tools import forecasting_tool as tool
    from tools.forecast_actions.evidence import import_source_evidence, import_source_evidence_batch
    ledger, qid = desk
    def fetch(adapter, source, args):
        rows = [{'entry_id': source + ':one', 'source_url': 'https://example.test/' + source,
                 'published_at': '2026-01-01T00:00:00Z', 'title': source}]
        if source == 'bad':
            rows.append({**rows[0], 'entry_id': source + ':two', 'published_at': 'invalid'})
        return rows
    monkeypatch.setattr(tool, '_load_source_adapter_items', fetch)
    if action == 'import_source_evidence':
        with pytest.raises(ValidationError):
            import_source_evidence({'question_id': qid, 'source_type': 'fred', 'source': 'bad'}, ledger)
        assert ledger.list_evidence(qid) == []
    else:
        result = json.loads(import_source_evidence_batch({'question_id': qid, 'sources': [
            {'source_type': 'fred', 'source': 'bad'}, {'source_type': 'fred', 'source': 'good'}
        ]}, ledger))
        assert result['success'] and result['imported_count'] == 1
        assert result['results'][0]['success'] is False
        assert result['results'][0]['imported_count'] == 0
        assert result['results'][1]['success'] is True
        assert [item.metadata['entry_id'] for item in ledger.list_evidence(qid)] == ['good:one']


def test_failure_after_insert_rolls_back_without_poisoning_retry(desk, monkeypatch):
    ledger, qid = desk
    original = ledger.add_evidence
    count = 0
    def fail_after_write(**kwargs):
        nonlocal count
        evidence = original(**kwargs)
        count += 1
        if count == 2:
            raise OSError('interrupted after evidence insert')
        return evidence
    monkeypatch.setattr(ledger, 'add_evidence', fail_after_write)
    with pytest.raises(OSError, match='after evidence insert'):
        commit_source_payloads(ledger, qid, [payload('one'), payload('two')])
    assert ledger.list_evidence(qid) == []
    monkeypatch.setattr(ledger, 'add_evidence', original)
    assert len(commit_source_payloads(ledger, qid, [payload('one'), payload('two')]).imported) == 2


@pytest.mark.parametrize('override', [{'question_id': 'other'}, {'archive_url_snapshot': True}])
def test_source_payload_cannot_redirect_ownership_or_enable_fetching(desk, override):
    ledger, qid = desk
    with pytest.raises(ValueError, match='ownership'):
        commit_source_payloads(ledger, qid, [payload('one', **override)])
    assert ledger.list_evidence(qid) == []
