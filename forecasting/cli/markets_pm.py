"""``forecast market-nightly`` / ``market-quality`` — market-nightly study + de-vig quality.

A carved CLI subcommand domain (the CLI-assembler pattern; see
:mod:`forecasting.cli.thesis`). ``market-nightly`` and ``market-quality`` sit at
two DIFFERENT positions in the registration order (``edge``/``tail-audit`` fall
between them), so this domain exposes two hooks — :func:`register`
(market-nightly) and :func:`register_quality` — each invoked at the exact
position its subcommand held pre-carve, keeping ``forecast --help``
byte-identical. (The prediction-market data plane, ``forecasting.pm``, has no CLI
verbs of its own yet; this is the ``markets`` half of the planned ``markets_pm``
slice.)

Shared helpers stay in ``core`` and are imported bare; ``_ledger`` is reached via
the call-time ``_core.`` hop. ``core`` imports this module back at its bottom for
registration + surface parity (``forecasting.cli._cmd_market_nightly_*`` are
called by ``tests/forecasting/test_market_nightly_forecaster.py``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from forecasting.cli import core as _core
from forecasting.cli.core import _resolve_active_model_id, utc_now_iso


def _ledger(args: argparse.Namespace):
    """Hop to ``core._ledger`` at CALL time (monkeypatch discipline)."""

    return _core._ledger(args)


def register(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``market-nightly`` command group (its registration position)."""

    market_nightly_parser = forecast_sub.add_parser(
        "market-nightly",
        help="AIA P2.1 — foreknowledge-proof live benchmark: sample OPEN markets, forecast NOW, score on close",
    )
    mn_sub = market_nightly_parser.add_subparsers(dest="market_nightly_command")
    mn_sample = mn_sub.add_parser(
        "sample",
        help="Sample currently-OPEN markets (close STRICTLY in the future) from a markets JSON file and record pending entries (explicit/opt-in; never hits a live API)",
    )
    mn_sample.add_argument(
        "--markets-json",
        required=True,
        dest="markets_json",
        help="Path to a JSON array of market dicts (id, probability/yes_price, close_time/resolution_time, ...). No network is contacted.",
    )
    mn_sample.add_argument("--as-of", dest="as_of", default=None, help="Forecast instant (default: now). The invariant is close STRICTLY > as_of.")
    mn_sample.add_argument("-n", "--count", type=int, default=10, dest="count", help="Max markets to sample (default: 10)")
    mn_sample.add_argument("--seed", type=int, default=0, dest="rng_seed", help="Seed for the deterministic pick (default: 0)")
    mn_sample.add_argument(
        "--agent-prob",
        type=float,
        default=None,
        dest="agent_prob",
        help="Constant agent P(yes) for every sampled market (offline; for piloting the loop without an LLM call).",
    )
    mn_sample.add_argument(
        "--agent-prob-field",
        default=None,
        dest="agent_prob_field",
        help="Read each market's agent P(yes) from this field in the market dict (offline; no LLM call).",
    )
    mn_sample.add_argument("--json", action="store_true", help="Emit the run record as JSON")
    mn_sample.set_defaults(_forecast_handler=_cmd_market_nightly_sample)

    mn_run = mn_sub.add_parser(
        "run",
        help=(
            "LIVE proof: fetch currently-OPEN markets from a source adapter, forecast "
            "each NOW with the SEARCH-ENABLED informed agent (web search ON — the "
            "legitimate live path, NOT closed-book), and record agent-vs-market. The "
            "market-hidden ForecastBench result proved the closed-book LLM has NO "
            "intrinsic edge; the only way to beat the market is fresh information, "
            "provable ONLY forward (searching a resolved question leaks the answer)."
        ),
    )
    mn_run.add_argument("-n", "--count", type=int, default=10, dest="count", help="Max open markets to sample + forecast (default: 10).")
    mn_run.add_argument("--source", default="manifold", help="Open-market source adapter (manifold|metaculus|...). Default: manifold.")
    mn_run.add_argument("--model", default=None, help="Agent model id (overrides the resolved active model).")
    mn_run.add_argument(
        "--research-arm",
        dest="research_arm",
        choices=["plain", "voi", "both"],
        default=None,
        help=(
            "A/B research arm (default: config forecasting.market_nightly.research_arm, "
            "itself 'plain'). plain = the plain agent-protocol packet (the existing "
            "accrued record); voi = the research-disciplined packet (VOI research plan + "
            "adequacy floor); both = forecast EACH sampled market TWICE, once per arm "
            "(2x LLM calls) recording two pendings, so the voi-vs-plain lift is paired "
            "and attributable in `report`."
        ),
    )
    mn_run.add_argument("--seed", type=int, default=0, dest="rng_seed", help="Deterministic sampling seed (default: 0).")
    mn_run.add_argument("--max-iterations", type=int, default=None, dest="max_iterations", help="Agent tool-calling budget per market.")
    mn_run.add_argument(
        "--parallel",
        type=int,
        default=1,
        dest="parallel",
        help=(
            "Bounded concurrency over the per-market agent forecasts (default: 1 = "
            "sequential). N>1 forecasts up to N markets at once (each gets its own "
            "isolated agent); ledger writes stay serialized."
        ),
    )
    mn_run.add_argument("--json", action="store_true", help="Emit the run record as JSON.")
    mn_run.set_defaults(_forecast_handler=_cmd_market_nightly_run)

    mn_score = mn_sub.add_parser("score", help="Score any pending entry whose market has since resolved (reuses the ledger scoring machinery)")
    mn_score.add_argument("--now", default=None, help="Scoring instant (default: now)")
    mn_score.add_argument("--json", action="store_true", help="Emit the result as JSON")
    mn_score.set_defaults(_forecast_handler=_cmd_market_nightly_score)

    mn_report = mn_sub.add_parser("report", help="Read-only roll-up: pending/scored counts + paired agent-vs-market edge")
    mn_report.add_argument("--json", action="store_true", help="Emit the report as JSON")
    mn_report.set_defaults(_forecast_handler=_cmd_market_nightly_report)



def register_quality(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``market-quality`` command group (its registration position)."""

    market_quality_parser = forecast_sub.add_parser(
        "market-quality",
        help=(
            "Stratify market readings by liquidity + recency into an advisory pooling "
            "weight, so a thin/stale market can't inflate a tail"
        ),
    )
    market_quality_parser.add_argument(
        "--markets",
        dest="market_quality_markets",
        required=True,
        help='JSON array of {source, volume?, updated_at?|age_days?, probability?} objects',
    )
    market_quality_parser.add_argument("--json", action="store_true")
    market_quality_parser.set_defaults(_forecast_handler=_cmd_market_quality)



def _cmd_market_quality(args: argparse.Namespace) -> None:
    from forecasting.market_quality import (
        MarketReading,
        classify_market,
        reading_from_evidence,
    )

    try:
        markets = json.loads(args.market_quality_markets)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"forecast market-quality: invalid --markets JSON: {exc.msg}") from exc
    if not isinstance(markets, list) or not markets:
        raise SystemExit("forecast market-quality: --markets must be a non-empty JSON array")

    results = []
    for row in markets:
        if not isinstance(row, dict):
            continue
        if row.get("age_days") is not None:
            reading = MarketReading(
                source=str(row.get("source") or "market"),
                probability=row.get("probability"),
                volume=row.get("volume"),
                age_days=row.get("age_days"),
            )
        else:
            reading = reading_from_evidence(row)
        results.append(classify_market(reading))

    if getattr(args, "json", False):
        print(json.dumps([r.to_dict() for r in results], indent=2, sort_keys=True))
        return
    print(f"{'source':<28} {'tier':<12} {'weight':>6}  why")
    print(f"{'-' * 28} {'-' * 12} {'-' * 6}  {'-' * 30}")
    for r in results:
        print(f"{r.source[:28]:<28} {r.tier:<12} {r.weight:>6.2f}  {'; '.join(r.reasons)[:50]}")


def _cmd_market_nightly_run(args: argparse.Namespace) -> None:
    """AIA P2.1 — the LIVE, SEARCH-ENABLED proof: forecast OPEN markets NOW.

    The inverse of the closed-book backtest runner. ``sample`` (above) pilots the
    loop OFFLINE from a JSON file; ``run`` is the real forward proof:

      1. Fetch currently-OPEN markets from a SOURCE ADAPTER (manifold|metaculus|…).
      2. Keep only strictly-future-close markets (the foreknowledge filter) and
         take up to ``--count`` with a seeded deterministic pick.
      3. Forecast each with the SEARCH-ENABLED informed agent (web search ON — this
         is the legitimate live path, NOT closed-book) via
         :func:`build_informed_market_forecaster`.
      4. ``record_pending`` stamps everything at NOW (live availability) and records
         the agent forecast alongside the de-vigged market price as the baseline.

    The market-hidden ForecastBench result proved the closed-book LLM has NO
    intrinsic edge over the market; the only path to beating it is fresh
    information — provable ONLY forward, because searching a RESOLVED question
    leaks the answer. This command accrues that out-of-sample, overfit-proof
    record. No live LLM/market call is made under test (both seams are injected).
    """
    from forecasting.market_nightly import (
        default_market_devig,
        record_pending,
        sample_open_markets,
    )
    from forecasting.market_nightly_forecaster import (
        build_informed_market_forecaster,
        load_open_markets,
    )
    from superforecasting_agent.configuration import cfg_get
    from superforecasting_agent.storage.configuration import read_configuration

    # available_at / evidence stamping is NOW (live): the whole point is the agent
    # uses fresh search on an OPEN market whose outcome does not exist yet. There is
    # NO closed-book restriction here (the inverse of _backtest_agent_protocol_runner).
    as_of = utc_now_iso()
    n = max(0, int(getattr(args, "count", 10) or 0))
    source = getattr(args, "source", "manifold") or "manifold"
    seed = int(getattr(args, "rng_seed", 0) or 0)

    cfg = read_configuration()
    # Resolve the agent model with the SAME logic the quorum uses (config["model"]
    # is a structured dict since the codex auth overhaul).
    model = getattr(args, "model", None) or _resolve_active_model_id(cfg.get("model"))

    # A/B research arm: CLI flag wins, else config default (itself 'plain' so the
    # existing accrued record stays comparable). 'both' forecasts each market TWICE.
    arm_choice = getattr(args, "research_arm", None) or cfg_get(
        cfg, "forecasting", "market_nightly", "research_arm", default="plain"
    )
    arm_choice = str(arm_choice or "plain").strip().lower()
    if arm_choice == "both":
        arms = ["plain", "voi"]
    elif arm_choice == "voi":
        arms = ["voi"]
    else:
        arms = ["plain"]

    try:
        candidates = load_open_markets(source, limit=max(n * 4, n, 1))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"forecast market-nightly run: could not load open markets: {exc}") from exc

    picked = sample_open_markets(candidates, as_of, n, rng_seed=seed)

    # Bounded parallelism over the slow per-market agent calls. N>1 forecasts up to
    # N markets concurrently; each worker gets its OWN agent (fresh_agent_per_call)
    # since the reused single agent carries non-thread-safe conversation state.
    # record_pending keeps every ledger write serialized regardless; N=1 preserves
    # the sequential recorded/skipped SET (notes may differ only on a narrow
    # intra-batch-duplicate edge — see record_pending's docstring).
    max_workers = max(1, int(getattr(args, "parallel", 1) or 1))

    ledger = _ledger(args)
    runs: list[Any] = []
    for arm in arms:
        forecaster_kwargs: dict[str, Any] = {"model": model, "research_arm": arm}
        if getattr(args, "max_iterations", None) is not None:
            forecaster_kwargs["max_iterations"] = int(args.max_iterations)
        if max_workers > 1:
            forecaster_kwargs["fresh_agent_per_call"] = True
        forecaster = build_informed_market_forecaster(**forecaster_kwargs)
        try:
            runs.append(
                record_pending(
                    ledger,
                    picked["sampled"],
                    as_of,
                    forecaster,
                    default_market_devig,
                    max_workers=max_workers,
                    arm=arm,
                )
            )
        finally:
            close = getattr(forecaster, "close", None)
            if callable(close):
                close()

    if getattr(args, "json", False):
        out = {
            "as_of": as_of,
            "source": source,
            "model": model,
            "research_arm": arm_choice,
            "candidates": len(candidates),
            "admissible": picked["admissible"],
            "sampled": len(picked["sampled"]),
            "rejected_sampling": picked["rejected"],
            "runs": {run.arm: run.to_dict() for run in runs},
        }
        # Back-compat: single-arm runs keep the flat "run" key existing tooling reads.
        if len(runs) == 1:
            out["run"] = runs[0].to_dict()
        print(json.dumps(out, indent=2, sort_keys=True))
        return

    print(f"market-nightly run @ {as_of}  (source={source}, model={model or 'active default'}, arm={arm_choice})")
    print(f"  candidates fetched: {len(candidates)}  admissible (future close): {picked['admissible']}")
    for run in runs:
        print(f"  [arm {run.arm}] sampled: {len(picked['sampled'])}  recorded: {run.n_recorded}  "
              f"rejected: {run.n_rejected}  skipped: {len(run.skipped_ids)}")
        for row in run.recorded:
            print(f"    - {row['question_id']} market={row['market_id']} "
                  f"agent={row['agent_forecast']:.3f} market={row['market_devig_probability']:.3f} "
                  f"close={row['close_time']}")
        for note in run.notes:
            print(f"    note: {note}")


def _cmd_market_nightly_sample(args: argparse.Namespace) -> None:
    """AIA P2.1 — sample currently-OPEN markets and record pending benchmark entries.

    Markets are read from a LOCAL JSON file (``--markets-json``); this command
    NEVER contacts a live market API. The agent forecast for each market is an
    OFFLINE seam: a constant ``--agent-prob`` or a per-market ``--agent-prob-field``
    (so the loop can be piloted without an LLM call). The foreknowledge-proof
    filter keeps ONLY markets whose close is STRICTLY after ``as_of``; rejected
    candidates are counted, never stored."""
    from forecasting.market_nightly import record_pending, sample_open_markets

    path = Path(args.markets_json).expanduser()
    try:
        markets = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"could not read markets JSON {path}: {exc}")
    if not isinstance(markets, list):
        raise SystemExit("markets JSON must be a JSON array of market dicts")

    as_of = args.as_of or utc_now_iso()
    picked = sample_open_markets(markets, as_of, args.count, rng_seed=args.rng_seed)

    if args.agent_prob is not None:
        const = float(args.agent_prob)
        forecaster = lambda _market: const  # noqa: E731 - explicit offline seam
    elif args.agent_prob_field:
        field = args.agent_prob_field
        forecaster = lambda market: market.get(field)  # noqa: E731 - explicit offline seam
    else:
        raise SystemExit(
            "provide --agent-prob <p> or --agent-prob-field <name> (the agent forecaster "
            "is an explicit offline seam; no LLM/market call is made by default)"
        )

    run = record_pending(_ledger(args), picked["sampled"], picked["as_of"], forecaster)
    if getattr(args, "json", False):
        out = {"sample": {k: v for k, v in picked.items() if k != "sampled"}, "run": run.to_dict()}
        print(json.dumps(out, indent=2, sort_keys=True))
        return
    print(f"as_of: {picked['as_of']}")
    print(f"candidates: {len(markets)}  admissible (future close): {picked['admissible']}  rejected: {picked['rejected']}")
    print(f"recorded pending: {run.n_recorded}  rejected at store: {run.n_rejected}  skipped: {len(run.skipped_ids)}")
    for row in run.recorded:
        print(f"  - {row['question_id']} market={row['market_id']} agent={row['agent_forecast']:.3f} market={row['market_devig_probability']:.3f} close={row['close_time']}")
    for note in run.notes:
        print(f"  note: {note}")


def _cmd_market_nightly_score(args: argparse.Namespace) -> None:
    """AIA P2.1 — score pending benchmark entries whose market has since resolved."""
    from forecasting.market_nightly import score_matured

    result = score_matured(_ledger(args), now=args.now)
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return
    print(f"now: {result['now']}")
    print(f"scored: {result['n_scored']}  still pending: {result['n_still_pending']}")
    for row in result["scored"]:
        ab = row.get("agent_brier")
        mb = row.get("market_brier")
        ab_s = f"{ab:.4f}" if isinstance(ab, (int, float)) else "-"
        mb_s = f"{mb:.4f}" if isinstance(mb, (int, float)) else "-"
        print(f"  - {row['question_id']} outcome={row['outcome']} agent_brier={ab_s} market_brier={mb_s}")
    for note in result["notes"]:
        print(f"  note: {note}")


def _cmd_market_nightly_report(args: argparse.Namespace) -> None:
    """AIA P2.1 — read-only roll-up of the foreknowledge-proof live benchmark."""
    from forecasting.market_nightly import market_nightly_report

    report = market_nightly_report(_ledger(args))
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    def _fmt(value: Any) -> str:
        return f"{value:.4f}" if isinstance(value, (int, float)) else "-"

    n_contemp = report.get("n_contemporaneous", 0)
    n_frozen = report.get("n_frozen_excluded", 0)
    print(
        f"pending: {report['n_pending']}  scored: {report['n_scored']}"
        f"  (contemporaneous: {n_contemp}, frozen-excluded: {n_frozen})"
    )
    # HEADLINE agent-vs-market: CONTEMPORANEOUS baselines ONLY (frozen priors quarantined
    # — a stale freeze price cannot contaminate the "agent beats the market" claim). The
    # clean mean Briers and paired edge are all computed over the contemporaneous subset.
    print(f"  HEADLINE agent vs market [contemporaneous baselines only, n={n_contemp}]")
    print(f"    mean agent Brier  = {_fmt(report.get('contemporaneous_mean_agent_brier'))}")
    print(f"    mean market Brier = {_fmt(report.get('contemporaneous_mean_market_brier'))}")
    edge = report.get("paired_agent_edge_mean_brier")
    lo = report.get("paired_agent_edge_ci95_low")
    hi = report.get("paired_agent_edge_ci95_high")
    band = f" [95% CI {lo:.4f}..{hi:.4f}]" if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) else ""
    print(f"    paired agent edge (market_brier - agent_brier) = {edge:+.4f}{band}" if isinstance(edge, (int, float)) else "    paired agent edge = -")
    p = report.get("paired_p_value")
    print(f"    paired p-value = {p:.4f}" if isinstance(p, (int, float)) else "    paired p-value = -")
    print(f"    wins agent/market/ties = {report.get('paired_agent_wins', 0)}/{report.get('paired_baseline_wins', 0)}/{report.get('paired_ties', 0)}")
    # DIAGNOSTICS — surfaced for transparency, NEVER the headline edge.
    full = report.get("full_set") or {}
    if full.get("n_scored"):
        ue = full.get("paired_agent_edge_mean_brier")
        print(
            f"  [diagnostic] full set: all {full.get('n_scored', 0)} samples incl. "
            f"{n_frozen} frozen-baseline excluded from edge"
        )
        print(f"    mean agent Brier  = {_fmt(full.get('mean_agent_brier'))}")
        print(f"    mean market Brier = {_fmt(full.get('mean_market_brier'))}")
        print(
            f"    full-set edge (incl. frozen) = "
            + (f"{ue:+.4f}" if isinstance(ue, (int, float)) else "-")
        )
    frozen = report.get("frozen_diagnostic") or {}
    if frozen.get("n_scored"):
        fe = frozen.get("paired_agent_edge_mean_brier")
        print(
            f"  [diagnostic] agent-vs-FROZEN-prior edge (n={frozen.get('n_scored', 0)}, NOT the claim) = "
            + (f"{fe:+.4f}" if isinstance(fe, (int, float)) else "-")
        )

    # A/B ARM SPLIT — per-arm agent-vs-market (contemporaneous baselines only).
    by_arm = report.get("by_arm") or {}
    for arm in ("plain", "voi"):
        a = by_arm.get(arm) or {}
        if not a.get("n_scored"):
            continue
        edge = a.get("paired_agent_edge_mean_brier")
        edge_s = f"{edge:+.4f}" if isinstance(edge, (int, float)) else "-"
        print(
            f"  [arm {arm}] n={a['n_scored']}  mean agent Brier={_fmt(a.get('mean_agent_brier'))}"
            f"  vs market={_fmt(a.get('mean_market_brier'))}  agent-vs-market edge={edge_s}"
        )

    # THE A/B SCOREBOARD — paired voi-vs-plain Brier delta (markets with BOTH arms).
    vp = report.get("paired_voi_vs_plain") or {}
    if vp.get("n_paired"):
        d = vp.get("delta_mean_brier")
        p = vp.get("p_value")
        lo = vp.get("ci95_low")
        hi = vp.get("ci95_high")
        band = (
            f" [95% CI {lo:+.4f}..{hi:+.4f}]"
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float))
            else ""
        )
        d_s = f"{d:+.4f}" if isinstance(d, (int, float)) else "-"
        p_s = f"{p:.2f}" if isinstance(p, (int, float)) else "-"
        # Honest significance note: only claim significance at the seeded-bootstrap p.
        sig = "significant" if isinstance(p, (int, float)) and p < 0.05 else "not yet significant"
        print(
            f"  voi arm: n={vp['n_paired']} paired, ΔBrier(plain−voi, +=VOI better)={d_s}{band}, "
            f"p={p_s} — {sig}"
        )
        print(
            f"    wins voi/plain/ties = {vp.get('voi_wins', 0)}/{vp.get('plain_wins', 0)}/{vp.get('ties', 0)}"
        )
