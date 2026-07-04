"""The quorum auto-run DECISION: whether a just-committed forecast should trigger a
detached multi-model quorum, and — when it should — START one on the jobs runtime.

Relocated out of the deleted ``forecasting.quorum_jobs`` (Arc B3): the QUORUM job
itself is now a TYPE on the one detached-job runtime
(:mod:`forecasting.jobs.types.quorum`), and this module is the thin DECISION layer
that sits above it. :func:`maybe_autorun_quorum` is THE shared seam for every commit
surface — the CLI ``forecast update`` verb AND the agent tool's ``update_forecast``
(which is what ``full_forecast``, the chained pipeline, and ``cycle run --agent``
commit through) — so the autonomous paths get the same multi-model fusion a
hand-typed update does. Semantics are unchanged from the legacy function, including
the auditable skip records.
"""

from __future__ import annotations

from typing import Any


def resolve_active_model_id(model_cfg: Any) -> str | None:
    """Extract the active model-id STRING from the config ``model`` value.

    Since the codex auth overhaul ``config["model"]`` is a structured dict
    ({base_url, default, provider}); the canonical id is ``default`` (or legacy
    ``model``), as fallback_cmd/dump/doctor resolve it. A legacy bare string is
    tolerated. Returns None when unset. (Passing the raw dict downstream made the
    quorum's `self`/judge model a dict and blew up the panelist with
    ``'dict' object has no attribute 'lower'`` — a silent, total quorum failure.)
    """

    if isinstance(model_cfg, dict):
        return (model_cfg.get("default") or model_cfg.get("model") or "").strip() or None
    if model_cfg:
        return str(model_cfg).strip() or None
    return None


def maybe_autorun_quorum(
    ledger: Any,
    question_id: str,
    *,
    snapshot: Any,
    has_panel: bool,
    has_prior_snapshot: bool,
    forecast_origin: str | None,
    notify: Any = None,
) -> dict[str, Any] | None:
    """AUTO-RUN a quorum (detached) when one is auto-indicated but none attached.

    THE shared seam for every commit surface — the CLI ``forecast update`` verb
    AND the agent tool's ``update_forecast`` (which is what ``full_forecast``,
    the chained pipeline, and ``cycle run --agent`` commit through) — so the
    autonomous paths get the same multi-model fusion a hand-typed update does.
    The panel shape is resolved by :func:`forecasting.quorum.resolve_quorum_defaults`
    (impact/type-aware, with the single-key reality guard) and cost-bounded by
    ``quorum.max_calls`` before we spend anything.

    STRICTLY BOUNDED + FAIL-OPEN: the commit already happened, so ANY failure
    here (config, resolution, job spawn) is reported via ``notify`` and never
    blocks or corrupts it. Only fires for LIVE forecasts with no panel already
    attached, and only when ``quorum.default_enabled`` + the scope gate say so.

    ``notify`` (optional callable) receives human-readable progress lines — the
    CLI passes ``print``; the tool collects them into its result. Returns a
    structured record ``{run_id, preset, delphi_rounds, estimated_calls, reason,
    cap_note}`` when a job was started, else ``None`` (or an auditable
    ``{skipped: True, reason}`` record for a by-design decline).

    The started job is a ``quorum`` TYPE on the one detached-job runtime
    (:func:`forecasting.jobs.types.quorum.start_job`), imported lazily so a
    monkeypatch of that module's ``start_job`` reaches this call site.
    """

    def _say(message: str) -> None:
        if notify is not None:
            notify(message)

    if has_panel:
        return {"skipped": True, "reason": "panel attached — quorum substitutes only when no panel ran"}
    if (forecast_origin or "live") != "live":
        return {"skipped": True, "reason": f"origin {forecast_origin!r} is not live"}
    try:
        from hermes_cli.config import load_config
        from forecasting.panel import should_run_panel
        from forecasting.jobs.types.quorum import start_job
        from forecasting.quorum import (
            available_provider_slugs,
            cap_preset_by_calls,
            quorum_auto_indicated,
            resolve_quorum_defaults,
        )

        full_cfg = load_config()
        cfg = full_cfg.get("quorum", {}) or {}
        if not cfg.get("default_enabled"):
            return {"skipped": True, "reason": "quorum.default_enabled is off"}
        question = ledger.get_question(question_id)
        panel_indicated = should_run_panel(
            impact=getattr(question, "impact", None),
            has_prior_snapshot=has_prior_snapshot,
        )
        if not quorum_auto_indicated(
            cfg, panel_indicated=panel_indicated, has_prior_snapshot=has_prior_snapshot
        ):
            return {"skipped": True, "reason": "not auto-indicated for this commit (impact/type/prior gate)"}

        active_model = resolve_active_model_id(full_cfg.get("model"))
        samples = 3
        defaults = resolve_quorum_defaults(
            question,
            available_providers=available_provider_slugs(),
            active_model=active_model,
            samples=samples,
        )
        preset = defaults["preset"]
        delphi_rounds = int(defaults["delphi_rounds"])
        trim = int(defaults["trim"])
        max_calls = int(cfg.get("max_calls", 12) or 12)
        preset, delphi_rounds, samples, est_calls, cap_note = cap_preset_by_calls(
            preset, delphi_rounds, max_calls=max_calls, samples=samples
        )

        judge = cfg.get("judge") or None
        self_fusion = preset == "self"
        models = None
        preset_for_spec: str | None = preset
        if self_fusion:
            if not active_model:
                _say(
                    "↳ quorum auto-run skipped: self-fusion needs a default model "
                    "(set one with `superforecasting-agent model`)."
                )
                return None
            models = [active_model] * samples
            judge = judge or active_model
            preset_for_spec = None  # models now explicit

        spec = {
            "question_id": question_id,
            # str() — the spec is JSON-persisted by the store; a Path is not
            # serializable. ForecastLedger accepts the str form.
            "db": (str(ledger.db_path) if getattr(ledger, "db_path", None) else None),
            "preset": preset_for_spec,
            "models": models,
            "judge": judge,
            "pool_method": cfg.get("pool_method") or "trimmed_geomean_odds",
            "trim": trim,
            "self_fusion": self_fusion,
            "samples": samples,
            "attach_snapshot": getattr(snapshot, "forecast_id", None),
            "triggered_by": "auto_quorum",
            "active_model": active_model,
            "max_iterations": int(cfg.get("max_iterations", 30)),
            "model_timeout": int(cfg.get("model_timeout", 300)),
            "supervisor_search": bool(cfg.get("supervisor_search")),
            "delphi_rounds": delphi_rounds,
        }
        run_id = start_job(spec, wait=False)
        _say(
            f"↳ quorum auto-run started: {run_id} "
            f"(preset={preset}, delphi={delphi_rounds}, ~{est_calls} model calls) — "
            f"{defaults['reason']}."
        )
        if cap_note:
            _say(f"  cost cap: {cap_note}")
        _say(f"  poll with:  forecast quorum status {run_id}")
        return {
            "run_id": run_id,
            "preset": preset,
            "delphi_rounds": delphi_rounds,
            "estimated_calls": est_calls,
            "reason": defaults["reason"],
            "cap_note": cap_note,
        }
    except Exception as exc:  # noqa: BLE001 — auto-run is fail-open; the commit stands
        # The commit already happened; ANY failure here (config, resolution, job
        # spawn) degrades to a one-line note and never blocks or corrupts it.
        _say(f"↳ quorum auto-run skipped (non-fatal): {type(exc).__name__}: {exc}")
        return None


__all__ = ["maybe_autorun_quorum", "resolve_active_model_id"]
