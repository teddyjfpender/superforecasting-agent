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


@pytest.mark.parametrize('surface', ['single', 'batch', 'watch'])
@pytest.mark.parametrize('invalid', [
    {'source': ['UNRATE']}, {'source_type': 17}, {'auto_watch': 'false'},
    {'admissible_for_backtests': 'false'}, {'reliability_rating': True}, {'dedupe': 'false'},
    {'metadata': {'entry_id': 'forged'}}, {'metadata': {'adapter_item': {'value': 9}}},
    {'metadata': {'source': 'OTHER'}}, {'metadata': {'adapter': 'OTHER'}},
    {'metadata': []}, {'request_id': ' '}, {'request_id': True},
])
def test_import_admission_rejects_coercion_before_fetch(desk, monkeypatch, surface, invalid):
    from tools import forecasting_tool as tool
    from tools.forecast_actions.evidence import import_source_evidence, import_source_evidence_batch
    from forecasting.sources import watched
    ledger, qid = desk
    calls = []
    def fetch(*args, **kwargs):
        calls.append(args)
        return []
    monkeypatch.setattr(tool, '_load_source_adapter_items', fetch)
    monkeypatch.setattr(watched, 'load_source_items', fetch)
    spec = {'source_type': 'fred', 'source': 'UNRATE', **invalid}
    if surface == 'single':
        with pytest.raises(ValueError, match='invalid source'):
            import_source_evidence({'question_id': qid, **spec}, ledger)
    elif surface == 'batch':
        result = json.loads(import_source_evidence_batch({'question_id': qid, 'sources': [spec]}, ledger))
        assert result['results'][0]['success'] is False
        assert 'invalid source' in result['results'][0]['error']
    else:
        identity = {key: spec[key] for key in ('source_type', 'source')}
        result = watched.fetch_watched_source_payloads([{**identity, 'args': spec}])[0]
        assert result['success'] is False
        assert 'invalid source' in result['error']
    assert calls == []
    assert ledger.list_evidence(qid) == []


@pytest.mark.parametrize('concurrency', [0, 9, True, '4', None])
def test_batch_concurrency_is_explicit_and_strict(desk, monkeypatch, concurrency):
    from tools import forecasting_tool as tool
    ledger, qid = desk
    def forbidden(*args):
        raise AssertionError('must validate before fetch')
    monkeypatch.setattr(tool, '_load_source_adapter_items', forbidden)
    with pytest.raises(ValueError, match='concurrency'):
        tool._import_source_evidence_batch_payload(ledger, {
            'question_id': qid, 'concurrency': concurrency,
            'sources': [{'source_type': 'fred', 'source': 'UNRATE'}],
        })


def test_batch_honors_source_dedupe_override(desk, monkeypatch):
    from tools import forecasting_tool as tool
    ledger, qid = desk
    monkeypatch.setattr(tool, '_load_source_adapter_items', lambda *args: [
        {'entry_id': 'same', 'title': 'Observation', 'source_url': 'https://example.test/series'}
    ])
    result = json.loads(tool._import_source_evidence_batch_payload(ledger, {
        'question_id': qid, 'dedupe': True, 'sources': [
            {'source_type': 'fred', 'source': 'UNRATE'},
            {'source_type': 'fred', 'source': 'UNRATE', 'dedupe': False},
            {'source_type': 'fred', 'source': 'UNRATE'},
        ],
    }))
    assert [item['imported_count'] for item in result['results']] == [1, 1, 0]
    assert result['skipped_duplicates'] == 1
    assert len(ledger.list_evidence(qid)) == 2


@pytest.mark.parametrize('changed', [
    {'source': 'OTHER'},
    {'adapter_item': {'entry_id': 'observation', 'value': 2, 'unit': 'percent'}},
    {'adapter_item': {'entry_id': 'observation', 'value': 1, 'unit': 'dollars'}},
])
def test_changed_observation_is_not_silently_classified_as_duplicate(desk, changed):
    from forecasting.application.source_batches import SourceRevisionConflict
    ledger, qid = desk
    metadata = {'entry_id': 'observation', 'source': 'SERIES', 'adapter': 'fred',
                'adapter_item': {'entry_id': 'observation', 'value': 1, 'unit': 'percent'}}
    original = payload('observation', metadata=metadata)
    persisted = commit_source_payloads(ledger, qid, [original]).imported[0].evidence
    with pytest.raises(SourceRevisionConflict) as error:
        commit_source_payloads(ledger, qid, [payload('new'), {**original, 'metadata': {**metadata, **changed}}])
    assert error.value.reason_code == 'source_revision_conflict'
    assert error.value.index == 1
    assert [item.id for item in ledger.list_evidence(qid)] == [persisted.id]
    assert commit_source_payloads(ledger, qid, [original]).duplicate_indices == (0,)


def test_conflicting_same_batch_entries_roll_back_and_explicit_revision_preserves_history(desk):
    from forecasting.application.source_batches import SourceRevisionConflict
    ledger, qid = desk
    first = payload('revision', metadata={'entry_id': 'revision', 'adapter_item': {'value': 1}})
    revised = payload('revision', metadata={'entry_id': 'revision', 'adapter_item': {'value': 2}})
    with pytest.raises(SourceRevisionConflict):
        commit_source_payloads(ledger, qid, [first, revised])
    assert ledger.list_evidence(qid) == []
    commit_source_payloads(ledger, qid, [first])
    commit_source_payloads(ledger, qid, [revised], dedupe=False)
    assert len(ledger.list_evidence(qid)) == 2
    # Legacy/imported divergent identities cannot be resolved by last-row-wins.
    with pytest.raises(SourceRevisionConflict):
        commit_source_payloads(ledger, qid, [first])
    assert len(ledger.list_evidence(qid)) == 2


def test_duplicate_comparison_normalizes_published_time_and_inferred_url(desk):
    ledger, qid = desk
    original = payload('published', source_or_note='https://example.test/observation',
                       published_at='2026-01-01T00:00:00Z')
    commit_source_payloads(ledger, qid, [original])
    assert commit_source_payloads(ledger, qid, [
        {**original, 'published_at': '2026-01-01T01:00:00+01:00', 'reliability_rating': 0.9}
    ]).duplicate_indices == (0,)


@pytest.mark.parametrize('action', ['single', 'batch'])
def test_tool_consumers_surface_revision_conflicts_without_partial_writes(desk, monkeypatch, action):
    from forecasting.application.source_batches import SourceRevisionConflict
    from tools import forecasting_tool as tool
    from tools.forecast_actions.evidence import import_source_evidence
    ledger, qid = desk
    items = [{'entry_id': 'one', 'value': 1, 'series_id': 'UNRATE', 'observation_date': '2026-01-01'}]
    monkeypatch.setattr(tool, '_load_source_adapter_items', lambda *args: items)
    request = {'question_id': qid, 'source_type': 'fred', 'source': 'UNRATE'}
    import_source_evidence(request, ledger)
    items[0] = {**items[0], 'value': 2}
    if action == 'single':
        with pytest.raises(SourceRevisionConflict):
            import_source_evidence(request, ledger)
    else:
        result = json.loads(tool._import_source_evidence_batch_payload(ledger, {
            'question_id': qid, 'sources': [request],
        }))
        assert not result['results'][0]['success']
        assert result['results'][0]['imported_count'] == 0
        assert 'source_revision_conflict' in result['results'][0]['error']
    assert len(ledger.list_evidence(qid)) == 1
    assert ledger.list_evidence(qid)[0].metadata['adapter_item']['value'] == 1
