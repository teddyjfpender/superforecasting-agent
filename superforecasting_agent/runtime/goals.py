"""Persistent session goals for Superforecasting Agent.

A goal is a free-form user objective that stays active across turns. After
each turn completes, a small judge call asks an auxiliary model "is this
goal satisfied by the forecaster's last response?". If not, the runtime feeds
a continuation prompt back into the same session and keeps working until the
goal is done, turn budget is exhausted, the user pauses/clears it, or the user
sends a new message (which takes priority and pauses the goal loop).

State is persisted in SessionDB's ``state_meta`` table keyed by
``goal:<session_id>`` so ``/resume`` picks it up.

Design notes / invariants:

- The continuation prompt is just a normal user message appended to the
  session via ``run_conversation``. No system-prompt mutation, no toolset
  swap — prompt caching stays intact.
- Judge failures are fail-OPEN: ``continue``. A broken judge must not wedge
  progress; the turn budget is the backstop.
- When a real user message arrives mid-loop it preempts the continuation
  prompt and also pauses the goal loop for that turn (we still re-judge
  after, so if the user's message happens to complete the goal the judge
  will say ``done``).
- This module has zero hard dependency on the inherited ``cli.HermesCLI``
  implementation class or the gateway runner; both wire the same
  ``GoalManager`` in.

Nothing in this module touches the agent's system prompt or toolset.
"""

from __future__ import annotations

import json
import logging
import re
import time
import weakref
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Constants & defaults
# ──────────────────────────────────────────────────────────────────────

DEFAULT_MAX_TURNS = 20
DEFAULT_JUDGE_TIMEOUT = 30.0
# Judge output budget. The freeform judge returns a one-line JSON verdict, but
# reasoning models (deepseek-v4, qwq, etc.) burn tokens on hidden reasoning
# before emitting the visible JSON — and the first /goal turn's prompt is
# larger than later turns, which pushes total reply length past tight caps.
# 200 tokens (the original default) reliably truncated the JSON on reasoning
# models, leaving '{"done": true, "reason": "The agent successfully' and
# triggering the auto-pause. 4096 covers reasoning + verdict on every model
# we've live-tested; override via auxiliary.goal_judge.max_tokens for
# specifically constrained setups.
DEFAULT_JUDGE_MAX_TOKENS = 4096
# Cap how much of the last response + recent messages we send to the judge.
_JUDGE_RESPONSE_SNIPPET_CHARS = 4000
# After this many consecutive judge *parse* failures (empty output / non-JSON),
# the loop auto-pauses and points the user at the goal_judge config. API /
# transport errors do NOT count toward this — those are transient. This guards
# against small models (e.g. deepseek-v4-flash) that cannot follow the strict
# JSON reply contract; without it the loop runs until the turn budget is
# exhausted with every reply shaped like `judge returned empty response` or
# `judge reply was not JSON`.
DEFAULT_MAX_CONSECUTIVE_PARSE_FAILURES = 3


CONTINUATION_PROMPT_TEMPLATE = (
    "[Continuing toward your standing goal]\n"
    "Goal: {goal}\n\n"
    "Continue working toward this goal. Take the next concrete step. "
    "If you believe the goal is complete, state so explicitly and stop. "
    "If you are blocked and need input from the user, say so clearly and stop."
)

# Used when the user has added one or more /subgoal criteria. Surfaced
# to the agent verbatim so it sees what to target on the next turn,
# and surfaced to the judge so the verdict considers them too.
CONTINUATION_PROMPT_WITH_SUBGOALS_TEMPLATE = (
    "[Continuing toward your standing goal]\n"
    "Goal: {goal}\n\n"
    "Additional criteria the user added mid-loop:\n"
    "{subgoals_block}\n\n"
    "Continue working toward the goal AND all additional criteria. Take "
    "the next concrete step. If you believe the goal and every "
    "additional criterion are complete, state so explicitly and stop. "
    "If you are blocked and need input from the user, say so clearly "
    "and stop."
)


JUDGE_SYSTEM_PROMPT = (
    "You are a strict judge evaluating whether an autonomous agent has "
    "achieved a user's stated goal. You receive the goal text and the "
    "agent's most recent response. Your only job is to decide whether "
    "the goal is fully satisfied based on that response.\n\n"
    "A goal is DONE only when:\n"
    "- The response explicitly confirms the goal was completed, OR\n"
    "- The response clearly shows the final deliverable was produced, OR\n"
    "- The response explains the goal is unachievable / blocked / needs "
    "user input (treat this as DONE with reason describing the block).\n\n"
    "Otherwise the goal is NOT done — CONTINUE.\n\n"
    "Reply ONLY with a single JSON object on one line:\n"
    '{\"done\": <true|false>, \"reason\": \"<one-sentence rationale>\"}'
)


JUDGE_USER_PROMPT_TEMPLATE = (
    "Goal:\n{goal}\n\n"
    "Agent's most recent response:\n{response}\n\n"
    "Current time: {current_time}\n\n"
    "Is the goal satisfied?"
)

# Used when the user has added /subgoal criteria. The judge must
# evaluate ALL of them being met, not just the original goal.
JUDGE_USER_PROMPT_WITH_SUBGOALS_TEMPLATE = (
    "Goal:\n{goal}\n\n"
    "Additional criteria the user added mid-loop (all must also be "
    "satisfied for the goal to be DONE):\n{subgoals_block}\n\n"
    "Agent's most recent response:\n{response}\n\n"
    "Current time: {current_time}\n\n"
    "Decision: For each numbered criterion above, find concrete "
    "evidence in the agent's response that the criterion is "
    "satisfied. Do not accept generic phrases like 'all requirements "
    "met' or 'implying it was done' — require specific evidence (a "
    "file contents excerpt, an output line, a command result). If "
    "ANY criterion lacks specific evidence in the response, the goal "
    "is NOT done — return CONTINUE.\n\n"
    "Is the goal AND every additional criterion satisfied?"
)


# ──────────────────────────────────────────────────────────────────────
# Dataclass
# ──────────────────────────────────────────────────────────────────────


@dataclass
class GoalState:
    """Serializable goal state stored per session."""

    goal: str
    status: str = "active"          # active | paused | done | cleared
    turns_used: int = 0
    max_turns: int = DEFAULT_MAX_TURNS
    created_at: float = 0.0
    last_turn_at: float = 0.0
    last_verdict: Optional[str] = None        # "done" | "continue" | "skipped"
    last_reason: Optional[str] = None
    paused_reason: Optional[str] = None       # why we auto-paused (budget, etc.)
    consecutive_parse_failures: int = 0       # judge-output parse failures in a row
    # User-added criteria appended mid-loop via the /subgoal command.
    # When non-empty the judge prompt and continuation prompt both
    # include them so the agent works toward them and the judge factors
    # them into the verdict. Backwards-compatible: defaults to empty so
    # old state_meta rows load unchanged.
    subgoals: List[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "GoalState":
        data = json.loads(raw)
        raw_subgoals = data.get("subgoals") or []
        subgoals: List[str] = []
        if isinstance(raw_subgoals, list):
            subgoals = [str(s).strip() for s in raw_subgoals if str(s).strip()]
        return cls(
            goal=data.get("goal", ""),
            status=data.get("status", "active"),
            turns_used=int(data.get("turns_used", 0) or 0),
            max_turns=int(data.get("max_turns", DEFAULT_MAX_TURNS) or DEFAULT_MAX_TURNS),
            created_at=float(data.get("created_at", 0.0) or 0.0),
            last_turn_at=float(data.get("last_turn_at", 0.0) or 0.0),
            last_verdict=data.get("last_verdict"),
            last_reason=data.get("last_reason"),
            paused_reason=data.get("paused_reason"),
            consecutive_parse_failures=int(data.get("consecutive_parse_failures", 0) or 0),
            subgoals=subgoals,
        )

    # --- subgoals helpers -------------------------------------------------

    def render_subgoals_block(self) -> str:
        """Render the subgoals as a numbered ``- N. text`` block. Empty
        when no subgoals exist."""
        if not self.subgoals:
            return ""
        return "\n".join(f"- {i}. {text}" for i, text in enumerate(self.subgoals, start=1))


# ──────────────────────────────────────────────────────────────────────
# Persistence (SessionDB state_meta)
# ──────────────────────────────────────────────────────────────────────


def _meta_key(session_id: str) -> str:
    return f"goal:{session_id}"


def _get_session_db() -> Optional[Any]:
    """Open a standalone goal database; the caller owns its lifetime."""
    try:
        from superforecasting_agent.storage.session import SessionDB

        return SessionDB()
    except Exception as exc:  # pragma: no cover
        logger.debug("GoalManager: SessionDB bootstrap failed (%s)", exc)
        return None


def load_goal(session_id: str) -> Optional[GoalState]:
    """Load the goal for a session, or None if none exists."""
    if not session_id:
        return None
    db = _get_session_db()
    if db is None:
        return None
    try:
        raw = db.get_meta(_meta_key(session_id))
    except Exception as exc:
        logger.debug("GoalManager: get_meta failed: %s", exc)
        return None
    finally:
        db.close()
    if not raw:
        return None
    try:
        return GoalState.from_json(raw)
    except Exception as exc:
        logger.warning("GoalManager: could not parse stored goal for %s: %s", session_id, exc)
        return None


def save_goal(session_id: str, state: GoalState) -> None:
    """Persist a goal to SessionDB. No-op if DB unavailable."""
    if not session_id:
        return
    db = _get_session_db()
    if db is None:
        return
    try:
        db.set_meta(_meta_key(session_id), state.to_json())
    except Exception as exc:
        logger.debug("GoalManager: set_meta failed: %s", exc)
    finally:
        db.close()


def clear_goal(session_id: str) -> None:
    """Mark a goal cleared in the DB (preserved for audit, status=cleared)."""
    state = load_goal(session_id)
    if state is None:
        return
    state.status = "cleared"
    save_goal(session_id, state)


# ──────────────────────────────────────────────────────────────────────
# Judge
# ──────────────────────────────────────────────────────────────────────


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "… [truncated]"


_JSON_OBJECT_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _goal_judge_max_tokens() -> int:
    """Resolve auxiliary.goal_judge.max_tokens, falling back to the default.

    ``load_config()`` is cached on the config file's (mtime, size), so calling
    this once per judge turn is cheap. A non-positive or non-int value falls
    back to the default rather than crashing the goal loop.
    """
    try:
        from superforecasting_agent.runtime.config import load_config

        cfg = load_config()
        value = (
            (cfg.get("auxiliary") or {})
            .get("goal_judge", {})
            .get("max_tokens", DEFAULT_JUDGE_MAX_TOKENS)
        )
        value = int(value)
        if value > 0:
            return value
    except Exception:
        pass
    return DEFAULT_JUDGE_MAX_TOKENS


def _parse_judge_response(raw: str) -> Tuple[bool, str, bool]:
    """Parse the judge's reply. Fail-open to ``(False, "<reason>", parse_failed)``.

    Returns ``(done, reason, parse_failed)``. ``parse_failed`` is True when the
    judge returned output that couldn't be interpreted as the expected JSON
    verdict (empty body, prose, malformed JSON). Callers use that flag to
    auto-pause after N consecutive parse failures so a weak judge model
    doesn't silently burn the turn budget.
    """
    if not raw:
        return False, "judge returned empty response", True

    text = raw.strip()

    # Strip markdown code fences the model may wrap JSON in.
    if text.startswith("```"):
        text = text.strip("`")
        # Peel off leading json/JSON/etc tag
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]

    # First try: parse the whole blob.
    data: Optional[Dict[str, Any]] = None
    try:
        data = json.loads(text)
    except Exception:
        # Second try: pull the first JSON object out.
        match = _JSON_OBJECT_RE.search(text)
        if match:
            try:
                data = json.loads(match.group(0))
            except Exception:
                data = None

    if not isinstance(data, dict):
        return False, f"judge reply was not JSON: {_truncate(raw, 200)!r}", True

    done_val = data.get("done")
    if isinstance(done_val, str):
        done = done_val.strip().lower() in {"true", "yes", "1", "done"}
    else:
        done = bool(done_val)
    reason = str(data.get("reason") or "").strip()
    if not reason:
        reason = "no reason provided"
    return done, reason, False


def judge_goal(
    goal: str,
    last_response: str,
    *,
    timeout: float = DEFAULT_JUDGE_TIMEOUT,
    subgoals: Optional[List[str]] = None,
) -> Tuple[str, str, bool]:
    """Ask the auxiliary model whether the goal is satisfied.

    Returns ``(verdict, reason, parse_failed)`` where verdict is ``"done"``,
    ``"continue"``, or ``"skipped"`` (when the judge couldn't be reached).

    ``parse_failed`` is True only when the judge call succeeded but its output
    was unusable (empty or non-JSON). API/transport errors return False — they
    are transient and should fail-open silently. Callers use this flag to
    auto-pause after N consecutive parse failures (see
    ``DEFAULT_MAX_CONSECUTIVE_PARSE_FAILURES``).

    ``subgoals`` is an optional list of user-added criteria (from
    ``/subgoal``) that the judge must also factor into its DONE/CONTINUE
    decision. When non-empty the prompt switches to the with-subgoals
    template; otherwise behavior is identical to the original judge.

    This is deliberately fail-open: any error returns ``("continue", "...", False)``
    so a broken judge doesn't wedge progress — the turn budget and the
    consecutive-parse-failures auto-pause are the backstops.
    """
    if not goal.strip():
        return "skipped", "empty goal", False
    if not last_response.strip():
        # No substantive reply this turn — almost certainly not done yet.
        return "continue", "empty response (nothing to evaluate)", False

    try:
        from agent.auxiliary_client import get_auxiliary_extra_body, get_text_auxiliary_client
    except Exception as exc:
        logger.debug("goal judge: auxiliary client import failed: %s", exc)
        return "continue", "auxiliary client unavailable", False

    try:
        client, model = get_text_auxiliary_client("goal_judge")
    except Exception as exc:
        logger.debug("goal judge: get_text_auxiliary_client failed: %s", exc)
        return "continue", "auxiliary client unavailable", False

    if client is None or not model:
        return "continue", "no auxiliary client configured", False

    # Build the prompt — pick the with-subgoals variant when applicable.
    clean_subgoals = [s.strip() for s in (subgoals or []) if s and s.strip()]
    current_time = datetime.now(tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    if clean_subgoals:
        subgoals_block = "\n".join(
            f"- {i}. {text}" for i, text in enumerate(clean_subgoals, start=1)
        )
        prompt = JUDGE_USER_PROMPT_WITH_SUBGOALS_TEMPLATE.format(
            goal=_truncate(goal, 2000),
            subgoals_block=_truncate(subgoals_block, 2000),
            response=_truncate(last_response, _JUDGE_RESPONSE_SNIPPET_CHARS),
            current_time=current_time,
        )
    else:
        prompt = JUDGE_USER_PROMPT_TEMPLATE.format(
            goal=_truncate(goal, 2000),
            response=_truncate(last_response, _JUDGE_RESPONSE_SNIPPET_CHARS),
            current_time=current_time,
        )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=_goal_judge_max_tokens(),
            timeout=timeout,
            extra_body=get_auxiliary_extra_body() or None,
        )
    except Exception as exc:
        logger.info("goal judge: API call failed (%s) — falling through to continue", exc)
        return "continue", f"judge error: {type(exc).__name__}", False

    try:
        raw = resp.choices[0].message.content or ""
    except Exception:
        raw = ""

    done, reason, parse_failed = _parse_judge_response(raw)
    verdict = "done" if done else "continue"
    logger.info("goal judge: verdict=%s reason=%s", verdict, _truncate(reason, 120))
    return verdict, reason, parse_failed


# ──────────────────────────────────────────────────────────────────────
# GoalManager — the orchestration surface CLI + gateway talk to
# ──────────────────────────────────────────────────────────────────────


class GoalManager:
    """Per-session goal state + continuation decisions.

    The CLI and gateway each hold one ``GoalManager`` per live session.

    Methods:

    - ``set(goal)`` — start a new standing goal.
    - ``clear()`` — remove the active goal.
    - ``pause()`` / ``resume()`` — explicit user controls.
    - ``status()`` — printable one-liner.
    - ``evaluate_after_turn(last_response)`` — call the judge, update state,
      and return a decision dict the caller uses to drive the next turn.
    - ``next_continuation_prompt()`` — the canonical user-role message to
      feed back into ``run_conversation``.
    """

    def __init__(
        self, session_id: str, *, default_max_turns: int = DEFAULT_MAX_TURNS,
        database_provider: Optional[Callable[[], Any]] = None,
    ):
        self.session_id = session_id
        self.default_max_turns = int(default_max_turns or DEFAULT_MAX_TURNS)
        self._database = (database_provider or _get_session_db)()
        self._owns_database = database_provider is None
        self._closed = False
        self._database_finalizer = None
        if self._database is None:
            raise RuntimeError("Goal storage is unavailable")
        try:
            self._refresh()
        except Exception:
            if self._owns_database:
                self._database.close()
            raise
        if self._owns_database:
            # Compatibility callers can omit a context manager. There is no
            # process-global cache retaining their abandoned connections.
            self._database_finalizer = weakref.finalize(self, self._database.close)

    def close(self) -> None:
        """Close an owned store; borrowed host storage is never closed here."""
        if self._closed:
            return
        if self._owns_database:
            self._database.close()
            self._database_finalizer.detach()
        self._closed = True

    def __enter__(self):
        if self._closed:
            raise RuntimeError("Goal manager is closed")
        return self

    def __exit__(self, *_exc):
        self.close()

    def _refresh(self) -> None:
        """Read from this manager's bound database, never a replacement profile."""
        if self._closed:
            raise RuntimeError("Goal manager is closed")
        raw = self._database.get_meta(_meta_key(self.session_id))
        state = GoalState.from_json(raw) if raw else None
        self._expected_state = state.to_json() if state is not None else None
        self._state = state if state is not None and state.status != "cleared" else None

    def _persist(self, state: GoalState, *, expected_state: Optional[str] = None) -> None:
        """Reject stale manager writes, including verdicts from an older judge."""
        if self._closed:
            raise RuntimeError("Goal manager is closed")
        value = state.to_json()
        expected = self._expected_state if expected_state is None else expected_state

        def update(raw):
            current = GoalState.from_json(raw).to_json() if raw else None
            if current != expected:
                raise RuntimeError("Goal changed while this operation was running; retry against the current goal.")
            return value

        try:
            self._database.mutate_meta(_meta_key(self.session_id), update)
        except Exception:
            try:
                self._refresh()
            except Exception:
                self._state = None
                self._expected_state = None
            raise
        self._state = state
        self._expected_state = value


    # --- introspection ------------------------------------------------

    @property
    def state(self) -> Optional[GoalState]:
        self._refresh()
        return self._state

    def is_active(self) -> bool:
        self._refresh()
        return self._state is not None and self._state.status == "active"

    def has_goal(self) -> bool:
        self._refresh()
        return self._state is not None and self._state.status in {"active", "paused"}

    def status_line(self) -> str:
        self._refresh()
        s = self._state
        if s is None or s.status in {"cleared",}:
            return "No active goal. Set one with /goal <text>."
        turns = f"{s.turns_used}/{s.max_turns} turns"
        sub = f", {len(s.subgoals)} subgoal{'s' if len(s.subgoals) != 1 else ''}" if s.subgoals else ""
        if s.status == "active":
            return f"⊙ Goal (active, {turns}{sub}): {s.goal}"
        if s.status == "paused":
            extra = f" — {s.paused_reason}" if s.paused_reason else ""
            return f"⏸ Goal (paused, {turns}{sub}{extra}): {s.goal}"
        if s.status == "done":
            return f"✓ Goal done ({turns}{sub}): {s.goal}"
        return f"Goal ({s.status}, {turns}{sub}): {s.goal}"

    # --- mutation -----------------------------------------------------

    def set(self, goal: str, *, max_turns: Optional[int] = None) -> GoalState:
        self._refresh()
        goal = (goal or "").strip()
        if not goal:
            raise ValueError("goal text is empty")
        state = GoalState(
            goal=goal,
            status="active",
            turns_used=0,
            max_turns=int(max_turns) if max_turns else self.default_max_turns,
            created_at=time.time(),
            last_turn_at=0.0,
        )
        self._state = state
        self._persist(state)
        return state

    def pause(self, reason: str = "user-paused") -> Optional[GoalState]:
        self._refresh()
        if not self._state:
            return None
        self._state.status = "paused"
        self._state.paused_reason = reason
        self._persist(self._state)
        return self._state

    def resume(self, *, reset_budget: bool = True) -> Optional[GoalState]:
        self._refresh()
        if not self._state:
            return None
        self._state.status = "active"
        self._state.paused_reason = None
        if reset_budget:
            self._state.turns_used = 0
        self._persist(self._state)
        return self._state

    def clear(self) -> None:
        self._refresh()
        if self._state is None:
            return
        self._state.status = "cleared"
        self._persist(self._state)
        self._state = None

    def mark_done(self, reason: str) -> None:
        self._refresh()
        if not self._state:
            return
        self._state.status = "done"
        self._state.last_verdict = "done"
        self._state.last_reason = reason
        self._persist(self._state)

    # --- /subgoal user controls ---------------------------------------

    def add_subgoal(self, text: str) -> str:
        """Append a user-added criterion to the active goal. Requires
        ``has_goal()``; raises ``RuntimeError`` otherwise.

        Returns the cleaned text so the caller can show it back to the user.
        """
        self._refresh()
        if self._state is None or self._state.status not in {"active", "paused"}:
            raise RuntimeError("no active goal")
        text = (text or "").strip()
        if not text:
            raise ValueError("subgoal text is empty")
        self._state.subgoals.append(text)
        self._persist(self._state)
        return text

    def remove_subgoal(self, index_1based: int) -> str:
        """Remove a subgoal by 1-based index. Returns the removed text."""
        self._refresh()
        if self._state is None or self._state.status not in {"active", "paused"}:
            raise RuntimeError("no active goal")
        idx = int(index_1based) - 1
        if idx < 0 or idx >= len(self._state.subgoals):
            raise IndexError(
                f"index out of range (1..{len(self._state.subgoals)})"
            )
        removed = self._state.subgoals.pop(idx)
        self._persist(self._state)
        return removed

    def clear_subgoals(self) -> int:
        """Wipe all subgoals. Returns the previous count."""
        self._refresh()
        if self._state is None or self._state.status not in {"active", "paused"}:
            raise RuntimeError("no active goal")
        prev = len(self._state.subgoals)
        self._state.subgoals = []
        self._persist(self._state)
        return prev

    def render_subgoals(self) -> str:
        """Public helper for the /subgoal slash command."""
        self._refresh()
        if self._state is None:
            return "(no active goal)"
        if not self._state.subgoals:
            return "(no subgoals — use /subgoal <text> to add criteria)"
        return self._state.render_subgoals_block()

    # --- the main entry point called after every turn -----------------

    def evaluate_after_turn(
        self,
        last_response: str,
        *,
        user_initiated: bool = True,
    ) -> Dict[str, Any]:
        """Run the judge and update state. Return a decision dict.

        ``user_initiated`` distinguishes a real user prompt (True) from a
        continuation prompt we fed ourselves (False). Both increment
        ``turns_used`` because both consume model budget.

        Decision keys:
          - ``status``: current goal status after update
          - ``should_continue``: bool — caller should fire another turn
          - ``continuation_prompt``: str or None
          - ``verdict``: "done" | "continue" | "skipped" | "inactive"
          - ``reason``: str
          - ``message``: user-visible one-liner to print/send
        """
        self._refresh()
        state = self._state
        if state is None or state.status != "active":
            return {
                "status": state.status if state else None,
                "should_continue": False,
                "continuation_prompt": None,
                "verdict": "inactive",
                "reason": "no active goal",
                "message": "",
            }

        # Judge an immutable snapshot. A concurrent command on this same manager
        # must not change the criteria underneath the in-flight verdict.
        expected = self._expected_state
        state = GoalState.from_json(state.to_json())

        # Count the turn that just finished.
        state.turns_used += 1
        state.last_turn_at = time.time()

        verdict, reason, parse_failed = judge_goal(
            state.goal, last_response, subgoals=state.subgoals or None
        )
        state.last_verdict = verdict
        state.last_reason = reason

        # Track consecutive judge parse failures. Reset on any usable reply,
        # including API / transport errors (parse_failed=False) so a flaky
        # network doesn't trip the auto-pause meant for bad judge models.
        if parse_failed:
            state.consecutive_parse_failures += 1
        else:
            state.consecutive_parse_failures = 0

        if verdict == "done":
            state.status = "done"
            self._persist(state, expected_state=expected)
            return {
                "status": "done",
                "should_continue": False,
                "continuation_prompt": None,
                "verdict": "done",
                "reason": reason,
                "message": f"✓ Goal achieved: {reason}",
            }

        # Auto-pause when the judge model can't produce the expected JSON
        # verdict N turns in a row. Points the user at the goal_judge config
        # so they can route this side task to a model that follows the
        # contract (e.g. google/gemini-3-flash-preview). Without this guard,
        # weak judge models burn the entire turn budget returning prose or
        # empty strings.
        if state.consecutive_parse_failures >= DEFAULT_MAX_CONSECUTIVE_PARSE_FAILURES:
            state.status = "paused"
            state.paused_reason = (
                f"judge model returned unparseable output {state.consecutive_parse_failures} turns in a row"
            )
            self._persist(state, expected_state=expected)
            return {
                "status": "paused",
                "should_continue": False,
                "continuation_prompt": None,
                "verdict": "continue",
                "reason": reason,
                "message": (
                    f"⏸ Goal paused — the judge model ({state.consecutive_parse_failures} turns) "
                    "isn't returning the required JSON verdict. Route the judge to a stricter "
                    "model in your active Superforecasting Agent config.yaml:\n"
                    "  auxiliary:\n"
                    "    goal_judge:\n"
                    "      provider: openrouter\n"
                    "      model: google/gemini-3-flash-preview\n"
                    "Then run /goal resume to continue."
                ),
            }

        if state.turns_used >= state.max_turns:
            state.status = "paused"
            state.paused_reason = f"turn budget exhausted ({state.turns_used}/{state.max_turns})"
            self._persist(state, expected_state=expected)
            return {
                "status": "paused",
                "should_continue": False,
                "continuation_prompt": None,
                "verdict": "continue",
                "reason": reason,
                "message": (
                    f"⏸ Goal paused — {state.turns_used}/{state.max_turns} turns used. "
                    "Use /goal resume to keep going, or /goal clear to stop."
                ),
            }

        self._persist(state, expected_state=expected)
        return {
            "status": "active",
            "should_continue": True,
            "continuation_prompt": self.next_continuation_prompt(),
            "verdict": "continue",
            "reason": reason,
            "message": (
                f"↻ Continuing toward goal ({state.turns_used}/{state.max_turns}): {reason}"
            ),
        }

    def next_continuation_prompt(self) -> Optional[str]:
        self._refresh()
        if not self._state or self._state.status != "active":
            return None
        if self._state.subgoals:
            return CONTINUATION_PROMPT_WITH_SUBGOALS_TEMPLATE.format(
                goal=self._state.goal,
                subgoals_block=self._state.render_subgoals_block(),
            )
        return CONTINUATION_PROMPT_TEMPLATE.format(goal=self._state.goal)


__all__ = [
    "GoalState",
    "GoalManager",
    "CONTINUATION_PROMPT_TEMPLATE",
    "CONTINUATION_PROMPT_WITH_SUBGOALS_TEMPLATE",
    "JUDGE_USER_PROMPT_TEMPLATE",
    "JUDGE_USER_PROMPT_WITH_SUBGOALS_TEMPLATE",
    "DEFAULT_MAX_TURNS",
    "load_goal",
    "save_goal",
    "clear_goal",
    "judge_goal",
]
