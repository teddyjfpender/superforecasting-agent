"""Shared background inspection and stop operations over owned registries.

None preserves the standalone CLI's process-wide scope. Hosted callers must pass
an explicit session key; an empty key selects only legacy unowned records.
"""

from __future__ import annotations


def _cleanup_lines(session_key: str | None) -> list[str]:
    from superforecasting_agent.hosting.delegations import pending_cleanup

    return [
        f"  Cleanup pending: {child['subagent_id']} · {child['error']}"
        for child in pending_cleanup(session_key=session_key)
    ]


def stop_background(*, session_key: str | None = None) -> str:
    """Stop processes and signal delegations, reporting actual registry results."""
    from tools.async_delegation import interrupt_all, list_async_delegations
    from tools.process_registry import process_registry

    running = [
        p
        for p in process_registry.list_sessions(session_key=session_key)
        if p.get("status") == "running"
    ]
    delegations = [
        d
        for d in list_async_delegations(session_key=session_key)
        if d.get("status") == "running"
    ]
    from superforecasting_agent.hosting.delegations import (
        interrupt_subagent,
        list_active_subagents,
        retry_cleanup,
    )

    background_agents = [
        child
        for child in list_active_subagents(session_key=session_key)
        if child.get("kind") == "background" and child.get("status") == "running"
    ]
    interrupted = sum(
        interrupt_subagent(child["subagent_id"], session_key=session_key)
        for child in background_agents
    )
    completed, pending = retry_cleanup(session_key=session_key)
    lines = []
    if background_agents:
        lines.append(
            f"  Interrupted {interrupted} of {len(background_agents)} background agent(s)."
        )
    if completed:
        lines.append(f"  Completed cleanup for {completed} child agent(s).")
    if pending:
        lines.append(
            f"  Cleanup still pending for {pending} child agent(s); retry /stop."
        )
    lines.extend(_cleanup_lines(session_key))
    if running:
        killed = process_registry.kill_all(session_key=session_key)
        lines.append(f"  Stopped {killed} background process(es).")
        if killed < len(running):
            lines.append(
                "  Some processes could not be stopped; inspect /agents and retry."
            )
    if delegations:
        stopped = interrupt_all(reason="/stop", session_key=session_key)
        lines.append(f"  Interrupted {stopped} background delegation(s).")
        if stopped < len(delegations):
            lines.append(
                "  Some delegations could not be interrupted; inspect /agents and retry."
            )
    return "\n".join(lines) if lines else "  No running background processes."


def describe_background(*, agent_running: bool, session_key: str | None = None) -> str:
    """Describe the same registry scope that stop_background controls."""
    from tools.async_delegation import list_async_delegations
    from tools.process_registry import format_uptime_short, process_registry

    processes = process_registry.list_sessions(session_key=session_key)
    running = [p for p in processes if p.get("status") == "running"]
    finished = [p for p in processes if p.get("status") != "running"]
    lines = [f"  Running processes: {len(running)}"]
    for process in running:
        command = process.get("command", "")[:80]
        uptime = format_uptime_short(process.get("uptime_seconds", 0))
        lines.append(f"    {process.get('session_id', '?')} · {uptime} · {command}")
    if finished:
        lines.append(f"  Recently finished: {len(finished)}")
    delegations = [
        d
        for d in list_async_delegations(session_key=session_key)
        if d.get("status") == "running"
    ]
    if delegations:
        lines.append(f"  Background delegations: {len(delegations)} running")
        for delegation in delegations:
            goal = (delegation.get("goal", "") or "")[:60]
            lines.append(
                f"    {delegation.get('delegation_id', '?')} · {delegation.get('status')} · {goal}"
            )
    from superforecasting_agent.hosting.delegations import list_active_subagents

    for child in list_active_subagents(session_key=session_key):
        if child.get("kind") == "background" and child.get("status") == "running":
            lines.append(
                f"  Background agent: {child['subagent_id']} · {str(child.get('goal', ''))[:60]}"
            )
    lines.extend(_cleanup_lines(session_key))
    lines.append(f"  Agent: {'running' if agent_running else 'idle'}")
    return "\n".join(lines)
