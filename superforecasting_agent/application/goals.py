"""Shared goal command transitions; products own display and kickoff delivery."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


class GoalDetails(Protocol):
    @property
    def goal(self) -> str: ...

    @property
    def max_turns(self) -> int: ...


class GoalCommands(Protocol):
    def status_line(self) -> str: ...
    def has_goal(self) -> bool: ...
    def set(self, goal: str) -> GoalDetails: ...
    def pause(self, reason: str = "user-paused") -> GoalDetails | None: ...
    def resume(self) -> GoalDetails | None: ...
    def clear(self) -> None: ...


@dataclass(frozen=True)
class GoalSnapshot:
    goal: str
    max_turns: int


@dataclass(frozen=True)
class GoalCommandResult:
    action: Literal["status", "pause", "resume", "clear", "set"]
    state: GoalSnapshot | None = None
    status: str = ""
    had_goal: bool = False


def execute_goal(manager: GoalCommands, argument: str) -> GoalCommandResult:
    """Apply one command once, returning values independent of mutable storage."""
    argument = argument.strip()
    action = argument.lower()
    if not argument or action == "status":
        return GoalCommandResult("status", status=manager.status_line())
    if action in {"clear", "stop", "done"}:
        had_goal = manager.has_goal()
        manager.clear()
        return GoalCommandResult("clear", had_goal=had_goal)
    if action == "pause":
        state = manager.pause(reason="user-paused")
        result_action: Literal["pause", "resume", "set"] = "pause"
    elif action == "resume":
        state = manager.resume()
        result_action = "resume"
    else:
        state = manager.set(argument)
        result_action = "set"
    snapshot = GoalSnapshot(state.goal, state.max_turns) if state is not None else None
    return GoalCommandResult(result_action, state=snapshot)


class SubgoalDetails(Protocol):
    @property
    def subgoals(self) -> Sequence[str]: ...


class SubgoalCommands(Protocol):
    @property
    def state(self) -> SubgoalDetails | None: ...

    def has_goal(self) -> bool: ...
    def status_line(self) -> str: ...
    def render_subgoals(self) -> str: ...
    def remove_subgoal(self, index_1based: int) -> str: ...
    def clear_subgoals(self) -> int: ...
    def add_subgoal(self, text: str) -> str: ...


def execute_subgoal(manager: SubgoalCommands, argument: str) -> str:
    """Apply a subgoal command to the caller's session-bound goal manager."""
    mgr = manager
    args = argument.strip()
    if not mgr.has_goal():
        return "No active goal. Set one with /goal <text>."

    # No args → list current subgoals.
    if not args:
        return f"{mgr.status_line()}\n{mgr.render_subgoals()}"

    tokens = args.split(None, 1)
    verb = tokens[0].lower()
    rest = tokens[1].strip() if len(tokens) > 1 else ""

    if verb == "remove":
        if not rest:
            return "Usage: /subgoal remove <n>"
        try:
            idx = int(rest)
        except ValueError:
            return "/subgoal remove: <n> must be an integer (1-based index)."
        try:
            removed = mgr.remove_subgoal(idx)
        except (IndexError, RuntimeError) as exc:
            return f"/subgoal remove: {exc}"
        return f"✓ Removed subgoal {idx}: {removed}"

    if verb == "clear":
        if rest:
            return "Usage: /subgoal clear"
        try:
            prev = mgr.clear_subgoals()
        except RuntimeError as exc:
            return f"/subgoal clear: {exc}"
        if prev:
            return f"✓ Cleared {prev} subgoal{'s' if prev != 1 else ''}."
        return "No subgoals to clear."

    try:
        text = mgr.add_subgoal(args)
    except (ValueError, RuntimeError) as exc:
        return f"/subgoal: {exc}"
    state = mgr.state
    idx = len(state.subgoals) if state else 0
    return f"✓ Added subgoal {idx}: {text}"
