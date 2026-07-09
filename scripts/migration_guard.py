#!/usr/bin/env python3
"""Upgrade migration guard — the red/green brain of ``scripts/upgrade.sh``.

An upgrade must never silently downgrade a box (installing an older binary over
a ledger a newer build already migrated) and must never skip a required schema
step (installing a build so new it cannot forward-migrate the ledger this box
carries). This module makes that decision as a *pure* function over three
version strings, so it is unit-testable red/green without a box, a network, or a
ledger:

    current           the SemVer currently installed here (from the
                      ``{home}/.release_version`` stamp the installer writes)
    new               the SemVer we are about to install
    min_migration     the release manifest's ``min_migration_version`` — the
                      OLDEST prior release whose on-disk ledger ``new`` opens +
                      forward-migrates

Decision rules (first match wins):

  1. bad input                         -> ERROR (exit 2)
  2. current unknown                   -> PROCEED, warn (can't detect a
                                          downgrade; forward migrations are
                                          additive so a backup-first proceed is
                                          the safe call)
  3. new  < current                    -> REFUSE downgrade (exit 3)
  4. current < min_migration           -> REFUSE below-min-migration (exit 3)
  5. otherwise (incl. reinstall)       -> PROCEED (exit 0)

CLI:
    migration_guard.py --current 0.18.0 --new 0.19.0 --min-migration 0.17.0
    migration_guard.py --current 0.18.0 --manifest release-manifest.json
    migration_guard.py --current 0.18.0 --manifest m.json --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

# Exit codes (also the shell contract for upgrade.sh).
EXIT_PROCEED = 0
EXIT_BAD_INPUT = 2
EXIT_REFUSE = 3

# Sentinels for an absent/unreadable current-version stamp.
_UNKNOWN = {"", "none", "null", "unknown", "unset"}


class GuardInputError(ValueError):
    """Raised when a version string is not strict SemVer."""


def parse_semver(value: str) -> tuple[int, int, int]:
    """Parse ``X.Y.Z`` into a comparable tuple; raise on anything else."""
    m = _SEMVER_RE.match((value or "").strip())
    if not m:
        raise GuardInputError(f"not strict SemVer X.Y.Z: {value!r}")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def cmp_semver(a: str, b: str) -> int:
    """Return -1/0/1 for ``a`` vs ``b`` (both strict SemVer)."""
    ta, tb = parse_semver(a), parse_semver(b)
    return (ta > tb) - (ta < tb)


def _is_unknown(current: str | None) -> bool:
    return current is None or str(current).strip().lower() in _UNKNOWN


@dataclass(frozen=True)
class Decision:
    """The guard's verdict. ``ok`` gates the upgrade; ``code`` names the branch."""

    ok: bool  # True -> proceed with the upgrade
    code: str  # ok | reinstall | unknown_current | downgrade | below_min_migration
    reason: str  # human-readable, safe to print
    warn: bool = False  # proceed, but loudly (backup-first)
    current: str | None = None
    new: str = ""
    min_migration: str = ""

    @property
    def exit_code(self) -> int:
        return EXIT_PROCEED if self.ok else EXIT_REFUSE


def evaluate(current: str | None, new: str, min_migration: str) -> Decision:
    """Pure upgrade decision. Raises :class:`GuardInputError` on bad new/min."""
    # new + min_migration MUST be valid SemVer — they come from the manifest.
    parse_semver(new)
    parse_semver(min_migration)

    base = {"current": current, "new": new, "min_migration": min_migration}

    if _is_unknown(current):
        return Decision(
            ok=True,
            code="unknown_current",
            warn=True,
            reason=(
                "no installed-version stamp found; cannot verify this is not a "
                f"downgrade. Proceeding to v{new} with a pre-upgrade backup. "
                "Forward migrations are additive, so this is safe; a downgrade "
                "would not be caught."
            ),
            **base,
        )

    # From here current is valid SemVer or raises (caller passed a garbage stamp).
    current_s = str(current).strip()
    parse_semver(current_s)

    if cmp_semver(new, current_s) < 0:
        return Decision(
            ok=False,
            code="downgrade",
            reason=(
                f"refusing to install v{new} over the newer v{current_s} already "
                "on this box. A newer build may have forward-migrated the ledger "
                f"past what v{new} understands; downgrading risks the ledger. "
                "Re-run with the same-or-newer release, or restore a backup first."
            ),
            **base,
        )

    if cmp_semver(current_s, min_migration) < 0:
        return Decision(
            ok=False,
            code="below_min_migration",
            reason=(
                f"v{new} cannot forward-migrate a ledger last touched by "
                f"v{current_s}: it requires at least v{min_migration}. Upgrade "
                f"through an intermediate release (>= v{min_migration}) first."
            ),
            **base,
        )

    if cmp_semver(new, current_s) == 0:
        return Decision(
            ok=True,
            code="reinstall",
            reason=f"re-installing v{new} (same version) — allowed (repair path).",
            **base,
        )

    return Decision(
        ok=True,
        code="ok",
        reason=f"upgrade v{current_s} -> v{new} is safe (>= min v{min_migration}).",
        **base,
    )


def _read_manifest(path: str | Path) -> tuple[str, str]:
    """Return ``(version, min_migration_version)`` from a release manifest file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    version = str(data.get("version", "")).strip()
    min_mig = str(data.get("min_migration_version", "")).strip()
    if not version or not min_mig:
        raise GuardInputError(
            f"manifest {path} missing version / min_migration_version"
        )
    return version, min_mig


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--current", default=None, help="installed SemVer (or omit if unknown)")
    ap.add_argument("--new", default=None, help="SemVer about to be installed")
    ap.add_argument("--min-migration", default=None, help="manifest min_migration_version")
    ap.add_argument("--manifest", default=None, help="read --new + --min-migration from a release manifest")
    ap.add_argument("--json", action="store_true", help="emit the decision as JSON")
    args = ap.parse_args(argv)

    new = args.new
    min_mig = args.min_migration
    if args.manifest:
        try:
            new, min_mig = _read_manifest(args.manifest)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"migration-guard: bad manifest: {exc}", file=sys.stderr)
            return EXIT_BAD_INPUT

    if not new or not min_mig:
        print(
            "migration-guard: need --new and --min-migration (or --manifest)",
            file=sys.stderr,
        )
        return EXIT_BAD_INPUT

    try:
        decision = evaluate(args.current, new, min_mig)
    except GuardInputError as exc:
        print(f"migration-guard: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT

    if args.json:
        print(json.dumps(asdict(decision), indent=2, sort_keys=True))
    else:
        verb = "PROCEED" if decision.ok else "REFUSE"
        marker = "!" if decision.warn else ("+" if decision.ok else "x")
        print(f"[{marker}] {verb} ({decision.code}): {decision.reason}")
    return decision.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
