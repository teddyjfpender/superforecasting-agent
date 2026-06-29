"""Seed the AI-infrastructure investment thesis from the design doc.

Instantiates, formally and idempotently:
  - ~55 member forecast questions (binary + distributional) from
    docs/plans/thesis-level-macro-forecasting-example-ai-stocks.md,
  - the "AI infrastructure scarcity thesis" with its §22 weighted members,
  - the per-name entities (NBIS/CRWV/BE/...) with their §22 suitability vectors,
  - the §23 "AI Infrastructure Factor (12m)" basket of per-stock return distributions,
  - exploratory BASELINE priors for every member (so the thesis/entities/factor
    produce output immediately) — clearly marked exploratory + supersedable by a
    live agent run.

Idempotent: questions are skipped by title, entities by name, links by (thesis,member).
Respects FORECAST_LEDGER_DB. Re-running only adds what's missing + re-aggregates.

Run:  python3 scripts/seed_ai_infra_thesis.py            (seeds priors + aggregates)
      python3 scripts/seed_ai_infra_thesis.py --no-baselines   (structure only)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forecasting import ForecastLedger
from forecasting.ledger import allow_ledger_writes
from forecasting.models import OutcomeSpace

# ── 1. Authored question specs (from the AI-infra doc) ───────────────────────
# Authored alongside this script (see scripts/ai_infra_questions.json); each is a
# dict with the create_question fields + a stable `key` used by the thesis /
# entity / factor wiring below.
_QUESTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_infra_questions.json")
AUTHORED_QUESTIONS: list[dict] = []
if os.path.exists(_QUESTIONS_FILE):
    with open(_QUESTIONS_FILE, encoding="utf-8") as _fh:
        AUTHORED_QUESTIONS = json.load(_fh)

# ── 2. Per-name 12-month return + max-drawdown distributions (templated) ─────
# These feed the §23 factor (returns) and the entity downside weights (drawdowns).
RETURN_TICKERS = [
    "NBIS", "CRWV", "BE", "APLD", "IREN", "CORZ", "SNDK", "MU",
    "RIOT", "CLSK", "BITF", "BTDR", "NVDA", "AMD", "TSM", "ASML",
]
DRAWDOWN_TICKERS = ["NBIS", "CRWV", "BE", "APLD", "IREN", "CORZ", "SNDK", "MU"]


def _templated_questions() -> list[dict]:
    out: list[dict] = []
    for ticker in RETURN_TICKERS:
        out.append({
            "key": f"ret_{ticker.lower()}",
            "title": f"What will the 12-month total return of {ticker} be (2026-06-30 to 2027-06-30)?",
            "description": (
                f"Per-name total-return distribution for {ticker}, conditional on the AI-infrastructure "
                "thesis forecasts. Feeds the AI Infrastructure Factor and the entity suitability layer."
            ),
            "outcome_type": "distribution",
            "units": "percent_return",
            "bounds": [-90.0, 250.0],
            "choices": [],
            "resolution_criteria": (
                f"Resolves to the realized 12-month total return (price change plus dividends) of {ticker} "
                "from the 2026-06-30 close to the 2027-06-30 close, expressed in percent."
            ),
            "resolution_source": f"{ticker} total-return from exchange/market close prices (e.g. Yahoo Finance).",
            "domain": "ai_returns",
            "topics": [ticker.lower(), "total_return", "ai_infra"],
            "impact": "medium",
            "close_time": "2027-06-29",
            "resolution_time": "2027-06-30",
        })
    for ticker in DRAWDOWN_TICKERS:
        out.append({
            "key": f"dd_{ticker.lower()}",
            "title": f"What will {ticker}'s maximum drawdown be over the next 12 months?",
            "description": (
                f"Left-tail / permanent-impairment risk for {ticker}; feeds the entity suitability layer (inverted)."
            ),
            "outcome_type": "distribution",
            "units": "percent_drawdown",
            "bounds": [0.0, 95.0],
            "choices": [],
            "resolution_criteria": (
                f"Resolves to the maximum peak-to-trough drawdown (percent) of {ticker} between 2026-06-30 and "
                "2027-06-30, measured on daily closes."
            ),
            "resolution_source": f"{ticker} daily closes from exchange/market data.",
            "domain": "ai_returns",
            "topics": [ticker.lower(), "drawdown", "risk"],
            "impact": "low",
            "close_time": "2027-06-29",
            "resolution_time": "2027-06-30",
        })
    return out


# ── 3. The thesis + §22 weighted members ─────────────────────────────────────
# member = (key, weight, direction, role[, target, hi_is_good])
THESIS = {
    "title": "AI infrastructure scarcity thesis",
    "description": (
        "AI scaling creates a sustained shortage of compute, power, data-center capacity, memory/storage, and "
        "energy infrastructure; the best equity returns accrue to constrained bottleneck owners, not only model "
        "labs or NVDA. Health aggregates the tagged member forecasts (§22 weighting)."
    ),
    "criteria": (
        "Aggregate health of the tagged member forecasts; reviewed after each member's latest run. Non-resolving "
        "meta-forecast (calibration-exempt)."
    ),
    "domain": "ai_infra",
    "topics": ["ai_infra", "thesis", "compute", "power", "memory"],
    "members": [
        # §22 core: 30% capex, 20% compute, 20% power, 15% monetization, 15% overbuild (inverted)
        ("capex_accel", 3.0, "support", "capex"),
        ("d_capex_2026", 1.5, "support", "capex_dist", 400.0, True),
        ("compute_shortage", 2.0, "support", "compute"),
        ("d_supply_demand", 1.0, "support", "compute_dist", 5.0, True),
        ("power_binding", 2.0, "support", "power"),
        ("d_power_severity", 1.0, "support", "power_dist", 50.0, True),
        ("monetization_validates", 1.5, "support", "monetization"),
        ("d_ai_revenue", 0.75, "support", "monetization_dist", 200.0, True),
        ("overbuild_2027", 1.5, "inverted", "overbuild_risk"),
        ("d_utilization", 0.75, "support", "utilization", 75.0, True),
        # duration + execution
        ("scarcity_2026", 1.5, "support", "duration"),
        ("nbis_exec", 0.75, "support", "execution"),
        ("crwv_margin", 0.75, "support", "execution"),
        # red-team risks (inverted)
        ("gpu_collapse", 0.75, "inverted", "redteam"),
        ("capex_guidedown", 0.75, "inverted", "redteam"),
        ("power_solved", 0.5, "inverted", "redteam"),
        ("model_progress_slows", 0.75, "inverted", "redteam"),
    ],
}

# ── 4. Entities — §22 per-name suitability weight vectors ─────────────────────
# weight = (key, weight, direction)
ENTITIES = [
    {"name": "NBIS", "kind": "equity", "label": "Nebius", "weights": [
        ("compute_shortage", 0.35, "support"), ("d_nbis_runrate", 0.25, "support"),
        ("d_gpu_price", 0.15, "support"), ("d_cost_capital", 0.15, "inverted"),
        ("d_valuation_multiple", 0.10, "inverted")]},
    {"name": "CRWV", "kind": "equity", "label": "CoreWeave", "weights": [
        ("compute_shortage", 0.35, "support"), ("d_crwv_revenue", 0.25, "support"),
        ("d_gpu_price", 0.15, "support"), ("d_cost_capital", 0.15, "inverted"),
        ("d_crwv_margin", 0.10, "support")]},
    {"name": "BE", "kind": "equity", "label": "Bloom Energy", "weights": [
        ("d_power_severity", 0.40, "support"), ("d_behind_meter_gw", 0.25, "support"),
        ("d_bloom_orders", 0.20, "support"), ("d_bloom_margin", 0.10, "support"),
        ("d_cost_capital", 0.05, "inverted")]},
    {"name": "IREN", "kind": "equity", "label": "IREN", "weights": [
        ("d_power_severity", 0.30, "support"), ("d_miner_mw", 0.25, "support"),
        ("d_miner_share", 0.20, "support"), ("d_cost_capital", 0.15, "inverted"),
        ("dd_iren", 0.10, "inverted")]},
    {"name": "CORZ", "kind": "equity", "label": "Core Scientific", "weights": [
        ("d_power_severity", 0.30, "support"), ("d_miner_mw", 0.25, "support"),
        ("d_miner_share", 0.20, "support"), ("d_cost_capital", 0.15, "inverted"),
        ("dd_corz", 0.10, "inverted")]},
    {"name": "APLD", "kind": "equity", "label": "Applied Digital", "weights": [
        ("d_power_severity", 0.30, "support"), ("d_miner_mw", 0.25, "support"),
        ("d_miner_share", 0.20, "support"), ("d_cost_capital", 0.15, "inverted"),
        ("dd_apld", 0.10, "inverted")]},
    {"name": "SNDK", "kind": "equity", "label": "SanDisk", "weights": [
        ("d_memory_index", 0.35, "support"), ("d_sndk_ai_share", 0.25, "support"),
        ("d_capex_2026", 0.15, "support"), ("d_valuation_multiple", 0.15, "inverted"),
        ("dd_sndk", 0.10, "inverted")]},
    {"name": "MU", "kind": "equity", "label": "Micron", "weights": [
        ("d_memory_index", 0.35, "support"), ("d_ai_revenue", 0.25, "support"),
        ("d_capex_2026", 0.20, "support"), ("dd_mu", 0.20, "inverted")]},
    {"name": "NVDA", "kind": "equity", "label": "Nvidia", "weights": [
        ("accelerator_share", 0.50, "support"), ("d_capex_2026", 0.30, "support"),
        ("d_ai_revenue", 0.20, "support")]},
    {"name": "AMD", "kind": "equity", "label": "AMD", "weights": [
        ("accelerator_share", 0.40, "inverted"), ("d_capex_2026", 0.30, "support"),
        ("compute_shortage", 0.30, "support")]},
    {"name": "TSM", "kind": "equity", "label": "TSMC", "weights": [
        ("d_capex_2026", 0.40, "support"), ("compute_shortage", 0.30, "support"),
        ("d_ai_revenue", 0.30, "support")]},
    {"name": "ASML", "kind": "equity", "label": "ASML", "weights": [
        ("d_capex_2026", 0.35, "support"), ("compute_shortage", 0.35, "support"),
        ("d_ai_revenue", 0.30, "support")]},
    {"name": "SMH", "kind": "etf", "label": "VanEck Semiconductor ETF", "weights": [
        ("d_capex_2026", 0.40, "support"), ("compute_shortage", 0.30, "support"),
        ("accelerator_share", 0.30, "support")]},
]

# ── 5. The §23 AI Infrastructure Factor ──────────────────────────────────────
# constituent = (return_key, weight, direction)  — weights are the §23 sleeves.
FACTOR = {
    "title": "AI Infrastructure Factor (12m)",
    "description": (
        "§23 custom AI Infrastructure factor: 25% neoclouds + 25% power/data-center + 20% memory/storage + "
        "15% miner-to-HPC optionality + 15% broad AI semis. Portfolio 12-month return distribution + volatility "
        "+ downside, aggregated from the per-name return forecasts."
    ),
    "criteria": (
        "Portfolio total return of the weighted constituent basket over 12 months; reviewed after the constituents "
        "update. Non-resolving meta-forecast (calibration-exempt)."
    ),
    "units": "percent_return",
    "domain": "ai_infra",
    "topics": ["ai_infra", "factor", "basket"],
    "constituents": (
        # 25% neoclouds
        [("ret_nbis", 0.125, "long"), ("ret_crwv", 0.125, "long")]
        # 25% power / data-center
        + [("ret_be", 0.0625, "long"), ("ret_apld", 0.0625, "long"),
           ("ret_iren", 0.0625, "long"), ("ret_corz", 0.0625, "long")]
        # 20% memory / storage
        + [("ret_sndk", 0.10, "long"), ("ret_mu", 0.10, "long")]
        # 15% miner-to-HPC optionality
        + [("ret_riot", 0.0375, "long"), ("ret_clsk", 0.0375, "long"),
           ("ret_bitf", 0.0375, "long"), ("ret_btdr", 0.0375, "long")]
        # 15% broad AI semis
        + [("ret_nvda", 0.0375, "long"), ("ret_amd", 0.0375, "long"),
           ("ret_tsm", 0.0375, "long"), ("ret_asml", 0.0375, "long")]
    ),
}

# ── 6. Exploratory baseline priors (so the structure produces output now) ────
# Doc-informed central tendencies for the flagship signals; everything else gets
# a wide, near-uninformative prior. These are origin="exploratory" (never scored)
# and are superseded the moment a live agent run commits a real forecast.
BINARY_PRIORS = {
    "capex_accel": 0.60, "compute_shortage": 0.62, "inference_majority": 0.55,
    "power_binding": 0.66, "behind_meter_5gw": 0.58, "bloom_orders": 0.50,
    "crwv_margin": 0.55, "nbis_exec": 0.55, "miner_contracts": 0.45,
    "nbis_scaleup": 0.52, "crwv_durability": 0.55, "be_power_deals": 0.50,
    "miner_conversion": 0.44, "memory_pricing_binary": 0.57, "accelerator_share": 0.70,
    "conc_persists": 0.65, "conc_maintain": 0.55, "basket_alpha_binary": 0.50,
    "scarcity_2026": 0.72, "overbuild_2027": 0.36, "monetization_validates": 0.55,
    "gpu_collapse": 0.25, "capex_guidedown": 0.30, "power_solved": 0.20,
    "model_progress_slows": 0.30,
}
# Distributional central-tendency overrides (doc §24 etc.); else midpoint of bounds.
DIST_MEAN_OVERRIDES = {
    "d_capex_2026": 390.0, "d_supply_demand": 15.0, "d_gpu_price": 5.0,
    "d_power_demand_gw": 35.0, "d_power_severity": 55.0, "d_behind_meter_gw": 7.0,
    "d_ai_revenue": 175.0, "d_capex_rev_ratio": 3.0, "d_utilization": 80.0,
    "d_overbuild_drawdown": -20.0, "d_basket_return": 12.0, "d_basket_alpha": 5.0,
    "d_contract_duration": 4.0, "d_cost_capital": 9.0, "d_valuation_multiple": 12.0,
    "d_scarcity_peak": 6.0, "d_miner_share": 18.0,
}
RETURN_PRIOR = {"mean": 15.0, "sd": 55.0}      # wide, mildly positive
DRAWDOWN_PRIOR = {"mean": 38.0, "sd": 18.0}


def _baseline_payload(q: dict):
    """A reasonable exploratory prior for one question (prob or distribution dict)."""
    key, otype = q["key"], q["outcome_type"]
    if otype == "binary":
        return BINARY_PRIORS.get(key, 0.5)
    if otype == "categorical":
        choices = q.get("choices") or []
        if not choices:
            return None
        return {c: round(1.0 / len(choices), 4) for c in choices}
    # distribution / numeric
    bounds = q.get("bounds") or []
    lo, hi = (bounds[0], bounds[1]) if len(bounds) == 2 else (0.0, 1.0)
    if key.startswith("ret_"):
        mean, sd = RETURN_PRIOR["mean"], RETURN_PRIOR["sd"]
    elif key.startswith("dd_"):
        mean, sd = DRAWDOWN_PRIOR["mean"], DRAWDOWN_PRIOR["sd"]
    else:
        mean = DIST_MEAN_OVERRIDES.get(key, (lo + hi) / 2.0)
        sd = max((hi - lo) / 6.0, 1e-6)
    q05 = max(lo, mean - 1.645 * sd)
    q95 = min(hi, mean + 1.645 * sd)
    return {"mean": round(mean, 4), "sd": round(sd, 4), "q05": round(q05, 4),
            "q50": round(mean, 4), "q95": round(q95, 4)}


def _outcome_space(q: dict) -> OutcomeSpace:
    otype = q["outcome_type"]
    if otype == "binary":
        return OutcomeSpace(type="binary")
    if otype == "categorical":
        return OutcomeSpace(type="categorical", choices=list(q.get("choices") or []))
    bounds = q.get("bounds") or []
    return OutcomeSpace(
        type=otype,
        units=(q.get("units") or None),
        bounds=([float(bounds[0]), float(bounds[1])] if len(bounds) == 2 else None),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the AI-infrastructure thesis")
    parser.add_argument("--db", default=None, help="ledger db path (else FORECAST_LEDGER_DB / default)")
    parser.add_argument("--no-baselines", action="store_true", help="create structure only; no exploratory priors")
    parser.add_argument("--rho", type=float, default=0.4)
    args = parser.parse_args(argv)

    questions = list(AUTHORED_QUESTIONS) + _templated_questions()
    if not AUTHORED_QUESTIONS:
        print("ERROR: AUTHORED_QUESTIONS is empty — fill the authored specs first.", file=sys.stderr)
        return 2

    # validate every wired key resolves to a question
    keys = {q["key"] for q in questions}
    referenced = (
        {m[0] for m in THESIS["members"]}
        | {w[0] for e in ENTITIES for w in e["weights"]}
        | {c[0] for c in FACTOR["constituents"]}
    )
    missing = sorted(referenced - keys)
    if missing:
        print(f"ERROR: wiring references unknown question keys: {missing}", file=sys.stderr)
        return 2

    ledger = ForecastLedger(args.db)
    by_title = {q.title: q for q in ledger.list_questions(limit=10000)}
    key_to_id: dict[str, str] = {}
    created = skipped = baselined = 0

    # Sanctioned operator seed tool: open the ledger-write context so the
    # create_question / create_snapshot calls below pass the default-ON
    # direct-write gate (which guards against the AGENT scripting fabricated
    # forecasts, not against operator seeding). See
    # forecasting.ledger.allow_ledger_writes.
    with allow_ledger_writes(reason="operator seed script"):
        for q in questions:
            existing = by_title.get(q["title"])
            if existing is not None:
                key_to_id[q["key"]] = existing.id
                skipped += 1
                continue
            question = ledger.create_question(
                title=q["title"],
                description=q.get("description", ""),
                resolution_criteria=q["resolution_criteria"],
                resolution_source=q.get("resolution_source"),
                outcome_space=_outcome_space(q),
                domain=q.get("domain"),
                topics=q.get("topics") or [],
                impact=q.get("impact"),
                close_time=q.get("close_time"),
                resolution_time=q.get("resolution_time"),
            )
            key_to_id[q["key"]] = question.id
            created += 1
            if not args.no_baselines:
                payload = _baseline_payload(q)
                if payload is not None:
                    ledger.create_snapshot(
                        question_id=question.id,
                        probability_or_distribution=payload,
                        rationale="Seeded exploratory prior from the AI-infra thesis doc; replace via a live agent run.",
                        forecast_origin="exploratory",
                    )
                    baselined += 1

        # thesis + members
        thesis_q = by_title.get(THESIS["title"])
        if thesis_q is None:
            thesis_q = ledger.create_question(
                title=THESIS["title"], description=THESIS["description"],
                resolution_criteria=THESIS["criteria"],
                outcome_space=OutcomeSpace(type="thesis", units="index"),
                domain=THESIS["domain"], topics=THESIS["topics"],
            )
        for member in THESIS["members"]:
            key, weight, direction, role = member[0], member[1], member[2], member[3]
            target = member[4] if len(member) > 4 else None
            hi_is_good = member[5] if len(member) > 5 else True
            ledger.add_thesis_member(
                thesis_q.id, key_to_id[key], direction=direction, weight=weight,
                role=role, target=target, hi_is_good=hi_is_good,
            )

        # entities
        for entity in ENTITIES:
            ledger.add_thesis_entity(
                thesis_q.id, entity["name"], kind=entity["kind"], label=entity.get("label"),
                weights=[{"member_id": key_to_id[k], "weight": w, "direction": d} for (k, w, d) in entity["weights"]],
            )

        # factor + constituents
        factor_q = by_title.get(FACTOR["title"])
        if factor_q is None:
            factor_q = ledger.create_question(
                title=FACTOR["title"], description=FACTOR["description"],
                resolution_criteria=FACTOR["criteria"],
                outcome_space=OutcomeSpace(type="thesis", units=FACTOR["units"]),
                domain=FACTOR["domain"], topics=FACTOR["topics"],
                metadata={"aggregation": "factor"},
            )
        for (key, weight, direction) in FACTOR["constituents"]:
            ledger.add_thesis_member(
                factor_q.id, key_to_id[key], direction=("inverted" if direction == "short" else "support"), weight=weight,
            )

        # aggregate now so the desk shows output immediately
        if not args.no_baselines:
            thesis_res = ledger.aggregate_thesis(thesis_q.id, rho=args.rho)
            factor_res = ledger.aggregate_thesis(factor_q.id, rho=args.rho)
        else:
            thesis_res = factor_res = None

    print(f"questions: created {created}, skipped {skipped} (existing), baselined {baselined}")
    print(f"thesis:    {thesis_q.id}  '{THESIS['title']}'  members={len(THESIS['members'])}  entities={len(ENTITIES)}")
    if thesis_res and thesis_res.get("payload", {}).get("health") is not None:
        p = thesis_res["payload"]
        print(f"           health {p['health']:.0%}  score {p['thesis_score']:.0f}  coverage {p['coverage']:.0%}")
        top = sorted(thesis_res.get("entities") or [], key=lambda e: -(e.get("suitability") or 0))[:5]
        for e in top:
            print(f"           entity {e['name']:<5} suit {e['suitability_display']:>4}  {e['action']}")
    print(f"factor:    {factor_q.id}  '{FACTOR['title']}'  constituents={len(FACTOR['constituents'])}")
    if factor_res and factor_res.get("payload", {}).get("factor_mean") is not None:
        p = factor_res["payload"]
        print(f"           return {p['factor_mean']:.1f}  vol {p['factor_sd']:.1f}  "
              f"band [{p['q05']:.0f}, {p['q95']:.0f}]  downside {p['downside']:.0f}")
    print()
    print("Next: run the live system to replace the seeded priors with real forecasts, then re-aggregate:")
    print("  forecast run-all                 # forecast members, then theses + factor lag them")
    print("  forecast thesis show <thesis_id> # health + entity suitability + triggers")
    print("  forecast factor show <factor_id> # basket return distribution + constituents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
