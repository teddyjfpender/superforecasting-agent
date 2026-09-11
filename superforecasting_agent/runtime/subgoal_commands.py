"""Shared subgoal validation and mutation for command consumers."""

from superforecasting_agent.runtime.goals import GoalManager


def execute_subgoal(manager: GoalManager, argument: str) -> str:
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
            idx = int(rest.split()[0])
        except ValueError:
            return "/subgoal remove: <n> must be an integer (1-based index)."
        try:
            removed = mgr.remove_subgoal(idx)
        except (IndexError, RuntimeError) as exc:
            return f"/subgoal remove: {exc}"
        return f"✓ Removed subgoal {idx}: {removed}"

    if verb == "clear":
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
    idx = len(mgr.state.subgoals) if mgr.state else 0
    return f"✓ Added subgoal {idx}: {text}"
