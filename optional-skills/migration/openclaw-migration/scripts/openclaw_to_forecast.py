#!/usr/bin/env python3
"""OpenClaw -> Superforecasting Agent migration helper.

This script migrates the parts of an OpenClaw user footprint that map cleanly
into Superforecasting Agent, archives selected unmapped docs for manual review, and
reports exactly what was skipped and why.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from _forecast_migration_files import (
    yaml as yaml,
    sha256_file as sha256_file,
    read_text as read_text,
    normalize_text as normalize_text,
    ensure_parent as ensure_parent,
    resolve_secret_input as resolve_secret_input,
    load_yaml_file as load_yaml_file,
    dump_yaml_file as dump_yaml_file,
    parse_env_file as parse_env_file,
    save_env_file as save_env_file,
    backup_existing as backup_existing,
    relative_label as relative_label,
)


from _forecast_migration_options import (
    ENTRY_DELIMITER as ENTRY_DELIMITER,
    DEFAULT_MEMORY_CHAR_LIMIT as DEFAULT_MEMORY_CHAR_LIMIT,
    DEFAULT_USER_CHAR_LIMIT as DEFAULT_USER_CHAR_LIMIT,
    SKILL_CATEGORY_DIRNAME as SKILL_CATEGORY_DIRNAME,
    SKILL_CATEGORY_DESCRIPTION as SKILL_CATEGORY_DESCRIPTION,
    SKILL_CONFLICT_MODES as SKILL_CONFLICT_MODES,
    SUPPORTED_SECRET_TARGETS as SUPPORTED_SECRET_TARGETS,
    WORKSPACE_INSTRUCTIONS_FILENAME as WORKSPACE_INSTRUCTIONS_FILENAME,
    MIGRATION_OPTION_METADATA as MIGRATION_OPTION_METADATA,
    MIGRATION_PRESETS as MIGRATION_PRESETS,
    STATUS_MIGRATED as STATUS_MIGRATED,
    STATUS_ARCHIVED as STATUS_ARCHIVED,
    STATUS_SKIPPED as STATUS_SKIPPED,
    STATUS_CONFLICT as STATUS_CONFLICT,
    STATUS_ERROR as STATUS_ERROR,
    STATUS_PLANNED as STATUS_PLANNED,
    REASON_TARGET_EXISTS as REASON_TARGET_EXISTS,
    REASON_BLOCKED_BY_APPLY_CONFLICT as REASON_BLOCKED_BY_APPLY_CONFLICT,
    ItemResult as ItemResult,
    parse_selection_values as parse_selection_values,
    resolve_selected_options as resolve_selected_options,
)


from _forecast_migration_text import (
    _REBRAND_PATTERNS as _REBRAND_PATTERNS,
    _case_preserving_replacement as _case_preserving_replacement,
    rebrand_text as rebrand_text,
    parse_existing_memory_entries as parse_existing_memory_entries,
    extract_markdown_entries as extract_markdown_entries,
    merge_entries as merge_entries,
)


# ───────────────────────────────────────────────────────────────────────
# Secret redaction for migration reports.
#
# The report JSON persists to disk inside the migration output directory and
# frequently ends up in bug reports or support channels.  Anything that looks
# like a credential — by key name or by value shape — is replaced with
# "[redacted]" before the report is written.
#
# Modelled on OpenClaw's src/plugin-sdk/migration.ts so both migration tools
# redact consistently.  Pure function — safe to call on any plain-data dict.
# ───────────────────────────────────────────────────────────────────────
from _forecast_migration_reports import (
    REDACTED_MIGRATION_VALUE as REDACTED_MIGRATION_VALUE,
    _SECRET_KEY_MARKERS as _SECRET_KEY_MARKERS,
    _SECRET_VALUE_PATTERNS as _SECRET_VALUE_PATTERNS,
    _normalize_secret_key as _normalize_secret_key,
    _is_secret_key as _is_secret_key,
    _redact_string as _redact_string,
    redact_migration_value as redact_migration_value,
    _redact_internal as _redact_internal,
    write_report as write_report,
)


from _forecast_migration_runner import Migrator as Migrator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate OpenClaw user state into Superforecasting Agent.")
    parser.add_argument("--source", default=str(Path.home() / ".openclaw"), help="OpenClaw home directory")
    parser.add_argument(
        "--target",
        default=(
            os.environ.get("SUPERFORECASTING_AGENT_HOME")
            or os.environ.get("FORECAST_HOME")
            or os.environ.get("HERMES_HOME")
            or str(Path.home() / ".superforecasting-agent")
        ),
        help="Superforecasting Agent home directory",
    )
    parser.add_argument(
        "--workspace-target",
        help="Optional workspace root where the workspace instructions file should be copied",
    )
    parser.add_argument("--execute", action="store_true", help="Apply changes instead of reporting a dry run")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing Superforecasting Agent targets after backing them up")
    parser.add_argument(
        "--migrate-secrets",
        action="store_true",
        help="Import a narrow allowlist of Superforecasting Agent-compatible secrets into the target env file",
    )
    parser.add_argument(
        "--skill-conflict",
        choices=sorted(SKILL_CONFLICT_MODES),
        default="skip",
        help="How to handle imported skill directory conflicts: skip, overwrite, or rename the imported copy.",
    )
    parser.add_argument(
        "--preset",
        choices=sorted(MIGRATION_PRESETS),
        help="Apply a named migration preset. 'user-data' excludes allowlisted secrets; 'full' includes all compatible groups.",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Comma-separated migration option ids to include (default: all). "
             f"Valid ids: {', '.join(sorted(MIGRATION_OPTION_METADATA))}",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Comma-separated migration option ids to skip. "
             f"Valid ids: {', '.join(sorted(MIGRATION_OPTION_METADATA))}",
    )
    parser.add_argument("--output-dir", help="Where to write report, backups, and archived docs")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print the migration report as JSON on stdout (redacted). "
             "Combine with no --execute for a safe plan-only machine-readable preview.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        selected_options = resolve_selected_options(args.include, args.exclude, preset=args.preset)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
        return 2
    migrator = Migrator(
        source_root=Path(os.path.expanduser(args.source)).resolve(),
        target_root=Path(os.path.expanduser(args.target)).resolve(),
        execute=bool(args.execute),
        workspace_target=Path(os.path.expanduser(args.workspace_target)).resolve() if args.workspace_target else None,
        overwrite=bool(args.overwrite),
        migrate_secrets=bool(args.migrate_secrets),
        output_dir=Path(os.path.expanduser(args.output_dir)).resolve() if args.output_dir else None,
        selected_options=selected_options,
        preset_name=args.preset or "",
        skill_conflict_mode=args.skill_conflict,
    )
    report = migrator.migrate()
    exit_code = 0 if report["summary"].get("error", 0) == 0 else 1

    # ── Machine-readable JSON mode ────────────────────────────
    # When --json is set, print the redacted report to stdout and skip the
    # human-readable terminal recap.  Useful for CI and scripted wrappers.
    if getattr(args, "json_output", False):
        print(json.dumps(redact_migration_value(report), indent=2, ensure_ascii=False))
        return exit_code

    # ── Human-readable terminal recap ─────────────────────────
    s = report["summary"]
    items = report["items"]
    mode_label = "DRY RUN" if not args.execute else "EXECUTED"
    total = sum(s.values())

    print()
    print(f"  ╔══════════════════════════════════════════════════════╗")
    print(f"  ║   OpenClaw -> Superforecasting Agent Migration   [{mode_label:>8s}]   ║")
    print(f"  ╠══════════════════════════════════════════════════════╣")
    print(f"  ║  Source:  {str(report['source_root'])[:42]:<42s}  ║")
    print(f"  ║  Target:  {str(report['target_root'])[:42]:<42s}  ║")
    print(f"  ╠══════════════════════════════════════════════════════╣")
    print(f"  ║  ✔ Migrated:  {s.get('migrated', 0):>3d}    ◆ Archived:  {s.get('archived', 0):>3d}        ║")
    print(f"  ║  ⊘ Skipped:   {s.get('skipped', 0):>3d}    ⚠ Conflicts: {s.get('conflict', 0):>3d}        ║")
    print(f"  ║  ✖ Errors:    {s.get('error', 0):>3d}    Total:       {total:>3d}        ║")
    print(f"  ╚══════════════════════════════════════════════════════╝")

    # Show what was migrated
    migrated = [i for i in items if i["status"] == "migrated"]
    if migrated:
        print()
        print("  Migrated:")
        seen_kinds = set()
        for item in migrated:
            label = item["kind"]
            if label in seen_kinds:
                continue
            seen_kinds.add(label)
            dest = item.get("destination") or ""
            if dest.startswith(str(report["target_root"])):
                dest = "~/.superforecasting-agent/" + dest[len(str(report["target_root"])) + 1:]
            meta = MIGRATION_OPTION_METADATA.get(label, {})
            display = meta.get("label", label)
            print(f"    ✔ {display:<35s} -> {dest}")

    # Show what was archived
    archived = [i for i in items if i["status"] == "archived"]
    if archived:
        print()
        print("  Archived (manual review needed):")
        seen_kinds = set()
        for item in archived:
            label = item["kind"]
            if label in seen_kinds:
                continue
            seen_kinds.add(label)
            reason = item.get("reason", "")
            meta = MIGRATION_OPTION_METADATA.get(label, {})
            display = meta.get("label", label)
            short_reason = reason[:50] + "..." if len(reason) > 50 else reason
            print(f"    ◆ {display:<35s}  {short_reason}")

    # Show conflicts
    conflicts = [i for i in items if i["status"] == "conflict"]
    if conflicts:
        print()
        print("  Conflicts (use --overwrite to force):")
        for item in conflicts:
            print(f"    ⚠ {item['kind']}: {item.get('reason', '')}")

    # Show errors
    errors = [i for i in items if i["status"] == "error"]
    if errors:
        print()
        print("  Errors:")
        for item in errors:
            print(f"    ✖ {item['kind']}: {item.get('reason', '')}")

    # PM2 reassurance
    print()
    print("  ℹ PM2 processes (Discord/Telegram bots) are NOT affected.")

    # Next steps
    if args.execute:
        print()
        print("  Next steps:")
        print("    1. Review ~/.superforecasting-agent/config.yaml")
        print("    2. Run: superforecasting-agent mcp list")
        if any(i["kind"] == "cron-jobs" and i["status"] == "archived" for i in items):
            print("    3. Recreate cron jobs: superforecasting-agent cron")
        if report.get("output_dir"):
            print(f"    → Full report: {report['output_dir']}/MIGRATION_NOTES.md")
    elif not args.execute:
        print()
        print("  This was a dry run. Add --execute to apply changes.")

    print()

    # Also dump JSON for programmatic use
    if os.environ.get("MIGRATION_JSON_OUTPUT"):
        print(json.dumps(redact_migration_value(report), indent=2, ensure_ascii=False))

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
