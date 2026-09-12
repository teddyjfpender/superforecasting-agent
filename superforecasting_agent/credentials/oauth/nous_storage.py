"""Nous storage operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def _nous_shared_auth_dir() -> _core.Path:
    """Resolve the directory that holds the shared Nous token store.

    Honors ``HERMES_SHARED_AUTH_DIR`` so tests can redirect it to a tmp
    path without touching the real user's home. Defaults to
    ``<hermes-root>/shared/``, where ``<hermes-root>`` is what
    :func:`superforecasting_agent.constants.get_default_agent_root` returns — so
    Linux/macOS classic installs land at ``~/.hermes/shared/``, native
    Windows installs at ``%LOCALAPPDATA%\\hermes\\shared\\``, and
    Docker / custom ``HERMES_HOME`` deployments at
    ``<HERMES_HOME>/shared/``. Sits outside any named profile so all
    profiles under the same root share the store.
    """
    override = _core.os.getenv("HERMES_SHARED_AUTH_DIR", "").strip()
    if override:
        return _core.Path(override).expanduser()
    from superforecasting_agent.constants import get_default_agent_root

    return get_default_agent_root() / "shared"


def _nous_shared_store_path() -> _core.Path:
    path = _core._nous_shared_auth_dir() / _core.NOUS_SHARED_STORE_FILENAME
    # Seat belt: if pytest is running and this resolves to a path under the
    # real user's Hermes root, refuse rather than silently corrupt cross-profile
    # state. Tests must set HERMES_SHARED_AUTH_DIR to a tmp_path (conftest
    # does not do this automatically — mirror the _auth_file_path() guard
    # so forgetting to set it fails loudly instead of writing to the real
    # shared store).
    if _core.os.environ.get("PYTEST_CURRENT_TEST"):
        from superforecasting_agent.constants import get_default_agent_root

        real_home_shared = (
            get_default_agent_root() / "shared" / _core.NOUS_SHARED_STORE_FILENAME
        ).resolve(strict=False)
        try:
            resolved = path.resolve(strict=False)
        except Exception:
            resolved = path
        if resolved == real_home_shared:
            raise RuntimeError(
                f"Refusing to touch real user shared Nous auth store during test run: "
                f"{path}. Set HERMES_SHARED_AUTH_DIR to a tmp_path in your test fixture."
            )
    return path


@_core.contextmanager
def _nous_shared_store_lock(timeout_seconds: float = _core.AUTH_LOCK_TIMEOUT_SECONDS):
    """Cross-profile lock for the shared Nous OAuth store.

    Lock ordering invariant: if both this and ``_auth_store_lock`` need
    to be held, acquire ``_auth_store_lock`` FIRST. All runtime refresh
    paths follow this order. The one exception is
    ``_try_import_shared_nous_state``, which holds this lock alone for
    the entire refresh+mint cycle so concurrent imports on sibling
    profiles can't race on the single-use shared refresh token; that
    helper must NOT be called with ``_auth_store_lock`` already held.
    """
    try:
        lock_path = _core._nous_shared_store_path().with_suffix(".lock")
    except RuntimeError:
        # No HERMES_HOME yet (pre-setup): fall through without locking.
        yield
        return

    with _core._file_lock(
        lock_path,
        _core._nous_shared_lock_holder,
        timeout_seconds,
        "Timed out waiting for shared Nous auth lock",
    ):
        yield


def _merge_shared_nous_oauth_state(state: _core.Dict[str, _core.Any]) -> bool:
    """Copy fresher shared OAuth tokens into a profile-local Nous state."""
    shared = _core._read_shared_nous_state()
    if not shared:
        return False

    shared_refresh = shared.get("refresh_token")
    if not isinstance(shared_refresh, str) or not shared_refresh.strip():
        return False

    local_refresh = state.get("refresh_token")
    shared_access_exp = _core._parse_iso_timestamp(shared.get("expires_at")) or 0.0
    local_access_exp = _core._parse_iso_timestamp(state.get("expires_at")) or 0.0
    refresh_changed = shared_refresh.strip() != str(local_refresh or "").strip()
    fresher_access = shared_access_exp > local_access_exp
    if not refresh_changed and not fresher_access:
        return False

    for key in (
        "access_token",
        "refresh_token",
        "token_type",
        "scope",
        "client_id",
        "portal_base_url",
        "inference_base_url",
        "obtained_at",
        "expires_at",
    ):
        value = shared.get(key)
        if value not in {None, ""}:
            state[key] = value
    return True


def _write_shared_nous_state(state: _core.Dict[str, _core.Any]) -> None:
    """Persist a minimal copy of the Nous OAuth state to the shared store.

    Best-effort: any failure is swallowed after logging. The shared store
    is a convenience layer; the per-profile auth.json remains the source
    of truth.

    We deliberately omit the runtime ``agent_key`` compatibility field
    (either an invoke JWT or legacy opaque session key) — only OAuth tokens
    are cross-profile useful.
    """
    refresh_token = state.get("refresh_token")
    access_token = state.get("access_token")
    if not (isinstance(refresh_token, str) and refresh_token.strip()):
        # No refresh_token = nothing worth sharing across profiles
        return
    if not (isinstance(access_token, str) and access_token.strip()):
        return

    shared = {
        "_schema": 1,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": state.get("token_type") or "Bearer",
        "scope": state.get("scope") or _core.DEFAULT_NOUS_SCOPE,
        "client_id": state.get("client_id") or _core.DEFAULT_NOUS_CLIENT_ID,
        "portal_base_url": state.get("portal_base_url")
        or _core.DEFAULT_NOUS_PORTAL_URL,
        "inference_base_url": state.get("inference_base_url")
        or _core.DEFAULT_NOUS_INFERENCE_URL,
        "obtained_at": state.get("obtained_at"),
        "expires_at": state.get("expires_at"),
        "updated_at": _core.datetime.now(_core.timezone.utc).isoformat(),
    }
    try:
        with _core._nous_shared_store_lock():
            path = _core._nous_shared_store_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                _core.os.chmod(path.parent, 0o700)
            except OSError:
                pass
            tmp = path.with_name(
                f"{path.name}.tmp.{_core.os.getpid()}.{_core.uuid.uuid4().hex}"
            )
            # Create with 0o600 atomically via os.open(O_EXCL) — closes the TOCTOU
            # window where write_text() + post-write chmod briefly exposed Nous
            # refresh_token at process umask. See #19673, #21148.
            fd = _core.os.open(
                str(tmp),
                _core.os.O_WRONLY | _core.os.O_CREAT | _core.os.O_EXCL,
                _core.stat.S_IRUSR | _core.stat.S_IWUSR,
            )
            try:
                with _core.owned_text_descriptor(fd) as fh:
                    fh.write(_core.json.dumps(shared, indent=2, sort_keys=True))
                    fh.flush()
                    _core.os.fsync(fh.fileno())
                _core.os.replace(tmp, path)
            finally:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
        _core._oauth_trace(
            "nous_shared_store_written",
            path=str(path),
            refresh_token_fp=_core._token_fingerprint(refresh_token),
        )
    except Exception as exc:
        _core.logger.debug("Failed to write shared Nous auth store: %s", exc)


def _read_shared_nous_state() -> _core.Optional[_core.Dict[str, _core.Any]]:
    """Return the shared Nous OAuth state if present and well-formed.

    Returns ``None`` when the file is missing, unreadable, malformed, or
    lacks required fields. Callers should treat ``None`` as "no shared
    credentials available — fall through to device-code".
    """
    try:
        path = _core._nous_shared_store_path()
    except RuntimeError:
        # Test seat belt tripped — treat as missing
        return None
    if not path.is_file():
        return None
    try:
        payload = _core.json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        _core.logger.debug("Shared Nous auth store at %s is unreadable: %s", path, exc)
        return None
    if not isinstance(payload, dict):
        return None
    refresh_token = payload.get("refresh_token")
    access_token = payload.get("access_token")
    if not (isinstance(refresh_token, str) and refresh_token.strip()):
        return None
    if not (isinstance(access_token, str) and access_token.strip()):
        return None
    return payload


def _clear_shared_nous_state(reason: str) -> None:
    """Remove the shared Nous OAuth store after a terminal token failure."""
    try:
        with _core._nous_shared_store_lock():
            path = _core._nous_shared_store_path()
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        _core._oauth_trace("nous_shared_store_cleared", reason=reason)
    except Exception as exc:
        _core.logger.debug("Failed to clear shared Nous auth store: %s", exc)


def _is_terminal_nous_refresh_error(exc: Exception) -> bool:
    """True when retrying the same Nous refresh token cannot succeed."""
    return (
        isinstance(exc, _core.AuthError)
        and exc.provider == "nous"
        and exc.code in {"invalid_grant", "invalid_token", "refresh_token_reused"}
        and bool(exc.relogin_required)
    )


def _quarantine_nous_oauth_state(
    state: _core.Dict[str, _core.Any],
    error: _core.AuthError,
    *,
    reason: str,
) -> None:
    """Keep routing metadata but remove dead OAuth material so it is not replayed."""
    for key in (
        "access_token",
        "refresh_token",
        "expires_at",
        "expires_in",
        "obtained_at",
        "agent_key",
        "agent_key_id",
        "agent_key_expires_at",
        "agent_key_expires_in",
        "agent_key_reused",
        "agent_key_obtained_at",
    ):
        state.pop(key, None)
    state["last_auth_error"] = {
        "provider": "nous",
        "code": error.code,
        "message": str(error),
        "reason": reason,
        "relogin_required": True,
        "at": _core.datetime.now(_core.timezone.utc).isoformat(),
    }
    _core._clear_shared_nous_state(reason)
    _core.invalidate_nous_auth_status_cache()


def _quarantine_nous_pool_entries(
    auth_store: _core.Dict[str, _core.Any],
    error: _core.AuthError,
    *,
    reason: str,
) -> bool:
    """Remove singleton-seeded Nous pool entries that contain dead OAuth state."""
    pool = auth_store.get("credential_pool")
    if not isinstance(pool, dict):
        return False
    entries = pool.get("nous")
    if not isinstance(entries, list):
        return False

    retained = []
    removed = False
    singleton_sources = {
        _core.NOUS_DEVICE_CODE_SOURCE,
        f"manual:{_core.NOUS_DEVICE_CODE_SOURCE}",
    }
    for entry in entries:
        if isinstance(entry, dict) and entry.get("source") in singleton_sources:
            removed = True
            continue
        retained.append(entry)

    if removed:
        pool["nous"] = retained
        _core._oauth_trace(
            "nous_pool_device_code_quarantined",
            reason=reason,
            error_code=error.code,
        )
    return removed


def _try_import_shared_nous_state(
    *,
    timeout_seconds: float = 15.0,
    min_key_ttl_seconds: int = 5 * 60,
) -> _core.Optional[_core.Dict[str, _core.Any]]:
    """Attempt to rehydrate Nous OAuth state from the shared store.

    Reads the shared file (if present), runs a forced refresh+mint using
    the stored refresh_token to produce a fresh access_token + agent_key
    scoped to this profile, and returns the full auth_state dict ready
    for ``persist_nous_credentials()``.

    Returns ``None`` when no shared state is available or the rehydrate
    fails for any reason (expired refresh_token, portal unreachable,
    etc.) — caller should then fall through to the normal device-code
    flow.
    """
    try:
        with _core._nous_shared_store_lock(
            timeout_seconds=max(timeout_seconds + 5.0, _core.AUTH_LOCK_TIMEOUT_SECONDS)
        ):
            shared = _core._read_shared_nous_state()
            if not shared:
                return None

            # Build a full state dict so refresh_nous_oauth_from_state has every
            # field it needs. force_refresh=True gets us a fresh access_token
            # for this profile; fresh auth mode avoids stale cached legacy keys.
            state: _core.Dict[str, _core.Any] = {
                "access_token": shared.get("access_token"),
                "refresh_token": shared.get("refresh_token"),
                "client_id": shared.get("client_id") or _core.DEFAULT_NOUS_CLIENT_ID,
                "portal_base_url": shared.get("portal_base_url")
                or _core.DEFAULT_NOUS_PORTAL_URL,
                "inference_base_url": shared.get("inference_base_url")
                or _core.DEFAULT_NOUS_INFERENCE_URL,
                "token_type": shared.get("token_type") or "Bearer",
                "scope": shared.get("scope") or _core.DEFAULT_NOUS_SCOPE,
                "obtained_at": shared.get("obtained_at"),
                "expires_at": shared.get("expires_at"),
                "agent_key": None,
                "agent_key_expires_at": None,
                "tls": {"insecure": False, "ca_bundle": None},
            }

            def _persist_shared_refresh(
                updated_state: _core.Dict[str, _core.Any], _reason: str
            ) -> None:
                _core._write_shared_nous_state(updated_state)

            refreshed = _core.refresh_nous_oauth_from_state(
                state,
                min_key_ttl_seconds=min_key_ttl_seconds,
                timeout_seconds=timeout_seconds,
                force_refresh=True,
                inference_auth_mode=_core.NOUS_INFERENCE_AUTH_MODE_FRESH,
                on_state_update=_persist_shared_refresh,
            )
            _core._write_shared_nous_state(refreshed)
    except _core.AuthError as exc:
        _core._oauth_trace(
            "nous_shared_import_failed",
            error_type=type(exc).__name__,
            error_code=getattr(exc, "code", None),
        )
        if _core._is_terminal_nous_refresh_error(exc):
            _core._clear_shared_nous_state("shared_import_terminal_refresh_failure")
        _core.logger.debug("Shared Nous import failed: %s", exc)
        return None
    except Exception as exc:
        _core._oauth_trace(
            "nous_shared_import_failed",
            error_type=type(exc).__name__,
        )
        _core.logger.debug("Shared Nous import failed: %s", exc)
        return None

    return refreshed
