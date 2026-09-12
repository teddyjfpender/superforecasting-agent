"""Auth-store schema and durable file IO, with explicit profile paths.

Callers own the cross-process read/modify/write lock. This module does not select
profiles, resolve credentials, refresh tokens or invoke interactive login flows.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from superforecasting_agent.storage.credential_policy import sanitize_auth_store
from superforecasting_agent.storage.files import atomic_replace, owned_text_descriptor

logger = logging.getLogger(__name__)
AUTH_STORE_VERSION = 1


def load_auth_store(
    auth_file: Path, *, preserve_corrupt: bool = True
) -> dict[str, Any]:
    """Read a store; read-only fallback callers disable corruption backup writes."""
    if not auth_file.exists():
        return {"version": AUTH_STORE_VERSION, "providers": {}}

    try:
        raw = json.loads(auth_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(
            "auth: failed to parse %s (%s) — starting with empty store", auth_file, exc
        )
        if preserve_corrupt:
            corrupt_path = auth_file.with_suffix(".json.corrupt")
            try:
                import shutil

                shutil.copy2(auth_file, corrupt_path)
            except Exception as backup_error:
                logger.warning(
                    "auth: could not preserve corrupt store at %s: %s",
                    corrupt_path,
                    backup_error,
                )
            else:
                logger.warning("auth: corrupt file preserved at %s", corrupt_path)
        return {"version": AUTH_STORE_VERSION, "providers": {}}

    if isinstance(raw, dict) and (
        isinstance(raw.get("providers"), dict)
        or isinstance(raw.get("credential_pool"), dict)
    ):
        raw.setdefault("providers", {})
        return raw

    # Migrate from PR's "systems" format if present
    if isinstance(raw, dict) and isinstance(raw.get("systems"), dict):
        systems = raw["systems"]
        providers = {}
        if "nous_portal" in systems:
            providers["nous"] = systems["nous_portal"]
        return {
            "version": AUTH_STORE_VERSION,
            "providers": providers,
            "active_provider": "nous" if providers else None,
        }

    return {"version": AUTH_STORE_VERSION, "providers": {}}


def save_auth_store(auth_file: Path, auth_store: dict[str, Any]) -> Path:
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    # Tighten parent dir to 0o700 so siblings can't traverse to creds.
    # No-op on Windows (POSIX mode bits not enforced); ignore failures.
    try:
        os.chmod(auth_file.parent, 0o700)
    except OSError:
        pass
    auth_store["version"] = AUTH_STORE_VERSION
    auth_store["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(sanitize_auth_store(auth_store), indent=2) + "\n"
    tmp_path = auth_file.with_name(
        f"{auth_file.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )
    try:
        # Create with 0o600 atomically via os.open(O_EXCL) + fdopen to close
        # the TOCTOU window where default umask (often 0o644) briefly exposed
        # OAuth tokens to other local users between open() and chmod().
        # Mirrors agent/google_oauth.py (#19673) and tools/mcp_oauth.py (#21148).
        fd = os.open(
            str(tmp_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        with owned_text_descriptor(fd) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        atomic_replace(tmp_path, auth_file)
        try:
            dir_fd = os.open(str(auth_file.parent), os.O_RDONLY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
    # Restrict file permissions to owner only
    try:
        auth_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return auth_file


def provider_state(store: dict[str, Any], provider_id: str) -> dict[str, Any] | None:
    """Return the stored provider mapping; an empty mapping is still present."""
    providers = store.get("providers")
    if not isinstance(providers, dict):
        return None
    state = providers.get(provider_id)
    return dict(state) if isinstance(state, dict) else None


def set_provider_state(
    store: dict[str, Any],
    provider_id: str,
    state: dict[str, Any],
    *,
    set_active: bool = True,
) -> None:
    """Update a caller-owned store; the caller retains locking and publication."""
    providers = store.get("providers")
    if not isinstance(providers, dict):
        providers = store["providers"] = {}
    providers[provider_id] = state
    if set_active:
        store["active_provider"] = provider_id


def select_credential_pool(
    profile: dict[str, Any],
    fallback: dict[str, Any],
    provider_id: str | None = None,
) -> dict[str, Any] | list[Any]:
    """Select stored candidates with per-provider local shadowing.

    Nonempty local lists shadow global lists. Empty or malformed local slices
    allow global fallback. This preserves legacy records without granting them
    validity or refreshing/seeding a token. Returned records are independent of
    the supplied snapshots, including nested provider metadata.
    """
    from copy import deepcopy

    local = profile.get("credential_pool")
    local = local if isinstance(local, dict) else {}
    global_pool = fallback.get("credential_pool")
    global_pool = global_pool if isinstance(global_pool, dict) else {}
    if provider_id is not None:
        entries = local.get(provider_id)
        if not isinstance(entries, list) or not entries:
            entries = global_pool.get(provider_id)
        return deepcopy(entries) if isinstance(entries, list) else []

    merged = dict(local)
    for provider, entries in global_pool.items():
        if not isinstance(entries, list) or not entries:
            continue
        existing = merged.get(provider)
        if not isinstance(existing, list) or not existing:
            merged[provider] = entries
    return deepcopy(merged)
