"""Review completion must not undo operator changes made during reporting."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from superforecasting_agent.storage import curator_state, files


def test_report_completion_preserves_concurrent_pause(tmp_path):
    path = tmp_path / '.curator_state'
    curator_state.save_state(path, {'paused': False, 'run_count': 1})
    reporting = threading.Event()
    finish_report = threading.Event()
    def complete_review():
        reporting.set()
        assert finish_report.wait(5)
        curator_state.mutate_state(path, lambda state: state.update(last_run_summary='finished'))
    with ThreadPoolExecutor(max_workers=1) as pool:
        review = pool.submit(complete_review)
        try:
            assert reporting.wait(5)
            curator_state.mutate_state(path, lambda state: state.update(paused=True))
        finally:
            finish_report.set()
        review.result(timeout=5)
    state = curator_state.load_state(path)
    assert state['paused'] is True
    assert state['last_run_summary'] == 'finished'
    assert state['run_count'] == 1


def test_parallel_run_counts_are_not_lost(tmp_path):
    path = tmp_path / '.curator_state'
    def increment(_):
        curator_state.mutate_state(path, lambda state: state.update(run_count=state['run_count'] + 1))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(increment, range(20)))
    assert curator_state.load_state(path)['run_count'] == 20


def test_failed_publication_propagates_and_preserves_previous_state(tmp_path, monkeypatch):
    path = tmp_path / '.curator_state'
    curator_state.save_state(path, {'paused': False})
    original = path.read_bytes()
    def fail(*args):
        raise OSError('publication unavailable')
    monkeypatch.setattr(files, 'atomic_replace', fail)
    with pytest.raises(OSError, match='publication unavailable'):
        curator_state.mutate_state(path, lambda state: state.update(paused=True))
    assert path.read_bytes() == original


def test_actual_review_does_not_overwrite_pause_during_report(tmp_path, monkeypatch):
    from agent import curator
    path = tmp_path / '.curator_state'
    monkeypatch.setattr(curator, '_state_file', lambda: path)
    monkeypatch.setattr(curator.skill_usage, 'agent_created_report', lambda: [])
    monkeypatch.setattr(curator, '_render_candidate_list', lambda: 'No agent-created skills')
    def report(**kwargs):
        curator.set_paused(True)
        return None
    monkeypatch.setattr(curator, '_write_run_report', report)
    curator.save_state({'paused': False, 'run_count': 1})
    curator.run_curator_review(synchronous=True, dry_run=True)
    assert curator.is_paused()
    assert 'skipped' in curator.load_state()['last_run_summary']


def test_notice_acknowledgement_preserves_newer_review_and_pause(tmp_path, monkeypatch):
    from agent import curator
    monkeypatch.setattr(curator, '_state_file', lambda: tmp_path / '.curator_state')
    curator.save_state({'paused': True, 'last_run_at': 'new-run', 'last_run_summary': 'new-summary'})
    curator.mark_summary_shown('old-run', 'old-summary')
    assert curator.load_state()['last_run_summary_shown_at'] is None
    curator.mark_summary_shown('new-run', 'old-summary')
    assert curator.load_state()['last_run_summary_shown_at'] is None
    curator.mark_summary_shown('new-run', 'new-summary')
    state = curator.load_state()
    assert state['last_run_summary_shown_at'] == 'new-run'
    assert state['paused'] is True


@pytest.mark.parametrize('contents', [b'{broken', b'[]', b'{"paused": "false"}', b'{"run_count": true}', b'{"run_count": -1}', b'\xff'])
def test_invalid_existing_state_is_not_overwritten(tmp_path, contents):
    path = tmp_path / '.curator_state'
    path.write_bytes(contents)
    with pytest.raises(ValueError):
        curator_state.mutate_state(path, lambda state: state.update(paused=True))
    assert path.read_bytes() == contents


def test_review_rejects_corrupt_state_before_skill_mutations(tmp_path, monkeypatch):
    from agent import curator
    path = tmp_path / '.curator_state'
    path.write_text('{broken', encoding='utf-8')
    monkeypatch.setattr(curator, '_state_file', lambda: path)
    def forbidden(**kwargs):
        pytest.fail('automatic skill mutation ran before state admission')
    monkeypatch.setattr(curator, 'apply_automatic_transitions', forbidden)
    with pytest.raises(ValueError):
        curator.run_curator_review(synchronous=True)
    assert path.read_text(encoding='utf-8') == '{broken'


def test_invalid_mutation_cannot_publish(tmp_path):
    path = tmp_path / '.curator_state'
    curator_state.save_state(path, {'paused': False})
    before = path.read_bytes()
    with pytest.raises(ValueError, match='boolean'):
        curator_state.mutate_state(path, lambda state: state.update(paused='false'))
    with pytest.raises(ValueError, match='integer'):
        curator_state.save_state(path, {'run_count': True})
    assert path.read_bytes() == before
