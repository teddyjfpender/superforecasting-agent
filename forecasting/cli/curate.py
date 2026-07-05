"""``forecast curate`` — propose calibration-fuel questions from live markets.

A carved CLI subcommand domain (registered via the shared ``register`` hook). It
fetches live prediction-market events, screens them to SHORT-HORIZON CONTESTED
LIQUID BINARIES with :func:`forecasting.curation.curate_market_candidates`, and
prints the survivors with a pre-drafted resolution criterion — a proposal the
operator confirms PER QUESTION. Nothing is created without an explicit
``--create <n>`` (never auto-created); the bare verb is a read-only dry run.

The market fetch lives here (the pure curation module stays network- and
ledger-free); ``_ledger`` is reached through a call-time ``_core.`` wrapper so a
test that patches ``forecasting.cli._ledger`` reaches this handler too.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from forecasting.cli import core as _core
from forecasting.curation import CurationFilters, curate_market_candidates
from forecasting.models import OutcomeSpace


def _ledger(args: argparse.Namespace):
    return _core._ledger(args)


def register(forecast_sub: argparse._SubParsersAction) -> None:
    curate = forecast_sub.add_parser(
        "curate",
        help="Propose short-horizon contested binary questions from live markets (calibration fuel)",
    )
    curate.add_argument("--venue", default=None, help="Restrict to one venue (polymarket/kalshi); default both")
    curate.add_argument("--query", default=None, help="Optional market search query")
    curate.add_argument("--tag", default=None, help="Optional Polymarket tag/category filter")
    curate.add_argument("--limit", type=int, default=60, help="Max live events to fetch and screen")
    curate.add_argument("--price-min", type=float, default=None, help="Contested-band lower bound (default 0.15)")
    curate.add_argument("--price-max", type=float, default=None, help="Contested-band upper bound (default 0.85)")
    curate.add_argument("--max-horizon-days", type=float, default=None, help="Resolve-within horizon (default 45)")
    curate.add_argument("--min-volume", type=float, default=None, help="Advisory liquidity floor (default 1000)")
    curate.add_argument(
        "--create",
        default=None,
        help="Comma-separated candidate numbers to CREATE (explicit per-question confirm); omit for a dry run",
    )
    curate.add_argument("--json", action="store_true", help="Emit machine-readable proposals")
    curate.set_defaults(_forecast_handler=_cmd_curate)


def _filters(args: argparse.Namespace) -> CurationFilters:
    base = CurationFilters()
    return CurationFilters(
        price_min=args.price_min if args.price_min is not None else base.price_min,
        price_max=args.price_max if args.price_max is not None else base.price_max,
        max_horizon_days=args.max_horizon_days if args.max_horizon_days is not None else base.max_horizon_days,
        min_volume=args.min_volume if args.min_volume is not None else base.min_volume,
    )


def _fetch_pairs(args: argparse.Namespace) -> list[Any]:
    """Fetch live (event, distribution) pairs from the PM data plane. Isolated so
    tests can monkeypatch it without touching the network."""
    from forecasting.pm import PMService

    service = PMService()
    limit = max(1, min(int(args.limit or 60), 200))
    return service.list_events(
        venue=str(args.venue) if args.venue else None,
        query=args.query or None,
        tag=args.tag or None,
        limit=limit,
    )


def _cmd_curate(args: argparse.Namespace) -> None:
    pairs = _fetch_pairs(args)
    report = curate_market_candidates(pairs, filters=_filters(args))
    candidates = report.candidates

    create_indices: list[int] = []
    if args.create:
        for token in str(args.create).split(","):
            token = token.strip()
            if token.isdigit():
                create_indices.append(int(token))

    if args.json and not create_indices:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return

    if not candidates:
        print("No contested short-horizon binary candidates found.")
        print(f"screened {report.screened} market(s); rejected {report.rejected}")
        return

    if not create_indices:
        # Dry run — propose only. Nothing is created.
        print(
            f"{len(candidates)} contested short-horizon binary candidate(s) "
            f"from {report.screened} screened market(s):"
        )
        for i, candidate in enumerate(candidates, start=1):
            horizon = f"{candidate.horizon_days:.0f}d" if candidate.horizon_days is not None else "?"
            print(
                f"\n[{i}] {candidate.title}  "
                f"(p={candidate.market_probability * 100:.0f}%, {horizon}, {candidate.venue})"
            )
            print(f"    criteria: {candidate.resolution_criteria}")
            if candidate.url:
                print(f"    url: {candidate.url}")
        print(
            f"\nProposal only — nothing created. Confirm one with "
            f"`forecast curate --create <n>` (per-question)."
        )
        return

    # Explicit per-question confirmation → create the selected candidates.
    ledger = _ledger(args)
    created = 0
    for index in create_indices:
        if index < 1 or index > len(candidates):
            print(f"skip {index}: out of range (1..{len(candidates)})")
            continue
        candidate = candidates[index - 1]
        question = ledger.create_question(
            title=candidate.title,
            resolution_criteria=candidate.resolution_criteria,
            outcome_space=OutcomeSpace(type="binary"),
            domain=candidate.domain,
            close_time=candidate.close_time,
            metadata={
                "curated_from": {
                    "venue": candidate.venue,
                    "event_id": candidate.event_id,
                    "market_id": candidate.market_id,
                    "url": candidate.url,
                    "market_probability": candidate.market_probability,
                }
            },
        )
        created += 1
        print(f"created {question.id}: {question.title}")
    print(f"created {created} question(s) from {len(create_indices)} confirmation(s).")
