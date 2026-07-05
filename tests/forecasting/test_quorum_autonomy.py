"""Wave-2 quorum autonomy: impact-aware defaults, provider reality, cost cap,
degraded-panel labeling, the auto-run path, the status RPC, and the config-gated
evidence-derived terminal Platt slope."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import forecasting.quorum as quorum
from forecasting.ledger import ForecastLedger


def _q(impact=None, qtype="binary"):
    return SimpleNamespace(
        impact=impact,
        outcome_space=SimpleNamespace(type=qtype),
        domain="macro",
    )


# ── item 1: resolve_quorum_defaults matrix (impact × keys) ────────────────────


def test_resolve_defaults_high_impact_is_frontier_delphi_trim():
    # Detection unavailable (None) ⇒ fail-open, multi-provider preset kept.
    d = quorum.resolve_quorum_defaults(_q(impact="high"), available_providers=None)
    assert d["preset"] == "frontier"
    assert d["delphi_rounds"] == 1
    assert d["trim"] == 1
    assert "high-impact" in d["reason"]


def test_resolve_defaults_contested_type_is_frontier_even_when_not_high():
    d = quorum.resolve_quorum_defaults(_q(impact="low", qtype="vote_share"), available_providers=None)
    assert d["preset"] == "frontier"
    assert d["delphi_rounds"] == 1


def test_resolve_defaults_medium_is_budget_with_delphi():
    # Multi-model budget panel defaults Delphi ON (finding #1: a real second read of
    # independent panelists earns the anonymous revision round).
    d = quorum.resolve_quorum_defaults(_q(impact="medium"), available_providers=None)
    assert d["preset"] == "budget"
    assert d["delphi_rounds"] == 1
    assert d["trim"] == 1


def test_resolve_defaults_routine_is_self():
    d = quorum.resolve_quorum_defaults(_q(impact="low"), available_providers=None)
    assert d["preset"] == "self"
    assert d["delphi_rounds"] == 0
    assert d["trim"] == 0


def test_resolve_defaults_single_key_falls_back_to_self():
    # Only anthropic reachable, no OpenRouter: a frontier panel (anthropic+openai)
    # cannot be served ⇒ honest self-fusion fallback (an active model IS available).
    d = quorum.resolve_quorum_defaults(
        _q(impact="high"),
        available_providers={"anthropic"},
        active_model="anthropic/claude-opus-4-8",
    )
    assert d["preset"] == "self"
    assert "self-fusion fallback" in d["reason"]
    # Single-model self-fusion drops the Delphi round (Delphi is a multi-model default).
    assert d["delphi_rounds"] == 0


def test_resolve_defaults_single_key_no_active_model_keeps_preset():
    # Single provider key but NO active model to self-fuse: keep the preset so the
    # job still runs (and degrades honestly) rather than dead-ending.
    d = quorum.resolve_quorum_defaults(
        _q(impact="high"), available_providers={"anthropic"}, active_model=None
    )
    assert d["preset"] == "frontier"
    assert "no active model" in d["reason"]


def test_resolve_defaults_openrouter_serves_the_whole_panel():
    # OpenRouter is a universal server — frontier stays reachable with one key.
    d = quorum.resolve_quorum_defaults(
        _q(impact="high"), available_providers={"openrouter"}
    )
    assert d["preset"] == "frontier"


# ── item 3: provider reachability helpers ─────────────────────────────────────


def test_models_reachable_none_is_fail_open():
    assert quorum.models_reachable(["anthropic/x", "openai/y"], None) is True


def test_models_reachable_requires_every_provider():
    assert quorum.models_reachable(["anthropic/x", "openai/y"], {"anthropic"}) is False
    assert quorum.models_reachable(["anthropic/x"], {"anthropic"}) is True


def test_models_reachable_openrouter_short_circuits():
    assert quorum.models_reachable(["anthropic/x", "openai/y"], {"openrouter"}) is True


# ── item 4: cost estimate + cap ───────────────────────────────────────────────


def test_estimate_counts_panelists_plus_judge_times_rounds():
    assert quorum.estimate_quorum_calls(model_count=2, delphi_rounds=0) == 3
    assert quorum.estimate_quorum_calls(model_count=2, delphi_rounds=1) == 6
    assert quorum.estimate_quorum_calls(model_count=10, delphi_rounds=1) == 22


def test_cap_within_budget_is_noop():
    preset, delphi, samples, calls, note = quorum.cap_preset_by_calls("frontier", 1, max_calls=12)
    assert (preset, delphi, calls) == ("frontier", 1, 6)
    assert samples == 3
    assert note is None


def test_cap_downgrades_wide_delphi_to_largest_fitting():
    # wide+delphi = 22 calls > 12; the largest fit is wide/no-delphi (11).
    preset, delphi, samples, calls, note = quorum.cap_preset_by_calls("wide", 1, max_calls=12)
    assert calls <= 12
    assert preset == "wide" and delphi == 0
    assert "downgrad" in note.lower()


def test_cap_drops_delphi_first_when_that_alone_fits():
    # frontier+delphi = 6; cap at 5 forces dropping the revision round to 3.
    preset, delphi, samples, calls, note = quorum.cap_preset_by_calls("frontier", 1, max_calls=5)
    assert preset == "frontier" and delphi == 0 and calls == 3
    assert "delphi" in note.lower()


def test_cap_never_upgrades_self_to_a_premium_preset():
    # A cheap self-fusion asked for 12 samples (13 calls) that overruns max_calls=12
    # must NOT be "downgraded" onto the premium `wide`/`frontier` panel — it stays
    # self-fusion with a REDUCED sample count. (Regression: the ladder used to pick
    # max(candidates) across ALL presets and land on wide.)
    preset, delphi, samples, calls, note = quorum.cap_preset_by_calls(
        "self", 0, max_calls=12, samples=12
    )
    assert preset == "self"
    assert calls <= 12
    assert samples < 12 and samples >= 1
    # estimate = (samples + 1) * 1 round, judge included
    assert calls == (samples + 1)


def test_cap_floor_falls_to_self_not_premium_frontier():
    # A cost-conscious cap below any multi-model floor must fail open to the CHEAPEST
    # real panel (self, one sample) — never to the premium `frontier` (2 premium
    # models). Regression: the old floor hardcoded 'frontier'.
    preset, delphi, samples, calls, note = quorum.cap_preset_by_calls(
        "self", 0, max_calls=2, samples=3
    )
    assert preset == "self"
    assert samples == 1 and delphi == 0 and calls == 2


def test_cap_downgrades_frontier_within_tier_bound():
    # frontier (tier 2) overrunning a tiny cap may drop to a cheaper tier (self/
    # budget) but must never jump UP to wide.
    preset, delphi, samples, calls, note = quorum.cap_preset_by_calls(
        "frontier", 0, max_calls=2, samples=3
    )
    assert preset in {"self", "budget", "frontier"}
    assert preset != "wide"
    assert calls <= 2


# ── item 3: degraded-panel labeling in run_quorum ─────────────────────────────


def _degraded_runner(good_model):
    def runner(model, system, user):
        if "JUDGE" in system:
            return json.dumps({"probability": 0.4, "rationale": "j"})
        if model == good_model:
            return json.dumps(
                {"probability": 0.3, "confidence_low": 0.1, "confidence_high": 0.5,
                 "rationale": "ok", "crux": "c"}
            )
        return "not json at all"  # this panelist errors out

    return runner


def test_run_quorum_flags_degraded_when_only_one_survivor():
    result = quorum.run_quorum(
        question_title="Will X happen?",
        resolution_criteria="Resolves YES if X.",
        models=["a/keep", "b/drop"],
        runner=_degraded_runner("a/keep"),
        judge_model=None,
    )
    assert result.degraded is True
    assert result.degraded_reason and "lone survivor" in result.degraded_reason
    assert result.to_dict()["degraded"] is True


def test_run_quorum_healthy_panel_is_not_degraded():
    def runner(model, system, user):
        if "JUDGE" in system:
            return json.dumps({"probability": 0.4, "rationale": "j"})
        return json.dumps({"probability": 0.3, "rationale": "ok", "crux": "c"})

    result = quorum.run_quorum(
        question_title="Will X happen?",
        resolution_criteria="Resolves YES if X.",
        models=["a/m1", "b/m2"],
        runner=runner,
        judge_model=None,
    )
    assert result.degraded is False
    assert result.degraded_reason is None


# ── item 2: auto-run on a high-impact live commit ─────────────────────────────


def _high_impact_ledger(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "auto.db"))
    q = ledger.create_question(
        title="Will the agency approve the merger before 2028?",
        resolution_criteria="Resolves YES if approval is announced before 2028-01-01.",
        impact="high",
    )
    return ledger, q


def _on_config():
    return {
        "quorum": {
            "default_enabled": True,
            "default_scope": "high_impact",
            "max_calls": 12,
            "pool_method": "trimmed_geomean_odds",
        },
        "model": {"default": "openai/gpt-5.5"},
    }


def test_autorun_fires_start_job_on_high_impact_live(tmp_path, monkeypatch):
    from forecasting import cli as fcli
    import forecasting.jobs.types.quorum as qj
    import hermes_cli.config as cfgmod

    ledger, q = _high_impact_ledger(tmp_path)
    snap = SimpleNamespace(forecast_id="fc_snap_1")

    captured = {}

    def _fake_start_job(spec, *, wait=False):
        captured["spec"] = spec
        return "qr_test123"

    monkeypatch.setattr(qj, "start_job", _fake_start_job)
    monkeypatch.setattr(cfgmod, "load_config", _on_config)
    # Fail-open provider detection ⇒ frontier stays reachable (no self fallback).
    monkeypatch.setattr(quorum, "available_provider_slugs", lambda: None)

    fcli._maybe_autorun_quorum(
        ledger, q.id, snapshot=snap,
        has_panel=False, has_prior_snapshot=False, forecast_origin="live",
    )

    assert captured, "start_job should have been enqueued"
    spec = captured["spec"]
    assert spec["attach_snapshot"] == "fc_snap_1"
    assert spec["triggered_by"] == "auto_quorum"
    assert spec["preset"] == "frontier"
    assert spec["delphi_rounds"] == 1


def test_autorun_respects_config_off(tmp_path, monkeypatch):
    from forecasting import cli as fcli
    import forecasting.jobs.types.quorum as qj
    import hermes_cli.config as cfgmod

    ledger, q = _high_impact_ledger(tmp_path)

    def _must_not_run(spec, *, wait=False):
        raise AssertionError("auto-run must not fire when default_enabled is off")

    monkeypatch.setattr(qj, "start_job", _must_not_run)
    monkeypatch.setattr(cfgmod, "load_config", lambda: {"quorum": {"default_enabled": False}})

    fcli._maybe_autorun_quorum(
        ledger, q.id, snapshot=SimpleNamespace(forecast_id="x"),
        has_panel=False, has_prior_snapshot=False, forecast_origin="live",
    )


def test_autorun_is_fail_open_when_start_job_raises(tmp_path, monkeypatch, capsys):
    from forecasting import cli as fcli
    import forecasting.jobs.types.quorum as qj
    import hermes_cli.config as cfgmod

    ledger, q = _high_impact_ledger(tmp_path)

    def _boom(spec, *, wait=False):
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(qj, "start_job", _boom)
    monkeypatch.setattr(cfgmod, "load_config", _on_config)
    monkeypatch.setattr(quorum, "available_provider_slugs", lambda: None)

    # Must NOT raise — the commit already happened.
    fcli._maybe_autorun_quorum(
        ledger, q.id, snapshot=SimpleNamespace(forecast_id="x"),
        has_panel=False, has_prior_snapshot=False, forecast_origin="live",
    )
    out = capsys.readouterr().out
    assert "skipped" in out.lower()


def test_autorun_skips_non_live(tmp_path, monkeypatch):
    from forecasting import cli as fcli
    import forecasting.jobs.types.quorum as qj

    ledger, q = _high_impact_ledger(tmp_path)
    monkeypatch.setattr(qj, "start_job", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no")))
    # backtest origin ⇒ never auto-run
    fcli._maybe_autorun_quorum(
        ledger, q.id, snapshot=SimpleNamespace(forecast_id="x"),
        has_panel=False, has_prior_snapshot=False, forecast_origin="backtest",
    )


# ── item 5: forecast.quorum.status RPC handler ────────────────────────────────


def test_quorum_status_rpc_returns_job(tmp_path, monkeypatch):
    from tui_gateway import server
    import forecasting.jobs.types.quorum as qj

    job = {
        "run_id": "qr_rpc1", "question_id": "fq_1", "status": "done",
        "created_at": "2026-07-01T00:00:00+00:00",
        "spec": {}, "progress": [{"stage": "start", "detail": "x", "at": "t"}],
        "panel_run_id": "pr_9",
        "result": {"aggregate_probability": 0.4, "degraded": True,
                   "degraded_reason": "lone survivor"},
        "error": None,
    }
    qj.write_job(job)

    resp = server.handle_request(
        {"id": "1", "method": "forecast.quorum.status", "params": {"run_id": "qr_rpc1"}}
    )
    assert "result" in resp, resp
    r = resp["result"]
    assert r["status"] == "done"
    assert r["panel_run_id"] == "pr_9"
    assert r["degraded"] is True


def test_quorum_status_rpc_missing_run_id_errors():
    from tui_gateway import server

    resp = server.handle_request(
        {"id": "1", "method": "forecast.quorum.status", "params": {}}
    )
    assert "error" in resp


def test_quorum_status_rpc_unknown_run_errors():
    from tui_gateway import server

    resp = server.handle_request(
        {"id": "1", "method": "forecast.quorum.status", "params": {"run_id": "qr_nope"}}
    )
    assert "error" in resp


# ── item 6: evidence-gated extremization — cold-start = 1.0 ────────────────────


def test_derive_alpha_cold_start_is_identity(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "cold.db"))
    q = ledger.create_question(
        title="Will inflation exceed 3% in 2028?",
        resolution_criteria="Resolves YES if annual CPI > 3% for 2028.",
        impact="medium",
        domain="macro",
    )
    # No resolved data at all ⇒ the validated gate forces the slope back to 1.0.
    assert ledger.derive_extremize_alpha(q) == 1.0


def test_derive_alpha_disabled_by_default(monkeypatch):
    import forecasting.jobs.types.quorum as qj

    # The config flag defaults OFF, so the derivation never runs uninvited.
    assert qj._derive_alpha_enabled() is False


def test_explicit_alpha_override_blocks_derivation():
    import forecasting.jobs.types.quorum as qj

    assert qj._has_explicit_alpha_override(
        {"forecast_hooks": {"thresholds": {"alpha_extremize": 1.5}}}
    ) is True
    assert qj._has_explicit_alpha_override({"forecast_hooks": {"thresholds": {}}}) is False
    assert qj._has_explicit_alpha_override(None) is False


# ── the AGENT path: update_forecast fires the SAME auto-run seam ──────────────
# Without this wiring, full_forecast / the chained pipeline / `cycle run --agent`
# (which all commit through the tool's update_forecast) would never get the
# multi-model fusion the CLI `forecast update` verb gets — the flagship autonomy
# feature would fire only for the least lazy path.


def _tool_update_args(ledger, q, **over):
    args = {
        "action": "update_forecast",
        "db": ledger.db_path,
        "question_id": q.id,
        "probability_or_distribution": 0.62,
        "rationale": "Regulator signaled conditional approval in the latest filing.",
        "components": {
            "base_rate": {"probability": 0.55, "weight": 2},
            "case_specific": {"probability": 0.7, "weight": 1},
        },
        "reasons_up": ["fresh filing signals approval"],
        "reasons_down": ["remedies could still collapse"],
        "change_my_mind": "A formal second request would flip this.",
        "reasoning_methods": ["outside_view", "base_rate", "disconfirmation"],
        "require_panel": False,
        "require_fresh_evidence": False,
        "require_decision_readiness": False,
    }
    # Link any seeded reference class to THIS snapshot so the (now-ERROR) outside-view
    # anchor gate is satisfied for the high-impact agent commit (finding #4).
    try:
        rcs = ledger.list_reference_classes(q.id)
    except Exception:
        rcs = []
    if rcs:
        args["reference_class_refs"] = [rcs[0]["id"]]
    args.update(over)
    return args


def _seed_commit_prereqs(ledger, q):
    ledger.add_evidence(
        question_id=q.id,
        source_or_note="regulator filing 2026-07-01",
        claim="conditional approval signaled",
    )
    ledger.add_reference_class(
        question_id=q.id,
        name="mega-merger approvals",
        inclusion_criteria="US mergers over $10B since 2010",
        base_rate=0.55,
    )


def test_tool_update_forecast_fires_autorun(tmp_path, monkeypatch):
    import forecasting.jobs.types.quorum as qj
    import hermes_cli.config as cfgmod
    from tools.forecasting_tool import forecast_ledger_tool

    ledger, q = _high_impact_ledger(tmp_path)
    _seed_commit_prereqs(ledger, q)

    captured = {}
    monkeypatch.setattr(qj, "start_job", lambda spec, *, wait=False: (captured.update(spec=spec), "qr_tool1")[1])
    monkeypatch.setattr(cfgmod, "load_config", _on_config)
    monkeypatch.setattr(quorum, "available_provider_slugs", lambda: None)

    out = json.loads(forecast_ledger_tool(_tool_update_args(ledger, q)))

    assert out["success"] is True, out.get("error")
    qa = out.get("quorum_autorun")
    assert qa, "the agent commit path must fire the same auto-quorum seam as the CLI"
    assert qa["run_id"] == "qr_tool1"
    assert captured["spec"]["triggered_by"] == "auto_quorum"
    # the job attaches to the JUST-committed snapshot
    assert captured["spec"]["attach_snapshot"] == out["forecast_snapshot"]["forecast_id"]
    assert any("auto-run started" in note for note in qa["notes"])


def test_tool_update_forecast_autorun_respects_config_off(tmp_path, monkeypatch):
    import forecasting.jobs.types.quorum as qj
    import hermes_cli.config as cfgmod
    from tools.forecasting_tool import forecast_ledger_tool

    ledger, q = _high_impact_ledger(tmp_path)
    _seed_commit_prereqs(ledger, q)
    monkeypatch.setattr(qj, "start_job", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not fire")))
    monkeypatch.setattr(cfgmod, "load_config", lambda: {"quorum": {"default_enabled": False}})

    out = json.loads(forecast_ledger_tool(_tool_update_args(ledger, q)))
    assert out["success"] is True
    # The decline is now AUDITABLE (the operator's Senate-batch review could
    # not tell a by-design skip from silent breakage): a skip record with a
    # reason replaces the old silent omission — and no job may start.
    assert out["quorum_autorun"]["skipped"] is True
    assert out["quorum_autorun"]["reason"]


def test_tool_update_forecast_autorun_skipped_when_panel_attached(tmp_path, monkeypatch):
    import forecasting.jobs.types.quorum as qj
    import hermes_cli.config as cfgmod
    from tools.forecasting_tool import forecast_ledger_tool

    ledger, q = _high_impact_ledger(tmp_path)
    _seed_commit_prereqs(ledger, q)
    panel = ledger.record_panel_run(
        question_id=q.id,
        estimates=[
            {"perspective": "base-rate", "probability": 0.5},
            {"perspective": "insider", "probability": 0.6},
            {"perspective": "skeptic", "probability": 0.45},
        ],
        aggregation_method="median",
    )
    monkeypatch.setattr(qj, "start_job", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not fire")))
    monkeypatch.setattr(cfgmod, "load_config", _on_config)

    out = json.loads(forecast_ledger_tool(_tool_update_args(ledger, q, panel_run_ref=panel["id"])))
    assert out["success"] is True
    # The decline is now AUDITABLE (the operator's Senate-batch review could
    # not tell a by-design skip from silent breakage): a skip record with a
    # reason replaces the old silent omission — and no job may start.
    assert out["quorum_autorun"]["skipped"] is True
    assert out["quorum_autorun"]["reason"]


def test_tool_update_forecast_autorun_fail_open(tmp_path, monkeypatch):
    import forecasting.jobs.types.quorum as qj
    import hermes_cli.config as cfgmod
    from tools.forecasting_tool import forecast_ledger_tool

    ledger, q = _high_impact_ledger(tmp_path)
    _seed_commit_prereqs(ledger, q)
    monkeypatch.setattr(qj, "start_job", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("spawn failed")))
    monkeypatch.setattr(cfgmod, "load_config", _on_config)
    monkeypatch.setattr(quorum, "available_provider_slugs", lambda: None)

    out = json.loads(forecast_ledger_tool(_tool_update_args(ledger, q)))
    # the commit stands; the failed auto-run is invisible except for the absence
    assert out["success"] is True
    # Hard failure inside the runner: fail-open swallows it — either the key is
    # absent (threw before the skip records) or it carries a skipped marker;
    # it must NEVER claim a started run.
    assert "quorum_autorun" not in out or out["quorum_autorun"].get("skipped") or out["quorum_autorun"].get("error")
