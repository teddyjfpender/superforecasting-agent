"""Legacy workers are lazy and cannot be replaced until ownership is released."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting.legacy_commands import invalidate_worker, use_worker


def test_failed_invalidation_retains_handle_and_retries_before_replacement():
    old = SimpleNamespace(
        close=Mock(side_effect=[OSError("still owned"), OSError("still owned"), None])
    )
    session = {"slash_worker": old}
    with pytest.raises(OSError):
        invalidate_worker(session)
    assert session["slash_worker"] is old
    replacement = SimpleNamespace(close=Mock())
    factory = Mock(return_value=replacement)
    with pytest.raises(OSError), use_worker(session, factory):
        pytest.fail("retiring worker was reused")
    factory.assert_not_called()
    with use_worker(session, factory) as worker:
        assert worker is replacement
    assert old.close.call_count == 3
    factory.assert_called_once()
    invalidate_worker(session)
    replacement.close.assert_called_once()


def test_failed_command_and_cleanup_keep_resource_for_later_retry():
    worker = SimpleNamespace(close=Mock(side_effect=[OSError("close failed"), None]))
    session = {"slash_worker": worker}
    with pytest.raises(RuntimeError, match="command failed.*cleanup pending"):
        with use_worker(session, Mock()) as owned:
            assert owned is worker
            raise ValueError("command failed")
    assert session["slash_worker"] is worker
    invalidate_worker(session)
    assert session["slash_worker"] is None


def test_keyboard_interrupt_is_preserved_when_cleanup_fails():
    session = {
        "slash_worker": SimpleNamespace(close=Mock(side_effect=OSError("close failed")))
    }
    with pytest.raises(KeyboardInterrupt) as caught:
        with use_worker(session, Mock()):
            raise KeyboardInterrupt()
    assert "cleanup pending" in caught.value.__notes__[0]
    assert session["_slash_worker_retiring"]


def test_invalidation_waits_until_command_releases_worker():
    worker = SimpleNamespace(close=Mock())
    session = {"slash_worker": worker}
    entered, release, invalidating = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    def command():
        with use_worker(session, Mock()) as owned:
            assert owned is worker
            entered.set()
            assert release.wait(3)

    def invalidate():
        invalidating.set()
        invalidate_worker(session)

    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(command)
        try:
            assert entered.wait(2)
            retiring = pool.submit(invalidate)
            assert invalidating.wait(2)
            worker.close.assert_not_called()
        finally:
            release.set()
        active.result(timeout=3)
        retiring.result(timeout=3)
    worker.close.assert_called_once()


def test_session_creation_and_invalidation_do_not_construct_classic_cli(monkeypatch):
    from tui_gateway import server
    from superforecasting_agent.hosting.runtime import RuntimeHost

    monkeypatch.setattr(server, "_host", RuntimeHost())
    factory = Mock(side_effect=AssertionError("classic CLI must stay lazy"))
    monkeypatch.setattr(server, "_SlashWorker", factory)
    monkeypatch.setattr(server, "_load_show_reasoning", lambda: False)
    monkeypatch.setattr(server, "_load_tool_progress_mode", lambda: "all")
    monkeypatch.setattr(
        server, "_start_notification_poller", lambda *args: threading.Event()
    )
    monkeypatch.setattr(server, "_wire_callbacks", lambda *args: None)
    monkeypatch.setattr(server, "_notify_session_boundary", lambda *args: None)
    server._init_session("runtime", "durable", SimpleNamespace(model="fixture"), [])
    session = server._host.sessions["runtime"]
    assert session["slash_worker"] is None
    server._restart_slash_worker(session)
    factory.assert_not_called()
    assert server.shutdown_runtime(2)
