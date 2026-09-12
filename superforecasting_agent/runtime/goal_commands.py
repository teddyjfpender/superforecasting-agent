"""Interactive goal commands and cross-turn continuation coordination."""

import logging

from .commands import _looks_like_slash_command
from .console_output import _cprint, _DIM, _RST

def _get_goal_manager(self):
    """Return the GoalManager bound to the current session_id.

        Cached on ``self._goal_manager`` and rebound lazily when
        ``session_id`` changes (e.g. after /new or a compression-driven
        session split).
        """
    try:
        from superforecasting_agent.runtime.goals import GoalManager
        from superforecasting_agent.runtime.config import load_config
    except Exception as exc:
        logging.debug("goal manager unavailable: %s", exc)
        return None

    sid = getattr(self, "session_id", None) or ""
    if not sid:
        return None

    database = getattr(self, "_session_db", None)
    if database is None:
        return None
    existing = getattr(self, "_goal_manager", None)
    if (existing is not None and getattr(existing, "session_id", None) == sid
            and getattr(existing, "_database", None) is database
            and not getattr(existing, "_closed", False)):
        return existing

    try:
        cfg = load_config() or {}
        goals_cfg = cfg.get("goals") or {}
        max_turns = int(goals_cfg.get("max_turns", 20) or 20)
    except Exception:
        max_turns = 20

    mgr = GoalManager(session_id=sid, default_max_turns=max_turns,
                      database_provider=lambda: database)
    if existing is not None:
        existing.close()
    self._goal_manager = mgr
    return mgr


def _handle_goal_command(self, cmd: str) -> None:
    """Dispatch /goal subcommands: set / status / pause / resume / clear."""
    parts = (cmd or "").strip().split(None, 1)
    arg = parts[1].strip() if len(parts) > 1 else ""

    mgr = self._get_goal_manager()
    if mgr is None:
        _cprint(f"  {_DIM}Goals unavailable (no active forecast session).{_RST}")
        return

    lower = arg.lower()

    # Bare /goal or /goal status → show current state
    if not arg or lower == "status":
        _cprint(f"  {mgr.status_line()}")
        return

    if lower == "pause":
        state = mgr.pause(reason="user-paused")
        if state is None:
            _cprint(f"  {_DIM}No goal set.{_RST}")
        else:
            _cprint(f"  ⏸ Goal paused: {state.goal}")
        return

    if lower == "resume":
        state = mgr.resume()
        if state is None:
            _cprint(f"  {_DIM}No goal to resume.{_RST}")
        else:
            _cprint(f"  ▶ Goal resumed: {state.goal}")
            _cprint(
                f"  {_DIM}Send any message (or press Enter on an empty prompt "
                f"is a no-op; type 'continue' to kick it off).{_RST}"
            )
        return

    if lower in {"clear", "stop", "done"}:
        had = mgr.has_goal()
        mgr.clear()
        if had:
            _cprint("  ✓ Goal cleared.")
        else:
            _cprint(f"  {_DIM}No active goal.{_RST}")
        return

    # Otherwise treat the arg as the goal text.
    try:
        state = mgr.set(arg)
    except ValueError as exc:
        _cprint(f"  Invalid goal: {exc}")
        return

    _cprint(f"  ⊙ Goal set ({state.max_turns}-turn budget): {state.goal}")
    _cprint(
        f"  {_DIM}After each turn, a judge model will check if the goal is done. "
        f"Superforecasting Agent keeps working until it is, you pause/clear it, or the budget is "
        f"exhausted. Use /goal status, /goal pause, /goal resume, /goal clear.{_RST}"
    )
    # Kick the loop off immediately so the user doesn't have to send a
    # separate message after setting the goal.
    try:
        self._pending_input.put(state.goal)
    except Exception:
        pass


def _handle_subgoal_command(self, cmd: str) -> None:
    """Dispatch /subgoal subcommands.

        Forms:
          /subgoal                              show current subgoals
          /subgoal <text>                       append a criterion
          /subgoal remove <n>                   drop subgoal n (1-based)
          /subgoal clear                        wipe all subgoals

        Subgoals are extra criteria the user adds mid-loop. They get
        appended to both the judge prompt (verdict must consider them)
        and the continuation prompt (agent sees them) on the next turn
        boundary. No special kick — the running turn finishes, the next
        judge call includes them.
        """
    parts = (cmd or "").strip().split(None, 1)
    arg = parts[1].strip() if len(parts) > 1 else ""

    mgr = self._get_goal_manager()
    if mgr is None:
        _cprint(f"  {_DIM}Goals unavailable (no active forecast session).{_RST}")
        return

    from superforecasting_agent.runtime.subgoal_commands import execute_subgoal

    for line in execute_subgoal(mgr, arg).splitlines():
        _cprint(f"  {line}")


def _maybe_continue_goal_after_turn(self) -> None:
    """Hook run after every CLI turn. Judges + maybe re-queues.

        Safe to call when no goal is set — returns quickly.

        Preemption is automatic: if a real user message is already in
        ``_pending_input`` we skip judging (the user's new input takes
        priority and we'll re-judge after that turn). If judge says done,
        mark it done and tell the user. If judge says continue and we're
        under budget, push the continuation prompt onto the queue.

        Interrupt handling: if the turn was user-cancelled (Ctrl+C), we
        AUTO-PAUSE the goal instead of judging + re-queuing. Otherwise
        Ctrl+C feels like it did nothing — the judge runs on whatever
        partial output landed, almost always says "continue", and the
        loop keeps going. Auto-pause keeps the goal recoverable via
        ``/goal resume`` once the user has sorted out what they want.
        The empty-response skip mirrors the gateway guard at
        ``_handle_message`` in ``gateway/run.py``.
        """
    mgr = self._get_goal_manager()
    if mgr is None or not mgr.is_active():
        return

    # If a real user message is already queued, don't inject a
    # continuation prompt on top — let the user's turn go first.
    # Slash commands don't count as "real user messages" for this
    # check: they're inspection/mutation (e.g. /subgoal added mid-
    # run) and the process_loop dispatches them via process_command,
    # not via chat(). If we treat a queued /subgoal as preempting,
    # the goal loop silently stalls — we'd return here, then the
    # slash command consumes its queue slot via process_command()
    # which never re-fires the goal hook. Peek at all queued entries
    # and only defer when there's a non-slash payload.
    try:
        pending = getattr(self, "_pending_input", None)
        if pending is not None and not pending.empty():
            has_real_message = False
            try:
                # Queue.queue is the underlying deque — direct peek
                # without disturbing FIFO order.
                for entry in list(pending.queue):
                    # Bundled payloads are (text, images) tuples;
                    # unpack for inspection.
                    if isinstance(entry, tuple) and entry:
                        entry = entry[0]
                    if isinstance(entry, str) and _looks_like_slash_command(entry):
                        continue
                    has_real_message = True
                    break
            except Exception:
                # Fallback: if we can't introspect the queue, behave
                # like the old check and defer to be safe.
                has_real_message = True
            if has_real_message:
                return
    except Exception:
        pass

    # If the turn was user-interrupted (Ctrl+C), auto-pause the goal
    # and bail. The judge call would almost always return "continue"
    # on the partial output and immediately re-queue another turn,
    # which is exactly what the user cancelled. Pausing (rather than
    # silently skipping) is the observable, recoverable behavior.
    if getattr(self, "_last_turn_interrupted", False):
        try:
            mgr.pause(reason="user-interrupted (Ctrl+C)")
        except Exception as exc:
            logging.debug("goal pause-on-interrupt failed: %s", exc)
        _cprint(
            f"  {_DIM}⏸ Goal paused — turn was interrupted. "
            f"Use /goal resume to continue, or /goal clear to stop.{_RST}"
        )
        return

    # Extract the agent's final response for this turn.
    last_response = ""
    try:
        hist = self.conversation_history or []
        for msg in reversed(hist):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Multimodal content — flatten text parts.
                    parts = [
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") in {"text", "output_text"}
                    ]
                    last_response = "\n".join(t for t in parts if t)
                else:
                    last_response = str(content or "")
                break
    except Exception:
        last_response = ""

    # Skip judging on empty/whitespace-only responses. These are almost
    # always transient failures (API error, empty stream) where the
    # judge would say "continue" and trip the consecutive-parse-failures
    # backstop unnecessarily. Mirrors the gateway guard.
    if not last_response.strip():
        return

    decision = mgr.evaluate_after_turn(last_response, user_initiated=True)
    msg = decision.get("message") or ""
    if msg:
        _cprint(f"  {msg}")

    if decision.get("should_continue"):
        prompt = decision.get("continuation_prompt")
        if prompt:
            try:
                self._pending_input.put(prompt)
            except Exception as exc:
                logging.debug("goal continuation enqueue failed: %s", exc)
