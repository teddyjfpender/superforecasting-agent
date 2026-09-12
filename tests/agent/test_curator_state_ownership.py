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
