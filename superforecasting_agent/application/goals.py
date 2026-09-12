"""Shared goal command transitions; products own display and kickoff delivery."""

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
