"""A curator running in the background must not capture foreground streams."""

import sys
import threading

from agent import curator, runtime
from superforecasting_agent.runtime import config, runtime_provider


def test_background_curator_preserves_foreground_streams(monkeypatch, capsys):
    entered = threading.Event()
    release = threading.Event()
    closed = []
    monkeypatch.setattr(config, 'load_config', lambda: {'model': {'default': 'fake', 'provider': 'custom'}})
    monkeypatch.setattr(runtime_provider, 'resolve_runtime_provider', lambda **kwargs: {'provider': 'custom'})

    class Review:
        def __init__(self, **kwargs):
            assert kwargs['quiet_mode'] is True
        def run_conversation(self, **kwargs):
            entered.set()
            assert release.wait(5)
            return {'final_response': 'done'}
        def close(self):
            closed.append(True)

    monkeypatch.setattr(runtime, 'AIAgent', Review)
    original_stdout, original_stderr = sys.stdout, sys.stderr
    results = []
    worker = threading.Thread(target=lambda: results.append(curator._run_llm_review('review')))
    worker.start()
    try:
        assert entered.wait(5)
        assert sys.stdout is original_stdout
        assert sys.stderr is original_stderr
        print('foreground output')
        print('foreground diagnostic', file=sys.stderr)
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert results[0]['error'] is None
    assert closed == [True]
    captured = capsys.readouterr()
    assert 'foreground output' in captured.out
    assert 'foreground diagnostic' in captured.err
