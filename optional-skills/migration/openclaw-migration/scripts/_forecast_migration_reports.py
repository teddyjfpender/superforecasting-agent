"""Secret redaction and on-disk reports for standalone migration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


REDACTED_MIGRATION_VALUE = "[redacted]"

_SECRET_KEY_MARKERS = (
    "accesstoken",
    "apikey",
    "authorization",
    "bearertoken",
    "clientsecret",
    "cookie",
    "credential",
    "password",
    "privatekey",
    "refreshtoken",
    "secret",
)

_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=\-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{8,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{12,}\b"),
)


def _normalize_secret_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _is_secret_key(key: str) -> bool:
    normalized = _normalize_secret_key(key)
    if normalized == "token" or normalized.endswith("token"):
        return True
    if normalized in {"auth", "authorization"}:
        return True
    return any(marker in normalized for marker in _SECRET_KEY_MARKERS)


def _redact_string(value: str) -> str:
    for pattern in _SECRET_VALUE_PATTERNS:
        value = pattern.sub(REDACTED_MIGRATION_VALUE, value)
    return value


def redact_migration_value(value: Any) -> Any:
    """Return a deep copy of ``value`` with secret-looking content replaced.

    Applied to every report written to disk.  Keys whose normalized form
    matches a credential marker get their value replaced wholesale.  Strings
    anywhere in the tree are scanned for common token patterns (sk-..., ghp_...,
    xox*-, AIza*, Bearer ...) and those substrings are replaced inline.
    """
    return _redact_internal(value, set())


def _redact_internal(value: Any, seen: set) -> Any:
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, (list, tuple)):
        return [_redact_internal(entry, seen) for entry in value]
    if isinstance(value, dict):
        obj_id = id(value)
        if obj_id in seen:
            return REDACTED_MIGRATION_VALUE
        seen.add(obj_id)
        out: Dict[str, Any] = {}
        for key, entry in value.items():
            if isinstance(key, str) and _is_secret_key(key):
                out[key] = REDACTED_MIGRATION_VALUE
            else:
                out[key] = _redact_internal(entry, seen)
        return out
    return value


def write_report(output_dir: Path, report: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    # Always redact before persisting.  Callers who need the raw object
    # (in-process) still get it back from build_report(); only the on-disk
    # copy is redacted.
    redacted = redact_migration_value(report)
    (output_dir / "report.json").write_text(
        json.dumps(redacted, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in redacted["items"]:
        grouped.setdefault(item["status"], []).append(item)

    lines = [
        "# OpenClaw -> Superforecasting Agent Migration Report",
        "",
        f"- Timestamp: {redacted['timestamp']}",
        f"- Mode: {redacted['mode']}",
        f"- Source: `{redacted['source_root']}`",
        f"- Target: `{redacted['target_root']}`",
        "",
        "## Summary",
        "",
    ]

    for key, value in redacted["summary"].items():
        lines.append(f"- {key}: {value}")

    warnings = redacted.get("warnings") or []
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")

    lines.extend(["", "## What Was Not Fully Brought Over", ""])
    skipped = grouped.get("skipped", []) + grouped.get("conflict", []) + grouped.get("error", [])
    if not skipped:
        lines.append("- Nothing. All discovered items were either migrated or archived.")
    else:
        for item in skipped:
            source = item["source"] or "(n/a)"
            dest = item["destination"] or "(n/a)"
            reason = item["reason"] or item["status"]
            lines.append(f"- `{source}` -> `{dest}`: {reason}")

    next_steps = redacted.get("next_steps") or []
    if next_steps:
        lines.extend(["", "## Next Steps", ""])
        for step in next_steps:
            lines.append(f"- {step}")

    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")



from dataclasses import asdict
from _forecast_migration_options import MIGRATION_OPTION_METADATA, MIGRATION_PRESETS, STATUS_SKIPPED

def build_report(self) -> Dict[str, Any]:
    summary: Dict[str, int] = {
        "migrated": 0,
        "archived": 0,
        "skipped": 0,
        "conflict": 0,
        "error": 0,
    }
    for item in self.items:
        summary[item.status] = summary.get(item.status, 0) + 1

    report = {
        "timestamp": self.timestamp,
        "mode": "execute" if self.execute else "dry-run",
        "source_root": str(self.source_root),
        "target_root": str(self.target_root),
        "workspace_target": str(self.workspace_target) if self.workspace_target else None,
        "output_dir": str(self.output_dir) if self.output_dir else None,
        "migrate_secrets": self.migrate_secrets,
        "preset": self.preset_name or None,
        "skill_conflict_mode": self.skill_conflict_mode,
        "selection": {
            "selected": sorted(self.selected_options),
            "preset": self.preset_name or None,
            "skill_conflict_mode": self.skill_conflict_mode,
            "available": [
                {"id": option_id, **meta}
                for option_id, meta in MIGRATION_OPTION_METADATA.items()
            ],
            "presets": [
                {"id": preset_id, "selected": sorted(option_ids)}
                for preset_id, option_ids in MIGRATION_PRESETS.items()
            ],
        },
        "summary": summary,
        "items": [asdict(item) for item in self.items],
        "warnings": self._build_warnings(summary),
        "next_steps": self._build_next_steps(summary),
    }

    if self.output_dir:
        write_report(self.output_dir, report)

    return report


def _build_warnings(self, summary: Dict[str, int]) -> List[str]:
    """Structured warnings surfaced on the report for downstream consumers.

        Modelled on OpenClaw's extensions/migrate-hermes/plan.ts warnings[].
        Keep the messages actionable — they show up in summary.md and the
        JSON report.
        """
    warnings: List[str] = []
    if summary.get("conflict", 0) > 0:
        warnings.append(
            "Conflicts were found. Re-run with --overwrite to replace conflicting "
            "targets after item-level backups."
        )
    if summary.get("error", 0) > 0:
        warnings.append(
            "One or more items failed. Inspect the report and re-run after fixing "
            "the underlying cause."
        )
    if self._config_apply_blocked and self.execute:
        warnings.append(
            "A config.yaml write hit a conflict or error mid-apply; later config "
            "items were skipped to avoid a partial write."
        )
    # Detect whether secrets were detected but not migrated.
    provider_keys_skipped = any(
        item.kind == "provider-keys" and item.status == STATUS_SKIPPED
        for item in self.items
    )
    if provider_keys_skipped and not self.migrate_secrets:
        warnings.append(
            "API keys and other credentials were detected but not imported. "
            "Re-run with --migrate-secrets to copy supported keys into the "
            "Superforecasting Agent env file."
        )
    return warnings


def _build_next_steps(self, summary: Dict[str, int]) -> List[str]:
    """Human-readable next-step guidance baked into the report."""
    if not self.execute:
        return [
            "Re-run without --dry-run to apply the migration.",
            "Pass --overwrite to resolve conflicts, or --migrate-secrets to "
            "include API keys.",
        ]
    steps: List[str] = []
    if summary.get("migrated", 0) > 0:
        steps.append(
            "Review the migration report at "
            f"{self.output_dir}/summary.md"
            if self.output_dir
            else "Review the migration report."
        )
        steps.append(
            "Start a new Superforecasting Agent session (or /reset) to pick up the imported config."
        )
    if summary.get("conflict", 0) > 0:
        steps.append(
            "Re-run with --overwrite to apply items that were blocked by conflicts."
        )
    return steps


def generate_migration_notes(self) -> None:
    if not self.output_dir:
        return
    notes = [
        "# OpenClaw -> Superforecasting Agent Migration Notes",
        "",
        "This document lists items that require manual attention after migration.",
        "",
        "## PM2 / External Processes",
        "",
        "Your PM2 processes (Discord bots, Telegram bots, etc.) are NOT affected",
        "by this migration. They run independently and will continue working.",
        "No action needed for PM2-managed processes.",
        "",
    ]

    archived = [i for i in self.items if i.status == "archived"]
    if archived:
        notes.extend([
            "## Archived Items (Manual Review Needed)",
            "",
            "These OpenClaw configurations were archived because they don't have a",
            "direct 1:1 mapping in Superforecasting Agent. Review each file and recreate manually:",
            "",
        ])
        for item in archived:
            notes.append(f"- **{item.kind}**: `{item.destination}` -- {item.reason}")
        notes.append("")

    conflicts = [i for i in self.items if i.status == "conflict"]
    if conflicts:
        notes.extend([
            "## Conflicts (Existing Superforecasting Agent Config Not Overwritten)",
            "",
            "These items already existed in your Superforecasting Agent config. Re-run with",
            "`--overwrite` to force, or merge manually:",
            "",
        ])
        for item in conflicts:
            notes.append(f"- **{item.kind}**: {item.reason}")
        notes.append("")

    has_cron_config_archive = any(
        i.kind == "cron-jobs" and i.status == "archived" and i.destination and i.destination.endswith("cron-config.json")
        for i in self.items
    )
    has_cron_store_archive = any(
        i.kind == "cron-jobs" and i.status == "archived" and i.destination and i.destination.endswith("cron-store")
        for i in self.items
    )

    notes.extend([
        "## IMPORTANT: Archive the OpenClaw Directory",
        "",
        "After migration, your OpenClaw directory still exists on disk with workspace",
        "state files (todo.json, sessions, logs). If the Superforecasting Agent agent discovers these",
        "directories, it may read/write to them instead of the Superforecasting Agent state, causing",
        "confusion (e.g., cron jobs reading a different todo list than interactive sessions).",
        "",
        "**Strongly recommended:** Run `superforecasting-agent claw cleanup` to rename the OpenClaw",
        "directory to `.openclaw.pre-migration`. This prevents the agent from finding it.",
        "The directory is renamed, not deleted — you can undo this at any time.",
        "",
        "If you skip this step and notice the agent getting confused about workspaces",
        "or todo lists, run `superforecasting-agent claw cleanup` to fix it.",
        "",
        "## Superforecasting Agent-Specific Setup",
        "",
        "After migration, you may want to:",
        "- Run `superforecasting-agent claw cleanup` to archive the OpenClaw directory (prevents state confusion)",
        "- Run `superforecasting-agent setup` to configure any remaining settings",
        "- Run `superforecasting-agent mcp list` to verify MCP servers were imported correctly",
    ])

    if has_cron_config_archive:
        notes.append("- Run `superforecasting-agent cron` to recreate scheduled tasks (see archive/cron-config.json)")
    elif has_cron_store_archive:
        notes.append("- Run `superforecasting-agent cron` to recreate scheduled tasks (see archived cron-store)")

    # Check if skills were imported
    has_skills = any(i.kind == "skills" and i.status == "migrated" for i in self.items)
    if has_skills:
        notes.extend([
            "",
            "## Imported Skills",
            "",
            "Imported skills require a new session to take effect. After migration,",
            "restart your agent or start a new interactive session, then run `/skills`",
            "to verify they loaded correctly.",
            "",
        ])

    # Check if WhatsApp was detected
    has_whatsapp = any(i.kind == "whatsapp-settings" and i.status == "migrated" for i in self.items)
    if has_whatsapp:
        notes.extend([
            "",
            "## WhatsApp Requires Re-Pairing",
            "",
            "WhatsApp uses QR-code pairing, not token-based auth. Your allowlist",
            "was migrated, but you must re-pair the device by running:",
            "",
            "    superforecasting-agent whatsapp",
            "",
        ])

    notes.extend([
        "- Run `superforecasting-agent gateway install` if you need the gateway service",
        "- Review `~/.superforecasting-agent/config.yaml` for any adjustments",
        "",
    ])

    if self.execute:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "MIGRATION_NOTES.md").write_text(
            "\n".join(notes) + "\n", encoding="utf-8"
        )


def write_config_archive(destination: Path, config: Any) -> None:
    """Keep known credentials out of configuration archives, as in reports."""
    destination.write_text(
        json.dumps(redact_migration_value(config), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
