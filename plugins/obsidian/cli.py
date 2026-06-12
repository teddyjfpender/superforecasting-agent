"""CLI commands for the obsidian plugin.

Wires ``superforecasting-agent obsidian <subcommand>``:
  status  — show the resolved vault path and note counts
  sync    — publish ledger learnings (lessons, question dossiers, index)
  path    — print the resolved vault path (for scripting)
"""

from __future__ import annotations

import argparse
import json

from plugins.obsidian.vault import resolve_vault_path


def register_cli(subparser: argparse.ArgumentParser) -> None:
    """Build the ``superforecasting-agent obsidian`` argparse tree."""
    subs = subparser.add_subparsers(dest="obsidian_command")

    subs.add_parser("status", help="Show vault path and note counts")
    subs.add_parser("path", help="Print the resolved vault path")

    sync_p = subs.add_parser(
        "sync", help="Publish forecast lessons + question dossiers to the vault"
    )
    sync_p.add_argument(
        "--scope", choices=["all", "lessons", "questions"], default="all",
        help="What to publish (default: all)",
    )
    sync_p.add_argument(
        "--active-only", action="store_true",
        help="Only publish calibration lessons with status='active'",
    )
    sync_p.add_argument(
        "--question-status", default="active",
        help="Question status filter (default: active; pass 'any' for all)",
    )
    sync_p.add_argument("--limit", type=int, default=None, help="Cap items published")
    sync_p.add_argument("--db", default=None, help="Override forecast ledger DB path")
    sync_p.add_argument("--json", action="store_true", help="Print summary as JSON")


def obsidian_command(args: argparse.Namespace) -> int:
    cmd = getattr(args, "obsidian_command", None)
    vault = resolve_vault_path()

    if cmd == "path":
        if vault is None:
            print("no vault found — set OBSIDIAN_VAULT_PATH")
            return 1
        print(vault)
        return 0

    if cmd == "sync":
        if vault is None:
            print(
                "no Obsidian vault found — set OBSIDIAN_VAULT_PATH (e.g. in "
                "~/.superforecasting-agent/.env) or create ~/Documents/Obsidian Vault"
            )
            return 1
        from plugins.obsidian.sync import sync_learnings

        status = args.question_status
        summary = sync_learnings(
            vault,
            db=args.db,
            scope=args.scope,
            active_only=args.active_only,
            question_status=None if status in ("any", "all", "") else status,
            limit=args.limit,
        )
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(
                f"synced {summary['questions']} question dossier(s) and "
                f"{summary['lessons']} lesson(s) → {summary['vault']}"
            )
        return 0

    # default / "status"
    if vault is None:
        print("vault: not found (set OBSIDIAN_VAULT_PATH)")
        return 1
    notes = sum(1 for _ in vault.rglob("*.md"))
    forecasting = vault / "Forecasting"
    published = sum(1 for _ in forecasting.rglob("*.md")) if forecasting.is_dir() else 0
    print(f"vault: {vault}")
    print(f"notes: {notes} markdown file(s), {published} published by the forecast desk")
    return 0
