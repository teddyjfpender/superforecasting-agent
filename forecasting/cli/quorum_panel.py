"""``forecast panel`` / ``quorum`` — multi-perspective panels + the model quorum.

A carved CLI subcommand domain (the CLI-assembler pattern; see
:mod:`forecasting.cli.thesis`). ``panel`` and ``quorum`` are contiguous in the
registration order, so both register via a single :func:`register` hook invoked
at their pre-carve position — ``forecast --help`` stays byte-identical. The
``_quorum_*`` sub-dispatchers (``run``/``status``/``config``/``bench`` …) and
``_print_quorum_job`` travelled with ``_cmd_quorum``.

Shared helpers stay in ``core`` and are imported bare; ``_ledger`` is reached
through the call-time ``_core.`` hop. This is the CLI-side of the quorum carve
(Wave-1 lands before the Wave-3 ``forecasting/quorum/`` package split).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from forecasting.cli import core as _core
from forecasting.cli.core import (
    _QUORUM_APPCONFIG_KEYS,
    _print_panel_summary,
    _resolve_active_model_id,
)


def _ledger(args: argparse.Namespace):
    """Hop to ``core._ledger`` at CALL time (monkeypatch discipline)."""

    return _core._ledger(args)


def register(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``panel`` + ``quorum`` command groups (contiguous block)."""

    panel_parser = forecast_sub.add_parser(
        "panel",
        help=(
            "Run / aggregate / inspect a multi-perspective forecast panel "
            "(outside, inside, market, red-team, sanity)"
        ),
    )
    panel_sub = panel_parser.add_subparsers(dest="panel_command")

    panel_perspectives_parser = panel_sub.add_parser(
        "perspectives",
        help="Print the system+user prompt for each panel perspective",
    )
    panel_perspectives_parser.add_argument("question_id", nargs="?")
    panel_perspectives_parser.add_argument(
        "--perspective",
        dest="perspectives",
        action="append",
        default=[],
        help=(
            "Subset of perspectives to print (repeatable). Defaults to all five: "
            "outside, inside, market, red_team, sanity."
        ),
    )
    panel_perspectives_parser.add_argument("--json", action="store_true")
    panel_perspectives_parser.set_defaults(_forecast_handler=_cmd_panel_perspectives)

    panel_aggregate_parser = panel_sub.add_parser(
        "aggregate",
        help="Aggregate a JSON array of perspective estimates without saving",
    )
    panel_aggregate_parser.add_argument(
        "--input",
        "-i",
        dest="panel_input",
        default=None,
        help="JSON array of estimate objects",
    )
    panel_aggregate_parser.add_argument(
        "--input-file",
        dest="panel_input_file",
        default=None,
    )
    panel_aggregate_parser.add_argument(
        "--method",
        choices=sorted(["trimmed_geomean_odds", "log_odds_pool", "median", "mean"]),
        default="trimmed_geomean_odds",
    )
    panel_aggregate_parser.add_argument(
        "--trim",
        type=int,
        default=1,
        help="Drop this many highest + lowest estimates before pooling (default 1)",
    )
    panel_aggregate_parser.add_argument("--json", action="store_true")
    panel_aggregate_parser.set_defaults(_forecast_handler=_cmd_panel_aggregate)

    panel_record_parser = panel_sub.add_parser(
        "record",
        help="Aggregate panel estimates AND save the panel_run for a question",
    )
    panel_record_parser.add_argument("question_id")
    panel_record_parser.add_argument(
        "--input", "-i", dest="panel_input", default=None,
        help="JSON array of estimate objects",
    )
    panel_record_parser.add_argument("--input-file", dest="panel_input_file", default=None)
    panel_record_parser.add_argument(
        "--method",
        choices=sorted(["trimmed_geomean_odds", "log_odds_pool", "median", "mean"]),
        default="trimmed_geomean_odds",
    )
    panel_record_parser.add_argument("--trim", type=int, default=1)
    panel_record_parser.add_argument(
        "--triggered-by",
        choices=["manual", "first_forecast", "impact_high", "force"],
        default="manual",
    )
    panel_record_parser.add_argument("--snapshot-id")
    panel_record_parser.add_argument(
        "--track-record-weights", action="store_true",
        help=(
            "Weight perspectives by their measured Brier edge over the committed "
            "aggregate (resolved questions only; advisory weights from `forecast "
            "track-record`). Estimates that already carry an explicit weight keep it."
        ),
    )
    panel_record_parser.set_defaults(_forecast_handler=_cmd_panel_record)

    panel_show_parser = panel_sub.add_parser(
        "show",
        help="Render a stored panel_run",
    )
    panel_show_parser.add_argument("panel_run_id")
    panel_show_parser.add_argument("--json", action="store_true")
    panel_show_parser.set_defaults(_forecast_handler=_cmd_panel_show)

    panel_list_parser = panel_sub.add_parser(
        "list",
        help="List panel_runs (optionally scoped to a question)",
    )
    panel_list_parser.add_argument("question_id", nargs="?")
    panel_list_parser.add_argument("--limit", type=int, default=20)
    panel_list_parser.set_defaults(_forecast_handler=_cmd_panel_list)

    quorum_parser = forecast_sub.add_parser(
        "quorum",
        help=(
            "Run a model-diverse forecast quorum (Fusion-style): dispatch a "
            "panel of models, then a judge synthesizes a verdict. Subcommands: "
            "`quorum <id>` (run), `quorum status [run-id]`, `quorum config "
            "[set k v]`, `quorum default on|off`."
        ),
    )
    quorum_parser.add_argument(
        "target",
        nargs="?",
        help="Question id to forecast, or one of: status | config | default.",
    )
    quorum_parser.add_argument(
        "rest",
        nargs="*",
        help="Sub-arguments (run-id for status; key value for config set; on/off for default).",
    )
    quorum_parser.add_argument(
        "--preset",
        choices=sorted(("frontier", "budget", "self", "wide")),
        help="Panel preset (overrides the configured default). 'wide' is the "
        "opt-in ~10-draw variance-reduction panel (AIA P1.4).",
    )
    quorum_parser.add_argument(
        "--models",
        help="Comma-separated OpenRouter model ids (overrides the preset).",
    )
    quorum_parser.add_argument("--judge", help="Judge model id (overrides the preset default).")
    quorum_parser.add_argument(
        "--pool",
        dest="pool_method",
        choices=sorted({"trimmed_geomean_odds", "log_odds_pool", "median", "mean"}),
        help="Pooling method for the panel ('mean' is the convexity baseline; "
        "the default stays trimmed_geomean_odds).",
    )
    quorum_parser.add_argument("--trim", type=int, help="Drop this many extremes before pooling.")
    quorum_parser.add_argument("--samples", type=int, help="Self-fusion sample count (self preset).")
    quorum_parser.add_argument(
        "--trials",
        type=int,
        help="Trials per panelist (BLF multi-trial). Each seat is drawn this many "
        "times and pooled as a variance-shrunk logit mean toward the anchor; "
        "default is impact-driven (high-impact 3, else 1).",
    )
    quorum_parser.add_argument(
        "--attach-snapshot",
        dest="attach_snapshot",
        help="Attach the resulting panel run to an existing snapshot id.",
    )
    quorum_parser.add_argument("--triggered-by", dest="triggered_by", default="quorum")
    quorum_parser.add_argument(
        "--supervisor-search",
        dest="supervisor_search",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Live agentic-supervisor fresh-search loop (AIA P1.1): when the judge "
        "flags an unresolved crux it runs a real bounded web/news search and "
        "re-synthesises once on the fresh evidence. DEFAULT ON for live runs "
        "(leak-guarded off for a historical evidence_cutoff); pass "
        "--no-supervisor-search to disable this run, or set quorum.supervisor_search "
        "= false fleet-wide.",
    )
    quorum_parser.add_argument(
        "--scope",
        choices=sorted(("high_impact", "always", "first_only")),
        help="For `quorum default`: which indicated panels get a quorum.",
    )
    quorum_parser.add_argument(
        "--wait",
        action="store_true",
        help="Run synchronously and print the result (default: background job + run-id).",
    )
    quorum_parser.add_argument(
        "--seed", type=int, default=0,
        help="Bootstrap seed for `quorum bench` (deterministic).",
    )
    quorum_parser.add_argument(
        "--draws", type=int,
        help="Bootstrap resamples per ensemble size for `quorum bench` (default 500).",
    )
    quorum_parser.add_argument(
        "--delphi",
        action="store_true",
        help="Add one anonymous Delphi-style revision round (shorthand for "
        "--delphi-rounds 1). Default OFF (byte-identical baseline).",
    )
    quorum_parser.add_argument(
        "--delphi-rounds",
        dest="delphi_rounds",
        type=int,
        choices=(0, 1),
        help="Number of Delphi revision rounds (v1 supports 0 or 1). Overrides "
        "quorum.delphi_rounds.",
    )
    quorum_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    quorum_parser.set_defaults(_forecast_handler=_cmd_quorum)



def _cmd_panel_perspectives(args: argparse.Namespace) -> None:
    from forecasting.panel import (
        DEFAULT_PANEL_PERSPECTIVES,
        PANEL_PERSPECTIVES,
        build_perspective_prompts,
    )
    from forecasting.protocol import build_context_packet

    perspectives = args.perspectives or list(DEFAULT_PANEL_PERSPECTIVES)
    if args.question_id:
        ledger = _ledger(args)
        question = ledger.get_question(args.question_id)
        snapshot = ledger.get_current_snapshot(question.id)
        context = build_context_packet(ledger, question, snapshot)
        prompts = build_perspective_prompts(
            question_title=question.title,
            resolution_criteria=question.resolution_criteria,
            context_packet=context,
            perspectives=perspectives,
        )
    else:
        prompts = build_perspective_prompts(
            question_title="<question title>",
            resolution_criteria="<resolution criteria>",
            context_packet="<ledger context packet>",
            perspectives=perspectives,
        )
    if args.json:
        print(json.dumps(prompts, indent=2, sort_keys=True))
        return
    for name, prompt in prompts.items():
        label = PANEL_PERSPECTIVES.get(name, {}).get("label", name)
        print(f"=== {name} — {label} ===")
        print("[system]")
        print(prompt["system"])
        print()
        print("[user]")
        print(prompt["user"])
        print()


def _cmd_panel_aggregate(args: argparse.Namespace) -> None:
    from forecasting.panel import aggregate_panel_estimates

    raw = args.panel_input
    if raw is None and args.panel_input_file:
        try:
            raw = Path(args.panel_input_file).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"forecast panel aggregate: cannot read --input-file: {exc}") from exc
    if not raw or not raw.strip():
        raise SystemExit("forecast panel aggregate: --input or --input-file required")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"forecast panel aggregate: invalid JSON: {exc.msg}") from exc
    if isinstance(data, dict) and "estimates" in data:
        data = data["estimates"]
    aggregation = aggregate_panel_estimates(
        data,
        method=args.method,
        trim=args.trim,
    )
    if args.json:
        print(json.dumps(aggregation.to_dict(), indent=2, sort_keys=True))
        return
    print(f"method: {aggregation.method} (trim={aggregation.trim})")
    print(f"aggregate: {aggregation.aggregate_probability:.4f}")
    print("spread:")
    for key in ("min", "p25", "median", "p75", "max", "iqr", "range", "count"):
        if key in aggregation.spread:
            print(f"  {key}: {aggregation.spread[key]:.4f}")
    print(f"estimates ({len(aggregation.estimates)}):")
    for estimate in aggregation.estimates:
        marker = "× " if estimate.get("trimmed") else "  "
        print(f"  {marker}{estimate['perspective']:<12} p={estimate['probability']:.3f}")
    for note in aggregation.notes:
        print(f"note: {note}")


def _cmd_panel_record(args: argparse.Namespace) -> None:
    raw = args.panel_input
    if raw is None and args.panel_input_file:
        try:
            raw = Path(args.panel_input_file).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"forecast panel record: cannot read --input-file: {exc}") from exc
    if not raw or not raw.strip():
        raise SystemExit("forecast panel record: --input or --input-file required")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"forecast panel record: invalid JSON: {exc.msg}") from exc
    if isinstance(data, dict) and "estimates" in data:
        data = data["estimates"]
    ledger = _ledger(args)
    if getattr(args, "track_record_weights", False) and isinstance(data, list):
        weights = ledger.recommended_component_weights(kind="panel")
        applied = []
        for row in data:
            if not isinstance(row, dict) or "weight" in row:
                continue
            weight = weights.get(str(row.get("perspective", "")).strip())
            if weight is not None:
                row["weight"] = weight
                applied.append(f"{row['perspective']}={weight:.2f}")
        if applied:
            print("track-record weights applied: " + ", ".join(applied))
        else:
            print(
                "track-record weights: none applied (no measured perspectives yet "
                "— see `forecast track-record`)"
            )
    record = ledger.record_panel_run(
        question_id=args.question_id,
        estimates=data,
        aggregation_method=args.method,
        trim=args.trim,
        snapshot_id=args.snapshot_id,
        triggered_by=args.triggered_by,
    )
    _print_panel_summary(record)


def _cmd_panel_show(args: argparse.Namespace) -> None:
    record = _ledger(args).get_panel_run(args.panel_run_id)
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
        return
    _print_panel_summary(record)
    for estimate in record.get("estimates", []):
        print()
        print(f"[{estimate['perspective']}] {'(trimmed)' if estimate.get('trimmed') else ''}")
        if estimate.get("rationale"):
            print(f"  rationale: {estimate['rationale']}")
        for label in ("reasons_up", "reasons_down", "change_my_mind"):
            items = estimate.get(label) or []
            if items:
                print(f"  {label}:")
                for item in items:
                    print(f"    - {item}")


def _cmd_panel_list(args: argparse.Namespace) -> None:
    rows = _ledger(args).list_panel_runs(question_id=args.question_id, limit=args.limit)
    if not rows:
        print("No panel runs found.")
        return
    print("ID             Created              Question        Method                  Trim  Aggregate  Spread")
    for row in rows:
        spread = row.get("spread_summary") or {}
        spread_text = (
            f"{spread.get('min', 0):.2f}-{spread.get('max', 0):.2f}"
            if spread
            else "-"
        )
        print(
            f"{row['id']:<14} {row['created_at']:<20} {row['question_id']:<15} "
            f"{row['aggregation_method']:<24} {row['trim']:<5} "
            f"{row['aggregate_probability']:.3f}     {spread_text}"
        )


def _cmd_quorum(args: argparse.Namespace) -> None:
    """Dispatch `forecast quorum …` (run | status | config | default)."""

    target = (args.target or "").strip()
    rest = [str(r) for r in (args.rest or [])]
    if target == "status":
        _quorum_status(args, rest)
        return
    if target == "config":
        _quorum_config(rest)
        return
    if target == "default":
        _quorum_default(rest, scope=args.scope)
        return
    if target == "calibration":
        _quorum_calibration(args)
        return
    if target == "bench":
        _quorum_bench(args)
        return
    if not target:
        _quorum_overview()
        return
    _quorum_run(args, question_id=target)


def _quorum_overview() -> None:
    from hermes_cli.config import load_config

    cfg = load_config().get("quorum", {})
    print("forecast quorum — model-diverse forecast panel with judge synthesis")
    print(f"  default_enabled: {bool(cfg.get('default_enabled'))}  "
          f"scope: {cfg.get('default_scope', 'high_impact')}")
    print(f"  preset: {cfg.get('preset', 'frontier')}  "
          f"pool: {cfg.get('pool_method', 'trimmed_geomean_odds')} (trim={cfg.get('trim', 1)})")
    print("usage:")
    print("  forecast quorum <question-id> [--preset frontier|budget|self] [--wait]")
    print("  forecast quorum status [run-id]")
    print("  forecast quorum config [set <key> <value>]")
    print("  forecast quorum default on|off [--scope high_impact|always|first_only]")
    print("  forecast quorum calibration   (how disagreement relates to realised error)")
    print("  forecast quorum bench         (ensemble-size variance-reduction curve, read-only)")


def _quorum_run(args: argparse.Namespace, *, question_id: str) -> None:
    from hermes_cli.config import load_config
    from forecasting.jobs.types.quorum import read_job, start_job

    cfg = load_config().get("quorum", {})
    active_model = _resolve_active_model_id(load_config().get("model"))

    # Fail fast if the question does not exist (immediate feedback before we
    # spawn a multi-minute background job).
    ledger = _ledger(args)
    question = ledger.get_question(question_id)

    from forecasting.models import ValidationError as _QuorumValidationError
    from forecasting.quorum import (
        available_provider_slugs,
        cap_preset_by_calls,
        cap_trials_by_calls,
        estimate_quorum_calls,
        preset_model_count,
        resolve_configured_panel,
        resolve_quorum_defaults,
        resolve_trial_count,
    )

    # Panel line-up precedence: explicit --models > QUORUM_PANEL_MODELS (appconfig,
    # operator-pinned) > quorum.models (legacy yaml). The pinned appconfig panel
    # takes PRECEDENCE over the connected-provider rebuild; a non-callable entry
    # fails fast HERE (naming itself) before any background job is spawned.
    models = None
    configured_judge: str | None = None
    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        try:
            configured = resolve_configured_panel()
        except _QuorumValidationError as exc:
            raise SystemExit(f"forecast quorum: {exc}") from exc
        if configured:
            models = configured["models"]
            configured_judge = configured.get("judge")
        elif cfg.get("models"):
            models = [str(m).strip() for m in cfg["models"] if str(m).strip()]

    # Default resolution (item 1). When the caller passed NO explicit --preset and
    # NO explicit model list, resolve the panel SHAPE from the question's
    # impact/type (single-key reality guarded) rather than a static config default —
    # so a bare `forecast quorum <id>` gets a right-sized panel. An explicit
    # --preset (or a model list) is honoured verbatim.
    samples_hint = args.samples or 3
    autonomous_preset = args.preset is None and not models
    resolution_note: str | None = None
    if autonomous_preset:
        defaults = resolve_quorum_defaults(
            question,
            available_providers=available_provider_slugs(),
            active_model=active_model,
            samples=samples_hint,
        )
        preset = defaults["preset"]
        default_delphi = int(defaults["delphi_rounds"])
        default_trim = int(defaults["trim"])
        resolution_note = defaults["reason"]
    else:
        preset = args.preset or cfg.get("preset") or "frontier"
        default_delphi = int(cfg.get("delphi_rounds", 0) or 0)
        default_trim = int(cfg.get("trim", 1))

    # --judge wins; else the pinned QUORUM_JUDGE_MODEL; else the legacy yaml judge.
    judge = args.judge or configured_judge or (cfg.get("judge") or None)
    # GATE 2 (AIA P1.1, live): the --supervisor-search flag wins when passed;
    # otherwise inherit the quorum.supervisor_search config (default OFF). Only a
    # truthy value goes into the spec, so the live default stays byte-identical.
    supervisor_search = (
        bool(args.supervisor_search)
        if getattr(args, "supervisor_search", None) is not None
        else bool(cfg.get("supervisor_search"))
    )
    pool_method = args.pool_method or cfg.get("pool_method") or "trimmed_geomean_odds"
    trim = args.trim if args.trim is not None else default_trim

    # Delphi revision rounds (v1: 0 or 1). Precedence: --delphi (=1) >
    # --delphi-rounds > resolved/config default > 0. --delphi with an explicit
    # --delphi-rounds 0 is a contradiction; fail fast.
    delphi_rounds_arg = getattr(args, "delphi_rounds", None)
    if args.delphi and delphi_rounds_arg is not None and delphi_rounds_arg == 0:
        raise SystemExit("forecast quorum: --delphi conflicts with --delphi-rounds 0")
    delphi_rounds = (
        1
        if args.delphi
        else delphi_rounds_arg
        if delphi_rounds_arg is not None
        else default_delphi
    )

    # Multi-trial per panelist (BLF A2): an explicit --trials wins; else K is
    # impact-driven (high-impact 3, else 1). ``1`` is byte-identical to pre-A2.
    if args.trials is not None:
        trials = max(1, int(args.trials))
    else:
        trials, _ = resolve_trial_count(question)

    # Cost cap (item 4): applies to any manual run WITHOUT an explicit --preset and
    # without an explicit model list — an oversized default preset is downgraded to
    # the largest that fits quorum.max_calls. An explicit --preset is respected.
    cap_note: str | None = None
    trials_note: str | None = None
    if args.preset is None and not models:
        max_calls = int(cfg.get("max_calls", 12) or 12)
        preset, delphi_rounds, samples_hint, est_calls, cap_note = cap_preset_by_calls(
            preset, delphi_rounds, max_calls=max_calls, samples=samples_hint
        )
        # Bound K to the SAME budget — extra trials of the same seats yield first.
        trials, trials_note = cap_trials_by_calls(
            preset=preset,
            delphi_rounds=delphi_rounds,
            samples=samples_hint,
            trials=trials,
            max_calls=max_calls,
        )

    if (resolution_note or cap_note or trials_note) and not args.json:
        model_count = preset_model_count(preset, samples=samples_hint)
        est = estimate_quorum_calls(
            model_count=model_count, delphi_rounds=delphi_rounds, trials=trials
        )
        trials_detail = "" if trials <= 1 else f", trials={trials}"
        detail = (
            f"↳ quorum defaults: preset {preset}: {model_count} models + judge, "
            f"delphi={delphi_rounds}{trials_detail}, ~{est} calls"
        )
        if resolution_note:
            detail += f" — {resolution_note}"
        print(detail)
        if cap_note:
            print(f"  cost cap: {cap_note}")
        if trials_note:
            print(f"  cost cap: {trials_note}")

    self_fusion = preset == "self" and not models
    if self_fusion:
        if not active_model:
            raise SystemExit(
                "forecast quorum: the 'self' preset needs a default model — set one "
                "with `--models <id>` or a config `model`."
            )
        # samples_hint carries the cost-cap's (possibly reduced) sample count, so a
        # capped self-fusion actually samples fewer times rather than silently
        # overrunning max_calls; for an uncapped run it is still args.samples or 3.
        samples = samples_hint
        models = [active_model] * samples
        judge = judge or active_model
        preset = None  # models now explicit

    spec = {
        "question_id": question_id,
        "db": getattr(args, "db", None),
        "preset": preset,
        "models": models,
        "judge": judge,
        "pool_method": pool_method,
        "trim": trim,
        "self_fusion": self_fusion,
        "samples": samples_hint if self_fusion else args.samples,
        "attach_snapshot": args.attach_snapshot,
        "triggered_by": args.triggered_by or "quorum",
        "active_model": active_model,
        "max_iterations": int(cfg.get("max_iterations", 30)),
        "model_timeout": int(cfg.get("model_timeout", 300)),
        "supervisor_search": supervisor_search,
        "delphi_rounds": delphi_rounds,
        "trials": trials,
    }

    run_id = start_job(spec, wait=bool(args.wait))

    if args.wait:
        job = read_job(run_id)
        _print_quorum_job(job, json_output=args.json)
        return
    if args.json:
        print(json.dumps({"run_id": run_id, "status": "queued"}, indent=2))
        return
    print(f"quorum run started: {run_id}")
    print(f"  poll with:  forecast quorum status {run_id}")


def _quorum_status(args: argparse.Namespace, rest: list[str]) -> None:
    from forecasting.jobs.types.quorum import list_jobs, read_job

    if not rest:
        jobs = list_jobs()
        if args.json:
            print(json.dumps(jobs, indent=2))
            return
        if not jobs:
            print("No quorum runs yet. Start one with `forecast quorum <question-id>`.")
            return
        print("Run            Status   Question        Updated")
        for job in jobs:
            print(
                f"{job['run_id']:<14} {job['status']:<8} "
                f"{(job.get('question_id') or '-'):<15} {job.get('updated_at', '-')}"
            )
        return
    try:
        job = read_job(rest[0])
    except FileNotFoundError as exc:
        raise SystemExit(f"forecast quorum status: {exc}") from exc
    _print_quorum_job(job, json_output=args.json)


def _print_quorum_job(job: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(job, indent=2, sort_keys=True))
        return
    print(f"quorum run: {job['run_id']}  [{job['status']}]")
    print(f"  question: {job.get('question_id')}")
    if job.get("panel_run_id"):
        print(f"  panel_run: {job['panel_run_id']}")
    if job.get("error"):
        print(f"  error: {job['error']}")
    for step in job.get("progress") or []:
        print(f"  · {step['stage']}: {step['detail']}")
    result = job.get("result")
    if not result:
        return
    if result.get("degraded"):
        print(f"  ⚠ DEGRADED PANEL: {result.get('degraded_reason') or 'fewer than 2 panelists survived'}")
    print(f"  pool: {result['aggregate_probability']:.3f}  "
          f"({result['pool_method']}, trim={result['trim']})")
    final_source = result.get("final_source", "pool")
    final_prob = result.get("final_probability", result["aggregate_probability"])
    delphi_rounds = int(result.get("delphi_rounds") or 0)
    if delphi_rounds:
        plural = "round" if delphi_rounds == 1 else "rounds"
        print(f"  delphi: {delphi_rounds} revision {plural}")
        rounds = ((result.get("delphi_audit") or {}).get("rounds")) or []
        for entry in rounds:
            r_dis = entry.get("disagreement") or {}
            r_prob = entry.get("aggregate_probability")
            prob_str = f"{r_prob:.3f}" if isinstance(r_prob, (int, float)) else "?"
            print(
                f"  round {entry.get('round_index', '?')} pool: {prob_str} "
                f"disagreement: {r_dis.get('disagreement_band', '?')}"
            )
    committed_label = (
        "committed (judge override)" if final_source == "judge_high" else "committed (pool)"
    )
    print(f"  {committed_label}: {final_prob:.3f}")
    dis = result.get("disagreement") or {}
    print(f"  disagreement: {dis.get('disagreement_band', '?')} "
          f"(index={dis.get('disagreement_index')}, sd_logit={dis.get('sd_logit')})")
    weights_used = result.get("model_weights_used") or {}
    if weights_used:
        print(
            "  track-record weights: "
            + ", ".join(f"{m}={w:.2f}" for m, w in sorted(weights_used.items()))
        )
    for f in result.get("forecasts") or []:
        if f.get("error"):
            print(f"    ✗ {f['model']}: {f['error']}")
        else:
            weight = f.get("weight")
            weight_str = (
                f" (weight {weight:.2f})"
                if isinstance(weight, (int, float)) and abs(float(weight) - 1.0) > 1e-9
                else ""
            )
            print(f"    • {f['model']}: {f['probability']:.3f}{weight_str}")
    judge = result.get("judge")
    if judge:
        if judge.get("probability") is not None:
            conf = judge.get("directional_confidence", "medium")
            print(
                f"  judge verdict: {judge['probability']:.3f} "
                f"[{conf} confidence] — {judge.get('rationale', '')}"
            )
        for spot in judge.get("blind_spots") or []:
            print(f"    blind spot: {spot}")


def _quorum_config(rest: list[str]) -> None:
    from hermes_cli.config import load_config, set_config_value

    if rest and rest[0] == "set":
        if len(rest) < 3:
            raise SystemExit("forecast quorum config set <key> <value>")
        key, value = rest[1], rest[2]
        # An appconfig panel key (QUORUM_PANEL_MODELS / QUORUM_JUDGE_MODEL) is written
        # to the config.yaml `env:` section so the layered loader + the doctor see it;
        # everything else stays a `quorum.<key>` yaml knob as before.
        canonical = _QUORUM_APPCONFIG_KEYS.get(key.strip().upper().replace("QUORUM.", ""))
        if canonical is None and key.strip().upper() in _QUORUM_APPCONFIG_KEYS:
            canonical = _QUORUM_APPCONFIG_KEYS[key.strip().upper()]
        if canonical:
            # Validate a pinned panel eagerly so a bad set is rejected NAMING the entry
            # rather than failing silently at the next run.
            if canonical == "QUORUM_PANEL_MODELS":
                from forecasting.models import ValidationError
                from forecasting.quorum import parse_panel_models_config, validate_panel_models

                try:
                    validate_panel_models(parse_panel_models_config(value))
                except ValidationError as exc:
                    raise SystemExit(f"forecast quorum config set: {exc}") from exc
            set_config_value(f"env.{canonical}", value)
            print(f"✓ set {canonical} = {value}  (config.yaml env:)")
            return
        set_config_value(f"quorum.{key}", value)
        print(f"✓ set quorum.{key} = {value}")
        return
    cfg = load_config().get("quorum", {})
    print("quorum config:")
    for key in (
        "default_enabled", "default_scope", "preset", "models",
        "judge", "pool_method", "trim", "model_timeout", "max_iterations",
        "delphi_rounds",
    ):
        print(f"  {key}: {cfg.get(key)}")
    # Operator-pinned panel (appconfig layer) — show the RESOLVED value + source so an
    # operator sees whether a pin comes from the env: section, a shell var, or is unset.
    from forecasting import appconfig

    ac = appconfig.get_config()
    ac.reload()
    print("  ── operator-pinned panel (appconfig) ──")
    for name in ("QUORUM_PANEL_MODELS", "QUORUM_JUDGE_MODEL"):
        value = ac.get_str(name, None)
        source = ac.source_of(name)
        print(f"  {name}: {value if value else '(unset)'}  [{source}]")


def _quorum_default(rest: list[str], *, scope: str | None) -> None:
    from hermes_cli.config import load_config, set_config_value

    state = rest[0].strip().lower() if rest else None
    if state in {"on", "off"}:
        set_config_value("quorum.default_enabled", "true" if state == "on" else "false")
        print(f"✓ quorum-by-default {'enabled' if state == 'on' else 'disabled'}")
    elif state is not None:
        raise SystemExit("forecast quorum default on|off")
    if scope:
        set_config_value("quorum.default_scope", scope)
        print(f"✓ quorum default scope = {scope}")
    cfg = load_config().get("quorum", {})
    print(f"quorum default_enabled: {bool(cfg.get('default_enabled'))}  "
          f"scope: {cfg.get('default_scope', 'high_impact')}")


def _quorum_calibration(args: argparse.Namespace) -> None:
    """Report how quorum disagreement relates to realised forecast error."""

    from forecasting.quorum_analysis import disagreement_calibration

    report = disagreement_calibration(_ledger(args))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    print(f"quorum disagreement → error  (n={report['n']} scored quorum forecasts)")
    if not report["n"]:
        print("  no scored quorum forecasts yet — resolve some and run again.")
        return
    corr = report["correlation"]
    print(f"  correlation(disagreement, brier): {corr if corr is not None else '—'}")
    for band in ("calm", "moderate", "high", "severe"):
        bucket = report["bands"].get(band)
        if bucket:
            print(f"    {band:<9} n={bucket['count']:<3} mean_brier={bucket['mean_brier']:.4f}")
    print(f"  → {report['interpretation']}")


def _quorum_bench(args: argparse.Namespace) -> None:
    """Read-only ensemble-size variance-reduction readout over resolved quorums.

    This NEVER changes any committed forecast or the live default ensemble size —
    it benchmarks how Brier variance falls as you add mean-pooled draws (AIA P1.4).
    """

    from forecasting.quorum_analysis import ensemble_bench

    seed = int(getattr(args, "seed", 0) or 0)
    draws_arg = getattr(args, "draws", None)
    draws = 500 if draws_arg is None else max(1, int(draws_arg))
    report = ensemble_bench(_ledger(args), seed=seed, draws=draws)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    print(
        f"quorum ensemble-size bench  (n_runs={report['n_runs']} resolved quorum forecasts)"
    )
    if not report["n_runs"]:
        print("  no resolved quorum forecasts yet — resolve some and run again.")
        return
    curve = report["curve"]["curve"]
    print(f"  bootstrap: draws={report['draws']} seed={report['seed']}")
    print("  k   mean_brier   95% CI width")
    for point in curve:
        print(
            f"  {point['k']:<3} {point['mean_brier']:<11.4f} {point['ci95_width']:.4f}"
        )
    var = report["variance"]
    print(
        f"  variance: sampling(LLM)={var['sampling_variance']:.5f}  "
        f"question={var['question_variance']:.5f}"
    )
    print(
        f"  Brier-of-mean={var['mean_brier_of_mean']:.5f}  "
        f"mean-of-Brier={var['mean_mean_of_brier']:.5f}  "
        f"Jensen gap={var['jensen_gap']:+.5f}  (>= 0 — the accuracy the simple mean buys)"
    )
