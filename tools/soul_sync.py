"""Keep the bundled SOUL.md persona template fresh in the agent home.

Mirrors ``skills_sync`` for the single ``SOUL.md`` file: it refreshes the soul
when the user has NOT customised it, and never clobbers a soul they have
edited. A one-line manifest (``.soul_manifest``) records the hash of the
template we last wrote, so we can tell "unchanged since we seeded it" (safe to
update) apart from "user-edited" (leave alone).

The forecasting *process* is code-owned and injected as the ephemeral system
prompt (see forecasting/protocol.py), so it already ships with every code
update. This sync only keeps the *persona* template current for un-edited
souls; a customised SOUL.md is always preserved.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from hermes_constants import get_hermes_home
from utils import atomic_replace

logger = logging.getLogger(__name__)


def _hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def sync_soul(quiet: bool = False) -> dict:
    """Refresh an un-edited SOUL.md to the current template; preserve edits.

    Returns a small status dict ({"action": ...}). Best-effort: any failure is
    logged and swallowed so a soul-sync hiccup never blocks launch.
    """

    try:
        from hermes_cli.default_soul import DEFAULT_SOUL_MD
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("soul sync skipped: cannot import template: %s", exc)
        return {"action": "skipped", "reason": "no_template"}

    try:
        home = get_hermes_home()
        soul_path = home / "SOUL.md"
        manifest_path = home / ".soul_manifest"
        template = DEFAULT_SOUL_MD
        template_hash = _hash(template)

        if not soul_path.exists():
            home.mkdir(parents=True, exist_ok=True)
            soul_path.write_text(template, encoding="utf-8")
            manifest_path.write_text(template_hash, encoding="utf-8")
            return {"action": "seeded"}

        current_hash = _hash(soul_path.read_text(encoding="utf-8", errors="replace"))
        recorded = manifest_path.read_text(encoding="utf-8").strip() if manifest_path.exists() else ""

        if current_hash == template_hash:
            # Already current — make sure the manifest records it so a later
            # template change is detected as updatable rather than user-edited.
            if recorded != template_hash:
                manifest_path.write_text(template_hash, encoding="utf-8")
            return {"action": "up_to_date"}

        if recorded and current_hash == recorded:
            # Untouched since we last wrote it, and the template moved on → update.
            tmp = soul_path.with_suffix(".md.tmp")
            tmp.write_text(template, encoding="utf-8")
            atomic_replace(str(tmp), str(soul_path))
            manifest_path.write_text(template_hash, encoding="utf-8")
            if not quiet:
                logger.info("Refreshed SOUL.md to the current persona template")
            return {"action": "updated"}

        # No manifest (legacy seed) or the soul differs from what we recorded →
        # treat as user-owned and leave it alone. Never clobber a custom soul.
        return {"action": "preserved_user_soul"}
    except Exception as exc:  # pragma: no cover — best-effort
        logger.debug("soul sync failed: %s", exc, exc_info=True)
        return {"action": "error", "reason": str(exc)}


__all__ = ["sync_soul"]
