"""CLI subcommand: `superforecasting-agent curator <subcommand>`.

Thin shell around agent/curator.py and tools/skill_usage.py. Renders a status
table, triggers a run, pauses/resumes, and pins/unpins skills.

This module intentionally has no side effects at import time — main.py wires
the argparse subparsers on demand.
"""

from __future__ import annotations

import argparse
import io
import shlex
import sys
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Optional

from superforecasting_agent.constants import display_agent_home
from superforecasting_agent.hosting.workers import RuntimeWorkers


_PRIMARY_CLI = "superforecasting-agent"


def _fmt_ts(ts: Optional[str]) -> str:
    if not ts:
        return "never"
    try:
        dt = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return str(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _cmd_status(args, *, emit=print, confirm=None) -> int:
    from agent import curator
    from tools import skill_usage

    state = curator.load_state(strict=True)
    enabled = curator.is_enabled()
    paused = state.get("paused", False)
    last_run = state.get("last_run_at")
    summary = state.get("last_run_summary") or "(none)"
    runs = state.get("run_count", 0)

    status_line = (
        "ENABLED" if enabled and not paused else "PAUSED" if paused else "DISABLED"
    )
    emit(f"curator: {status_line}")
    emit(f"  runs:           {runs}")
    emit(f"  last run:       {_fmt_ts(last_run)}")
    # Summary may be multi-line when the curator archived skills (the rename
    # map gets appended as `name → umbrella` lines). Indent continuation
    # lines so the block reads as one logical field.
    if "\n" in summary:
        first, *rest = summary.splitlines()
        emit(f"  last summary:   {first}")
        for line in rest:
            emit(f"                  {line}")
    else:
        emit(f"  last summary:   {summary}")
    _report = state.get("last_report_path")
    if _report:
        suffix = "" if Path(_report).exists() else " (missing)"
        emit(f"  last report:    {_report}{suffix}")
    _ih = curator.get_interval_hours()
    _interval_label = f"{_ih // 24}d" if _ih % 24 == 0 and _ih >= 24 else f"{_ih}h"
    emit(f"  interval:       every {_interval_label}")
    emit(f"  stale after:    {curator.get_stale_after_days()}d unused")
    emit(f"  archive after:  {curator.get_archive_after_days()}d unused")

    rows = skill_usage.agent_created_report()
    if not rows:
        emit("\nno agent-created skills")
        return 0

    by_state = {"active": [], "stale": [], "archived": []}
    pinned = []
    for r in rows:
        state_name = r.get("state", "active")
        by_state.setdefault(state_name, []).append(r)
        if r.get("pinned"):
            pinned.append(r["name"])

    emit(f"\nagent-created skills: {len(rows)} total")
    for state_name in ("active", "stale", "archived"):
        bucket = by_state.get(state_name, [])
        emit(f"  {state_name:10s} {len(bucket)}")

    if pinned:
        emit(f"\npinned ({len(pinned)}): {', '.join(pinned)}")

    # Show top 5 least-recently-active skills. Views and edits are activity too:
    # curator should not report a skill as "never used" right after skill_view()
    # or skill_manage() touched it.
    active = sorted(
        by_state.get("active", []),
        key=lambda r: r.get("last_activity_at") or r.get("created_at") or "",
    )[:5]
    if active:
        emit("\nleast recently active (top 5):")
        for r in active:
            last = _fmt_ts(r.get("last_activity_at"))
            emit(
                f"  {r['name']:40s}  "
                f"activity={r.get('activity_count', 0):3d}  "
                f"use={r.get('use_count', 0):3d}  "
                f"view={r.get('view_count', 0):3d}  "
                f"patches={r.get('patch_count', 0):3d}  "
                f"last_activity={last}"
            )

    # Show top 5 most-active and least-active skills by activity_count
    # (use + view + patch). This is a different signal from
    # least-recently-active: activity_count reflects frequency,
    # last_activity_at reflects recency. A skill touched 30 times a year
    # ago is high-frequency but stale; a skill touched once yesterday is
    # recent but low-frequency. Both can matter.
    active_all = by_state.get("active", [])
    if active_all:
        most_active = sorted(
            active_all,
            key=lambda r: (
                r.get("activity_count") or 0,
                r.get("last_activity_at") or "",
            ),
            reverse=True,
        )[:5]
        if most_active and (most_active[0].get("activity_count") or 0) > 0:
            emit("\nmost active (top 5):")
            for r in most_active:
                last = _fmt_ts(r.get("last_activity_at"))
                emit(
                    f"  {r['name']:40s}  "
                    f"activity={r.get('activity_count', 0):3d}  "
                    f"use={r.get('use_count', 0):3d}  "
                    f"view={r.get('view_count', 0):3d}  "
                    f"patches={r.get('patch_count', 0):3d}  "
                    f"last_activity={last}"
                )

        least_active = sorted(
            active_all,
            key=lambda r: (
                r.get("activity_count") or 0,
                r.get("last_activity_at") or "",
            ),
        )[:5]
        if least_active:
            emit("\nleast active (top 5):")
            for r in least_active:
                last = _fmt_ts(r.get("last_activity_at"))
                emit(
                    f"  {r['name']:40s}  "
                    f"activity={r.get('activity_count', 0):3d}  "
                    f"use={r.get('use_count', 0):3d}  "
                    f"view={r.get('view_count', 0):3d}  "
                    f"patches={r.get('patch_count', 0):3d}  "
                    f"last_activity={last}"
                )

    return 0


def _cmd_run(
    args, *, emit=print, confirm=None, workers: RuntimeWorkers | None = None
) -> int:
    from agent import curator

    if not curator.is_enabled():
        emit("curator: disabled via config; enable with `curator.enabled: true`")
        return 1

    dry = bool(getattr(args, "dry_run", False))
    background = bool(getattr(args, "background", False))
    synchronous = bool(getattr(args, "synchronous", False)) or not background
    if not synchronous and workers is not None:
        # Admit before any review mutations. The whole pass, including state and
        # report publication, remains counted after this command returns.
        workers.start(
            lambda: curator.run_curator_review(synchronous=True, dry_run=dry),
            name="curator-review",
        )
        emit(
            f"curator: review running in background — check `{_PRIMARY_CLI} curator status` later"
        )
        return 0
    if dry:
        emit("curator: running DRY-RUN (report only, no mutations)...")
    else:
        emit("curator: running review pass...")

    def _on_summary(msg: str) -> None:
        emit(msg)

    result = curator.run_curator_review(
        on_summary=_on_summary,
        synchronous=synchronous,
        dry_run=dry,
    )
    auto = result.get("auto_transitions", {})
    if auto:
        if dry:
            emit(
                f"auto (preview): {auto.get('checked', 0)} candidate skill(s) "
                "— no transitions applied in dry-run"
            )
        else:
            emit(
                f"auto: checked={auto.get('checked', 0)} "
                f"stale={auto.get('marked_stale', 0)} "
                f"archived={auto.get('archived', 0)} "
                f"reactivated={auto.get('reactivated', 0)}"
            )
    if not synchronous:
        emit(
            f"llm pass running in background — check `{_PRIMARY_CLI} curator status` later"
        )
    if dry:
        if synchronous:
            emit(
                "dry-run: no changes applied. Read the report with "
                f"`{_PRIMARY_CLI} curator status` and run `{_PRIMARY_CLI} curator run` "
                "(no flag) to apply."
            )
        else:
            emit(
                "dry-run: no changes applied. When the report lands, read it with "
                f"`{_PRIMARY_CLI} curator status` and run `{_PRIMARY_CLI} curator run` "
                "(no flag) to apply."
            )
    return 0


def _cmd_pause(args, *, emit=print, confirm=None) -> int:
    from agent import curator

    curator.set_paused(True)
    emit("curator: paused")
    return 0


def _cmd_resume(args, *, emit=print, confirm=None) -> int:
    from agent import curator

    curator.set_paused(False)
    emit("curator: resumed")
    return 0


def _cmd_pin(args, *, emit=print, confirm=None) -> int:
    from tools import skill_usage

    if not skill_usage.is_agent_created(args.skill):
        emit(
            f"curator: '{args.skill}' is bundled or hub-installed — cannot pin "
            "(only agent-created skills participate in curation)"
        )
        return 1
    skill_usage.set_pinned(args.skill, True)
    emit(f"curator: pinned '{args.skill}' (will bypass auto-transitions)")
    return 0


def _cmd_unpin(args, *, emit=print, confirm=None) -> int:
    from tools import skill_usage

    if not skill_usage.is_agent_created(args.skill):
        emit(
            f"curator: '{args.skill}' is bundled or hub-installed — "
            "there's nothing to unpin (curator only tracks agent-created skills)"
        )
        return 1
    skill_usage.set_pinned(args.skill, False)
    emit(f"curator: unpinned '{args.skill}'")
    return 0


def _cmd_restore(args, *, emit=print, confirm=None) -> int:
    from tools import skill_usage

    ok, msg = skill_usage.restore_skill(args.skill)
    emit(f"curator: {msg}")
    return 0 if ok else 1


def _cmd_archive(args, *, emit=print, confirm=None) -> int:
    """Manually archive an agent-created skill. Refuses if pinned.

    The auto-curator archives stale skills on its own schedule; this verb is
    for the user who wants to archive *now* without waiting for a run.
    """
    from tools import skill_usage

    if skill_usage.get_record(args.skill).get("pinned"):
        emit(
            f"curator: '{args.skill}' is pinned — unpin first with "
            f"`{_PRIMARY_CLI} curator unpin {args.skill}`"
        )
        return 1
    ok, msg = skill_usage.archive_skill(args.skill)
    emit(f"curator: {msg}")
    return 0 if ok else 1


def _idle_days(record: dict) -> Optional[int]:
    """Days since the skill's last activity (view / use / patch).

    Falls back to ``created_at`` so a skill that was authored but never used
    can still be pruned — otherwise never-touched skills would be immortal.
    Returns None only when both fields are missing or unparseable.
    """
    ts = record.get("last_activity_at") or record.get("created_at")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - dt).days)


def _cmd_prune(args, *, emit=print, confirm=None) -> int:
    """Bulk-archive agent-created skills idle for >= N days.

    Pinned skills are exempt. Already-archived skills are skipped. Default
    ``--days 90`` matches a conservative read of the curator's own archive
    threshold; adjust with ``--days``. Use ``--dry-run`` to preview.
    """
    from tools import skill_usage

    days = getattr(args, "days", 90)
    if days < 1:
        emit(f"curator: --days must be >= 1 (got {days})", file=sys.stderr)
        return 2

    dry_run = bool(getattr(args, "dry_run", False))
    skip_confirm = bool(getattr(args, "yes", False))

    candidates = []
    for r in skill_usage.agent_created_report():
        if r.get("pinned"):
            continue
        if r.get("state") == skill_usage.STATE_ARCHIVED:
            continue
        idle = _idle_days(r)
        if idle is None or idle < days:
            continue
        candidates.append((r["name"], idle))

    if not candidates:
        emit(f"curator: nothing to prune (no unpinned skills idle >= {days}d)")
        return 0

    candidates.sort(key=lambda c: -c[1])
    emit(f"curator: {len(candidates)} skill(s) idle >= {days}d:")
    for name, idle in candidates:
        emit(f"  {name:40s} idle {idle}d")

    if dry_run:
        emit("\n(dry run — no changes made)")
        return 0

    if not skip_confirm:
        try:
            reply = (
                (confirm or input)(f"\nArchive {len(candidates)} skill(s)? [y/N] ")
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt):
            emit("\ncurator: aborted")
            return 1
        if reply not in {"y", "yes"}:
            emit("curator: aborted")
            return 1

    archived = 0
    failures = []
    for name, _ in candidates:
        ok, msg = skill_usage.archive_skill(name)
        if ok:
            archived += 1
        else:
            failures.append((name, msg))

    emit(f"\ncurator: archived {archived}/{len(candidates)}")
    if failures:
        emit("failures:")
        for name, msg in failures:
            emit(f"  {name}: {msg}")
        return 1
    return 0


def _cmd_backup(args, *, emit=print, confirm=None) -> int:
    """Take a manual snapshot of the skills tree. Same mechanism as the
    automatic pre-run snapshot, just user-initiated."""
    from agent import curator_backup

    if not curator_backup.is_enabled():
        emit(
            "curator: backups are disabled via config "
            "(`curator.backup.enabled: false`); re-enable to snapshot"
        )
        return 1
    reason = getattr(args, "reason", None) or "manual"
    snap = curator_backup.snapshot_skills(reason=reason)
    if snap is None:
        emit("curator: snapshot failed — check logs (backup disabled or IO error)")
        return 1
    emit(
        f"curator: snapshot created at "
        f"{display_agent_home()}/skills/.curator_backups/{snap.name}"
    )
    return 0


def _cmd_rollback(args, *, emit=print, confirm=None) -> int:
    """Restore the skills tree from a snapshot. Defaults to newest.

    ``--list`` prints available snapshots and exits. ``--id <stamp>`` picks
    a specific one. Without ``-y``, prompts for confirmation. A safety
    snapshot of the current tree is always taken first, so rollbacks are
    themselves undoable.
    """
    from agent import curator_backup

    if getattr(args, "list", False):
        emit(curator_backup.summarize_backups())
        return 0

    backup_id = getattr(args, "backup_id", None)
    target_path = curator_backup._resolve_backup(backup_id)
    if target_path is None:
        rows = curator_backup.list_backups()
        if not rows:
            emit(
                "curator: no snapshots exist yet. Take one with "
                f"`{_PRIMARY_CLI} curator backup` or wait for the next curator run."
            )
        else:
            emit(
                f"curator: no snapshot matching "
                f"{'id ' + repr(backup_id) if backup_id else 'your query'}."
            )
            emit("Available:")
            emit(curator_backup.summarize_backups())
        return 1

    manifest = curator_backup._read_manifest(target_path)
    emit(f"Rollback target: {target_path.name}")
    if manifest:
        emit(f"  reason:      {manifest.get('reason', '?')}")
        emit(f"  created_at:  {manifest.get('created_at', '?')}")
        emit(f"  skill files: {manifest.get('skill_files', '?')}")
        cron = manifest.get("cron_jobs") or {}
        if isinstance(cron, dict):
            if cron.get("backed_up"):
                emit(
                    f"  cron jobs:   {cron.get('jobs_count', 0)} "
                    f"(will be restored for skill-link fields only)"
                )
            else:
                reason = cron.get("reason", "not captured")
                emit(f"  cron jobs:   not in snapshot ({reason})")
    emit(
        f"\nThis will replace the current {display_agent_home()}/skills/ tree (a safety "
        "snapshot of the current state is taken first so this is undoable). "
        "Cron jobs that still exist will have their skills/skill fields "
        "restored from the snapshot; all other cron fields are left alone."
    )

    if not getattr(args, "yes", False):
        try:
            ans = (confirm or input)("Proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            emit("\ncancelled")
            return 1
        if ans not in {"y", "yes"}:
            emit("cancelled")
            return 1

    ok, msg, _ = curator_backup.rollback(backup_id=target_path.name)
    if ok:
        emit(f"curator: {msg}")
        return 0
    emit(f"curator: rollback failed — {msg}")
    return 1


def _cmd_list_archived(args, *, emit=print, confirm=None) -> int:
    """List archived (recoverable) skills."""
    from tools import skill_usage

    names = skill_usage.list_archived_skill_names()
    if not names:
        emit("curator: no archived skills")
        return 0
    for name in names:
        emit(name)
    return 0


# ---------------------------------------------------------------------------
# argparse wiring (called from superforecasting_agent.runtime.main)
# ---------------------------------------------------------------------------


def register_cli(
    parent: argparse.ArgumentParser, *, workers: RuntimeWorkers | None = None
) -> None:
    """Attach `curator` subcommands to *parent*.

    main.py calls this with the ArgumentParser returned by
    ``subparsers.add_parser("curator", ...)``.
    """
    parent.set_defaults(func=lambda a, **kwargs: (parent.print_help(), 0)[1])
    subs = parent.add_subparsers(dest="curator_command")

    p_status = subs.add_parser("status", help="Show curator status and skill stats")
    p_status.set_defaults(func=_cmd_status)

    p_run = subs.add_parser("run", help="Trigger a curator review now")
    p_run.add_argument(
        "--sync",
        "--synchronous",
        dest="synchronous",
        action="store_true",
        help="Wait for the LLM review pass to finish (default for manual runs)",
    )
    p_run.add_argument(
        "--background",
        dest="background",
        action="store_true",
        help="Start the LLM review pass in a background thread and return immediately",
    )
    p_run.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Report only — no state changes, no archives, no consolidation "
        "(use this to preview what curator would do)",
    )
    p_run.set_defaults(func=partial(_cmd_run, workers=workers))

    p_pause = subs.add_parser("pause", help="Pause the curator until resumed")
    p_pause.set_defaults(func=_cmd_pause)

    p_resume = subs.add_parser("resume", help="Resume a paused curator")
    p_resume.set_defaults(func=_cmd_resume)

    p_pin = subs.add_parser(
        "pin", help="Pin a skill so the curator never auto-transitions it"
    )
    p_pin.add_argument("skill", help="Skill name")
    p_pin.set_defaults(func=_cmd_pin)

    p_unpin = subs.add_parser("unpin", help="Unpin a skill")
    p_unpin.add_argument("skill", help="Skill name")
    p_unpin.set_defaults(func=_cmd_unpin)

    p_restore = subs.add_parser("restore", help="Restore an archived skill")
    p_restore.add_argument("skill", help="Skill name")
    p_restore.set_defaults(func=_cmd_restore)

    subs.add_parser("list-archived", help="List archived skills").set_defaults(
        func=_cmd_list_archived
    )

    p_archive = subs.add_parser(
        "archive",
        help="Manually archive a skill (move to .archive/, excluded from prompt)",
    )
    p_archive.add_argument("skill", help="Skill name")
    p_archive.set_defaults(func=_cmd_archive)

    p_prune = subs.add_parser(
        "prune",
        help="Bulk-archive agent-created skills idle for >= N days (default 90)",
    )
    p_prune.add_argument(
        "--days",
        type=int,
        default=90,
        help="Archive skills idle for at least N days (default: 90)",
    )
    p_prune.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt",
    )
    p_prune.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Show what would be archived without doing it",
    )
    p_prune.set_defaults(func=_cmd_prune)

    p_backup = subs.add_parser(
        "backup",
        help=f"Take a manual tar.gz snapshot of {display_agent_home()}/skills/ "
        "(curator also does this automatically before every real run)",
    )
    p_backup.add_argument(
        "--reason",
        default=None,
        help="Free-text label stored in manifest.json (default: 'manual')",
    )
    p_backup.set_defaults(func=_cmd_backup)

    p_rollback = subs.add_parser(
        "rollback",
        help=f"Restore {display_agent_home()}/skills/ from a curator snapshot "
        "(defaults to the newest)",
    )
    p_rollback.add_argument(
        "--list",
        action="store_true",
        help="List available snapshots and exit without restoring",
    )
    p_rollback.add_argument(
        "--id",
        dest="backup_id",
        default=None,
        help="Snapshot id to restore (see `--list`); default: newest",
    )
    p_rollback.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    p_rollback.set_defaults(func=_cmd_rollback)


def cli_main(
    argv=None, *, emit=print, confirm=None, workers: RuntimeWorkers | None = None
) -> int:
    """Standalone entry (also usable by superforecasting_agent.runtime.main fallthrough)."""

    class CommandParser(argparse.ArgumentParser):
        def _print_message(self, message, file=None):
            if message:
                emit(message, end="", file=file)

    parser = CommandParser(prog=f"{_PRIMARY_CLI} curator")
    register_cli(parser, workers=workers)
    args = parser.parse_args(argv)
    fn = getattr(args, "func", None)
    if fn is None:
        parser.print_help()
        return 0
    try:
        return int(fn(args, emit=emit, confirm=confirm) or 0)
    except (OSError, ValueError) as exc:
        emit(f"curator: operation failed: {exc}")
        return 1


def command_output(
    argument: str, *, confirm=None, workers: RuntimeWorkers | None = None
) -> tuple[int, str]:
    """Run a slash command without process-global stream redirection.

    Confirmation includes the accumulated preview so a transport can display
    exactly which skills or snapshot the user is approving.
    """
    output = io.StringIO()

    def emit(*values, **kwargs):
        kwargs["file"] = output
        print(*values, **kwargs)

    def ask(question):
        if confirm is None:
            return ""
        return confirm(output.getvalue().strip() + "\n\n" + question) or ""

    try:
        argv = shlex.split(argument) or ["status"]
        code = cli_main(argv, emit=emit, confirm=ask, workers=workers)
    except ValueError as exc:
        emit(f"curator: {exc}")
        code = 2
    except SystemExit as exc:
        code = int(exc.code or 0)
    return code, output.getvalue().rstrip()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(cli_main())
