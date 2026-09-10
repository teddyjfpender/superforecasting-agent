"""Envelope-encrypted private trace archives with audited retention."""

from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from superforecasting_agent.constants import get_agent_home

from forecasting.change_control.models import canonical_json, content_digest
from forecasting.change_control.provenance import ensure_bundle
from forecasting.models import LedgerNotFoundError, ValidationError, utc_now_iso


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - base install supplies PyJWT[crypto]
        raise RuntimeError("cryptography is required for private trace encryption") from exc
    return AESGCM


def parse_workspace_key(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        key = value
    else:
        raw = str(value or "").strip()
        try:
            key = bytes.fromhex(raw) if len(raw) == 64 else base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except (ValueError, TypeError) as exc:
            raise ValidationError("workspace trace key must be 32-byte hex or base64") from exc
    if len(key) != 32:
        raise ValidationError("workspace trace key must decode to exactly 32 bytes")
    return key


def workspace_key_from_env() -> bytes:
    value = os.environ.get("FORECAST_TRACE_ENCRYPTION_KEY", "")
    if not value:
        raise ValidationError("FORECAST_TRACE_ENCRYPTION_KEY is required")
    return parse_workspace_key(value)


def capture_trace_archive(
    ledger: Any,
    changeset_id: str,
    trace: Mapping[str, Any],
    *,
    workspace_key: bytes | str | None = None,
    key_version: str = "v1",
    retention_days: int = 90,
    authorization: Mapping[str, Any] | None = None,
    object_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Encrypt a trace locally and persist only ciphertext metadata in SQLite."""

    if retention_days < 0:
        raise ValidationError("retention_days must be non-negative")
    bundle = ensure_bundle(ledger, changeset_id)
    archive_id = f"trace_{uuid.uuid4().hex[:16]}"
    key = parse_workspace_key(workspace_key) if workspace_key is not None else workspace_key_from_env()
    data_key = os.urandom(32)
    data_nonce, wrap_nonce = os.urandom(12), os.urandom(12)
    aad = canonical_json(
        {
            "archive_id": archive_id,
            "bundle_id": bundle["id"],
            "changeset_id": changeset_id,
            "key_version": key_version,
        }
    ).encode()
    AESGCM = _aesgcm()
    plaintext = canonical_json(dict(trace)).encode("utf-8")
    envelope = {
        "version": 1,
        "algorithm": "AES-256-GCM",
        "key_version": key_version,
        "aad": base64.b64encode(aad).decode("ascii"),
        "data_nonce": base64.b64encode(data_nonce).decode("ascii"),
        "wrap_nonce": base64.b64encode(wrap_nonce).decode("ascii"),
        "wrapped_data_key": base64.b64encode(
            AESGCM(key).encrypt(wrap_nonce, data_key, aad)
        ).decode("ascii"),
        "ciphertext": base64.b64encode(
            AESGCM(data_key).encrypt(data_nonce, plaintext, aad)
        ).decode("ascii"),
    }
    ciphertext = canonical_json(envelope).encode("utf-8")
    directory = (
        Path(object_dir).expanduser()
        if object_dir is not None
        else get_agent_home() / "provenance" / "raw-traces"
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{archive_id}.trace.enc"
    path.write_bytes(ciphertext)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    now = datetime.now(timezone.utc)
    deadline = (now + timedelta(days=retention_days)).isoformat().replace("+00:00", "Z")
    with ledger._connect() as conn:
        conn.execute(
            """INSERT INTO provenance_trace_archives
               (id, bundle_id, object_locator, ciphertext_digest, byte_size,
                retention_deadline, key_version, authorization, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                archive_id,
                bundle["id"],
                str(path),
                content_digest(ciphertext.decode("utf-8")),
                len(ciphertext),
                deadline,
                key_version,
                json.dumps(dict(authorization or {}), sort_keys=True),
                utc_now_iso(),
            ),
        )
    return get_trace_archive(ledger, archive_id)


def get_trace_archive(ledger: Any, archive_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM provenance_trace_archives WHERE id = ?", (archive_id,)
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"trace archive not found: {archive_id}")
    result = dict(row)
    result["authorization"] = json.loads(result["authorization"])
    result["legal_hold"] = bool(result["legal_hold"])
    return result


def _access_event(
    ledger: Any,
    archive_id: str,
    *,
    actor_id: str,
    action: str,
    reason: str,
) -> None:
    with ledger._connect() as conn:
        conn.execute(
            """INSERT INTO provenance_access_events
               (id, archive_id, actor_id, action, reason, occurred_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                f"access_{uuid.uuid4().hex[:16]}",
                archive_id,
                actor_id,
                action,
                reason,
                utc_now_iso(),
            ),
        )


def read_trace_archive(
    ledger: Any,
    archive_id: str,
    *,
    actor_id: str,
    reason: str,
    authorize: Callable[[dict[str, Any], str], bool],
    workspace_key: bytes | str | None = None,
) -> dict[str, Any]:
    """Decrypt through an explicit authorization callback and audit every attempt."""

    record = get_trace_archive(ledger, archive_id)
    if record["state"] != "active":
        _access_event(
            ledger, archive_id, actor_id=actor_id, action="read_denied", reason="archive inactive"
        )
        raise ValidationError("trace archive is not active")
    if not actor_id or not reason:
        raise ValidationError("trace access requires actor_id and reason")
    if not authorize(record, actor_id):
        _access_event(
            ledger, archive_id, actor_id=actor_id, action="read_denied", reason=reason
        )
        raise PermissionError("trace archive access denied")
    ciphertext = Path(record["object_locator"]).read_bytes()
    if content_digest(ciphertext.decode("utf-8")) != record["ciphertext_digest"]:
        _access_event(
            ledger, archive_id, actor_id=actor_id, action="read_failed", reason="digest mismatch"
        )
        raise ValidationError("trace ciphertext digest mismatch")
    envelope = json.loads(ciphertext)
    aad = base64.b64decode(envelope["aad"])
    key = parse_workspace_key(workspace_key) if workspace_key is not None else workspace_key_from_env()
    AESGCM = _aesgcm()
    data_key = AESGCM(key).decrypt(
        base64.b64decode(envelope["wrap_nonce"]),
        base64.b64decode(envelope["wrapped_data_key"]),
        aad,
    )
    plaintext = AESGCM(data_key).decrypt(
        base64.b64decode(envelope["data_nonce"]),
        base64.b64decode(envelope["ciphertext"]),
        aad,
    )
    _access_event(ledger, archive_id, actor_id=actor_id, action="read", reason=reason)
    return json.loads(plaintext)


def pin_trace_archive(
    ledger: Any,
    archive_id: str,
    *,
    reason: str,
    expires_at: str | None = None,
    legal_hold: bool = False,
    administrator: bool = False,
) -> dict[str, Any]:
    if not reason.strip():
        raise ValidationError("pin reason is required")
    if expires_at is None and not (legal_hold and administrator):
        raise ValidationError("indefinite retention requires an administrator legal hold")
    get_trace_archive(ledger, archive_id)
    with ledger._connect() as conn:
        conn.execute(
            """UPDATE provenance_trace_archives
               SET pin_reason = ?, pin_expires_at = ?, legal_hold = ? WHERE id = ?""",
            (reason.strip(), expires_at, 1 if legal_hold else 0, archive_id),
        )
    return get_trace_archive(ledger, archive_id)


def sweep_expired_traces(ledger: Any, *, now: str | None = None) -> list[str]:
    cutoff = now or utc_now_iso()
    with ledger._connect() as conn:
        rows = conn.execute(
            """SELECT * FROM provenance_trace_archives
               WHERE state = 'active' AND retention_deadline <= ?
                 AND legal_hold = 0
                 AND (pin_expires_at IS NULL OR pin_expires_at <= ?)""",
            (cutoff, cutoff),
        ).fetchall()
    deleted: list[str] = []
    for row in rows:
        record = dict(row)
        path = Path(record["object_locator"])
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        deleted_at = utc_now_iso()
        with ledger._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO provenance_retention_tombstones
                   (archive_id, ciphertext_digest, reason, deleted_at)
                   VALUES (?, ?, 'retention_expired', ?)""",
                (record["id"], record["ciphertext_digest"], deleted_at),
            )
            conn.execute(
                """UPDATE provenance_trace_archives
                   SET state = 'deleted', deleted_at = ?
                   WHERE id = ? AND state = 'active'""",
                (deleted_at, record["id"]),
            )
        deleted.append(record["id"])
    return deleted


__all__ = [
    "capture_trace_archive",
    "get_trace_archive",
    "parse_workspace_key",
    "pin_trace_archive",
    "read_trace_archive",
    "sweep_expired_traces",
]
