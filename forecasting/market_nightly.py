"""AIA P2.1 — the MarketNightly future-close LIVE benchmark.

The paper's core epistemic point: a backtest can never fully rule out
foreknowledge (the model may have ingested the answer during pre-training, or a
leakage check may miss a subtle channel). The only *defensible* claim of live
superiority comes from a continuously-running benchmark on questions that
resolve in the FUTURE: sample currently-OPEN markets, forecast NOW, and score
on confirmed settlement. A future market close is a sampling safeguard, not
proof that the underlying event was still unknown: event timing and evidence
availability require separate audit.

This module makes that invariant load-bearing:

  * :func:`sample_open_markets` is PURE — it keeps ONLY markets whose
    close/resolution time is STRICTLY AFTER ``as_of`` (a market closing exactly
    at, or before, the forecast instant is rejected), takes up to ``n`` with a
    seeded deterministic pick, and reports the rejected count so a caller can
    see how many candidates failed the foreknowledge filter.

  * :func:`record_pending` stores, for each sampled market, a live snapshot
    tagged ``forecast_origin="market_nightly"`` at ``as_of`` carrying the AGENT
    forecast, plus the de-vigged MARKET price as a baseline comparison. It
    RE-ASSERTS the strictly-future-close invariant before writing anything — a
    non-future-close entry raises and is never stored.

  * :func:`score_matured` finds pending market-nightly entries whose market has
    since RESOLVED (a confirmed resolution exists AND its close <= ``now``),
    records nothing new about Brier itself — it reuses the ledger's existing
    scoring + baseline machinery to score the agent forecast and the market
    baseline against the realized binary outcome.

  * :func:`market_nightly_report` rolls the scored set up READ-ONLY: pending vs
    scored counts, mean agent Brier vs mean market Brier, and the paired
    agent-edge with the P0.2 seeded paired-bootstrap p-value/CI (reusing
    :meth:`ForecastLedger._paired_brier_summary`).

HARD CONSTRAINTS honored here:
  (a) Nothing hits a live market API. The market source and the agent
      forecaster are INJECTED seams (callables); this module never imports or
      calls a network adapter. The CLI only runs them when explicitly invoked.
  (b) The future-close invariant is enforced at BOTH the pure sampler and
      the storing step — a violation is rejected and counted, never silently
      admitted.
  (c) Additive only: no existing forecast number, score, or default changes.
      market-nightly snapshots are ``calibration_eligible=False`` and carry the
      segregated ``forecast_origin="market_nightly"`` tag, so they never enter
      the live calibration profile or the agent's curated live book.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from forecasting.ledger import allow_ledger_writes_decorator
from forecasting.models import (
    OutcomeSpace,
    parse_timestamp,
    timestamp_to_datetime,
    utc_now_iso,
)

# The segregated origin tag + the baseline_type used for the de-vigged market
# price. ``MARKET_BASELINE_TYPE`` is one of the market-typed strings
# :func:`forecasting.market_ensemble.collect_market_llm_triples` already
# recognises, so the nightly market baselines also flow into the P1.3
# complementarity surface for free.
MARKET_NIGHTLY_ORIGIN = "market_nightly"
MARKET_BASELINE_TYPE = "market_price"
# A metadata marker on the stored snapshot so score_matured / the report can find
# market-nightly entries without scanning every snapshot field.
PENDING_MARKER = "market_nightly"

# The A/B research arms. ``plain`` is the plain agent-protocol packet (the existing
# accrued record); ``voi`` is the research-disciplined variant (VOI research plan +
# adequacy floor). Any legacy row WITHOUT an arm field reads as ``plain`` (back-compat),
# so the historical record is fully comparable to the plain arm going forward.
DEFAULT_RESEARCH_ARM = "plain"
RESEARCH_ARMS = ("plain", "voi")


def _normalize_arm(arm: Any) -> str:
    """Coerce an arm value to one of :data:`RESEARCH_ARMS`; unknown/blank -> ``plain``."""

    val = str(arm or "").strip().lower()
    return val if val in RESEARCH_ARMS else DEFAULT_RESEARCH_ARM

# CONTEMPORANEOUS-BASELINE THRESHOLD. The live-edge "agent beats the market" claim is
# only honest when the market price the agent is measured against was sampled at (very
# nearly) the SAME instant as the forecast. A baseline whose price vintage
# (``price_asof``) is older than this gap from the forecast instant is a FROZEN prior
# (e.g. a ForecastBench freeze price stamped weeks before the run) and is QUARANTINED
# from the headline edge — it is still scored, just in a separate diagnostic bucket.
# 48h is generous enough to absorb a same-day/next-day live fetch while still excluding
# a multi-day-stale frozen baseline.
CONTEMPORANEOUS_THRESHOLD_SECONDS = 48 * 3600


# ── injected-seam contracts (Callables — no live API in this module) ──────────
#
# ``MarketSource``  : () -> Sequence[market dicts]. Each market is a mapping with
#                     at least an id, a YES probability (raw market price, to be
#                     de-vigged), and a close/resolution time. Real callers wire
#                     this to a market adapter; tests wire a fake.
# ``AgentForecaster``: (market) -> float in [0, 1]. The agent's P(yes) for the
#                     market's question, produced NOW (at as_of). Real callers
#                     wire the forecasting agent; tests wire a fake.
# ``MarketDevig``    : (market) -> float in [0, 1]. The fair YES probability after
#                     removing the vig. Defaults to :func:`default_market_devig`.
MarketSource = Callable[[], Sequence[Mapping[str, Any]]]
AgentForecaster = Callable[[Mapping[str, Any]], float]
MarketDevig = Callable[[Mapping[str, Any]], float]


# ── numeric / field helpers ───────────────────────────────────────────────────


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _coerce_prob(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return _clamp01(f)


def _first(market: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in market and market[key] is not None:
            return market[key]
    return None


def market_id(market: Mapping[str, Any]) -> str:
    """A stable id for a market dict (so re-sampling is idempotent per market)."""

    raw = _first(market, "id", "market_id", "slug", "ticker", "question_id")
    return str(raw) if raw is not None else ""


def market_close_time(market: Mapping[str, Any]) -> str | None:
    """The market's close/resolution instant as a normalized timestamp, or None.

    Prefers the explicit close time, then a resolution time, then a generic end
    date. The STRICTER of close/resolution is what gates admissibility; we use
    the EARLIEST present so a market cannot sneak in by advertising a late
    resolution while already closed."""

    candidates = [
        _first(market, "close_time", "closeTime", "close"),
        _first(market, "resolution_time", "resolutionTime", "end_date", "endDate"),
    ]
    parsed: list[str] = []
    for c in candidates:
        if c is None or not str(c).strip():
            continue
        try:
            p = parse_timestamp(str(c))
        except Exception:  # noqa: BLE001 — a malformed close/resolution is UNUSABLE,
            continue  # so this candidate is dropped (-> rejected), never raised.
        if p:
            parsed.append(p)
    if not parsed:
        return None
    return min(parsed)


def market_yes_price(market: Mapping[str, Any]) -> float | None:
    """The raw market YES probability/price (pre-devig)."""

    return _coerce_prob(
        _first(market, "probability", "yes_price", "yes", "price", "mid", "yes_mid")
    )


def default_market_devig(market: Mapping[str, Any]) -> float:
    """De-vig a market dict's quotes into a fair YES probability.

    Reuses :func:`forecasting.bayes_toolkit.devig_binary_market` when paired
    bid/ask quotes are present (removes the overround); otherwise the single YES
    price de-vigs to itself. Pure: never touches a network."""

    from forecasting import bayes_toolkit

    bid_yes = _first(market, "bid_yes", "bidYes")
    ask_yes = _first(market, "ask_yes", "askYes")
    if bid_yes is not None and ask_yes is not None:
        try:
            return _clamp01(
                bayes_toolkit.devig_binary_market(
                    float(bid_yes),
                    float(ask_yes),
                    bid_no=_first(market, "bid_no", "bidNo"),
                    ask_no=_first(market, "ask_no", "askNo"),
                )
            )
        except Exception:
            pass
    price = market_yes_price(market)
    if price is None:
        raise ValueError(f"market {market_id(market)!r} has no readable YES price to de-vig")
    return price


def _is_strictly_future_close(close: str | None, as_of: str) -> bool:
    """The future-close admissibility test: close STRICTLY > as_of.

    A missing close, or a close at/earlier than the forecast instant, is
    INADMISSIBLE. Passing this timing test alone does not rule out an already
    known underlying event."""

    if not close:
        return False
    # Callers normalize as_of before calling; parse defensively so a stray raw
    # value rejects (returns False) rather than raising.
    close_dt = timestamp_to_datetime(close)
    try:
        as_of_dt = timestamp_to_datetime(parse_timestamp(as_of, field_name="as_of"))
    except Exception:  # noqa: BLE001
        as_of_dt = None
    if close_dt is None or as_of_dt is None:
        return False
    return close_dt > as_of_dt


# ── baseline price-provenance (the contemporaneous-vs-frozen distinguisher) ────


def market_price_asof(market: Mapping[str, Any], *, forecast_as_of: str) -> str:
    """The TRUE price-sample timestamp of this market's baseline YES price.

    A direct manifold/metaculus/polymarket fetch carries the LIVE quote, so its
    ``price_asof`` is the fetch instant (which the source adapters now stamp, and
    which equals the forecast instant to within the sweep duration). A
    forecastbench-sourced market carries a FROZEN freeze price whose vintage is the
    set's ``freeze_datetime`` — recorded as ``price_asof``. When a market dict omits
    an explicit ``price_asof`` we fall back to the forecast instant (the safe
    assumption for a live source); a forecastbench id is additionally treated as
    frozen by :func:`baseline_is_contemporaneous` so a missing stamp on a legacy
    frozen row is never mis-counted as live."""

    raw = _first(market, "price_asof", "priceAsOf", "price_as_of")
    if raw is not None and str(raw).strip():
        try:
            parsed = parse_timestamp(str(raw))
        except Exception:  # noqa: BLE001 — a garbage stamp falls back to forecast instant
            parsed = None
        if parsed:
            return parsed
    return forecast_as_of


def _baseline_lag_seconds(price_asof: str | None, forecast_as_of: str | None) -> float | None:
    """``forecast_as_of - price_asof`` in seconds (how STALE the baseline price is), or
    None when either instant is unparseable."""

    pa = timestamp_to_datetime(price_asof) if price_asof else None
    fa = timestamp_to_datetime(forecast_as_of) if forecast_as_of else None
    if pa is None or fa is None:
        return None
    return (fa - pa).total_seconds()


def baseline_is_contemporaneous(
    *,
    metadata: Mapping[str, Any] | None = None,
    forecast_as_of: str | None = None,
    market_id_str: str | None = None,
    source: str | None = None,
) -> bool:
    """Classify a recorded market baseline as CONTEMPORANEOUS (live) vs FROZEN (stale).

    Robust to both the new honestly-recorded rows AND legacy rows written before the
    fix, in priority order:

      1. an explicit recorded ``contemporaneous`` bool (newest rows),
      2. an explicit recorded ``baseline_is_frozen`` bool,
      3. a recorded ``price_asof`` vs ``forecast_as_of`` GAP under the threshold,
      4. FALLBACK for legacy rows that predate the provenance fields — a
         ``forecastbench:`` market id (or ``forecastbench`` source) is FROZEN; any
         other (direct live-fetch) market is contemporaneous.

    The legacy fallback deliberately does NOT trust a baseline ``as_of`` that equals
    the forecast instant: the pre-fix bug stamped every frozen freeze price with the
    forecast time, so that gap reads as zero and would mis-classify a stale baseline
    as live. The id/source proxy is what survives that bug."""

    meta = metadata or {}
    flag = meta.get("contemporaneous")
    if isinstance(flag, bool):
        return flag
    frozen = meta.get("baseline_is_frozen")
    if isinstance(frozen, bool):
        return not frozen
    price_asof = meta.get("price_asof")
    fa = meta.get("forecast_as_of") or forecast_as_of
    if price_asof:
        lag = _baseline_lag_seconds(price_asof, fa)
        if lag is not None:
            return lag <= CONTEMPORANEOUS_THRESHOLD_SECONDS
    # Legacy fallback: a frozen ForecastBench baseline is identifiable by its id/source.
    mid = str(market_id_str or "").strip().lower()
    src = str(source or "").strip().lower()
    if mid.startswith("forecastbench") or src.startswith("forecastbench"):
        return False
    return True


# ── 1. the pure, seeded future-close sampler ───────────────────────────


def sample_open_markets(
    markets: Sequence[Mapping[str, Any]],
    as_of: str,
    n: int,
    *,
    rng_seed: int = 0,
) -> dict[str, Any]:
    """Keep ONLY strictly-future-close markets, then take up to ``n`` (seeded).

    PURE: no I/O, no ledger, no clock — ``as_of`` is supplied by the caller. The
    future-close filter drops every market whose close/resolution time is
    not STRICTLY after ``as_of`` (a market closing exactly at, or before, the
    forecast instant is rejected). The surviving markets are shuffled with a
    seeded :class:`random.Random` and the first ``n`` are taken, so the pick is
    deterministic for a given ``(markets, rng_seed)``.

    Returns ``{"sampled": [...], "admissible": int, "rejected": int,
    "rejected_ids": [...], "as_of": str, "n_requested": int}``. ``rejected`` is
    the count of candidates that FAILED the foreknowledge filter, so the caller
    can see exactly how many samples violated the invariant.
    """

    as_of_norm = parse_timestamp(as_of, field_name="as_of")
    if not as_of_norm:
        raise ValueError("sample_open_markets requires a concrete as_of timestamp")

    admissible: list[Mapping[str, Any]] = []
    rejected_ids: list[str] = []
    for market in markets:
        close = market_close_time(market)
        if _is_strictly_future_close(close, as_of_norm):
            admissible.append(market)
        else:
            rejected_ids.append(market_id(market))

    # Seeded deterministic pick. Sort by a stable key FIRST so the shuffle order
    # does not depend on the incoming list order (only on the seed + contents).
    ordered = sorted(admissible, key=lambda m: (market_close_time(m) or "", market_id(m)))
    rng = random.Random(rng_seed)
    rng.shuffle(ordered)
    take = max(0, int(n))
    sampled = ordered[:take]

    return {
        "sampled": sampled,
        "admissible": len(admissible),
        "rejected": len(rejected_ids),
        "rejected_ids": rejected_ids,
        "as_of": as_of_norm,
        "n_requested": take,
    }


# ── 2. the run record ──────────────────────────────────────────────────────────


@dataclass
class MarketNightlyRun:
    """The outcome of one :func:`record_pending` sweep.

    ``recorded`` is one dict per stored market (its market id, the new question
    id, the agent snapshot's forecast id, the agent P(yes), the de-vigged market
    price, and the close time). ``rejected`` counts (and lists) any sampled
    market that FAILED the strictly-future-close invariant at store time — these
    are never written. ``as_of`` is the forecast instant the invariant was tested
    against."""

    as_of: str
    arm: str = "plain"
    recorded: list[dict[str, Any]] = field(default_factory=list)
    rejected_ids: list[str] = field(default_factory=list)
    skipped_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def n_recorded(self) -> int:
        return len(self.recorded)

    @property
    def n_rejected(self) -> int:
        return len(self.rejected_ids)

    @property
    def question_ids(self) -> list[str]:
        return [row["question_id"] for row in self.recorded]

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "arm": self.arm,
            "recorded": self.recorded,
            "n_recorded": self.n_recorded,
            "rejected_ids": self.rejected_ids,
            "n_rejected": self.n_rejected,
            "skipped_ids": self.skipped_ids,
            "notes": self.notes,
        }


def _binary_outcome_space(market: Mapping[str, Any]) -> OutcomeSpace:
    """A YES/NO outcome space for a market-nightly question (markets are binary)."""

    return OutcomeSpace(type="binary", choices=["yes", "no"])


@allow_ledger_writes_decorator("market_nightly.record_pending")
def record_pending(
    ledger: Any,
    sampled: Sequence[Mapping[str, Any]],
    as_of: str,
    agent_forecaster: AgentForecaster,
    market_devig: MarketDevig | None = None,
    *,
    domain: str | None = "market_nightly",
    tags: Sequence[str] | None = None,
    max_workers: int = 1,
    arm: str = DEFAULT_RESEARCH_ARM,
) -> MarketNightlyRun:
    """Store a pending market-nightly entry for each sampled market.

    ``arm`` (``plain`` | ``voi``, default ``plain``) tags every stored question,
    snapshot, and recorded row with the A/B research arm that produced the forecast,
    so the scoring/report path can split agent-vs-market metrics BY ARM and compute a
    PAIRED voi-vs-plain Brier delta on markets that carry BOTH arms. Idempotence is
    arm-aware: the SAME market may hold one ``plain`` entry AND one ``voi`` entry (the
    two arms of a paired A/B), but never two entries for the SAME arm. A legacy row
    written before arm tagging reads as ``plain`` (back-compat), so re-running the
    plain arm still dedups against it exactly as before.

    For each market this:
      1. RE-ASSERTS the future-close invariant (close STRICTLY > as_of);
         a violator is appended to ``rejected_ids`` and NEVER stored.
      2. Creates a binary forecast question for the market (close/resolution
         carried through so the question itself records when it may be scored).
      3. Commits an agent snapshot tagged ``forecast_origin="market_nightly"`` at
         ``as_of`` carrying the injected agent forecast — NOT calibration
         eligible (the benchmark is segregated from the live calibration book).
      4. Attaches the de-vigged MARKET price as a ``market_price`` baseline
         comparison for the head-to-head agent-vs-market scoring later.

    ``agent_forecaster`` and ``market_devig`` are INJECTED seams; this function
    never reaches a live market API. Returns a :class:`MarketNightlyRun`.

    ``max_workers`` (default 1) bounds parallelism of the SLOW part — the
    ``agent_forecaster(market)`` search-agent calls (each ~75s). With
    ``max_workers == 1`` the recorded/skipped SET is preserved versus the
    historical sequential sweep; an intra-batch duplicate id whose first
    occurrence FAILS (None forecast / devig raise) is now deduped earlier (a
    more-correct skip-note reclassification on that narrow edge, not a
    byte-identical note). With ``max_workers > 1`` the admissible markets are
    forecast CONCURRENTLY in a :class:`ThreadPoolExecutor` (mirroring
    :func:`forecasting.quorum.run_quorum`'s panelist dispatch), but the ORDER of
    recording is preserved and EVERY ledger write stays serialized on the calling
    thread — the create_question / create_snapshot / add_baseline_comparison
    calls never race, and the recorded order is deterministic (input order of the
    admissible markets) regardless of which forecast finished first.

    THREAD-SAFETY CONTRACT: when ``max_workers > 1`` ONLY the injected
    ``agent_forecaster`` runs concurrently (the SLOW pass-2 fan-out), so the
    CALLER must supply a thread-safe ``agent_forecaster``. ``market_devig`` is
    called in the SERIAL pass 3 on the calling thread (never from a worker), so
    it carries no concurrency requirement. The production forecaster from
    :func:`forecasting.market_nightly_forecaster.build_informed_market_forecaster`
    reuses ONE agent (shared conversation state — NOT thread-safe), so the CLI
    builds it with ``fresh_agent_per_call=True`` for parallel runs (a fresh agent
    per forecast). We do NOT lock the agent calls: the agent call is the whole
    cost, so serializing it would defeat the parallelism — isolation, not a lock,
    is the correct fix.
    """

    devig = market_devig or default_market_devig
    arm = _normalize_arm(arm)
    as_of_norm = parse_timestamp(as_of, field_name="as_of")
    if not as_of_norm:
        raise ValueError("record_pending requires a concrete as_of timestamp")

    run = MarketNightlyRun(as_of=as_of_norm, arm=arm)
    tag_list = list(tags or []) + [MARKET_NIGHTLY_ORIGIN]
    # Idempotence (ARM-AWARE): a still-open market re-sampled on a later night must
    # NOT be recorded twice FOR THE SAME ARM (a resolved market won't be re-sampled
    # — it fails the strictly-future-close filter). The dedup key is
    # ``(market_id, arm)`` so the same market may carry one plain AND one voi entry
    # (the paired A/B) while never duplicating within an arm. A legacy entry with no
    # arm reads as ``plain``. Seed from existing questions, then grow as we record
    # this batch so an intra-batch duplicate id (same arm) is also skipped.
    existing_pairs: set[tuple[str, str]] = set()
    try:
        for q in _market_nightly_questions(ledger):
            meta = getattr(q, "metadata", {}) or {}
            existing = meta.get("market_id")
            if existing:
                existing_pairs.add((str(existing), _normalize_arm(meta.get("arm"))))
    except Exception:  # noqa: BLE001 — a ledger without prior entries -> no dedup needed
        existing_pairs = set()

    # ── pass 1 (serial, cheap): admissibility / dedup / foreknowledge filter ────
    # Resolve which markets are ELIGIBLE to forecast WITHOUT appending to the run
    # lists yet — every skip/reject append is deferred to pass 3 so it lands in
    # original ``sampled`` order (byte-identical to the historical single loop).
    # ``admissible_index`` maps an admissible market's sampled-index -> its slot in
    # the agent_probs array. Intra-batch duplicate ids are skipped against
    # ``seen_in_batch`` (the parallel pass must not forecast the same id twice).
    admissible: list[Mapping[str, Any]] = []
    admissible_slot: dict[int, int] = {}
    dup_skip: set[int] = set()
    seen_in_batch: set[tuple[str, str]] = set()
    for sidx, market in enumerate(sampled):
        mid = market_id(market)
        if mid and ((mid, arm) in existing_pairs or (mid, arm) in seen_in_batch):
            dup_skip.add(sidx)
            continue
        close = market_close_time(market)
        # (b) The invariant is the whole point — re-assert at store time. A market
        # whose close is not strictly after the forecast instant is rejected and
        # counted, never stored. This gate runs BEFORE any forecaster call so a
        # non-future-close market never reaches the (parallel) agent.
        if not _is_strictly_future_close(close, as_of_norm):
            continue  # rejection note emitted in pass 3 (original order)
        admissible_slot[sidx] = len(admissible)
        admissible.append(market)
        if mid:
            seen_in_batch.add((mid, arm))

    # ── pass 2 (the SLOW part — optionally parallel): agent_forecaster(market) ──
    # Each entry becomes the agent's P(yes) for one admissible market. With
    # max_workers == 1 this is a plain sequential loop (byte-identical to before);
    # with max_workers > 1 the agent calls fan out across a bounded thread pool
    # while preserving input order in ``agent_probs`` (results are placed by index).
    workers = max(1, min(int(max_workers), len(admissible))) if admissible else 1
    agent_probs: list[Any] = [None] * len(admissible)
    if workers == 1:
        for slot, market in enumerate(admissible):
            agent_probs[slot] = agent_forecaster(market)
    else:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(agent_forecaster, market): slot
                for slot, market in enumerate(admissible)
            }
            for future in futures:
                slot = futures[future]
                # A single forecaster raising must not abort the sweep; treat it as
                # a None forecast (skipped below), matching the "any failure -> None"
                # contract the production forecaster already honours internally.
                try:
                    agent_probs[slot] = future.result()
                except Exception:  # noqa: BLE001
                    agent_probs[slot] = None

    # ── pass 3 (serial — ALL ledger writes here): record in deterministic order ─
    # Walk the ORIGINAL sampled order so every recorded/skipped/rejected append +
    # note matches the historical single-loop sequence exactly. Nothing below
    # touches a worker thread, so the ledger writes can never race and the
    # recorded order is deterministic regardless of which forecast finished first.
    for sidx, market in enumerate(sampled):
        mid = market_id(market)
        if sidx in dup_skip:
            run.skipped_ids.append(mid)
            run.notes.append(
                f"skipped {mid!r}: already has a {arm!r}-arm market-nightly entry (idempotent re-sample)"
            )
            continue
        if sidx not in admissible_slot:
            close = market_close_time(market)
            run.rejected_ids.append(mid)
            run.notes.append(
                f"rejected {mid!r}: close {close!r} is not strictly after as_of {as_of_norm!r} "
                "(foreknowledge not ruled out by construction)"
            )
            continue
        close = market_close_time(market)
        agent_p = _coerce_prob(agent_probs[admissible_slot[sidx]])
        if agent_p is None:
            run.skipped_ids.append(mid)
            run.notes.append(f"skipped {mid!r}: agent forecaster returned a non-probability")
            continue
        try:
            market_p = _clamp01(float(devig(market)))
        except Exception as exc:  # a single bad market must not abort the sweep
            run.skipped_ids.append(mid)
            run.notes.append(f"skipped {mid!r}: market de-vig failed ({exc})")
            continue

        # PRICE PROVENANCE (the contemporaneous-vs-frozen distinguisher). The agent
        # snapshot is stamped with the FORECAST instant (as_of_norm); the market
        # baseline is instead stamped with the price's TRUE vintage (``price_asof``) so a
        # frozen ForecastBench freeze price (sampled weeks before the run) is no longer
        # disguised as a forecast-time quote. We record the explicit lag + contemporaneous
        # flag so the live-edge roll-up can quarantine a stale baseline from the "agent
        # beats the market" claim without re-deriving it.
        explicit_price_asof = _first(market, "price_asof", "priceAsOf", "price_as_of")
        price_asof = market_price_asof(market, forecast_as_of=as_of_norm)
        baseline_lag = _baseline_lag_seconds(price_asof, as_of_norm)
        explicit_frozen = market.get("baseline_is_frozen")
        if isinstance(explicit_frozen, bool):
            is_contemporaneous = not explicit_frozen
        elif explicit_price_asof is not None and str(explicit_price_asof).strip():
            # A market that carries its TRUE price vintage: classify by the lag.
            is_contemporaneous = (
                baseline_lag is None or baseline_lag <= CONTEMPORANEOUS_THRESHOLD_SECONDS
            )
        else:
            # No explicit provenance — DON'T trust the fallback-to-forecast-instant lag
            # (it reads as zero and would mis-classify a frozen ForecastBench prior as
            # live). Use the id/source proxy instead (forecastbench => frozen).
            is_contemporaneous = baseline_is_contemporaneous(
                forecast_as_of=as_of_norm, market_id_str=mid,
                source=str(_first(market, "source", "platform") or ""),
            )

        title = str(_first(market, "question", "title", "name") or f"Market {mid}").strip() or f"Market {mid}"
        criteria = str(
            _first(market, "resolution_criteria", "description")
            or "Resolves YES/NO according to the linked market's settlement rules."
        ).strip()

        question = ledger.create_question(
            title=title,
            resolution_criteria=criteria,
            outcome_space=_binary_outcome_space(market),
            description=str(_first(market, "description") or ""),
            close_time=close,
            resolution_time=market_close_time(market),
            domain=domain,
            tags=tag_list,
            metadata={
                "market_nightly": True,
                "market_id": mid,
                "market_source": str(_first(market, "source", "platform") or ""),
                "as_of": as_of_norm,
                "arm": arm,
            },
        )

        snapshot = ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=agent_p,
            rationale=(
                "AIA P2.1 MarketNightly future-close live benchmark: agent forecast "
                f"committed at {as_of_norm} against an OPEN market closing at {close} "
                "(underlying event timing and evidence availability require separate audit)."
            ),
            as_of=as_of_norm,
            method="market_nightly",
            forecast_origin=MARKET_NIGHTLY_ORIGIN,
            calibration_eligible=False,
            calibration_weight=0.0,
            metadata={
                PENDING_MARKER: True,
                "market_id": mid,
                "market_close_time": close,
                "arm": arm,
                "agent_forecast": agent_p,
                "market_devig_probability": market_p,
                # Carry the baseline provenance onto the snapshot too, so score_matured
                # can propagate the contemporaneous flag without re-reading the baseline.
                "baseline_price_asof": price_asof,
                "baseline_contemporaneous": is_contemporaneous,
                "baseline_is_frozen": not is_contemporaneous,
            },
        )

        baseline = ledger.add_baseline_comparison(
            question_id=question.id,
            source=str(_first(market, "source", "platform") or f"market:{mid}"),
            baseline_type=MARKET_BASELINE_TYPE,
            probability_or_distribution=market_p,
            as_of=price_asof,
            metadata={
                "market_nightly": True,
                "market_id": mid,
                "raw_yes_price": market_yes_price(market),
                "agent_forecast_id": snapshot.forecast_id,
                "price_asof": price_asof,
                "forecast_as_of": as_of_norm,
                "baseline_lag_seconds": baseline_lag,
                "contemporaneous": is_contemporaneous,
                "baseline_is_frozen": not is_contemporaneous,
            },
        )

        run.recorded.append(
            {
                "market_id": mid,
                "question_id": question.id,
                "forecast_id": snapshot.forecast_id,
                "baseline_id": baseline["id"],
                "arm": arm,
                "agent_forecast": agent_p,
                "market_devig_probability": market_p,
                "close_time": close,
                "price_asof": price_asof,
                "baseline_lag_seconds": baseline_lag,
                "contemporaneous": is_contemporaneous,
            }
        )

    return run


# ── pending discovery (shared by score_matured + the report) ──────────────────


def _pending_market_nightly_snapshots(ledger: Any) -> list[Any]:
    """Every market-nightly snapshot the ledger holds (origin-tagged).

    Reads the segregated ``forecast_origin="market_nightly"`` set via list_scores
    is not possible (unscored entries have no score row), so we walk the snapshots
    for market-nightly questions. We rely on the question metadata marker written
    by :func:`record_pending` to find the questions cheaply."""

    questions = _market_nightly_questions(ledger)
    out: list[Any] = []
    for question in questions:
        for snap in ledger.list_snapshots(question.id):
            if snap.forecast_origin == MARKET_NIGHTLY_ORIGIN:
                out.append(snap)
    return out


def _market_nightly_questions(ledger: Any) -> list[Any]:
    """Questions tagged as market-nightly, via list_questions + the metadata marker."""

    out: list[Any] = []
    for question in ledger.list_questions():
        meta = getattr(question, "metadata", {}) or {}
        if meta.get("market_nightly") or MARKET_NIGHTLY_ORIGIN in (getattr(question, "tags", []) or []):
            out.append(question)
    return out


def _snapshot_arm(snapshot: Any) -> str:
    """The A/B research arm a market-nightly snapshot was recorded under (``plain`` |
    ``voi``). A snapshot with no ``arm`` metadata (legacy, pre-tagging) reads as
    ``plain`` so the historical record stays comparable to the plain arm."""

    meta = getattr(snapshot, "metadata", None) or {}
    return _normalize_arm(meta.get("arm"))


def _market_baseline_row(ledger: Any, question_id: str) -> dict[str, Any] | None:
    """The recorded market-price baseline ROW (with its provenance metadata), or None."""

    try:
        baselines = ledger.list_baseline_comparisons(question_id)
    except Exception:  # noqa: BLE001
        return None
    for baseline in baselines:
        if str(baseline.get("baseline_type") or "").lower() == MARKET_BASELINE_TYPE:
            return baseline
    return None


def _snapshot_baseline_is_contemporaneous(ledger: Any, snapshot: Any) -> bool:
    """Classify a market-nightly snapshot's MARKET baseline as contemporaneous vs frozen.

    Reads the authoritative baseline-row provenance metadata when present, else the
    snapshot's carried provenance, else the legacy id/source fallback — so the
    distinguisher works for both honestly-recorded and pre-fix rows."""

    snap_meta = getattr(snapshot, "metadata", None) or {}
    market_id_str = snap_meta.get("market_id")
    forecast_as_of = getattr(snapshot, "as_of", None) or snap_meta.get("as_of")

    row = _market_baseline_row(ledger, snapshot.question_id)
    if row is not None:
        return baseline_is_contemporaneous(
            metadata=row.get("metadata") or {},
            forecast_as_of=forecast_as_of,
            market_id_str=market_id_str,
            source=str(row.get("source") or ""),
        )
    # No baseline row resolvable — fall back to the snapshot's carried provenance.
    return baseline_is_contemporaneous(
        metadata=snap_meta,
        forecast_as_of=forecast_as_of,
        market_id_str=market_id_str,
    )


# ── 3. score the matured entries ───────────────────────────────────────────────


@allow_ledger_writes_decorator("market_nightly.score_matured")
def score_matured(ledger: Any, *, now: str | None = None) -> dict[str, Any]:
    """Score every pending market-nightly entry whose market has RESOLVED.

    A pending entry matures when BOTH hold: its question carries a CONFIRMED,
    criteria-satisfied, scoreable resolution (the outcome now exists), AND its
    market close time is <= ``now`` (the close has actually passed). For each
    matured entry this reuses the ledger's existing scoring machinery:
      * ``score_snapshot`` scores the AGENT forecast against the binary outcome,
      * ``score_baseline_comparisons`` scores the de-vigged MARKET baseline.
    Brier is NOT re-implemented here — both calls go through the same proper-score
    path the rest of the desk uses. Idempotent: an already-scored entry is a
    no-op. READ-ONLY w.r.t. the live book — nothing here touches a "live" record.

    Returns ``{"scored": [...], "still_pending": [...], "n_scored": int,
    "n_still_pending": int, "now": str, "notes": [...]}``.
    """

    now_norm = parse_timestamp(now, field_name="now") if now else utc_now_iso()
    now_dt = timestamp_to_datetime(now_norm)

    scored: list[dict[str, Any]] = []
    still_pending: list[dict[str, Any]] = []
    notes: list[str] = []

    for snapshot in _pending_market_nightly_snapshots(ledger):
        qid = snapshot.question_id
        meta = snapshot.metadata or {}
        mid = meta.get("market_id")
        close = meta.get("market_close_time")

        # The foreknowledge proof is the SAMPLE-TIME invariant (record_pending only
        # admits markets whose close is strictly after as_of, so the forecast was
        # locked before any outcome existed). This close-gate is a SECONDARY maturity
        # guard — don't surface a score before the market's stated close has passed.
        close_dt = timestamp_to_datetime(close) if close else None
        if close_dt is not None and now_dt is not None and close_dt > now_dt:
            still_pending.append({"question_id": qid, "market_id": mid, "reason": "market not yet closed"})
            continue

        resolution = ledger.get_latest_resolution(qid, confirmed_only=True)
        if resolution is None:
            still_pending.append({"question_id": qid, "market_id": mid, "reason": "no confirmed resolution yet"})
            continue

        # Did this entry already carry a score BEFORE this sweep? (so the cron only
        # announces what it NEWLY scored, not every matured entry forever.)
        try:
            prior = ledger._existing_score(snapshot.forecast_id, getattr(resolution, "id", None))
        except Exception:  # noqa: BLE001
            prior = None
        already_scored = prior is not None and getattr(prior, "brier_score", None) is not None

        # Agent forecast — reuse the ledger's scoring; idempotent.
        try:
            agent_score = ledger.score_snapshot(snapshot.forecast_id)
        except Exception as exc:
            notes.append(f"agent scoring failed for {qid}: {exc}")
            still_pending.append({"question_id": qid, "market_id": mid, "reason": f"agent scoring error: {exc}"})
            continue

        # Market baseline — reuse the existing baseline-scoring machinery.
        market_brier: float | None = None
        try:
            baseline_scores = ledger.score_baseline_comparisons(qid)
            for row in baseline_scores:
                if str(row.get("baseline_type") or "").lower() != MARKET_BASELINE_TYPE:
                    continue
                score = row.get("score")
                if score is not None and getattr(score, "brier_score", None) is not None:
                    market_brier = float(score.brier_score)
                    break
        except Exception as exc:
            notes.append(f"market-baseline scoring failed for {qid}: {exc}")

        # Propagate the contemporaneous flag onto each scored entry: the resolver
        # scores BOTH arms (its job is maturity + Brier), but the EDGE only counts
        # contemporaneous pairs, so the cron/report must be able to read this flag.
        contemporaneous = _snapshot_baseline_is_contemporaneous(ledger, snapshot)
        scored.append(
            {
                "question_id": qid,
                "market_id": mid,
                "forecast_id": snapshot.forecast_id,
                "arm": _snapshot_arm(snapshot),
                "agent_brier": agent_score.brier_score,
                "market_brier": market_brier,
                "outcome": resolution.outcome,
                "newly_scored": not already_scored,
                "contemporaneous": contemporaneous,
                "baseline_is_frozen": not contemporaneous,
            }
        )

    n_newly_scored = sum(1 for s in scored if s["newly_scored"])
    n_contemporaneous = sum(1 for s in scored if s["contemporaneous"])
    n_by_arm = {a: sum(1 for s in scored if s["arm"] == a) for a in RESEARCH_ARMS}
    return {
        "scored": scored,
        "still_pending": still_pending,
        "n_scored": len(scored),
        "n_newly_scored": n_newly_scored,
        "n_contemporaneous": n_contemporaneous,
        "n_frozen_excluded": len(scored) - n_contemporaneous,
        "n_by_arm": n_by_arm,
        "n_still_pending": len(still_pending),
        "now": now_norm,
        "notes": notes,
    }


# ── 4. the read-only report ────────────────────────────────────────────────────


def _mean(values: list[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def _paired_block(ledger: Any, pairs: list[tuple[Any, Any]]) -> dict[str, Any]:
    """The P0.2 seeded paired-bootstrap summary over agent/market score pairs (or
    the empty stub when there are no pairs)."""

    return ledger._paired_brier_summary(pairs) if pairs else _empty_paired()


def market_nightly_report(ledger: Any) -> dict[str, Any]:
    """READ-ONLY roll-up of the market-nightly benchmark.

    The HEADLINE agent-vs-market edge counts ONLY markets whose market baseline is a
    CONTEMPORANEOUS price (sampled at — within :data:`CONTEMPORANEOUS_THRESHOLD_SECONDS`
    of — the forecast instant). Frozen-baseline markets (e.g. a ForecastBench freeze
    price stamped weeks before the run) are STILL scored and reported, but in a
    SEPARATE ``frozen_diagnostic`` bucket ("agent-vs-frozen-prior") that NEVER feeds the
    headline ``paired_agent_edge_*`` / win counts — a stale baseline cannot contaminate
    the "agent beats the market" claim. The full set (contemporaneous + frozen) is also
    surfaced under ``full_set`` so nothing is silently dropped; ``n_frozen_excluded``
    flags how many scored pairs were quarantined from the headline.

    Reuses :meth:`ForecastLedger._paired_brier_summary` over the matched agent/market
    score pairs. Never scores or mutates anything.
    """

    n_pending = 0
    contemporaneous_pairs: list[tuple[Any, Any]] = []
    frozen_pairs: list[tuple[Any, Any]] = []
    all_pairs: list[tuple[Any, Any]] = []
    agent_briers: list[float] = []
    market_briers: list[float] = []
    c_agent_briers: list[float] = []
    c_market_briers: list[float] = []
    f_agent_briers: list[float] = []
    f_market_briers: list[float] = []

    # ── A/B arm splits ─────────────────────────────────────────────────────────
    # ``per_arm``: per-arm CONTEMPORANEOUS agent-vs-market pairs (mirrors the headline
    # discipline, split by arm). ``by_market_agent``: mid -> {arm: agent_score}, used to
    # build the PAIRED voi-vs-plain agent-vs-agent comparison on markets forecast by
    # BOTH arms. The voi-vs-plain comparison uses ONLY the two agent snapshots on the
    # same resolved outcome (the market baseline never enters it), so it does NOT gate
    # on the market baseline being scored or contemporaneous — both arms forecast the
    # same open market at the same instant, so there is no staleness asymmetry.
    per_arm: dict[str, dict[str, list[Any]]] = {
        a: {"pairs": [], "agent": [], "market": []} for a in RESEARCH_ARMS
    }
    by_market_agent: dict[str, dict[str, Any]] = {}

    from forecasting.evaluation import market_evaluation_records

    with ledger._connect() as conn:
        evaluations = {r["forecast_id"]: r for r in market_evaluation_records(conn)}

    for snapshot in _pending_market_nightly_snapshots(ledger):
        qid = snapshot.question_id
        arm = _snapshot_arm(snapshot)
        mid = str((getattr(snapshot, "metadata", None) or {}).get("market_id") or qid)
        evaluation = evaluations.get(snapshot.forecast_id)
        agent_score = (
            ledger.get_score(evaluation["score_id"])
            if evaluation and evaluation["agent_valid"] else None
        )
        if agent_score is None or agent_score.brier_score is None:
            n_pending += 1
            continue

        # Record the scored AGENT forecast for the voi-vs-plain pairing BEFORE the
        # market-baseline gate — that comparison needs only the two agent scores.
        by_market_agent.setdefault(mid, {})[arm] = agent_score

        market_score = (
            ledger.get_score(evaluation["market_score_id"])
            if evaluation and evaluation["exclusion_reason"] is None else None
        )
        if market_score is None or market_score.brier_score is None:
            # Agent scored but the market baseline is not (yet) scored — count it as
            # pending for the paired comparison (an unpaired agent score cannot enter
            # the paired bootstrap honestly).
            n_pending += 1
            continue

        a_brier = float(agent_score.brier_score)
        m_brier = float(market_score.brier_score)
        agent_briers.append(a_brier)
        market_briers.append(m_brier)
        # _paired_brier_summary computes deltas as baseline_brier - agent_brier
        # (POSITIVE == agent better), exactly the agent-vs-market edge we want.
        pair = (agent_score, market_score)
        all_pairs.append(pair)
        if evaluation["contemporaneous"]:
            contemporaneous_pairs.append(pair)
            c_agent_briers.append(a_brier)
            c_market_briers.append(m_brier)
            # Per-arm headline mirrors the contemporaneous-only discipline.
            bucket = per_arm[arm]
            bucket["pairs"].append(pair)
            bucket["agent"].append(a_brier)
            bucket["market"].append(m_brier)
        else:
            frozen_pairs.append(pair)
            f_agent_briers.append(a_brier)
            f_market_briers.append(m_brier)

    # HEADLINE: the agent-vs-market edge is the CONTEMPORANEOUS-only paired summary.
    headline = _paired_block(ledger, contemporaneous_pairs)
    full = _paired_block(ledger, all_pairs)
    frozen = _paired_block(ledger, frozen_pairs)

    # ── PAIRED voi-vs-plain: same market forecast by BOTH arms, agent-vs-agent ──
    # Pair (voi_agent, plain_agent) so _paired_brier_summary yields deltas of
    # plain_brier - voi_brier (POSITIVE == VOI better, matching the "positive = the
    # left arm improves" convention used for the agent-vs-market edge). This is the
    # scoreboard that makes the Arc-2 research lift ATTRIBUTABLE.
    voi_plain_pairs: list[tuple[Any, Any]] = [
        (arms["voi"], arms["plain"])
        for arms in by_market_agent.values()
        if "voi" in arms and "plain" in arms
    ]
    voi_vs_plain = _paired_block(ledger, voi_plain_pairs)

    return {
        "n_pending": n_pending,
        # n_scored stays the FULL scored count (both arms recorded); the headline edge
        # below is the contemporaneous-only subset.
        "n_scored": len(all_pairs),
        "n_contemporaneous": len(contemporaneous_pairs),
        "n_frozen_excluded": len(frozen_pairs),
        # HEADLINE means — CONTEMPORANEOUS baselines ONLY. These are the clean
        # agent-vs-market numbers the CLI leads with; frozen-baseline markets are
        # excluded so a stale price cannot contaminate the "agent beats market" claim.
        "contemporaneous_mean_agent_brier": _mean(c_agent_briers),
        "contemporaneous_mean_market_brier": _mean(c_market_briers),
        # Means over the FULL scored set (back-compat DIAGNOSTIC — INCLUDES the
        # n_frozen_excluded frozen-baseline markets, so NOT the headline);
        # contemporaneous/frozen means live in their respective buckets.
        "mean_agent_brier": _mean(agent_briers),
        "mean_market_brier": _mean(market_briers),
        # HEADLINE agent-vs-market edge — CONTEMPORANEOUS baselines ONLY.
        "paired_agent_edge_mean_brier": headline.get("paired_agent_edge_mean_brier"),
        "paired_agent_edge_ci95_low": headline.get("paired_agent_edge_ci95_low"),
        "paired_agent_edge_ci95_high": headline.get("paired_agent_edge_ci95_high"),
        "paired_p_value": headline.get("paired_p_value"),
        "paired_agent_wins": headline.get("paired_agent_wins", 0),
        "paired_baseline_wins": headline.get("paired_baseline_wins", 0),
        "paired_ties": headline.get("paired_ties", 0),
        # FULL-set diagnostic (contemporaneous + frozen) — surfaced, NOT the claim.
        "full_set": {
            "n_scored": len(all_pairs),
            "mean_agent_brier": _mean(agent_briers),
            "mean_market_brier": _mean(market_briers),
            **full,
        },
        # FROZEN-baseline diagnostic bucket — "agent vs frozen prior", never the edge.
        "frozen_diagnostic": {
            "n_scored": len(frozen_pairs),
            "mean_agent_brier": _mean(f_agent_briers),
            "mean_market_brier": _mean(f_market_briers),
            **frozen,
        },
        # A/B ARM SPLIT. Per-arm agent-vs-market (CONTEMPORANEOUS baselines only, same
        # discipline as the headline) so ``plain`` and ``voi`` each carry their own
        # n / mean Briers / paired edge vs the market.
        "by_arm": {
            a: {
                "n_scored": len(per_arm[a]["pairs"]),
                "mean_agent_brier": _mean(per_arm[a]["agent"]),
                "mean_market_brier": _mean(per_arm[a]["market"]),
                **_paired_block(ledger, per_arm[a]["pairs"]),
            }
            for a in RESEARCH_ARMS
        },
        # THE A/B SCOREBOARD: paired voi-vs-plain Brier delta over markets forecast by
        # BOTH arms. ``delta_mean_brier`` = plain_brier - voi_brier (POSITIVE = VOI
        # better); ``voi_wins``/``plain_wins``/``ties`` and the seeded-bootstrap CI + p
        # come straight from the reused P0.2 paired machinery — never reimplemented.
        "paired_voi_vs_plain": {
            "n_paired": len(voi_plain_pairs),
            "delta_mean_brier": voi_vs_plain.get("paired_agent_edge_mean_brier"),
            "ci95_low": voi_vs_plain.get("paired_agent_edge_ci95_low"),
            "ci95_high": voi_vs_plain.get("paired_agent_edge_ci95_high"),
            "p_value": voi_vs_plain.get("paired_p_value"),
            "voi_wins": voi_vs_plain.get("paired_agent_wins", 0),
            "plain_wins": voi_vs_plain.get("paired_baseline_wins", 0),
            "ties": voi_vs_plain.get("paired_ties", 0),
        },
    }


def _scored_market_baseline(ledger: Any, question_id: str) -> Any | None:
    """The already-recorded market-price baseline SCORE for a question, or None.

    READ-ONLY: walks baseline_comparisons + their score_record_id; never scores."""

    try:
        baselines = ledger.list_baseline_comparisons(question_id)
    except Exception:
        return None
    for baseline in baselines:
        if str(baseline.get("baseline_type") or "").lower() != MARKET_BASELINE_TYPE:
            continue
        score_id = baseline.get("score_record_id")
        if not score_id:
            continue
        try:
            return ledger.get_score(score_id)
        except Exception:
            continue
    return None


def _empty_paired() -> dict[str, Any]:
    return {
        "paired_agent_edge_mean_brier": None,
        "paired_agent_edge_ci95_low": None,
        "paired_agent_edge_ci95_high": None,
        "paired_p_value": None,
        "paired_agent_wins": 0,
        "paired_baseline_wins": 0,
        "paired_ties": 0,
    }
