"""Gateway RPCs for the subagent/delegation/spawn-tree family — carved from server.

Moves-only slice of the Wave-2 server family-split (docs/plans/2026-07-10-
modularization-program.md §W2.a). ``delegation.status`` / ``delegation.pause`` /
``subagent.interrupt`` and the disk-persisted spawn-tree snapshot RPCs
(``spawn_tree.save`` / ``spawn_tree.list`` / ``spawn_tree.load``) moved here
VERBATIM. The local ``rpc_validated`` / ``method`` decorators capture handlers
into ``_REGISTRARS``; ``server.py`` calls :func:`register` (at load AND on
``importlib.reload`` — the pm_rpc/jobs_rpc sibling contract), replaying them
through the REAL ``server.rpc_validated`` / ``server.method`` so registration
lands in the same ``tui_gateway.server._methods`` dispatch dict — byte-identical.

Session lookup uses the server bound at registration, so replacing a package
attribute cannot redirect a request into another host registry. The spawn-tree disk helpers
(``_spawn_trees_root`` / ``_spawn_tree_session_dir`` / ``_append_spawn_tree_index``
/ ``_read_spawn_tree_index`` + ``_SPAWN_TREE_INDEX``) stay in core and are
imported bare (no ``_core.`` hop).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import tui_gateway.server as _core

from tui_gateway.server import (
    _SPAWN_TREE_INDEX,
    _append_spawn_tree_index,
    _err,
    _ok,
    _read_spawn_tree_index,
    _spawn_tree_session_dir,
    _spawn_trees_root,
)

_REGISTRARS: list[tuple[str, str, object]] = []


def rpc_validated(name: str):
    def _dec(fn):
        _REGISTRARS.append(("rpc_validated", name, fn))
        return fn

    return _dec


def method(name: str):
    def _dec(fn):
        _REGISTRARS.append(("method", name, fn))
        return fn

    return _dec


def register(server) -> None:
    """(Re-)register every carved subagent/spawn-tree handler into ``_methods``."""
    global _core, _SPAWN_TREE_INDEX, _append_spawn_tree_index, _err, _ok, _read_spawn_tree_index, _spawn_tree_session_dir, _spawn_trees_root
    _core = server
    _SPAWN_TREE_INDEX = server._SPAWN_TREE_INDEX
    _append_spawn_tree_index = server._append_spawn_tree_index
    _err = server._err
    _ok = server._ok
    _read_spawn_tree_index = server._read_spawn_tree_index
    _spawn_tree_session_dir = server._spawn_tree_session_dir
    _spawn_trees_root = server._spawn_trees_root
    for kind, name, fn in _REGISTRARS:
        getattr(server, kind)(name)(fn)


def _session_owner(rid, params):
    session, error = _core._sess_nowait(params, rid)
    if error:
        return None, error
    key = session.get("session_key")
    if not key:
        return None, _err(rid, 4004, "session has no delegation owner")
    return key, None


__all__ = ["register"]
@rpc_validated("delegation.status")
def _(rid, params: dict) -> dict:
    session_key, error = _session_owner(rid, params)
    if error:
        return error

    from superforecasting_agent.hosting.delegations import is_spawn_paused, list_active_subagents
    from tools.delegate_tool import (
        _get_max_async_children,
        _get_max_concurrent_children,
        _get_max_spawn_depth,
    )

    # Background (async) delegations live in their own registry, not the
    # synchronous subagent list — surface both so the TUI can show them.
    try:
        from tools.async_delegation import list_async_delegations

        async_delegations = list_async_delegations(session_key=session_key)
    except Exception:
        async_delegations = []

    return _ok(
        rid,
        {
            "active": list_active_subagents(session_key=session_key),
            "async": async_delegations,
            "paused": is_spawn_paused(session_key=session_key),
            "max_spawn_depth": _get_max_spawn_depth(),
            "max_concurrent_children": _get_max_concurrent_children(),
            "max_async_children": _get_max_async_children(),
        },
    )


@rpc_validated("delegation.pause")
def _(rid, params: dict) -> dict:
    session_key, error = _session_owner(rid, params)
    if error:
        return error

    from superforecasting_agent.hosting.delegations import set_spawn_paused

    paused = params.get("paused", True)
    if not isinstance(paused, bool):
        return _err(rid, 4004, "paused must be a boolean")
    return _ok(rid, {"paused": set_spawn_paused(paused, session_key=session_key)})


@rpc_validated("subagent.interrupt")
def _(rid, params: dict) -> dict:
    session_key, error = _session_owner(rid, params)
    if error:
        return error

    from superforecasting_agent.hosting.delegations import interrupt_subagent

    subagent_id = str(params.get("subagent_id") or "").strip()
    if not subagent_id:
        return _err(rid, 4000, "subagent_id required")
    ok = interrupt_subagent(subagent_id, session_key=session_key)
    return _ok(rid, {"found": ok, "subagent_id": subagent_id})


@method("spawn_tree.save")
def _(rid, params: dict) -> dict:
    session_id = str(params.get("session_id") or "").strip()
    subagents = params.get("subagents") or []
    if not isinstance(subagents, list) or not subagents:
        return _err(rid, 4000, "subagents list required")

    from datetime import datetime

    started_at = params.get("started_at")
    finished_at = params.get("finished_at") or time.time()
    label = str(params.get("label") or "")
    ts = datetime.utcfromtimestamp(float(finished_at)).strftime("%Y%m%dT%H%M%S")
    fname = f"{ts}.json"
    d = _spawn_tree_session_dir(session_id or "default")
    path = d / fname
    try:
        payload = {
            "session_id": session_id,
            "started_at": float(started_at) if started_at else None,
            "finished_at": float(finished_at),
            "label": label,
            "subagents": subagents,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        return _err(rid, 5000, f"spawn_tree.save failed: {exc}")

    _append_spawn_tree_index(
        d,
        {
            "path": str(path),
            "session_id": session_id,
            "started_at": payload["started_at"],
            "finished_at": payload["finished_at"],
            "label": label,
            "count": len(subagents),
        },
    )

    return _ok(rid, {"path": str(path), "session_id": session_id})


@rpc_validated("spawn_tree.list")
def _(rid, params: dict) -> dict:
    session_id = str(params.get("session_id") or "").strip()
    limit = int(params.get("limit") or 50)
    cross_session = bool(params.get("cross_session"))

    if cross_session:
        root = _spawn_trees_root()
        roots = [p for p in root.iterdir() if p.is_dir()]
    else:
        roots = [_spawn_tree_session_dir(session_id or "default")]

    entries: list[dict] = []
    for d in roots:
        indexed = _read_spawn_tree_index(d)
        if indexed:
            # Skip index entries whose snapshot file was manually deleted.
            entries.extend(
                e for e in indexed if (p := e.get("path")) and Path(p).exists()
            )
            continue

        # Fallback for legacy (pre-index) sessions: full scan.  O(N) reads
        # but only runs once per session until the next save writes the index.
        for p in d.glob("*.json"):
            if p.name == _SPAWN_TREE_INDEX:
                continue
            try:
                stat = p.stat()
                try:
                    raw = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    raw = {}
                subagents = raw.get("subagents") or []
                entries.append(
                    {
                        "path": str(p),
                        "session_id": raw.get("session_id") or d.name,
                        "finished_at": raw.get("finished_at") or stat.st_mtime,
                        "started_at": raw.get("started_at"),
                        "label": raw.get("label") or "",
                        "count": len(subagents) if isinstance(subagents, list) else 0,
                    }
                )
            except OSError:
                continue

    entries.sort(key=lambda e: e.get("finished_at") or 0, reverse=True)
    return _ok(rid, {"entries": entries[:limit]})


@rpc_validated("spawn_tree.load")
def _(rid, params: dict) -> dict:
    from pathlib import Path

    raw_path = str(params.get("path") or "").strip()
    if not raw_path:
        return _err(rid, 4000, "path required")

    # Reject paths escaping the spawn-trees root.
    root = _spawn_trees_root().resolve()
    try:
        resolved = Path(raw_path).resolve()
        resolved.relative_to(root)
    except (ValueError, OSError) as exc:
        return _err(rid, 4030, f"path outside spawn-trees root: {exc}")

    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _err(rid, 5000, f"spawn_tree.load failed: {exc}")

    return _ok(rid, payload)
