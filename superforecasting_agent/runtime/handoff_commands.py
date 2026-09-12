"""Classic CLI session handoff to a configured gateway platform."""

from .console_output import _cprint

def _handle_handoff_command(self, cmd_original: str) -> bool:
    """Handle ``/handoff <platform>`` — transfer this CLI session to a gateway platform.

        Flow:
          1. Validate platform name + the gateway has a home channel for it.
          2. Reject if the agent is currently running (the in-flight turn
             would race with the gateway's switch_session).
          3. Write ``handoff_state='pending'`` on this session row.
          4. Block-poll ``state.db`` for terminal state (timeout 60s).
          5. On ``completed`` → print resume hint and signal CLI exit by
             returning False (the caller honors that like ``/quit``).
          6. On ``failed`` / timeout → print error and return True so the
             user keeps their CLI session.

        Returns:
            False to signal CLI exit, True to keep going.
        """
    from superforecasting_agent.storage.session import format_session_db_unavailable

    parts = cmd_original.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        _cprint("  Usage: /handoff <platform>")
        _cprint("  Hands the current forecast session off to that platform's home channel.")
        _cprint("  The CLI forecast session ends here; resume it later with /resume.")
        return True

    platform_name = parts[1].strip().lower()

    # Validate platform name + home channel via the live gateway config.
    try:
        from gateway.config import load_gateway_config, Platform
    except Exception as exc:  # pragma: no cover — gateway pkg always shipped
        _cprint(f"  Could not load gateway config: {exc}")
        return True

    try:
        platform = Platform(platform_name)
    except (ValueError, KeyError):
        _cprint(f"  Unknown platform '{platform_name}'.")
        return True

    try:
        gw_config = load_gateway_config()
    except Exception as exc:
        _cprint(f"  Could not load gateway config: {exc}")
        return True

    pcfg = gw_config.platforms.get(platform)
    if not pcfg or not pcfg.enabled:
        _cprint(f"  Platform '{platform_name}' is not configured/enabled in the gateway.")
        return True

    home = gw_config.get_home_channel(platform)
    if not home or not home.chat_id:
        _cprint(f"  No home channel configured for {platform_name}.")
        _cprint(f"  Set one with /sethome on the destination forecast conversation first.")
        return True

    # Refuse mid-turn: an in-flight agent run would race with the
    # gateway's switch_session and the synthetic turn dispatch.
    if getattr(self, "_agent_running", False):
        _cprint("  Forecast agent is busy. Wait for the current turn to finish, then retry /handoff.")
        return True

    # Make sure we have a SessionDB handle.
    if not self._session_db:
        try:
            from superforecasting_agent.storage.session import SessionDB
            self._session_db = SessionDB()
        except Exception:
            pass
    if not self._session_db:
        _cprint(f"  {format_session_db_unavailable()}")
        return True

    # Make sure the session row exists in state.db. Most CLI sessions
    # are written via _flush_messages_to_session_db on the first turn
    # already, but if the user tries to hand off an empty session we
    # still want a row to mark.
    try:
        row = self._session_db.get_session(self.session_id)
        if not row:
            # Nothing has flushed yet. Create a stub so the gateway has
            # something to switch_session onto. Inserting via title-set
            # is the simplest path because set_session_title's INSERT OR
            # IGNORE creates the row.
            placeholder_title = f"handoff-{self.session_id[:8]}"
            self._session_db.set_session_title(self.session_id, placeholder_title)
    except Exception as exc:
        _cprint(f"  Could not ensure session row in state.db: {exc}")
        return True

    # Display title for messaging.
    session_title = ""
    try:
        row = self._session_db.get_session(self.session_id)
        if row:
            session_title = row.get("title") or ""
    except Exception:
        pass
    if not session_title:
        session_title = self.session_id[:8]

    # Mark pending — gateway watcher will pick this up.
    from uuid import uuid4
    attempt_id = uuid4().hex
    ok = self._session_db.request_handoff(self.session_id, platform_name, attempt_id=attempt_id)
    if not ok:
        _cprint("  Session is already in flight for handoff. Wait for it to settle, then retry.")
        return True

    _cprint(f"  Queued handoff of '{session_title}' → {platform_name} (home: {home.name}).")
    _cprint(f"  Waiting for the gateway to pick it up...")

    # Poll-block on terminal state. Tick every 0.5s; bail at ~60s.
    import time as _time
    deadline = _time.monotonic() + 60.0
    last_state = "pending"
    while _time.monotonic() < deadline:
        try:
            state_row = self._session_db.get_handoff_state(self.session_id)
        except Exception:
            state_row = None
        if state_row and state_row.get("attempt_id") != attempt_id:
            _cprint("  Handoff attempt changed. This wait no longer owns the current transfer.")
            return True
        current = (state_row or {}).get("state") or "pending"
        if current != last_state:
            if current == "running":
                _cprint("  Gateway picked it up; transferring...")
            last_state = current
        if current == "completed":
            _cprint("")
            _cprint(f"  ↻ Handoff complete. The session is now active on {platform_name}.")
            _cprint(f"  Resume it on this CLI later with: /resume {session_title}")
            _cprint("")
            # End the CLI cleanly — same exit semantics as /quit.
            self._should_exit = True
            return False
        if current == "failed":
            err = (state_row or {}).get("error") or "unknown error"
            _cprint(f"  Handoff failed: {err}")
            _cprint("  Your CLI session is intact. Try /handoff again, or /resume on the platform manually.")
            return True
        _time.sleep(0.5)

    # A local waiting deadline cannot revoke a transfer already owned by the gateway.
    try:
        cancelled = self._session_db.cancel_pending_handoff(
            self.session_id, "timed out waiting for gateway", attempt_id=attempt_id
        )
        state_row = self._session_db.get_handoff_state(self.session_id)
    except Exception as exc:
        _cprint(f"  Could not verify handoff state: {exc}. Check the gateway before retrying.")
        return True
    if state_row and state_row.get("attempt_id") != attempt_id:
        _cprint("  Handoff attempt changed. Check the current transfer before retrying.")
        return True
    current = (state_row or {}).get("state")
    if current == "completed":
        _cprint(f"  Handoff complete. The session is now active on {platform_name}.")
        self._should_exit = True
        return False
    if cancelled:
        _cprint("  Timed out before gateway pickup; the pending handoff was cancelled.")
    elif current == "running":
        _cprint("  Gateway transfer is still running. The handoff remains owned by the gateway; do not retry yet.")
    elif current == "failed":
        _cprint(f"  Handoff failed: {(state_row or {}).get('error') or 'unknown error'}")
    else:
        _cprint("  Handoff state is unavailable. Check the gateway before retrying.")
    return True
