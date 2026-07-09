"""``forecast thesis …`` / ``forecast factor …`` — thesis + factor subcommands.

A carved CLI subcommand domain (the CLI-assembler analogue of a ledger domain
leaf). Registers its own subparsers via the shared ``register(forecast_sub)``
hook and owns its handlers; the assembler
(:func:`forecasting.cli.core.register_cli`) calls :func:`register` at this
domain's position so ``forecast --help`` stays byte-identical.

Shared helpers stay in ``core``. ``_resolve_question_id`` (never monkeypatched at
the façade) is imported bare; ``_ledger`` IS patched at ``forecasting.cli._ledger``
by tests, so it is reached through a call-time ``_core.`` wrapper — a test that
patches ``forecasting.cli._ledger`` (façade-forwarded to ``core._ledger``) reaches
these handlers' call sites too (the tool-registry ``_core.`` discipline; every
future domain that touches ``_ledger`` inherits this). The domain-private printers
(``_print_factor_distribution``, ``_format_thesis_band``) travelled with the
handlers. ``core`` imports this module back at its bottom for registration +
surface parity (``forecasting.cli._cmd_thesis_dashboard`` is imported by a test).
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from forecasting.models import OutcomeSpace

from forecasting.cli import core as _core
from forecasting.cli.core import _resolve_question_id


def _ledger(args: argparse.Namespace):
    """Delegate to ``core._ledger`` at CALL time so a test that patches
    ``forecasting.cli._ledger`` reaches these carved handlers (the ``_core.``
    monkeypatch discipline)."""

    return _core._ledger(args)


def register(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``thesis`` + ``factor`` command groups onto the subparsers."""

    # Thesis: aggregate the latest beliefs of several weighted member forecasts
    # into a single thesis-level health snapshot (the thesis lags its members).
    thesis_parser = forecast_sub.add_parser(
        "thesis",
        help="Group member forecasts under a thesis and aggregate their health",
    )
    thesis_sub = thesis_parser.add_subparsers(dest="thesis_command")
    thesis_create = thesis_sub.add_parser("create", help="Create a thesis question (outcome type 'thesis')")
    thesis_create.add_argument("title")
    thesis_create.add_argument("--criteria", help="Resolution criteria (>=5 words); a sensible default is used when omitted")
    thesis_create.add_argument("--domain")
    thesis_create.add_argument("--topics", help="Comma-separated topics")
    thesis_create.add_argument("--horizon", help="Free-text review horizon stored in question metadata")
    thesis_create.add_argument("--rho", type=float, help="Default member correlation stored in question metadata")
    thesis_create.set_defaults(_forecast_handler=_cmd_thesis_create)
    thesis_tag = thesis_sub.add_parser("tag", help="Tag a member forecast into a thesis (idempotent upsert)")
    thesis_tag.add_argument("thesis", help="row number, id, or search words for the thesis")
    thesis_tag.add_argument("member", help="row number, id, or search words for the member forecast")
    thesis_tag.add_argument("--weight", type=float, default=1.0)
    thesis_tag.add_argument("--direction", choices=["support", "inverted"], default="support")
    thesis_tag.add_argument("--role")
    thesis_tag.add_argument("--target", type=float, default=None)
    thesis_tag.add_argument(
        "--lo-is-good",
        dest="hi_is_good",
        action="store_false",
        default=True,
        help="Lower member values are good for the thesis (default: higher is good)",
    )
    thesis_tag.add_argument("--rationale", default="")
    thesis_tag.set_defaults(_forecast_handler=_cmd_thesis_tag)
    thesis_untag = thesis_sub.add_parser("untag", help="Untag a member from a thesis")
    thesis_untag.add_argument("thesis", help="row number, id, or search words for the thesis")
    thesis_untag.add_argument("member", help="row number, id, or search words for the member forecast")
    thesis_untag.set_defaults(_forecast_handler=_cmd_thesis_untag)
    thesis_members = thesis_sub.add_parser("members", help="List a thesis's member forecasts")
    thesis_members.add_argument("thesis", help="row number, id, or search words for the thesis")
    thesis_members.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    thesis_members.set_defaults(_forecast_handler=_cmd_thesis_members)
    thesis_aggregate = thesis_sub.add_parser("aggregate", help="Aggregate members into a fresh thesis snapshot")
    thesis_aggregate.add_argument("thesis", help="row number, id, or search words for the thesis")
    thesis_aggregate.add_argument("--rho", type=float, default=0.4)
    thesis_aggregate.set_defaults(_forecast_handler=_cmd_thesis_aggregate)
    thesis_corr = thesis_sub.add_parser("set-correlation", help="Pin a pairwise correlation between two thesis members (members co-move unequally)")
    thesis_corr.add_argument("thesis", help="row number, id, or search words for the thesis")
    thesis_corr.add_argument("member_a", help="member question id")
    thesis_corr.add_argument("member_b", help="member question id")
    thesis_corr.add_argument("rho", type=float, help="pairwise correlation in [0, 0.95]")
    thesis_corr.set_defaults(_forecast_handler=_cmd_thesis_set_correlation)
    thesis_event = thesis_sub.add_parser(
        "set-event",
        help="Configure the thesis as a JOINT THRESHOLD EVENT — P(#member successes >= K) via copula MC",
    )
    thesis_event.add_argument("thesis", help="row number, id, or search words for the thesis")
    thesis_event.add_argument(
        "--kind", choices=["count_threshold", "all", "any"], default="count_threshold",
        help="count_threshold (needs --threshold), all (=every member), or any (>=1 member)",
    )
    thesis_event.add_argument(
        "--threshold", type=int, default=None,
        help="K for count_threshold: P(at least K member successes)",
    )
    thesis_event.add_argument(
        "--clear", action="store_true", help="remove the event spec (revert to the mean-index headline)",
    )
    thesis_event.set_defaults(_forecast_handler=_cmd_thesis_set_event)
    thesis_member_iv = thesis_sub.add_parser(
        "member-intervals",
        help="Derive + stamp per-member probability intervals for a thesis's competitive binary members so its event band earns its width (dry-run by default)",
    )
    thesis_member_iv.add_argument("thesis", help="row number, id, or search words for the thesis")
    thesis_member_iv.add_argument("--weight-floor", type=float, default=1.5, help="Only members with weight >= this are backfilled (default 1.5)")
    thesis_member_iv.add_argument("--apply", action="store_true", help="Stamp the derived intervals onto each competitive member's snapshot (default is a dry-run preview).")
    thesis_member_iv.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    thesis_member_iv.set_defaults(_forecast_handler=_cmd_thesis_member_intervals)
    thesis_show = thesis_sub.add_parser("show", help="Show thesis health + per-member contributions (no commit)")
    thesis_show.add_argument("thesis", help="row number, id, or search words for the thesis")
    thesis_show.add_argument("--rho", type=float, default=0.4)
    thesis_show.add_argument(
        "--sensitivity", action="store_true",
        help="Add the explainability view: biggest marginal movers, stale members, and how the band depends on the correlation assumption",
    )
    thesis_show.set_defaults(_forecast_handler=_cmd_thesis_show)
    thesis_list = thesis_sub.add_parser("list", help="List thesis questions")
    thesis_list.add_argument("--limit", type=int, default=None)
    thesis_list.set_defaults(_forecast_handler=_cmd_thesis_list)
    thesis_dashboard = thesis_sub.add_parser("dashboard", help="Thesis master list (health / score / Δ / coverage / members) — the dedicated thesis dashboard")
    thesis_dashboard.add_argument("--json", action="store_true", help="Emit machine-readable thesis dashboard JSON")
    thesis_dashboard.set_defaults(_forecast_handler=_cmd_thesis_dashboard)

    # Entity suitability: register tradeable entities (equities, candidates,
    # currencies, sectors) under a thesis, weight them against member signals,
    # and read per-entity suitability + trade triggers off the aggregator.
    thesis_entity = thesis_sub.add_parser("entity", help="Manage entity suitability under a thesis")
    thesis_entity_sub = thesis_entity.add_subparsers(dest="thesis_entity_command")
    entity_add = thesis_entity_sub.add_parser("add", help="Register an entity under a thesis (no weights yet)")
    entity_add.add_argument("thesis", help="row number, id, or search words for the thesis")
    entity_add.add_argument("name", help="entity name (unique within the thesis)")
    entity_add.add_argument(
        "--kind",
        choices=["equity", "candidate", "currency", "sector", "entity"],
        default="entity",
    )
    entity_add.add_argument("--label", default=None)
    entity_add.add_argument("--action-threshold", dest="action_threshold", type=float, default=None)
    entity_add.set_defaults(_forecast_handler=_cmd_thesis_entity_add)
    entity_weight = thesis_entity_sub.add_parser("weight", help="Add/replace one member signal weight on an entity")
    entity_weight.add_argument("thesis", help="row number, id, or search words for the thesis")
    entity_weight.add_argument("name", help="entity name")
    entity_weight.add_argument("member", help="row number, id, or search words for the member forecast")
    entity_weight.add_argument("--weight", type=float, default=1.0)
    entity_weight.add_argument("--direction", choices=["support", "inverted"], default="support")
    entity_weight.add_argument("--target", type=float, default=None)
    entity_weight.add_argument(
        "--lo-is-good",
        dest="hi_is_good",
        action="store_false",
        default=True,
        help="Lower member values are good for this entity (default: higher is good)",
    )
    entity_weight.add_argument("--role", default=None)
    entity_weight.set_defaults(_forecast_handler=_cmd_thesis_entity_weight)
    entity_remove = thesis_entity_sub.add_parser("remove", help="Remove an entity from a thesis")
    entity_remove.add_argument("thesis", help="row number, id, or search words for the thesis")
    entity_remove.add_argument("name", help="entity name")
    entity_remove.set_defaults(_forecast_handler=_cmd_thesis_entity_remove)
    entity_list = thesis_entity_sub.add_parser("list", help="List a thesis's entities + their latest suitability")
    entity_list.add_argument("thesis", help="row number, id, or search words for the thesis")
    entity_list.add_argument("--rho", type=float, default=0.4)
    entity_list.set_defaults(_forecast_handler=_cmd_thesis_entity_list)

    # Factor: a weighted basket of constituent RETURN distributions, aggregated
    # by portfolio math into a return distribution + volatility + downside. A
    # factor is a thesis with metadata aggregation=factor, so it reuses the
    # thesis membership table (a SHORT constituent is direction='inverted').
    factor_parser = forecast_sub.add_parser(
        "factor",
        help="Build a weighted basket of constituent return distributions and aggregate it",
    )
    factor_sub = factor_parser.add_subparsers(dest="factor_command")
    factor_create = factor_sub.add_parser("create", help="Create a factor question (a thesis with aggregation=factor)")
    factor_create.add_argument("title")
    factor_create.add_argument("--units", default="return", help="Return units stored on the outcome space (default: return)")
    factor_create.add_argument("--domain")
    factor_create.add_argument("--topics", help="Comma-separated topics")
    factor_create.add_argument("--criteria", help="Resolution criteria (>=5 words); a sensible default is used when omitted")
    factor_create.add_argument("--rho", type=float, help="Default constituent correlation stored in question metadata")
    factor_create.set_defaults(_forecast_handler=_cmd_factor_create)
    factor_add = factor_sub.add_parser("add", help="Add a constituent return distribution to a factor (short → inverted)")
    factor_add.add_argument("factor", help="row number, id, or search words for the factor")
    factor_add.add_argument("constituent", help="row number, id, or search words for the constituent forecast")
    factor_add.add_argument("--weight", type=float, default=1.0)
    factor_add.add_argument("--direction", choices=["long", "short"], default="long")
    factor_add.set_defaults(_forecast_handler=_cmd_factor_add)
    factor_remove = factor_sub.add_parser("remove", help="Remove a constituent from a factor")
    factor_remove.add_argument("factor", help="row number, id, or search words for the factor")
    factor_remove.add_argument("constituent", help="row number, id, or search words for the constituent forecast")
    factor_remove.set_defaults(_forecast_handler=_cmd_factor_remove)
    factor_list = factor_sub.add_parser("list", help="List factor questions")
    factor_list.add_argument("--limit", type=int, default=None)
    factor_list.set_defaults(_forecast_handler=_cmd_factor_list)
    factor_aggregate = factor_sub.add_parser("aggregate", help="Aggregate constituents into a fresh factor snapshot")
    factor_aggregate.add_argument("factor", help="row number, id, or search words for the factor")
    factor_aggregate.add_argument("--rho", type=float, default=0.4)
    factor_aggregate.set_defaults(_forecast_handler=_cmd_factor_aggregate)
    factor_show = factor_sub.add_parser("show", help="Show the factor distribution + per-constituent contributions (no commit)")
    factor_show.add_argument("factor", help="row number, id, or search words for the factor")
    factor_show.add_argument("--rho", type=float, default=0.4)
    factor_show.set_defaults(_forecast_handler=_cmd_factor_show)


def _cmd_thesis_create(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    criteria = (args.criteria or "").strip() or (
        "Aggregate health of the tagged member forecasts; reviewed as members update."
    )
    topics = [t.strip() for t in (args.topics or "").split(",") if t.strip()] or None
    metadata: dict[str, Any] = {}
    if args.horizon:
        metadata["horizon"] = args.horizon
    if args.rho is not None:
        metadata["rho"] = float(args.rho)
    question = ledger.create_question(
        title=args.title,
        resolution_criteria=criteria,
        outcome_space=OutcomeSpace(type="thesis"),
        domain=args.domain,
        topics=topics,
        metadata=metadata or None,
    )
    print(f"created thesis {question.id}")
    print(f"title: {question.title}")
    print(f"status: {question.status}")
    if metadata.get("horizon"):
        print(f"horizon: {metadata['horizon']}")
    if "rho" in metadata:
        print(f"rho: {metadata['rho']}")


def _cmd_thesis_tag(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    thesis_id = _resolve_question_id(ledger, args.thesis)
    member_id = _resolve_question_id(ledger, args.member)
    row = ledger.add_thesis_member(
        thesis_id,
        member_id,
        direction=args.direction,
        weight=args.weight,
        role=args.role,
        target=args.target,
        hi_is_good=getattr(args, "hi_is_good", True),
        rationale=args.rationale or "",
        created_by="cli",
    )
    print(f"tagged member {row['member_question_id']} into thesis {thesis_id}")
    print(f"direction: {row['direction']}  weight: {row['weight']}")
    if row.get("role"):
        print(f"role: {row['role']}")
    if row.get("target") is not None:
        print(f"target: {row['target']}  hi_is_good: {row['hi_is_good']}")


def _cmd_thesis_untag(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    thesis_id = _resolve_question_id(ledger, args.thesis)
    member_id = _resolve_question_id(ledger, args.member)
    removed = ledger.remove_thesis_member(thesis_id, member_id)
    print(f"removed {removed} member(s) from thesis {thesis_id}")


def _cmd_thesis_members(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    thesis_id = _resolve_question_id(ledger, args.thesis)
    members = ledger.list_thesis_members(thesis_id)
    if getattr(args, "json", False):
        print(json.dumps({"thesis_id": thesis_id, "count": len(members), "members": members}, indent=2, sort_keys=True))
        return
    if not members:
        print("No members tagged. Add some with `forecast thesis tag <thesis> <member>`.")
        return
    print("Direction   Weight  Role            Target    Type          Member")
    for member in members:
        target = member.get("target")
        target_str = f"{float(target):.4g}" if target is not None else "-"
        print(
            f"{(member.get('direction') or '-'):<11} "
            f"{float(member.get('weight') or 0.0):<7.2f} "
            f"{(member.get('role') or '-'):<15} "
            f"{target_str:<9} "
            f"{(member.get('member_outcome_type') or '-'):<13} "
            f"{member.get('member_title') or member.get('member_question_id')}"
        )


def _cmd_thesis_set_correlation(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    thesis_id = _resolve_question_id(ledger, args.thesis)
    corr = ledger.set_thesis_correlation(thesis_id, args.member_a, args.member_b, args.rho)
    print(f"pinned pairwise correlations for thesis {thesis_id}:")
    for pair, rho in sorted(corr.items()):
        print(f"  {pair}: {rho}")
    print("(applied on the next aggregate; unspecified pairs fall back to the scalar rho)")


def _cmd_thesis_set_event(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    thesis_id = _resolve_question_id(ledger, args.thesis)
    if args.clear:
        removed = ledger.clear_thesis_event(thesis_id)
        print(f"cleared event spec for thesis {thesis_id}" if removed else "no event spec was set")
        return
    spec = ledger.set_thesis_event(thesis_id, kind=args.kind, threshold=args.threshold)
    print(f"thesis {thesis_id} configured as a joint threshold event: {spec}")
    print("(P(#member successes >= K) is stamped as event_probability on the next aggregate)")


def _cmd_thesis_aggregate(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    thesis_id = _resolve_question_id(ledger, args.thesis)
    result = ledger.aggregate_thesis(thesis_id, rho=args.rho)
    agg = result["aggregate"]
    print(f"thesis {thesis_id}: {result['title']}")
    print(f"members: {result['member_count']}")
    if agg.health is None:
        print("health: withheld (no usable fresh member signal)")
        for note in agg.notes:
            print(f"  note: {note}")
        if result.get("analyst_note_id"):
            print(f"analyst_note: {result['analyst_note_id']}")
        return
    event = result.get("event")
    if event is not None and getattr(event, "event_probability", None) is not None:
        kind = event.event.get("kind")
        k = event.event.get("threshold")
        label = f">={k} of {event.participants}" if kind == "count_threshold" else str(kind)
        cd = event.count_distribution or {}
        print(
            f"EVENT P({label}): {event.event_probability * 100:.1f}%  "
            f"(copula MC, {event.n_draws} draws, rho {event.rho:.2f})"
        )
        if cd:
            print(f"  count: mean {cd.get('mean', 0):.1f}  p10-p90 {cd.get('p10', 0):.0f}-{cd.get('p90', 0):.0f}")
        for sens in event.top_sensitivities(3):
            print(
                f"  swing: {sens.get('title') or sens.get('member_id')} "
                f"±2pp => {sens.get('delta_p_event', 0.0):+.1%} on P(event)"
            )
    print(f"health: {agg.health * 100:.1f}% (mean-index diagnostic)")
    print(f"score: {agg.thesis_score:.1f}  band: {_format_thesis_band(agg.band)}")
    print(f"coverage: {agg.coverage:.0%}  n_eff: {agg.n_eff:.1f}  rho: {agg.rho:.2f}")
    if result.get("snapshot_id"):
        print(f"snapshot: {result['snapshot_id']}")


def _cmd_thesis_member_intervals(args: argparse.Namespace) -> None:
    import json as _json

    ledger = _ledger(args)
    thesis_id = _resolve_question_id(ledger, args.thesis)
    apply = bool(getattr(args, "apply", False))
    if apply:
        from forecasting.ledger import allow_ledger_writes

        with allow_ledger_writes(reason="forecast thesis member-intervals --apply"):
            result = ledger.backfill_thesis_member_intervals(thesis_id, weight_floor=args.weight_floor, apply=True)
    else:
        result = ledger.backfill_thesis_member_intervals(thesis_id, weight_floor=args.weight_floor, apply=False)
    if getattr(args, "json", False):
        print(_json.dumps(result, indent=2, sort_keys=True))
        return
    mode = "APPLIED" if apply else "DRY-RUN (pass --apply to stamp)"
    print(f"thesis member-interval backfill {mode}")
    print(
        f"  {result['competitive_members']} competitive member(s) (weight >= {result['weight_floor']}); "
        f"panel-spread={result['by_source'].get('panel', 0)}, default-width={result['by_source'].get('default', 0)}"
    )
    if apply:
        print(f"  stamped {result['applied']} member snapshot(s) — re-aggregate the thesis to earn the band")
    for p in result["proposals"]:
        lo, hi = p["p_ci90"]
        print(f"    [{p['source']:<7}] w={p['weight']:.1f} p={p['committed_p']:.2f} ci90=[{lo:.2f},{hi:.2f}]  {(p['title'] or '')[:44]}")


def _cmd_thesis_show(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    thesis_id = _resolve_question_id(ledger, args.thesis)
    result = ledger.aggregate_thesis(thesis_id, rho=args.rho, commit=False)
    agg = result["aggregate"]
    print(f"thesis {thesis_id}: {result['title']}")
    print(f"members: {result['member_count']}")
    if agg.health is None:
        print("health: withheld (no usable fresh member signal)")
        for note in agg.notes:
            print(f"  note: {note}")
    else:
        print(f"health: {agg.health * 100:.1f}%  score: {agg.thesis_score:.1f}  band: {_format_thesis_band(agg.band)}")
        components = sorted(
            agg.components,
            key=lambda c: c.get("contribution_pts") or 0.0,
            reverse=True,
        )
        if components:
            print("")
            print("Direction   Weight  w_norm  signal  contrib_pts  Status   Member")
            for comp in components:
                s_i = comp.get("s_i")
                signal_str = f"{float(s_i):.3f}" if s_i is not None else "-"
                print(
                    f"{(comp.get('direction') or '-'):<11} "
                    f"{float(comp.get('weight') or 0.0):<7.2f} "
                    f"{float(comp.get('w_norm') or 0.0):<7.3f} "
                    f"{signal_str:<7} "
                    f"{float(comp.get('contribution_pts') or 0.0):<+12.2f} "
                    f"{(comp.get('status') or '-'):<8} "
                    f"{comp.get('title') or comp.get('member_id')}"
                )
    entities = result.get("entities") or []
    if entities:
        print("")
        print("ENTITY SUITABILITY")
        print("Name              Kind        Suitability  Stance            Δ(pp)   Top driver")
        for entity in entities:
            delta = entity.get("delta")
            delta_str = f"{delta * 100:+.0f}" if isinstance(delta, (int, float)) else "-"
            trend = entity.get("trend")
            stance = entity.get("stance") or "-"
            stance_str = f"{stance} ({trend})" if trend else stance
            print(
                f"{(entity.get('name') or '-'):<17} "
                f"{(entity.get('kind') or 'entity'):<11} "
                f"{(entity.get('suitability_display') or '—'):<12} "
                f"{stance_str:<17} "
                f"{delta_str:<7} "
                f"{entity.get('top_driver') or '-'}"
            )
    triggers = result.get("triggers") or []
    if triggers:
        print("")
        print("TRADE TRIGGERS")
        for trigger in triggers:
            note_line = trigger.get("note")
            if note_line:
                print(f"  {note_line}")
    if getattr(args, "sensitivity", False) and agg.health is not None:
        print("")
        print("EXPLAINABILITY")
        # Biggest marginal movers: which member swings thesis health most if dropped.
        movers = sorted(agg.components, key=lambda c: abs(c.get("marginal_health_delta") or 0.0), reverse=True)
        top_movers = [m for m in movers if (m.get("marginal_health_delta") or 0.0) != 0.0][:3]
        if top_movers:
            print("  biggest movers (leave-one-out health delta):")
            for mover in top_movers:
                label = mover.get("title") or mover.get("member_id")
                print(f"    {label}: {float(mover.get('marginal_health_delta') or 0.0) * 100:+.1f} pp")
        # Stale members: signal aging out (the thesis lags a member that stopped updating).
        stale = [c for c in agg.components if (c.get("status") or "") == "stale"]
        if stale:
            print("  stale members: " + ", ".join((c.get("title") or c.get("member_id")) for c in stale))
        # Correlation sensitivity: how much the honest band depends on the co-movement
        # assumption (members co-move, so the band is only as trustworthy as rho).
        print("  correlation sensitivity (band vs assumed rho):")
        for assumed in (0.0, 0.2, 0.4, 0.6, 0.8):
            swept = ledger.aggregate_thesis(thesis_id, rho=assumed, commit=False)["aggregate"]
            if swept.band:
                width = swept.band[2] - swept.band[0]
                print(f"    rho={assumed:.1f}: band {_format_thesis_band(swept.band)}  width {width:.1f}  n_eff {swept.n_eff:.2f}")

    note = ledger.latest_analyst_note(thesis_id, kind="brief")
    if note and note.get("headline"):
        print("")
        print(f"latest note: {note['headline']}")


def _cmd_thesis_dashboard(args: argparse.Namespace) -> None:
    """The dedicated thesis dashboard: a master list of every active thesis (health /
    score / Δ / coverage / members), reusing the same payload the gateway serves on
    `forecast.theses` and the TUI lens renders."""
    from forecasting.dashboard import build_factor_summary, build_thesis_summary

    ledger = _ledger(args)
    rows = build_thesis_summary(ledger=ledger)
    factors = build_factor_summary(ledger=ledger)
    if args.json:
        print(json.dumps({"theses": rows, "factors": factors}, indent=2, sort_keys=True))
        return
    if not rows and not factors:
        print("No active theses. Create one with `forecast thesis create <title>`.")
        return

    def _num(value: Any, fmt: str, *, pct: bool = False) -> str:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return "-"
        return format(value * 100 if pct else value, fmt)

    if rows:
        print(f"{'thesis':<44} {'health':>7} {'score':>7} {'Δ':>6} {'cov':>5} {'n_eff':>6} {'mem':>4}  status")
        for r in rows:
            delta = r.get("delta")
            delta_txt = (_num(delta, "+.0f", pct=True) + "pp") if isinstance(delta, (int, float)) and not isinstance(delta, bool) else "-"
            print(
                f"{(r['title'] or '')[:44]:<44} "
                f"{(r['health_display'] or '-'):>7} "
                f"{_num(r.get('thesis_score'), '.1f'):>7} "
                f"{delta_txt:>6} "
                f"{_num(r.get('coverage'), '.2f'):>5} "
                f"{_num(r.get('n_eff'), '.1f'):>6} "
                f"{r.get('member_count', 0):>4}  {r.get('status', '')}"
            )
    if factors:
        print(f"\n{'factor (basket)':<44} {'members':>7}  status")
        for f in factors:
            print(f"{(f.get('title') or '')[:44]:<44} {f.get('member_count', 0):>7}  {f.get('status', '')}")


def _cmd_thesis_list(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    theses = [q for q in ledger.list_questions(status="active") if ledger.is_thesis(q)]
    if args.limit is not None:
        theses = theses[: args.limit]
    if not theses:
        print("No thesis questions found. Create one with `forecast thesis create <title>`.")
        return
    print("ID             Members  Health    Title")
    for thesis in theses:
        member_count = len(ledger.list_thesis_members(thesis.id))
        snapshot = ledger.get_current_snapshot(thesis.id)
        health = "-"
        if snapshot is not None:
            payload = snapshot.probability_or_distribution
            if isinstance(payload, dict) and payload.get("health") is not None:
                health = f"{float(payload['health']) * 100:.1f}%"
        print(f"{thesis.id:<14} {member_count:<8} {health:<9} {thesis.title}")


def _cmd_factor_create(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    criteria = (args.criteria or "").strip() or (
        "Portfolio return of the weighted constituent basket; reviewed as constituents update."
    )
    topics = [t.strip() for t in (args.topics or "").split(",") if t.strip()] or None
    metadata: dict[str, Any] = {"aggregation": "factor"}
    if args.rho is not None:
        metadata["rho"] = float(args.rho)
    units = (args.units or "return").strip() or "return"
    question = ledger.create_question(
        title=args.title,
        resolution_criteria=criteria,
        outcome_space=OutcomeSpace(type="thesis", units=units),
        domain=args.domain,
        topics=topics,
        metadata=metadata,
    )
    print(f"created factor {question.id}")
    print(f"title: {question.title}")
    print(f"status: {question.status}")
    print(f"units: {units}")
    if "rho" in metadata:
        print(f"rho: {metadata['rho']}")


def _cmd_factor_add(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    factor_id = _resolve_question_id(ledger, args.factor)
    constituent_id = _resolve_question_id(ledger, args.constituent)
    direction = "inverted" if args.direction == "short" else "support"
    row = ledger.add_thesis_member(
        factor_id,
        constituent_id,
        direction=direction,
        weight=args.weight,
    )
    side = "short" if row["direction"] == "inverted" else "long"
    print(f"added constituent {row['member_question_id']} to factor {factor_id}")
    print(f"direction: {side}  weight: {float(row['weight']):.2f}")


def _cmd_factor_remove(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    factor_id = _resolve_question_id(ledger, args.factor)
    constituent_id = _resolve_question_id(ledger, args.constituent)
    removed = ledger.remove_thesis_member(factor_id, constituent_id)
    print(f"removed {removed} constituent(s) from factor {factor_id}")


def _cmd_factor_list(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    factors = [q for q in ledger.list_questions(status="active") if ledger.is_factor(q)]
    if args.limit is not None:
        factors = factors[: args.limit]
    if not factors:
        print("No factor questions found. Create one with `forecast factor create <title>`.")
        return
    print("ID             Const.   μ         vol       Title")
    for factor in factors:
        const_count = len(ledger.list_thesis_members(factor.id))
        mean_str = "-"
        vol_str = "-"
        snapshot = ledger.get_current_snapshot(factor.id)
        if snapshot is not None:
            payload = snapshot.probability_or_distribution
            if isinstance(payload, dict):
                if payload.get("factor_mean") is not None:
                    mean_str = f"{float(payload['factor_mean']):+.3f}"
                if payload.get("factor_sd") is not None:
                    vol_str = f"{float(payload['factor_sd']):.3f}"
        print(f"{factor.id:<14} {const_count:<8} {mean_str:<9} {vol_str:<9} {factor.title}")


def _print_factor_distribution(payload: dict[str, Any]) -> None:
    print(f"μ (mean return): {float(payload['factor_mean']):+.4f}")
    print(f"σ (volatility):  {float(payload['factor_sd']):.4f}")
    print(
        f"90% band: [{float(payload['q05']):+.4f} .. {float(payload['q95']):+.4f}]"
    )
    print(f"downside (q05):  {float(payload['downside']):+.4f}")
    print(f"CVaR (5%):       {float(payload['cvar']):+.4f}")
    print(f"coverage: {float(payload['coverage']):.0%}  n_eff: {float(payload['n_eff']):.1f}")


def _cmd_factor_aggregate(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    factor_id = _resolve_question_id(ledger, args.factor)
    result = ledger.aggregate_thesis(factor_id, rho=args.rho)
    payload = result.get("payload") or {}
    print(f"factor {factor_id}: {result['title']}")
    print(f"constituents: {result['member_count']}")
    if payload.get("factor_mean") is None:
        print("distribution: withheld — insufficient fresh constituents")
        for note in (result["aggregate"].notes or []):
            print(f"  note: {note}")
        if result.get("analyst_note_id"):
            print(f"analyst_note: {result['analyst_note_id']}")
        return
    _print_factor_distribution(payload)
    if result.get("snapshot_id"):
        print(f"snapshot: {result['snapshot_id']}")


def _cmd_factor_show(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    factor_id = _resolve_question_id(ledger, args.factor)
    result = ledger.aggregate_thesis(factor_id, rho=args.rho, commit=False)
    agg = result["aggregate"]
    payload = result.get("payload") or {}
    print(f"factor {factor_id}: {result['title']}")
    print(f"constituents: {result['member_count']}")
    if payload.get("factor_mean") is None:
        print("distribution: withheld — insufficient fresh constituents")
        for note in (agg.notes or []):
            print(f"  note: {note}")
    else:
        _print_factor_distribution(payload)
        components = sorted(
            agg.components,
            key=lambda c: abs(c.get("contribution") or 0.0),
            reverse=True,
        )
        if components:
            print("")
            print("Direction   Title                       Weight  w_norm  μ(mu)     σ(sigma)  contribution")
            for comp in components:
                mu = comp.get("mu")
                sigma = comp.get("sigma")
                mu_str = f"{float(mu):+.4f}" if mu is not None else "-"
                sigma_str = f"{float(sigma):.4f}" if sigma is not None else "-"
                title = comp.get("title") or comp.get("member_id") or "-"
                print(
                    f"{(comp.get('direction') or '-'):<11} "
                    f"{title[:27]:<27} "
                    f"{float(comp.get('weight') or 0.0):<7.2f} "
                    f"{float(comp.get('w_norm') or 0.0):<7.3f} "
                    f"{mu_str:<9} "
                    f"{sigma_str:<9} "
                    f"{float(comp.get('contribution') or 0.0):+.4f}"
                )
    note = ledger.latest_analyst_note(factor_id, kind="brief")
    if note and note.get("headline"):
        print("")
        print(f"latest note: {note['headline']}")


def _cmd_thesis_entity_add(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    thesis_id = _resolve_question_id(ledger, args.thesis)
    entity = ledger.add_thesis_entity(
        thesis_id,
        args.name,
        label=args.label,
        kind=args.kind,
        action_threshold=args.action_threshold,
        created_by="cli",
    )
    print(f"entity {entity['name']} ({entity.get('kind') or 'entity'}) on thesis {thesis_id}")
    if entity.get("label"):
        print(f"label: {entity['label']}")
    if entity.get("action_threshold") is not None:
        print(f"action_threshold: {entity['action_threshold']}")


def _cmd_thesis_entity_weight(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    thesis_id = _resolve_question_id(ledger, args.thesis)
    member_id = _resolve_question_id(ledger, args.member)
    entity = ledger.set_entity_weight(
        thesis_id,
        args.name,
        member_id,
        weight=args.weight,
        direction=args.direction,
        hi_is_good=getattr(args, "hi_is_good", True),
        target=args.target,
        role=args.role,
    )
    print(f"weight set on entity {entity['name']}: {member_id} → {args.weight:.2f}·{args.direction}")
    print(f"weights: {len(entity.get('weights') or [])}")


def _cmd_thesis_entity_remove(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    thesis_id = _resolve_question_id(ledger, args.thesis)
    removed = ledger.remove_thesis_entity(thesis_id, args.name)
    print(f"removed {removed} entity(ies) from thesis {thesis_id}")


def _cmd_thesis_entity_list(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    thesis_id = _resolve_question_id(ledger, args.thesis)
    entities = ledger.list_thesis_entities(thesis_id)
    if not entities:
        print("No entities registered. Add some with `forecast thesis entity add <thesis> <name>`.")
        return
    print("Name              Kind        Label            Weights  Signals")
    for entity in entities:
        weights = entity.get("weights") or []
        signal_strs = []
        for weight in weights:
            direction = weight.get("direction") or "support"
            signal_strs.append(
                f"{weight.get('member_id')}→{float(weight.get('weight') or 0.0):.2g}·{direction}"
            )
        signals = ", ".join(signal_strs) if signal_strs else "-"
        print(
            f"{(entity.get('name') or '-'):<17} "
            f"{(entity.get('kind') or 'entity'):<11} "
            f"{(entity.get('label') or '-'):<16} "
            f"{len(weights):<8} "
            f"{signals}"
        )
    # If the thesis has a current aggregate, also surface the latest suitability.
    try:
        result = ledger.aggregate_thesis(thesis_id, rho=args.rho, commit=False)
    except Exception:
        result = None
    suitability_rows = (result or {}).get("entities") or []
    if suitability_rows:
        print("")
        print("Name              Suitability  Stance")
        for row in suitability_rows:
            print(
                f"{(row.get('name') or '-'):<17} "
                f"{(row.get('suitability_display') or '—'):<12} "
                f"{row.get('action') or row.get('stance') or '-'}"
            )


def _format_thesis_band(band: Any) -> str:
    """Format the (q05, q50, q95) 0..100 band tuple, or '-' when withheld."""

    if not band:
        return "-"
    q05, q50, q95 = band
    return f"{q05:.1f} / {q50:.1f} / {q95:.1f}"
