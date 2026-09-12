"""Snapshot command policy shared by terminal and RPC consumers."""

from __future__ import annotations

import shlex

from superforecasting_agent.constants import display_agent_home
from superforecasting_agent.storage import snapshots as backup

_USAGE = "Usage: /snapshot [list|create [label]|restore <id>|prune [N]]"


def execute_snapshot(argument: str, *, allow_restore: bool = True) -> str:
    """Execute against shared storage; hosts explicitly admit live restoration."""
    parts = shlex.split(argument)
    action = parts.pop(0).lower() if parts else "list"
    action = {"ls": "list", "rewind": "restore"}.get(action, action)
    if action not in {"list", "create", "restore", "prune"}:
        raise ValueError(f"Unknown subcommand: {action}\n{_USAGE}")
    if (action == "list" and parts) or (
        action in {"prune", "restore"} and len(parts) > 1
    ):
        raise ValueError(_USAGE)
    if action == "restore" and not allow_restore:
        return (
            "/snapshot restore is blocked in the TUI because it changes "
            "config/state on disk while the live agent has cached settings. "
            "Run it in the classic CLI, then restart the TUI."
        )
    if action == "list":
        snapshots = backup.list_quick_snapshots()
        if not snapshots:
            return "No state snapshots yet.\nCreate one: /snapshot create [label]"
        lines = [
            f"State snapshots ({display_agent_home()}/state-snapshots/):\n",
            f"{'#':>3}  {'ID':<35} {'Files':>5} {'Size':>10} Label",
        ]
        for index, snapshot in enumerate(snapshots, 1):
            size = snapshot.get("total_size", 0)
            size_text = (
                f"{size} B"
                if size < 1024
                else f"{size / 1024:.0f} KB"
                if size < 1024 * 1024
                else f"{size / 1024 / 1024:.1f} MB"
            )
            lines.append(
                f"{index:3}  {snapshot['id']:<35} {snapshot.get('file_count', 0):>5} "
                f"{size_text:>10} {snapshot.get('label') or ''}"
            )
        return "\n".join(lines)
    if action == "create":
        snapshot_id = backup.create_quick_snapshot(label=" ".join(parts) or None)
        return (
            f"Snapshot created: {snapshot_id}"
            if snapshot_id
            else "No state files found to snapshot."
        )
    if action == "prune":
        try:
            keep = int(parts[0]) if parts else 20
        except ValueError:
            raise ValueError("Usage: /snapshot prune [keep-count]") from None
        deleted = backup.prune_quick_snapshots(keep=keep)
        return f"Pruned {deleted} old snapshot(s) (keeping {keep})."
    if not parts:
        recent = backup.list_quick_snapshots(limit=1)
        hint = f"\nMost recent: {recent[0]['id']}" if recent else ""
        return "Usage: /snapshot restore <snapshot-id>" + hint
    snapshot_id = parts[0]
    try:
        index = int(snapshot_id)
    except ValueError:
        pass
    else:
        snapshots = backup.list_quick_snapshots()
        if not 1 <= index <= len(snapshots):
            raise ValueError(f"Invalid snapshot number. Use 1-{len(snapshots)}.")
        snapshot_id = snapshots[index - 1]["id"]
    if backup.restore_quick_snapshot(snapshot_id):
        return f"Restored state from: {snapshot_id}\nRestart recommended for state.db changes to take effect."
    return f"Snapshot not found: {snapshot_id}"
