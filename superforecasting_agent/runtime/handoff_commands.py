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

    # Storage is borrowed from the host; a command must not open an implicit owner.
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
            self._session_db.create_session(self.session_id, source="cli")
            self._session_db.set_session_title(self.session_id, f"handoff-{self.session_id[:8]}")
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

    from superforecasting_agent.application.handoff import wait_for_handoff

    try:
        result = wait_for_handoff(self._session_db, self.session_id, attempt_id)
    except Exception as exc:
        _cprint(f"  Could not verify handoff state: {exc}. Check the gateway before retrying.")
        return True
    if result.state == "completed":
        _cprint(f"  Handoff complete. The session is now active on {platform_name}.")
        _cprint(f"  Resume it later with: /resume {session_title}")
        self._should_exit = True
        return False
    if result.state == "running":
        _cprint("  Gateway transfer is still running. The handoff remains owned by the gateway; do not retry yet.")
    elif result.state == "failed":
        if result.wait_ended and result.error == "timed out waiting for gateway":
            _cprint("  Timed out before gateway pickup; the pending handoff was cancelled.")
        else:
            _cprint(f"  Handoff failed: {result.error or 'unknown error'}")
    else:
        _cprint(f"  {result.error or 'Handoff state is unavailable'}. Check the gateway before retrying.")
    return True
