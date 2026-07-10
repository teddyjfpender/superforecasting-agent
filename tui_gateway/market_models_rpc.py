"""Gateway RPCs for Market Models + news ranking — carved from server.py.

Moves-only slice of the Wave-2 server family-split (docs/plans/2026-07-10-
modularization-program.md §W2.a). The agentic quant-research ``markets.model.*``
family (build/chat/retry/list/get/renarrate/export/to_forecast/delete) plus the
contiguous ``news.search`` article-ranking RPC moved here VERBATIM. The local
``method`` decorator captures handlers into ``_REGISTRARS``; ``server.py`` calls
:func:`register` (at load AND on ``importlib.reload`` — the pm_rpc/jobs_rpc
sibling contract), which replays them through the REAL ``server.method`` so the
registration lands in the same ``tui_gateway.server._methods`` dispatch dict —
wire byte-identical.

``_emit`` is monkeypatched by the test suite, so it is reached via the
``_core._emit`` call-time hop (a patch on ``tui_gateway.server._emit`` still
reaches these moved event emissions). ``_ok`` / ``_err`` / ``_session_runtime``
are not patched — imported bare from core.
"""
from __future__ import annotations

import contextvars
import threading

import tui_gateway.server as _core
from tui_gateway.server import _err, _ok, _session_runtime

# Handlers captured at import; replayed into the gateway by register() so they
# survive a server module reload (the re-entrant sibling seam).
_REGISTRARS: list[tuple[str, str, object]] = []


def method(name: str):
    def _dec(fn):
        _REGISTRARS.append(("method", name, fn))
        return fn

    return _dec


def register(server) -> None:
    """(Re-)register every carved markets/news handler into ``server._methods``."""
    for kind, name, fn in _REGISTRARS:
        getattr(server, kind)(name)(fn)


__all__ = ["register"]


@method("news.search")
def _(rid, params: dict) -> dict:
    """Semantically rank the caller's RSS articles against a query.

    The TUI sends its loaded articles ({title, summary, source}); we return the
    ranked indices so the view can reorder its own list. Slow (LLM call) — listed
    in _LONG_HANDLERS. Falls back to lexical ranking if the model is unavailable.
    """
    try:
        from forecasting.news_search import rank_news_articles

        query = str(params.get("query") or "").strip()
        raw = params.get("articles")
        limit = max(1, min(100, int(params.get("limit") or 25)))
        if not query or not isinstance(raw, list):
            return _ok(rid, {"results": [], "engine": "none"})

        # Bound + sanitize what we forward to the model.
        articles = [
            {
                "title": str(a.get("title", ""))[:300],
                "summary": str(a.get("summary", ""))[:600],
                "source": str(a.get("source", ""))[:80],
            }
            for a in raw[:300]
            if isinstance(a, dict)
        ]
        return _ok(rid, rank_news_articles(query, articles, limit=limit))
    except Exception as e:
        return _err(rid, 5008, str(e))


# ── Market Models ─────────────────────────────────────────────────────────────
# Agentic quant-research builds run in the BACKGROUND (a daemon thread with the
# request's transport context snapshotted) so the create/chat RPCs return an id
# immediately and the TUI watches progress events or gets notified on completion.


def _spawn_market_job(sid: str, model_id: str, job) -> None:
    """Run a market-model build/refine on a daemon thread, routing events back."""
    ctx = contextvars.copy_context()

    def _run():
        try:
            job()
        except Exception as e:  # never lose the model; surface the failure
            _core._emit("markets.model.error", sid, {"id": model_id, "message": str(e)})

    threading.Thread(target=lambda: ctx.run(_run), daemon=True).start()


@method("markets.model.create")
def _(rid, params: dict) -> dict:
    try:
        from forecasting import market_model as MM
        from forecasting.ledger import ForecastLedger

        sid = str(params.get("session_id") or "")
        question = str(params.get("question") or "").strip()
        if not question:
            return _err(rid, 5008, "question is required")
        mparams = params.get("params") if isinstance(params.get("params"), dict) else {}
        depth = mparams.get("depth") if mparams.get("depth") in MM.DEPTH_PRESETS else MM.DEFAULT_DEPTH
        ledger = ForecastLedger()
        model = ledger.create_market_model(
            title=(mparams.get("title") or question)[:120], question=question, depth=depth,
            spec={}, tags=mparams.get("tags") or [],
        )
        mid = model["id"]
        runtime = _session_runtime(sid)

        def _job():
            _core._emit("markets.model.progress", sid, {"id": mid, "phase": "starting", "message": "starting"})
            out = MM.build_market_model(
                question, mparams, ledger=ForecastLedger(), model_id=mid, runtime=runtime,
                progress=lambda m: _core._emit("markets.model.progress", sid, {"id": mid, "message": m}),
            )
            _core._emit("markets.model.complete", sid, {"id": mid, "version": out.get("version"), "status": out.get("status")})

        _spawn_market_job(sid, mid, _job)
        return _ok(rid, {"model_id": mid, "version": 0, "status": "building"})
    except Exception as e:
        return _err(rid, 5008, str(e))


@method("markets.model.chat")
def _(rid, params: dict) -> dict:
    try:
        from forecasting import market_model as MM
        from forecasting.ledger import ForecastLedger

        sid = str(params.get("session_id") or "")
        mid = str(params.get("id") or "").strip()
        message = str(params.get("message") or "").strip()
        if not mid or not message:
            return _err(rid, 5008, "id and message are required")
        mparams = params.get("params") if isinstance(params.get("params"), dict) else {}
        runtime = _session_runtime(sid)

        def _job():
            _core._emit("markets.model.progress", sid, {"id": mid, "phase": "refining", "message": "refining"})
            out = MM.chat_market_model(
                mid, message, ledger=ForecastLedger(), params=mparams, runtime=runtime,
                progress=lambda m: _core._emit("markets.model.progress", sid, {"id": mid, "message": m}),
            )
            _core._emit("markets.model.complete", sid, {"id": mid, "version": out.get("version"), "status": out.get("status")})

        _spawn_market_job(sid, mid, _job)
        return _ok(rid, {"model_id": mid, "status": "building"})
    except Exception as e:
        return _err(rid, 5008, str(e))


@method("markets.model.retry")
def _(rid, params: dict) -> dict:
    """Re-run a model's build using its stored question + depth (same id), so a
    failed/partial model can be retried without the user re-prompting."""
    try:
        from forecasting import market_model as MM
        from forecasting.ledger import ForecastLedger

        sid = str(params.get("session_id") or "")
        mid = str(params.get("id") or "").strip()
        if not mid:
            return _err(rid, 5008, "id is required")
        ledger = ForecastLedger()
        model = ledger.get_market_model(mid)
        if not model:
            return _err(rid, 5008, "model not found")
        question = str(model.get("question") or "").strip()
        if not question:
            return _err(rid, 5008, "model has no stored question to retry")
        mparams = {"depth": model.get("depth") if model.get("depth") in MM.DEPTH_PRESETS else MM.DEFAULT_DEPTH}
        runtime = _session_runtime(sid)

        def _job():
            _core._emit("markets.model.progress", sid, {"id": mid, "phase": "starting", "message": "retrying"})
            out = MM.build_market_model(
                question, mparams, ledger=ForecastLedger(), model_id=mid, runtime=runtime,
                progress=lambda m: _core._emit("markets.model.progress", sid, {"id": mid, "message": m}),
            )
            _core._emit("markets.model.complete", sid, {"id": mid, "version": out.get("version"), "status": out.get("status")})

        _spawn_market_job(sid, mid, _job)
        return _ok(rid, {"model_id": mid, "status": "building"})
    except Exception as e:
        return _err(rid, 5008, str(e))


@method("markets.model.list")
def _(rid, params: dict) -> dict:
    try:
        from forecasting.ledger import ForecastLedger

        ledger = ForecastLedger()
        status = params.get("status", "active")
        limit = int(params.get("limit") or 200)
        models = ledger.list_market_models(status=status if status else None, limit=limit)
        rows = []
        for m in models:
            row = {
                "id": m["id"], "title": m["title"], "question": m["question"], "depth": m.get("depth"),
                "status": m.get("status"), "last_status": m.get("last_status"),
                "current_version": m.get("current_version"),
                "updated_at": m.get("updated_at"), "tags": m.get("tags") or [],
            }
            # R4 Living Models: attach the model's measured skill (payload only; TUI
            # renders later). Best-effort — a skill hiccup never drops the model row.
            try:
                skill = ledger.model_skill(market_model_id=m["id"])
                row["skill"] = {
                    "n_scored": skill.get("n_scored"),
                    "n_binary": skill.get("n_binary"),
                    "n_numeric": skill.get("n_numeric"),
                    "brier": skill.get("brier"),
                    "coverage": skill.get("coverage"),
                    "weight_multiplier": skill.get("weight_multiplier"),
                    "status": skill.get("status"),
                }
            except Exception:
                row["skill"] = None
            rows.append(row)
        return _ok(rid, {"models": rows})
    except Exception as e:
        return _err(rid, 5008, str(e))


@method("markets.model.get")
def _(rid, params: dict) -> dict:
    """Return the stored presentation immediately, then re-pull+recompute in the
    background and emit ``markets.model.refreshed`` with the fresh version."""
    try:
        from forecasting import market_model as MM
        from forecasting.ledger import ForecastLedger

        sid = str(params.get("session_id") or "")
        mid = str(params.get("id") or "").strip()
        version = params.get("version")
        ledger = ForecastLedger()
        packet = ledger.export_market_model(mid)
        if version is not None:
            try:
                packet["presentation"] = ledger.get_market_presentation(mid, version=int(version))
            except Exception:
                pass

        # Background refresh (re-pull live data + recompute) for the current version only.
        if version is None:
            def _job():
                opened = MM.open_market_model(mid, ledger=ForecastLedger())
                if opened.get("refreshed"):
                    _core._emit("markets.model.refreshed", sid, {"id": mid, "presentation": opened.get("presentation")})

            _spawn_market_job(sid, mid, _job)
        return _ok(rid, {"packet": packet})
    except Exception as e:
        return _err(rid, 5008, str(e))


@method("markets.model.renarrate")
def _(rid, params: dict) -> dict:
    try:
        from forecasting import market_model as MM
        from forecasting.ledger import ForecastLedger

        mid = str(params.get("id") or "").strip()
        out = MM.renarrate_market_model(mid, ledger=ForecastLedger())
        return _ok(rid, out)
    except Exception as e:
        return _err(rid, 5008, str(e))


@method("markets.model.export")
def _(rid, params: dict) -> dict:
    """Write a full JSON data packet to the workspace exports dir; return the path."""
    try:
        import json as _json
        import re as _re
        from pathlib import Path

        from forecasting.ledger import ForecastLedger
        from hermes_cli.config import get_hermes_home

        mid = str(params.get("id") or "").strip()
        ledger = ForecastLedger()
        packet = ledger.export_market_model(mid)
        title = (packet.get("model") or {}).get("title") or mid
        slug = _re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or mid
        exports = Path(get_hermes_home()) / "exports"
        exports.mkdir(parents=True, exist_ok=True)
        path = exports / f"market-model-{slug}-{mid}.json"
        path.write_text(_json.dumps(packet, indent=2, default=str), encoding="utf-8")
        return _ok(rid, {"path": str(path), "bytes": path.stat().st_size})
    except Exception as e:
        return _err(rid, 5008, str(e))


@method("markets.model.to_forecast")
def _(rid, params: dict) -> dict:
    try:
        from forecasting import market_model as MM
        from forecasting.ledger import ForecastLedger

        mid = str(params.get("id") or "").strip()
        return _ok(rid, MM.model_to_forecast(mid, ledger=ForecastLedger()))
    except Exception as e:
        return _err(rid, 5008, str(e))


@method("markets.model.delete")
def _(rid, params: dict) -> dict:
    try:
        from forecasting.ledger import ForecastLedger

        mid = str(params.get("id") or "").strip()
        deleted = ForecastLedger().delete_market_model(mid)
        return _ok(rid, {"deleted": bool(deleted)})
    except Exception as e:
        return _err(rid, 5008, str(e))
