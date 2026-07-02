"""R4 Living Models: score model_runs at resolution, on-read per-model skill,
skill-weighted deterministic re-pool + audit trail, and the surfacing seams."""

from __future__ import annotations

import argparse

import pytest

from forecasting import ForecastLedger
from forecasting.models import OutcomeSpace


def _ledger(tmp_path) -> ForecastLedger:
    ledger = ForecastLedger(db_path=str(tmp_path / "r4.db"))
    ledger.initialize_schema()
    return ledger


def _binary_q(ledger, title="Will candidate R win the 2026 race?"):
    return ledger.create_question(
        title=title,
        resolution_criteria="Resolves yes if the Republican nominee is certified as the winner; otherwise no.",
    )


def _numeric_q(ledger, title="What will the closing index level be on 2026-12-31?"):
    return ledger.create_question(
        title=title,
        resolution_criteria="Resolves to the official closing index level published on 2026-12-31.",
        outcome_space=OutcomeSpace(type="numeric", units="points", bounds=[0.0, 10000.0]),
    )


def _baseline_snapshot(ledger, qid, prob=0.55, mmid=None):
    """A binary snapshot with a market component + a model-sourced component."""
    model_component = {"name": "market model leg", "probability": 0.60, "weight": 2}
    if mmid is not None:
        model_component["source"] = f"market_model:{mmid}"
    ledger.create_snapshot(
        question_id=qid,
        probability_or_distribution=prob,
        rationale="baseline ensemble",
        method="log_odds_pool",
        ensemble_components={
            "components": [
                {"name": "markets", "source": "manifold:race", "probability": 0.55, "weight": 3},
                model_component,
            ]
        },
        require_panel=False,
    )
    ledger.add_watched_source(scope_type="question", scope_ref=qid, source="race", source_type="manifold")


def _market_fetcher(probability):
    def fetch(specs):
        return [
            {
                "source_type": spec["source_type"],
                "source": spec["source"],
                "success": True,
                "payloads": [
                    {
                        "source_or_note": f"{spec['source_type']} {spec['source']}",
                        "source_type": f"adapter:{spec['source_type']}",
                        "claim": "market reading",
                        "summary": "",
                        "metadata": {
                            "adapter": spec["source_type"],
                            "source": spec["source"],
                            "adapter_item": {"probability": probability},
                        },
                    }
                ],
                "error": None,
            }
            for spec in specs
        ]

    return fetch


# ── 1. scoring at resolution ────────────────────────────────────────────────


def test_binary_model_run_scored_brier_at_resolution(tmp_path):
    ledger = _ledger(tmp_path)
    q = _binary_q(ledger)
    ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=0.6, rationale="r", method="m",
        require_panel=False,
    )
    run = ledger.record_model_run(
        question_id=q.id, model_type="ols", output={"value": 0.8}, market_model_id="mm_000000000001",
    )
    ledger.resolve_question(question_id=q.id, outcome="yes")
    scored = ledger.get_model_run(run["id"])
    assert scored["scored_at"] is not None
    assert scored["interval_hit"] is None  # binary → no interval
    assert scored["outcome_score"] == pytest.approx((0.8 - 1.0) ** 2)  # 0.04


def test_numeric_model_run_scored_coverage_and_abs_error(tmp_path):
    ledger = _ledger(tmp_path)
    q = _numeric_q(ledger)
    ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=100.0, rationale="r", method="m",
        require_panel=False,
    )
    hit = ledger.record_model_run(
        question_id=q.id, model_type="arima", output={"projected_value": 100.0, "lo": 90.0, "hi": 110.0},
    )
    miss = ledger.record_model_run(
        question_id=q.id, model_type="arima", output={"projected_value": 50.0, "lo": 40.0, "hi": 60.0},
    )
    ledger.resolve_question(question_id=q.id, outcome=105.0)
    hit_row = ledger.get_model_run(hit["id"])
    miss_row = ledger.get_model_run(miss["id"])
    assert hit_row["interval_hit"] == 1
    assert hit_row["outcome_score"] == pytest.approx(5.0)
    assert miss_row["interval_hit"] == 0
    assert miss_row["outcome_score"] == pytest.approx(55.0)


def test_forecast_refresh_run_not_scored_as_model(tmp_path):
    """A forecast_refresh run stores proposed_probability, which is deliberately
    NOT matched — the desk's own number never masquerades as a model observation."""
    ledger = _ledger(tmp_path)
    q = _binary_q(ledger)
    ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=0.6, rationale="r", method="m",
        require_panel=False,
    )
    run = ledger.record_model_run(
        question_id=q.id, model_type="forecast_refresh", output={"proposed_probability": 0.7},
    )
    ledger.resolve_question(question_id=q.id, outcome="yes")
    assert ledger.get_model_run(run["id"])["scored_at"] is None


# ── 2. model skill math ─────────────────────────────────────────────────────


def _resolve_binary_with_model(ledger, mmid, prob, outcome, i):
    q = _binary_q(ledger, title=f"Binary skill probe {i}?")
    ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="r", method="m",
        require_panel=False,
    )
    ledger.record_model_run(
        question_id=q.id, model_type="ols", output={"value": prob}, market_model_id=mmid,
    )
    ledger.resolve_question(question_id=q.id, outcome=outcome)


def test_model_skill_cold_start_is_identity(tmp_path):
    ledger = _ledger(tmp_path)
    mmid = "mm_00000000000a"
    # Only 3 scored binaries — below the min-sample gate (10).
    for i in range(3):
        _resolve_binary_with_model(ledger, mmid, 0.9, "yes", i)
    skill = ledger.model_skill(market_model_id=mmid)
    assert skill["n_binary"] == 3
    assert skill["status"] == "insufficient_track_record"
    assert skill["weight_multiplier"] == 1.0


def test_model_skill_measured_shrunk_above_gate(tmp_path):
    ledger = _ledger(tmp_path)
    mmid = "mm_00000000000b"
    # 12 confident + correct binaries → strong positive edge over the 0.25 baseline.
    for i in range(12):
        _resolve_binary_with_model(ledger, mmid, 0.9, "yes", i)
    skill = ledger.model_skill(market_model_id=mmid)
    assert skill["n_binary"] == 12
    assert skill["status"] == "measured"
    # Brier of 0.9 vs yes = 0.01; edge = 0.25 - 0.01 = 0.24, shrunk toward 0 but
    # still a meaningful lift above 1.0 (and clipped below the 4.0 ceiling).
    assert skill["brier"] == pytest.approx(0.01)
    assert 1.0 < skill["weight_multiplier"] <= 4.0


def test_model_skill_numeric_coverage_and_mae(tmp_path):
    """A numeric model's skill reports coverage + MAE and never pollutes the
    binary weight multiplier (which stays identity with no binary runs)."""
    ledger = _ledger(tmp_path)
    mmid = "mm_00000000000f"
    # Two numeric questions: one interval hit (err 5), one interval miss (err 55).
    for i, (proj, lo, hi, outcome) in enumerate(
        [(100.0, 90.0, 110.0, 105.0), (50.0, 40.0, 60.0, 105.0)]
    ):
        q = _numeric_q(ledger, title=f"Numeric skill probe {i}?")
        ledger.create_snapshot(
            question_id=q.id, probability_or_distribution=proj, rationale="r", method="m",
            require_panel=False,
        )
        ledger.record_model_run(
            question_id=q.id, model_type="arima",
            output={"projected_value": proj, "lo": lo, "hi": hi}, market_model_id=mmid,
        )
        ledger.resolve_question(question_id=q.id, outcome=outcome)
    skill = ledger.model_skill(market_model_id=mmid)
    assert skill["n_binary"] == 0
    assert skill["n_numeric"] == 2
    assert skill["coverage"] == pytest.approx(0.5)
    assert skill["mae"] == pytest.approx(30.0)  # (5 + 55) / 2
    assert skill["weight_multiplier"] == 1.0  # no binary evidence → identity


def test_model_skill_by_model_type_filter(tmp_path):
    ledger = _ledger(tmp_path)
    _seed_model_with_skill(ledger, "mm_0000000000aa")  # model_type "ols"
    by_type = ledger.model_skill(model_type="ols")
    assert by_type["n_binary"] == 12
    assert by_type["status"] == "measured"
    # A different model_type has no scored runs.
    assert ledger.model_skill(model_type="montecarlo")["n_scored"] == 0


# ── 3. skill-weighted re-pool ───────────────────────────────────────────────


def _seed_model_with_skill(ledger, mmid, prob=0.9, outcome="yes", n=12):
    for i in range(n):
        _resolve_binary_with_model(ledger, mmid, prob, outcome, i)


def test_repool_applies_skill_multiplier_and_audit_trail(tmp_path):
    ledger = _ledger(tmp_path)
    mmid = "mm_00000000000c"
    _seed_model_with_skill(ledger, mmid)
    multiplier = ledger.model_skill(market_model_id=mmid)["weight_multiplier"]
    assert multiplier > 1.0

    q = _binary_q(ledger, title="Live question weighted by model skill?")
    _baseline_snapshot(ledger, q.id, mmid=mmid)

    weighted = ledger.refresh_forecast(q.id, fetcher=_market_fetcher(0.72), skill_weights=True)

    # Audit trail present on the result and the snapshot metadata.
    applied = weighted["skill_multipliers"]
    assert len(applied) == 1
    assert applied[0]["market_model_id"] == mmid
    assert applied[0]["multiplier"] == pytest.approx(multiplier)
    assert applied[0]["new_weight"] == pytest.approx(applied[0]["prior_weight"] * multiplier)
    snap_meta = ledger.get_current_snapshot(q.id).metadata
    assert snap_meta["skill_multipliers"][0]["market_model_id"] == mmid
    # Persisted component weight stays the ORIGINAL (unscaled) so it never compounds.
    comps = ledger.get_current_snapshot(q.id).ensemble_components["components"]
    model_comp = next(c for c in comps if c.get("source") == f"market_model:{mmid}")
    assert model_comp["weight"] == pytest.approx(2.0)


def test_repool_below_gate_skips_skill_scan(tmp_path):
    """Cold-start / below-gate models pay ~nothing: the O(resolved) skill scan is
    short-circuited by the cheap scored-run precheck, so a batch sweep over
    model-bearing questions does not run model_skill per question until a model
    actually clears the sample gate. Behaviour (identity multiplier) is unchanged."""
    ledger = _ledger(tmp_path)
    mmid = "mm_0000000000be"
    # 3 scored binaries — below the min-sample gate (10).
    for i in range(3):
        _resolve_binary_with_model(ledger, mmid, 0.9, "yes", i)
    assert ledger._market_model_scored_run_count(mmid) == 3

    q = _binary_q(ledger, title="Below-gate model question?")
    _baseline_snapshot(ledger, q.id, mmid=mmid)

    calls: list[str] = []
    real_model_skill = ledger.model_skill

    def _spy(*args, **kwargs):
        calls.append(kwargs.get("market_model_id") or "?")
        return real_model_skill(*args, **kwargs)

    ledger.model_skill = _spy  # type: ignore[method-assign]
    out = ledger.refresh_forecast(q.id, fetcher=_market_fetcher(0.72), skill_weights=True)
    # The full skill scan was skipped (precheck proved identity), yet the result is
    # the same identity outcome: no multiplier applied.
    assert calls == []
    assert out["skill_multipliers"] == []


def test_repool_at_gate_still_scans_and_weights(tmp_path):
    """The precheck never suppresses a real, gate-clearing skill weight."""
    ledger = _ledger(tmp_path)
    mmid = "mm_0000000000bf"
    _seed_model_with_skill(ledger, mmid)  # 12 scored binaries
    assert ledger._market_model_scored_run_count(mmid) >= ledger.MODEL_WEIGHT_MIN_SAMPLE

    q = _binary_q(ledger, title="At-gate model question?")
    _baseline_snapshot(ledger, q.id, mmid=mmid)
    out = ledger.refresh_forecast(q.id, fetcher=_market_fetcher(0.72), skill_weights=True)
    assert len(out["skill_multipliers"]) == 1
    assert out["skill_multipliers"][0]["market_model_id"] == mmid


def test_repool_config_off_is_identity(tmp_path):
    """With skill weighting off the pooled number matches the unweighted re-pool."""
    ledger = _ledger(tmp_path)
    mmid = "mm_00000000000d"
    _seed_model_with_skill(ledger, mmid)

    q_on = _binary_q(ledger, title="On question?")
    _baseline_snapshot(ledger, q_on.id, mmid=mmid)
    q_off = _binary_q(ledger, title="Off question?")
    _baseline_snapshot(ledger, q_off.id, mmid=mmid)

    on = ledger.refresh_forecast(q_on.id, fetcher=_market_fetcher(0.72), skill_weights=True, dry_run=True)
    off = ledger.refresh_forecast(q_off.id, fetcher=_market_fetcher(0.72), skill_weights=False, dry_run=True)

    assert off["skill_multipliers"] == []
    assert on["proposed_probability"] != pytest.approx(off["proposed_probability"])


def test_repool_no_model_component_is_untouched(tmp_path):
    ledger = _ledger(tmp_path)
    q = _binary_q(ledger, title="No model component?")
    _baseline_snapshot(ledger, q.id, mmid=None)  # no model-sourced component
    out = ledger.refresh_forecast(q.id, fetcher=_market_fetcher(0.72), skill_weights=True)
    assert out["skill_multipliers"] == []


# ── 4. refresh phase default on + bounded ───────────────────────────────────


def test_install_script_writes_refresh_market_models_flag(tmp_path):
    from forecasting import cron_runner

    script = tmp_path / "job.py"
    cron_runner.install_script(script, refresh_market_models=True)
    body = script.read_text()
    assert "--refresh-market-models" in body

    script2 = tmp_path / "job2.py"
    cron_runner.install_script(script2, refresh_market_models=False)
    assert "--refresh-market-models" not in script2.read_text()


def test_refresh_market_models_bounded_to_open_linked(tmp_path):
    """The nightly phase only touches active models linked to still-OPEN questions."""
    from forecasting import cron_runner

    ledger = _ledger(tmp_path)
    # A model whose linked question is already resolved → must be skipped.
    q = _binary_q(ledger, title="Resolved linked question?")
    ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=0.6, rationale="r", method="m",
        require_panel=False,
    )
    model = ledger.create_market_model(title="T", question="Q", spec={"forecast_question_id": q.id})
    ledger.resolve_question(question_id=q.id, outcome="yes")

    out = cron_runner.refresh_market_models(ledger)
    assert out["checked"] == 0  # resolved question → not checked
    assert out["alerted"] == []


# ── 5. surfacing: gateway payload + CLI ─────────────────────────────────────


def test_gateway_model_list_includes_skill(tmp_path, monkeypatch):
    import forecasting.ledger as ledger_mod
    import tui_gateway.server as server

    ledger = _ledger(tmp_path)
    mmid_model = ledger.create_market_model(title="Skill model", question="Q")
    # Give THIS market model a measured skill by scoring runs tagged with its id.
    _seed_model_with_skill(ledger, mmid_model["id"])

    # The handler does `from forecasting.ledger import ForecastLedger; ForecastLedger()`,
    # so patch the class the handler resolves at call time.
    monkeypatch.setattr(ledger_mod, "ForecastLedger", lambda *a, **k: ledger)
    resp = server._methods["markets.model.list"]("rid", {"status": "active"})
    models = resp["result"]["models"]
    row = next(m for m in models if m["id"] == mmid_model["id"])
    assert row["skill"] is not None
    assert row["skill"]["status"] == "measured"
    assert row["skill"]["weight_multiplier"] > 1.0


def test_cli_model_skill_one_liner(tmp_path, capsys):
    from forecasting.cli import register_cli

    parser = argparse.ArgumentParser(prog="forecast-test")
    sub = parser.add_subparsers(dest="command")
    register_cli(sub)

    ledger = _ledger(tmp_path)
    mmid = "mm_00000000000e"
    _seed_model_with_skill(ledger, mmid)

    args = parser.parse_args(["forecast", "--db", str(tmp_path / "r4.db"), "model", "skill", mmid])
    args._forecast_handler(args)
    out = capsys.readouterr().out
    assert "model skill" in out
    assert "weight multiplier" in out
    assert "measured" in out
