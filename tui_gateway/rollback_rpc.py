"""Gateway RPCs for the ``rollback.*`` family — carved from server.py.

Moves-only slice of the Wave-2 server family-split (docs/plans/2026-07-10-
modularization-program.md §W2.a). ``rollback.list`` / ``rollback.restore`` /
``rollback.diff`` moved here VERBATIM. The local ``rpc_validated`` decorator
captures handlers into ``_REGISTRARS``; ``server.py`` calls :func:`register`
(at load AND on ``importlib.reload`` — the pm_rpc/jobs_rpc sibling contract),
replaying them through the REAL ``server.rpc_validated`` so registration lands in
the same ``tui_gateway.server._methods`` dispatch dict — wire byte-identical.

No monkeypatched names are referenced, so there is no ``_core.`` hop: the
checkpoint helpers (``_with_checkpoints`` / ``_resolve_checkpoint_hash``, which
live near the session runtime) and ``_sess`` / ``_ok`` / ``_err`` stay in core
and are imported bare; ``render_diff`` comes from :mod:`tui_gateway.render`.
"""
from __future__ import annotations

from tui_gateway.render import render_diff
from tui_gateway.server import (
    _err,
    _ok,
    _resolve_checkpoint_hash,
    _sess,
    _with_checkpoints,
)

_REGISTRARS: list[tuple[str, str, object]] = []


def rpc_validated(name: str):
    def _dec(fn):
        _REGISTRARS.append(("rpc_validated", name, fn))
        return fn

    return _dec


def register(server) -> None:
    """(Re-)register every carved rollback.* handler into ``server._methods``."""
    for kind, name, fn in _REGISTRARS:
        getattr(server, kind)(name)(fn)


__all__ = ["register"]
@rpc_validated("rollback.list")
def _(rid, params: dict) -> dict:
    session, err = _sess(params, rid)
    if err:
        return err
    try:

        def go(mgr, cwd):
            if not mgr.enabled:
                return _ok(rid, {"enabled": False, "checkpoints": []})
            return _ok(
                rid,
                {
                    "enabled": True,
                    "checkpoints": [
                        {
                            "hash": c.get("hash", ""),
                            "timestamp": c.get("timestamp", ""),
                            "message": c.get("message", ""),
                        }
                        for c in mgr.list_checkpoints(cwd)
                    ],
                },
            )

        return _with_checkpoints(session, go)
    except Exception as e:
        return _err(rid, 5020, str(e))


@rpc_validated("rollback.restore")
def _(rid, params: dict) -> dict:
    session, err = _sess(params, rid)
    if err:
        return err
    target = params.get("hash", "")
    file_path = params.get("file_path", "")
    if not target:
        return _err(rid, 4014, "hash required")
    # Full-history rollback mutates session history.  Rejecting during
    # an in-flight turn prevents prompt.submit from silently dropping
    # the agent's output (version mismatch path) or clobbering the
    # rollback (version-matches path).  A file-scoped rollback only
    # touches disk, so we allow it.
    if not file_path and session.get("running"):
        return _err(
            rid,
            4009,
            "session busy — /interrupt the current turn before full rollback.restore",
        )
    try:

        def go(mgr, cwd):
            resolved = _resolve_checkpoint_hash(mgr, cwd, target)
            result = mgr.restore(cwd, resolved, file_path=file_path or None)
            if result.get("success") and not file_path:
                removed = 0
                with session["history_lock"]:
                    history = session.get("history", [])
                    while history and history[-1].get("role") in {"assistant", "tool"}:
                        history.pop()
                        removed += 1
                    if history and history[-1].get("role") == "user":
                        history.pop()
                        removed += 1
                    if removed:
                        session["history_version"] = (
                            int(session.get("history_version", 0)) + 1
                        )
                result["history_removed"] = removed
            return result

        return _ok(rid, _with_checkpoints(session, go))
    except Exception as e:
        return _err(rid, 5021, str(e))


@rpc_validated("rollback.diff")
def _(rid, params: dict) -> dict:
    session, err = _sess(params, rid)
    if err:
        return err
    target = params.get("hash", "")
    if not target:
        return _err(rid, 4014, "hash required")
    try:
        r = _with_checkpoints(
            session,
            lambda mgr, cwd: mgr.diff(cwd, _resolve_checkpoint_hash(mgr, cwd, target)),
        )
        raw = r.get("diff", "")[:4000]
        payload = {"stat": r.get("stat", ""), "diff": raw}
        rendered = render_diff(raw, session.get("cols", 80))
        if rendered:
            payload["rendered"] = rendered
        return _ok(rid, payload)
    except Exception as e:
        return _err(rid, 5022, str(e))
