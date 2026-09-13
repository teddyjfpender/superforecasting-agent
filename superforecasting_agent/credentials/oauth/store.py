"""Store operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def _auth_file_path() -> _core.Path:
    path = _core.get_agent_home() / "auth.json"
    # Seat belt: if pytest is running and HERMES_HOME resolves to the real
    # user's auth store, refuse rather than silently corrupt it. This catches
    # tests that forgot to monkeypatch HERMES_HOME, tests invoked without the
    # hermetic conftest, or sandbox escapes via threads/subprocesses. In
    # production (no PYTEST_CURRENT_TEST) this is a single dict lookup.
    if _core.os.environ.get("PYTEST_CURRENT_TEST"):
        real_home_auth = {
            (_core.Path.home() / home / "auth.json").resolve(strict=False)
            for home in (".superforecasting-agent", ".hermes")
        }
        try:
            resolved = path.resolve(strict=False)
        except Exception:
            resolved = path
        if resolved in real_home_auth:
            raise RuntimeError(
                f"Refusing to touch real user auth store during test run: {path}. "
                "Set HERMES_HOME to a tmp_path in your test fixture, or run "
                "via scripts/run_tests.sh for hermetic CI-parity env."
            )
    return path


def _global_auth_file_path() -> _core.Optional[_core.Path]:
    """Return the global-root auth.json when the process is in profile mode.

    Returns ``None`` when the profile and global root resolve to the same
    directory (classic mode, or custom HERMES_HOME that is not a profile).
    Used by read-only fallback paths so providers authed at the root are
    visible to profile processes that haven't configured them locally.

    See issue #18594 follow-up (credential_pool shadowing).
    """
    try:
        from superforecasting_agent.constants import get_default_agent_root

        global_root = get_default_agent_root()
    except Exception:
        return None
    profile_home = _core.get_agent_home()
    try:
        if profile_home.resolve(strict=False) == global_root.resolve(strict=False):
            return None
    except Exception:
        if profile_home == global_root:
            return None
    # No pytest seat belt here: this is a pure read-only path, and
    # ``_load_global_auth_store()`` wraps the read in a try/except so an
    # unreadable global file can never break the profile process.  The
    # write-side seat belt still lives on ``_auth_file_path()`` where it
    # belongs (that's what protects the real user's auth store from being
    # corrupted by a mis-configured test).
    return global_root / "auth.json"


def _load_global_auth_store() -> _core.Dict[str, _core.Any]:
    """Load the global-root auth store (read-only fallback).

    Returns an empty dict when no global fallback exists (classic mode,
    or the global auth.json is absent). Never raises on missing file.

    Seat belt: under pytest, refuses to read the real user's
    ``~/.hermes/auth.json`` even when HERMES_HOME is set to a profile
    path. The hermetic conftest does not redirect ``HOME``, so
    ``get_default_agent_root()`` for a profile-shaped HERMES_HOME can
    still resolve to the real user's home on a dev machine. That would
    leak real credentials into tests. This guard uses the unmodified
    ``HOME`` env var (what ``os.path.expanduser('~')`` would resolve to),
    not ``Path.home()``, because ``Path.home`` is sometimes monkeypatched
    by fixtures that want to relocate the global root to a tmp path.
    """
    global_path = _core._global_auth_file_path()
    if global_path is None or not global_path.exists():
        return {}
    if _core.os.environ.get("PYTEST_CURRENT_TEST"):
        real_home_env = _core.os.environ.get("HOME", "")
        if real_home_env:
            real_roots = {
                (_core.Path(real_home_env) / home / "auth.json").resolve(strict=False)
                for home in (".superforecasting-agent", ".hermes")
            }
            try:
                if global_path.resolve(strict=False) in real_roots:
                    return {}
            except Exception:
                pass
    try:
        from superforecasting_agent.storage.auth import load_auth_store

        return load_auth_store(global_path, preserve_corrupt=False)
    except Exception:
        # A malformed global store must not break profile reads. The
        # profile's own auth store is still authoritative.
        return {}


def _auth_lock_path() -> _core.Path:
    return _core._auth_file_path().with_suffix(".lock")


@_core.contextmanager
def _file_lock(lock_path, holder, timeout_seconds, timeout_message):
    from superforecasting_agent.storage.locking import file_lock

    with file_lock(
        lock_path,
        holder,
        timeout_seconds,
        timeout_message,
        posix=_core.fcntl,
        windows=_core.msvcrt,
    ):
        yield


@_core.contextmanager
def _auth_store_lock(timeout_seconds: float = _core.AUTH_LOCK_TIMEOUT_SECONDS):
    """Cross-process advisory lock for auth.json reads+writes.  Reentrant.

    Lock ordering invariant: when this lock is held together with
    ``_nous_shared_store_lock``, acquire ``_auth_store_lock`` FIRST
    (outer) and the shared Nous lock SECOND (inner). All runtime
    refresh paths follow this order; violating it risks deadlock
    against a concurrent import on the shared store.
    """
    from superforecasting_agent.storage.profile_lease import ProfileLease

    with (
        ProfileLease(_core._auth_file_path().parent),
        _core._file_lock(
            _core._auth_lock_path(),
            _core._auth_lock_holder,
            timeout_seconds,
            "Timed out waiting for auth store lock",
        ),
    ):
        yield


def _load_auth_store(
    auth_file: _core.Optional[_core.Path] = None,
) -> _core.Dict[str, _core.Any]:
    from superforecasting_agent.storage.auth import load_auth_store

    return load_auth_store(auth_file or _core._auth_file_path())


def _save_auth_store(auth_store: _core.Dict[str, _core.Any]) -> _core.Path:
    from superforecasting_agent.storage.auth import save_auth_store

    return save_auth_store(_core._auth_file_path(), auth_store)


def _load_provider_state(
    auth_store: _core.Dict[str, _core.Any], provider_id: str
) -> _core.Optional[_core.Dict[str, _core.Any]]:
    from superforecasting_agent.storage.auth import provider_state

    return provider_state(auth_store, provider_id)


def _save_provider_state(
    auth_store: _core.Dict[str, _core.Any],
    provider_id: str,
    state: _core.Dict[str, _core.Any],
) -> None:
    _core._store_provider_state(auth_store, provider_id, state)


def _store_provider_state(
    auth_store: _core.Dict[str, _core.Any],
    provider_id: str,
    state: _core.Dict[str, _core.Any],
    *,
    set_active: bool = True,
) -> None:
    from superforecasting_agent.storage.auth import set_provider_state

    set_provider_state(auth_store, provider_id, state, set_active=set_active)


def mark_provider_active_if_unset(provider_id: str) -> None:
    """Set ``active_provider`` to *provider_id* only when none is set yet.

    Used by ``auth add`` OAuth paths that create credential-pool
    entries directly (no singleton ``providers.<id>`` block). Adding the
    very first credential for a provider should make it the active provider
    so the setup wizard's ``_model_section_has_credentials()`` check (which
    consults ``get_active_provider()``) does not report "No inference
    provider configured". Subsequent adds for an already-active setup leave
    the user's chosen active provider untouched.
    """
    with _core._auth_store_lock():
        auth_store = _core._load_auth_store()
        if not (auth_store.get("active_provider") or "").strip():
            auth_store["active_provider"] = provider_id
            _core._save_auth_store(auth_store)


def is_known_auth_provider(provider_id: str) -> bool:
    normalized = (provider_id or "").strip().lower()
    return (
        normalized in _core.PROVIDER_REGISTRY
        or normalized in _core.SERVICE_PROVIDER_NAMES
    )


def get_auth_provider_display_name(provider_id: str) -> str:
    normalized = (provider_id or "").strip().lower()
    if normalized in _core.PROVIDER_REGISTRY:
        return _core.PROVIDER_REGISTRY[normalized].name
    return _core.SERVICE_PROVIDER_NAMES.get(normalized, provider_id)


def read_credential_pool(
    provider_id: _core.Optional[str] = None,
) -> _core.Dict[str, _core.Any] | _core.List[_core.Any]:
    """Return the persisted credential pool, or one provider slice.

    In profile mode, the profile's credential pool is authoritative. If a
    provider has no entries in the profile, entries from the global-root
    ``auth.json`` are used as a read-only fallback — so workers spawned in a
    profile can see providers that were only authenticated at global scope.

    Profile entries always win: the global fallback only applies per-provider
    when the profile has zero entries for that provider. Once the user runs
    ``superforecasting-agent auth add <provider>`` inside the profile, profile
    entries fully shadow global for that provider on the next read.

    Writes always go to the profile (``write_credential_pool`` is unchanged).
    See issue #18594 follow-up.
    """
    from superforecasting_agent.storage.auth import select_credential_pool

    return select_credential_pool(
        _core._load_auth_store(), _core._load_global_auth_store(), provider_id
    )


def write_credential_pool(
    provider_id: str, entries: _core.List[_core.Dict[str, _core.Any]]
) -> _core.Path:
    """Persist one provider's credential pool under auth.json.

    This is the final disk-boundary guard for borrowed/reference-only
    credentials. Callers may pass raw dictionaries, so sanitize here even when
    ``PooledCredential.to_dict()`` already did the same work upstream.
    """
    with _core._auth_store_lock():
        auth_store = _core._load_auth_store()
        pool = auth_store.get("credential_pool")
        if not isinstance(pool, dict):
            pool = {}
            auth_store["credential_pool"] = pool
        pool[provider_id] = [
            _core.sanitize_borrowed_credential_payload(entry, provider_id)
            if isinstance(entry, dict)
            else entry
            for entry in entries
        ]
        return _core._save_auth_store(auth_store)


def suppress_credential_source(provider_id: str, source: str) -> None:
    """Mark a credential source as suppressed so it won't be re-seeded."""
    with _core._auth_store_lock():
        auth_store = _core._load_auth_store()
        suppressed = auth_store.setdefault("suppressed_sources", {})
        provider_list = suppressed.setdefault(provider_id, [])
        if source not in provider_list:
            provider_list.append(source)
        _core._save_auth_store(auth_store)


def is_source_suppressed(provider_id: str, source: str) -> bool:
    """Check if a credential source has been suppressed by the user."""
    try:
        auth_store = _core._load_auth_store()
        suppressed = auth_store.get("suppressed_sources", {})
        return source in suppressed.get(provider_id, [])
    except Exception:
        return False


def unsuppress_credential_source(provider_id: str, source: str) -> bool:
    """Clear a suppression marker so the source will be re-seeded on the next load.

    Returns True if a marker was cleared, False if no marker existed.
    """
    with _core._auth_store_lock():
        auth_store = _core._load_auth_store()
        suppressed = auth_store.get("suppressed_sources")
        if not isinstance(suppressed, dict):
            return False
        provider_list = suppressed.get(provider_id)
        if not isinstance(provider_list, list) or source not in provider_list:
            return False
        provider_list.remove(source)
        if not provider_list:
            suppressed.pop(provider_id, None)
        if not suppressed:
            auth_store.pop("suppressed_sources", None)
        _core._save_auth_store(auth_store)
        return True


def get_provider_auth_state(
    provider_id: str,
) -> _core.Optional[_core.Dict[str, _core.Any]]:
    """Return persisted auth state for a provider, or None.

    In profile mode, falls back to the global-root ``auth.json`` when the
    profile has no state for this provider. Profile state always wins when
    present. Writes (``_save_auth_store`` / ``persist_*_credentials``) are
    unchanged — they still target the profile only. This mirrors
    ``read_credential_pool``'s per-provider shadowing semantics so that
    ``_seed_from_singletons`` can reseed a profile's credential pool from
    global-scope provider state (e.g. a globally-authenticated Anthropic
    OAuth or Nous device-code session). See issue #18594 follow-up.
    """
    auth_store = _core._load_auth_store()
    state = _core._load_provider_state(auth_store, provider_id)
    if state is not None:
        return state
    global_store = _core._load_global_auth_store()
    if not global_store:
        return None
    return _core._load_provider_state(global_store, provider_id)


def get_active_provider() -> _core.Optional[str]:
    """Return the currently active provider ID from auth store."""
    auth_store = _core._load_auth_store()
    return auth_store.get("active_provider")


def is_provider_explicitly_configured(provider_id: str) -> bool:
    """Return True only if the user has explicitly configured this provider.

    Checks:
      1. active_provider in auth.json matches
      2. model.provider in config.yaml matches
      3. Provider-specific env vars are set (e.g. ANTHROPIC_API_KEY)

    This is used to gate auto-discovery of external credentials (e.g.
    Claude Code's ~/.claude/.credentials.json) so they are never used
    without the user's explicit choice.  See PR #4210 for the same
    pattern applied to the setup wizard gate.
    """
    normalized = (provider_id or "").strip().lower()

    # 1. Check auth.json active_provider
    try:
        auth_store = _core._load_auth_store()
        active = (auth_store.get("active_provider") or "").strip().lower()
        if active and active == normalized:
            return True
    except Exception:
        pass

    # 2. Check config.yaml model.provider
    try:
        from superforecasting_agent.credentials.environment import load_config

        cfg = load_config()
        model_cfg = cfg.get("model")
        if isinstance(model_cfg, dict):
            cfg_provider = (model_cfg.get("provider") or "").strip().lower()
            if cfg_provider == normalized:
                return True
    except Exception:
        pass

    # 3. Check provider-specific env vars
    # Exclude CLAUDE_CODE_OAUTH_TOKEN — it's set by Claude Code itself,
    # not by the user explicitly configuring anthropic in Hermes.
    _IMPLICIT_ENV_VARS = {"CLAUDE_CODE_OAUTH_TOKEN"}
    pconfig = _core.PROVIDER_REGISTRY.get(normalized)
    if pconfig and pconfig.auth_type == "api_key":
        for env_var in pconfig.api_key_env_vars:
            if env_var in _IMPLICIT_ENV_VARS:
                continue
            if _core.has_usable_secret(_core.os.getenv(env_var, "")):
                return True

    return False


def clear_provider_auth(provider_id: _core.Optional[str] = None) -> bool:
    """
    Clear auth state for a provider. Used by `hermes logout`.
    If provider_id is None, clears the active provider.
    Returns True if something was cleared.
    """
    with _core._auth_store_lock():
        auth_store = _core._load_auth_store()
        target = provider_id or auth_store.get("active_provider")
        if not target:
            return False

        providers = auth_store.get("providers", {})
        if not isinstance(providers, dict):
            providers = {}
            auth_store["providers"] = providers

        pool = auth_store.get("credential_pool")
        if not isinstance(pool, dict):
            pool = {}
            auth_store["credential_pool"] = pool

        cleared = False
        if target in providers:
            del providers[target]
            cleared = True
        if target in pool:
            del pool[target]
            cleared = True

        if auth_store.get("active_provider") == target:
            auth_store["active_provider"] = None
            cleared = True

        if not cleared:
            return False
        _core._save_auth_store(auth_store)
    return True


def deactivate_provider() -> None:
    """
    Clear active_provider in auth.json without deleting credentials.
    Used when the user switches to a non-OAuth provider (OpenRouter, custom)
    so auto-resolution doesn't keep picking the OAuth provider.
    """
    with _core._auth_store_lock():
        auth_store = _core._load_auth_store()
        auth_store["active_provider"] = None
        _core._save_auth_store(auth_store)
