"""Tests for session handoff (CLI to gateway platform).

The handoff state machine lives on the ``sessions`` table:

    None  → "pending" → "running" → ("completed" | "failed")

CLI side calls ``request_handoff`` and poll-waits on ``get_handoff_state``.
Gateway side iterates ``list_pending_handoffs``, calls ``claim_handoff`` to
flip pending → running, and finishes with ``complete_handoff`` or
``fail_handoff``.
"""

from __future__ import annotations

import time
from contextlib import closing

import pytest

from superforecasting_agent.storage.session import SessionDB


class TestHandoffStateDB:
    """Test the handoff schema + helper methods on SessionDB."""

    @pytest.fixture
    def db(self, tmp_path, monkeypatch):
        home = tmp_path / ".hermes"
        home.mkdir()
        monkeypatch.setenv("HERMES_HOME", str(home))
        db = SessionDB(db_path=home / "state.db")
        try:
            yield db
        finally:
            db.close()

    def _make_session(self, db, session_id, source="cli", title=None):
        """Insert a session row directly for testing."""
        def _do(conn):
            conn.execute(
                "INSERT OR IGNORE INTO sessions (id, source, title, started_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, source, title, time.time()),
            )
        db._execute_write(_do)

    def test_columns_exist(self, db):
        db._conn.execute(
            "SELECT handoff_state, handoff_platform, handoff_error "
            "FROM sessions LIMIT 0"
        )

    def test_request_handoff_marks_pending(self, db):
        sid = "sess-1"
        self._make_session(db, sid)

        assert db.request_handoff(sid, "telegram") is True

        state = db.get_handoff_state(sid)
        assert state == {
            "state": "pending",
            "platform": "telegram",
            "error": None,
            "attempt_id": state["attempt_id"],
        }

    def test_request_handoff_rejects_in_flight(self, db):
        sid = "sess-2"
        self._make_session(db, sid)

        assert db.request_handoff(sid, "telegram") is True
        # Still pending → reject re-request
        assert db.request_handoff(sid, "discord") is False

        # And after gateway claims it (running) → still rejected
        assert db.claim_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"]) is True
        assert db.request_handoff(sid, "discord") is False

    def test_request_handoff_after_terminal_state_resets_error(self, db):
        sid = "sess-3"
        self._make_session(db, sid)
        db.request_handoff(sid, "telegram")
        db.claim_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"])
        db.fail_handoff(sid, "earlier failure", attempt_id=db.get_handoff_state(sid)["attempt_id"])

        # User retries — should be allowed and clear the prior error.
        assert db.request_handoff(sid, "discord") is True
        state = db.get_handoff_state(sid)
        assert state["state"] == "pending"
        assert state["platform"] == "discord"
        assert state["error"] is None

    def test_list_pending_handoffs_excludes_running_and_terminal(self, db):
        a, b, c, d = "sess-a", "sess-b", "sess-c", "sess-d"
        for sid in (a, b, c, d):
            self._make_session(db, sid)

        db.request_handoff(a, "telegram")
        db.request_handoff(b, "discord")
        db.request_handoff(c, "telegram")
        db.claim_handoff(c, attempt_id=db.get_handoff_state(c)["attempt_id"])  # c is now running, not pending
        db.request_handoff(d, "slack")
        db.claim_handoff(d, attempt_id=db.get_handoff_state(d)["attempt_id"])
        db.complete_handoff(d, attempt_id=db.get_handoff_state(d)["attempt_id"])  # d is terminal

        pending = db.list_pending_handoffs()
        ids = [r["id"] for r in pending]
        assert set(ids) == {a, b}

    def test_claim_handoff_is_atomic(self, db):
        sid = "sess-claim"
        self._make_session(db, sid)
        db.request_handoff(sid, "telegram")

        # First claim wins
        assert db.claim_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"]) is True
        # Second claim is a no-op (state is now "running", not "pending")
        assert db.claim_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"]) is False
        assert db.get_handoff_state(sid)["state"] == "running"

    def test_complete_handoff_clears_error(self, db):
        sid = "sess-complete"
        self._make_session(db, sid)
        db.request_handoff(sid, "telegram")
        db.claim_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"])
        db.fail_handoff(sid, "transient", attempt_id=db.get_handoff_state(sid)["attempt_id"])
        # User retries; mock the watcher path
        db.request_handoff(sid, "telegram")
        db.claim_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"])
        db.complete_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"])

        state = db.get_handoff_state(sid)
        assert state["state"] == "completed"
        assert state["error"] is None

    def test_fail_handoff_records_reason(self, db):
        sid = "sess-fail"
        self._make_session(db, sid)
        db.request_handoff(sid, "telegram")
        db.claim_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"])
        db.fail_handoff(sid, "no home channel for telegram", attempt_id=db.get_handoff_state(sid)["attempt_id"])

        state = db.get_handoff_state(sid)
        assert state["state"] == "failed"
        assert state["error"] == "no home channel for telegram"

    def test_fail_handoff_truncates_long_reasons(self, db):
        sid = "sess-fail-long"
        self._make_session(db, sid)
        db.request_handoff(sid, "telegram")
        db.claim_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"])

        # 1000-character error string
        big_err = "x" * 1000
        db.fail_handoff(sid, big_err, attempt_id=db.get_handoff_state(sid)["attempt_id"])

        state = db.get_handoff_state(sid)
        assert len(state["error"]) <= 500

    def test_get_handoff_state_for_unknown_session(self, db):
        assert db.get_handoff_state("does-not-exist") is None

    def test_full_pending_to_completed_flow(self, db):
        """End-to-end sequence the CLI + gateway watcher follow."""
        sid = "sess-flow"
        self._make_session(db, sid, title="my session")
        db.append_message(sid, "user", "Hello")
        db.append_message(sid, "assistant", "Hi there!")

        # CLI: request handoff
        assert db.request_handoff(sid, "telegram") is True
        assert db.get_handoff_state(sid)["state"] == "pending"

        # Gateway watcher: discover + claim
        pending = db.list_pending_handoffs()
        assert len(pending) == 1
        assert pending[0]["id"] == sid
        assert db.claim_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"]) is True
        assert db.get_handoff_state(sid)["state"] == "running"

        # Gateway uses get_messages to load the transcript (real flow uses
        # session_store.switch_session which reads the same table).
        messages = db.get_messages(sid)
        assert [m["role"] for m in messages] == ["user", "assistant"]

        # Gateway: mark completed
        db.complete_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"])
        assert db.get_handoff_state(sid)["state"] == "completed"
        assert db.list_pending_handoffs() == []


    def test_timeout_cannot_cancel_claimed_or_completed_transfer(self, db):
        sid = 'timeout-race'
        self._make_session(db, sid)
        assert db.request_handoff(sid, 'telegram')
        assert db.claim_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"])
        assert not db.cancel_pending_handoff(sid, 'local deadline', attempt_id=db.get_handoff_state(sid)["attempt_id"])
        assert db.get_handoff_state(sid)['state'] == 'running'
        assert not db.request_handoff(sid, 'discord')
        assert db.complete_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"])
        assert not db.cancel_pending_handoff(sid, 'late deadline', attempt_id=db.get_handoff_state(sid)["attempt_id"])
        assert not db.fail_handoff(sid, 'late worker failure', attempt_id=db.get_handoff_state(sid)["attempt_id"])
        assert db.get_handoff_state(sid)['state'] == 'completed'

    def test_unclaimed_timeout_prevents_late_claim(self, db):
        sid = 'unclaimed-timeout'
        self._make_session(db, sid)
        assert db.request_handoff(sid, 'telegram')
        assert not db.complete_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"])
        assert not db.fail_handoff(sid, 'not owned by worker', attempt_id=db.get_handoff_state(sid)["attempt_id"])
        assert db.cancel_pending_handoff(sid, 'local deadline', attempt_id=db.get_handoff_state(sid)["attempt_id"])
        assert not db.claim_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"])
        assert db.get_handoff_state(sid)['error'] == 'local deadline'
        assert db.request_handoff(sid, 'discord')

    def test_claim_and_timeout_have_one_winner(self, db):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        sid = 'claim-timeout-race'
        self._make_session(db, sid)
        assert db.request_handoff(sid, 'telegram')
        barrier = Barrier(2)

        def claim():
            barrier.wait(timeout=5)
            return db.claim_handoff(sid, attempt_id=db.get_handoff_state(sid)["attempt_id"])

        def cancel():
            barrier.wait(timeout=5)
            return db.cancel_pending_handoff(sid, 'deadline', attempt_id=db.get_handoff_state(sid)["attempt_id"])

        with ThreadPoolExecutor(max_workers=2) as pool:
            claimed, cancelled = pool.submit(claim), pool.submit(cancel)
            assert claimed.result() != cancelled.result()
        assert db.get_handoff_state(sid)['state'] in {'running', 'failed'}


    def test_stale_attempt_cannot_mutate_retry(self, db):
        sid = 'attempt-retry'
        self._make_session(db, sid)
        assert db.request_handoff(sid, 'telegram')
        old = db.get_handoff_state(sid)['attempt_id']
        assert db.claim_handoff(sid, attempt_id=old)
        assert db.fail_handoff(sid, 'retry needed', attempt_id=old)
        assert db.request_handoff(sid, 'discord')
        new = db.get_handoff_state(sid)['attempt_id']
        assert new and new != old
        assert not db.claim_handoff(sid, attempt_id=old)
        assert not db.cancel_pending_handoff(sid, 'late timeout', attempt_id=old)
        assert db.claim_handoff(sid, attempt_id=new)
        assert not db.complete_handoff(sid, attempt_id=old)
        assert not db.fail_handoff(sid, 'late failure', attempt_id=old)
        assert db.get_handoff_state(sid)['state'] == 'running'
        assert db.complete_handoff(sid, attempt_id=new)

    def test_legacy_handoff_identity_migration_is_stable(self, db):
        sid = 'legacy-attempt'
        self._make_session(db, sid)
        def legacy(conn):
            conn.execute("UPDATE sessions SET handoff_state='pending', handoff_platform='telegram', handoff_attempt_id=NULL WHERE id=?", (sid,))
            conn.execute('UPDATE schema_version SET version=11')
        db._execute_write(legacy)
        with closing(SessionDB(db_path=db.db_path)) as migrated:
            attempt = migrated.get_handoff_state(sid)['attempt_id']
            assert isinstance(attempt, str) and len(attempt) == 32
        with closing(SessionDB(db_path=db.db_path)) as reopened:
            assert reopened.get_handoff_state(sid)['attempt_id'] == attempt
            assert reopened.claim_handoff(sid, attempt_id=attempt)


class TestHandoffCommandRegistration:
    """Slash-command surface checks."""

    def test_command_registered(self):
        from superforecasting_agent.runtime.commands import resolve_command
        cmd = resolve_command("handoff")
        assert cmd is not None
        assert cmd.name == "handoff"
        # Fork change (606488c89): handoff was re-categorized from "Session"
        # to "Compatibility" when the forecast-desk help took priority.
        assert cmd.category == "Compatibility"

    def test_command_is_cli_only(self):
        """`/handoff` is initiated from the CLI; gateway shouldn't expose it."""
        from superforecasting_agent.runtime.commands import resolve_command, GATEWAY_KNOWN_COMMANDS
        cmd = resolve_command("handoff")
        assert cmd is not None
        assert cmd.cli_only is True
        assert "handoff" not in GATEWAY_KNOWN_COMMANDS


@pytest.mark.parametrize('state,exit_expected,visible', [
    ('running', False, 'still running'),
    ('completed', True, 'Handoff complete'),
    ('failed', False, 'pending handoff was cancelled'),
])
def test_cli_timeout_reports_durable_state(monkeypatch, capsys, state, exit_expected, visible):
    import sys
    from types import SimpleNamespace
    from unittest.mock import Mock
    import gateway.config as gateway_config
    from superforecasting_agent.runtime import handoff_commands

    config = SimpleNamespace(
        platforms={gateway_config.Platform.TELEGRAM: SimpleNamespace(enabled=True)},
        get_home_channel=lambda platform: SimpleNamespace(chat_id='fixture', name='home'),
    )
    monkeypatch.setattr(gateway_config, 'load_gateway_config', lambda: config)
    monkeypatch.setattr(handoff_commands, '_cprint', print)
    db = Mock()
    db.get_session.return_value = {'title': 'fixture'}
    db.request_handoff.return_value = True
    db.cancel_pending_handoff.return_value = state == 'failed'
    db.get_handoff_state.side_effect = lambda sid: {'state': state, 'attempt_id': db.request_handoff.call_args.kwargs['attempt_id']}
    shell = SimpleNamespace(session_id='fixture-session', _session_db=db, _agent_running=False, _should_exit=False)
    ticks = iter([0.0, 61.0])
    with monkeypatch.context() as patch_time:
        patch_time.setitem(sys.modules, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))
        keep_running = handoff_commands._handle_handoff_command(shell, '/handoff telegram')
    assert keep_running is not exit_expected
    assert shell._should_exit is exit_expected
    assert visible in capsys.readouterr().out
    db.fail_handoff.assert_not_called()


@pytest.mark.asyncio
async def test_gateway_watcher_carries_claimed_attempt(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from gateway.run import GatewayRunner
    import gateway.run as gateway_runtime

    with closing(SessionDB(db_path=tmp_path / 'state.db')) as db:
        sid = db.create_session(session_id='gateway-attempt', source='cli')
        assert db.request_handoff(sid, 'telegram')
        attempt = db.get_handoff_state(sid)['attempt_id']
        runner = SimpleNamespace(_running=True, _session_db=db)

        async def process(row):
            assert row['handoff_attempt_id'] == attempt
            assert db.get_handoff_state(sid)['state'] == 'running'
            runner._running = False

        runner._process_handoff = process
        monkeypatch.setattr(gateway_runtime.asyncio, 'sleep', AsyncMock())
        await GatewayRunner._handoff_watcher(runner)
        assert db.get_handoff_state(sid)['state'] == 'completed'
