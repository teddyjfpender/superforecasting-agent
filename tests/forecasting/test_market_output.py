"""Market artifact handoff retains only the latest result for its worker."""
from concurrent.futures import ThreadPoolExecutor
import threading

from forecasting.application.market_output import record_emitted, reset_emitted, take_emitted


def test_latest_emission_is_consumed_once_and_isolated_across_threads():
    barrier = threading.Barrier(2)
    def run(title):
        reset_emitted()
        try:
            record_emitted({'title': 'draft'}, {})
            record_emitted({'title': title}, {'recipe': title})
            barrier.wait(timeout=3)
            assert take_emitted() == {'presentation': {'title': title}, 'spec': {'recipe': title}}
            assert take_emitted() is None
        finally:
            reset_emitted()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, ['first', 'second']))
