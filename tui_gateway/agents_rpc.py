"""Gateway RPCs for the ``agents.*`` family — carved from server.py.

Moves-only slice of the Wave-2 server family-split (docs/plans/2026-07-10-
modularization-program.md §W2.a). ``agents.list`` (the delegatable subagent
catalog) and ``agents.active.summary`` (the live spawn-tree roll-up) moved here
VERBATIM. The local ``rpc_validated`` decorator captures handlers into
``_REGISTRARS``; ``server.py`` calls :func:`register` (at load AND on
``importlib.reload`` — the pm_rpc/jobs_rpc sibling contract), replaying them
through the REAL ``server.rpc_validated`` so registration lands in the same
``tui_gateway.server._methods`` dispatch dict — wire byte-identical.

No monkeypatched names are referenced: ``_ok`` / ``_err`` stay in core and are
imported bare (no ``_core.`` hop).
"""
from __future__ import annotations

from typing import Any

from tui_gateway.server import _err, _ok

_REGISTRARS: list[tuple[str, str, object]] = []


def rpc_validated(name: str):
    def _dec(fn):
        _REGISTRARS.append(("rpc_validated", name, fn))
        return fn

    return _dec


def register(server) -> None:
    """(Re-)register every carved agents.* handler into ``server._methods``."""
    global _err, _ok
    _err = server._err
    _ok = server._ok
    for kind, name, fn in _REGISTRARS:
        getattr(server, kind)(name)(fn)


__all__ = ["register"]
@rpc_validated("agents.list")
def _(rid, params: dict) -> dict:
    try:
        from tools.process_registry import process_registry

        procs = process_registry.list_sessions()
        return _ok(
            rid,
            {
                "processes": [
                    {
                        "session_id": p["session_id"],
                        "command": p["command"][:80],
                        "status": p["status"],
                        "uptime": p["uptime_seconds"],
                    }
                    for p in procs
                ]
            },
        )
    except Exception as e:
        return _err(rid, 5033, str(e))


@rpc_validated("agents.active.summary")
def _(rid, params: dict) -> dict:
    """ONE cheap glanceable aggregate: how many agent-ish jobs are live RIGHT NOW.

    The operator's ask: "when the chat invoked an agent run across all those
    systems, there is no visual that the agents are running." Since Arc B every
    detached job (reforecast/task/quorum/refresh/…) lives on ONE store, so this
    reads that ONE store in a single scan — no more tri-store aggregation — plus the
    in-memory process registry (the one NON-jobs source: proc_ batches / agent runs
    that never became job records). It returns a Claude-Code-style
    ``{count, kinds, headline}`` the TUI status bar renders as
    "✦ N agents running · <label>", labelled from the NEWEST live item (proc command
    trimmed, or reforecast/task mode + question count, or quorum question).

    FAIL-SAFE by construction: each source is read under its own guard, so a source
    that errors contributes 0 and NEVER breaks the RPC — a status bar polling this
    every few seconds must never take the gateway down. No network, no ledger read;
    just the job files (incl. any surviving legacy rf_/qr_ record via the store's
    read-shim) + the process registry.
    """
    import time as _time
    from datetime import datetime as _dt

    def _epoch(iso: Any) -> float:
        # Parse an ISO ``created_at`` into epoch seconds so every live item sorts on
        # one axis; an unparseable value sorts oldest (0.0).
        try:
            return _dt.fromisoformat(str(iso)).timestamp()
        except Exception:  # noqa: BLE001
            return 0.0

    # (started_epoch, label) per live item; the newest wins the headline label.
    candidates: list[tuple[float, str]] = []
    procs = reforecast = quorum = 0

    try:
        # 1) Background processes — only those still RUNNING (a proc_ batch / agent
        #    run). list_sessions() also returns recently-EXITED ones; skip those.
        #    This is the ONE non-jobs source: procs that never became job records.
        try:
            from tools.process_registry import process_registry

            now = _time.time()
            for p in process_registry.list_sessions():
                if p.get("status") != "running":
                    continue
                # A session can linger in the registry's _running set with a DEAD
                # child: the reader thread only flips ``exited`` on stdout EOF, so an
                # orphaned-pipe hang (a descendant holding the pipe open — issue
                # #17327) leaves it "running" forever. Unlike ``poll()``,
                # ``list_sessions()`` does NOT reconcile against the real child, so a
                # finished chat-spawned agent would keep the chip lit. Gate on actual
                # host-pid liveness: only count a proc whose pid is truly alive. A
                # missing pid (env/sandbox-backed) can't be proven dead → still count.
                pid = p.get("pid")
                if pid and not process_registry._is_host_pid_alive(pid):
                    continue
                procs += 1
                cmd = str(p.get("command") or "").strip()
                label = (cmd[:44] + "…") if len(cmd) > 45 else (cmd or "process")
                candidates.append((now - float(p.get("uptime_seconds") or 0), label))
        except Exception:  # noqa: BLE001 — a source failure contributes 0, never breaks the RPC
            pass

        try:
            # 2) THE ONE job store — every detached "agent" job in a SINGLE scan
            #    (reforecast + task + quorum), incl. any legacy rf_/qr_ file the
            #    store's read-shim surfaces. active() already filters to queued|
            #    running. Deterministic re-pool (refresh) and warning-automode jobs
            #    are not "agent" work for this chip, so they are not counted.
            from forecasting.jobs.store import JobStore

            for rec in JobStore().active():
                spec = rec.spec or {}
                if rec.type in ("reforecast", "task"):
                    reforecast += 1
                    n = int(rec.total or len(spec.get("question_ids") or []) or 0)
                    kind = "desk task" if rec.type == "task" else "reforecast"
                    label = f"{kind} · {n} question{'' if n == 1 else 's'}" if n else kind
                    candidates.append((_epoch(rec.created_at), label))
                elif rec.type == "quorum":
                    quorum += 1
                    qid = str(spec.get("question_id") or "").strip()
                    candidates.append((_epoch(rec.created_at), f"quorum · {qid}" if qid else "quorum"))
        except Exception:  # noqa: BLE001
            pass

        count = procs + reforecast + quorum
        if count == 0:
            return _ok(rid, {"count": 0, "kinds": {"procs": 0, "reforecast": 0, "quorum": 0}, "headline": ""})

        # Label the headline from the NEWEST live item across all three stores.
        newest_label = max(candidates, key=lambda c: c[0])[1] if candidates else ""
        noun = "agent" if count == 1 else "agents"
        headline = f"{count} {noun} running" + (f" · {newest_label}" if newest_label else "")
        return _ok(
            rid,
            {
                "count": count,
                "kinds": {"procs": procs, "reforecast": reforecast, "quorum": quorum},
                "headline": headline,
            },
        )
    except Exception:  # noqa: BLE001 — belt-and-suspenders: degrade to an empty summary, never _err
        return _ok(rid, {"count": 0, "kinds": {"procs": 0, "reforecast": 0, "quorum": 0}, "headline": ""})
