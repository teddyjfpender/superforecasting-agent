"""AIA P2.1 — the MarketNightly foreknowledge-proof LIVE benchmark.

The paper's core epistemic point: a backtest can never fully rule out
foreknowledge (the model may have ingested the answer during pre-training, or a
leakage check may miss a subtle channel). The only *defensible* claim of live
superiority comes from a continuously-running benchmark on questions that
resolve in the FUTURE: sample currently-OPEN markets, forecast NOW, and score
when they close. Foreknowledge is impossible BY CONSTRUCTION because the
outcome does not exist yet at forecast time.

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
  (b) The foreknowledge-proof invariant is enforced at BOTH the pure sampler and
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
    """The foreknowledge-proof admissibility test: close STRICTLY > as_of.

    A missing close, or a close at/earlier than the forecast instant, is
    INADMISSIBLE — the outcome could already exist, so foreknowledge is not ruled
    out by construction."""

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


# ── 1. the pure, seeded foreknowledge-proof sampler ───────────────────────────


def sample_open_markets(
    markets: Sequence[Mapping[str, Any]],
    as_of: str,
    n: int,
    *,
    rng_seed: int = 0,
) -> dict[str, Any]:
    """Keep ONLY strictly-future-close markets, then take up to ``n`` (seeded).

    PURE: no I/O, no ledger, no clock — ``as_of`` is supplied by the caller. The
    foreknowledge-proof filter drops every market whose close/resolution time is
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
) -> MarketNightlyRun:
    """Store a pending market-nightly entry for each sampled market.

    For each market this:
      1. RE-ASSERTS the foreknowledge-proof invariant (close STRICTLY > as_of);
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
    as_of_norm = parse_timestamp(as_of, field_name="as_of")
    if not as_of_norm:
        raise ValueError("record_pending requires a concrete as_of timestamp")

    run = MarketNightlyRun(as_of=as_of_norm)
    tag_list = list(tags or []) + [MARKET_NIGHTLY_ORIGIN]
    # Idempotence: a still-open market re-sampled on a later night must NOT be
    # recorded twice. Skip any market that already has a market-nightly entry (a
    # resolved market won't be re-sampled — it fails the strictly-future-close
    # filter). Seed from existing questions, then grow as we record this batch so
    # an intra-batch duplicate id is also skipped.
    existing_mids: set[str] = set()
    try:
        for q in _market_nightly_questions(ledger):
            existing = (getattr(q, "metadata", {}) or {}).get("market_id")
            if existing:
                existing_mids.add(str(existing))
    except Exception:  # noqa: BLE001 — a ledger without prior entries -> no dedup needed
        existing_mids = set()

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
    seen_in_batch: set[str] = set()
    for sidx, market in enumerate(sampled):
        mid = market_id(market)
        if mid and (mid in existing_mids or mid in seen_in_batch):
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
            seen_in_batch.add(mid)

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
            run.notes.append(f"skipped {mid!r}: already has a market-nightly entry (idempotent re-sample)")
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
            },
        )

        snapshot = ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=agent_p,
            rationale=(
                "AIA P2.1 MarketNightly foreknowledge-proof live benchmark: agent forecast "
                f"committed at {as_of_norm} against an OPEN market closing at {close} "
                "(outcome does not exist yet)."
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
                "agent_forecast": agent_p,
                "market_devig_probability": market_p,
            },
        )

        baseline = ledger.add_baseline_comparison(
            question_id=question.id,
            source=str(_first(market, "source", "platform") or f"market:{mid}"),
            baseline_type=MARKET_BASELINE_TYPE,
            probability_or_distribution=market_p,
            as_of=as_of_norm,
            metadata={
                "market_nightly": True,
                "market_id": mid,
                "raw_yes_price": market_yes_price(market),
            },
        )

        run.recorded.append(
            {
                "market_id": mid,
                "question_id": question.id,
                "forecast_id": snapshot.forecast_id,
                "baseline_id": baseline["id"],
                "agent_forecast": agent_p,
                "market_devig_probability": market_p,
                "close_time": close,
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


# ── 3. score the matured entries ───────────────────────────────────────────────


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

        scored.append(
            {
                "question_id": qid,
                "market_id": mid,
                "forecast_id": snapshot.forecast_id,
                "agent_brier": agent_score.brier_score,
                "market_brier": market_brier,
                "outcome": resolution.outcome,
                "newly_scored": not already_scored,
            }
        )

    n_newly_scored = sum(1 for s in scored if s["newly_scored"])
    return {
        "scored": scored,
        "still_pending": still_pending,
        "n_scored": len(scored),
        "n_newly_scored": n_newly_scored,
        "n_still_pending": len(still_pending),
        "now": now_norm,
        "notes": notes,
    }


# ── 4. the read-only report ────────────────────────────────────────────────────


def market_nightly_report(ledger: Any) -> dict[str, Any]:
    """READ-ONLY roll-up of the market-nightly benchmark.

    Reports ``n_pending`` (recorded but not yet scored), ``n_scored``, the mean
    agent Brier vs the mean market Brier, and the paired agent-edge (agent vs
    market) with the P0.2 seeded paired-bootstrap p-value/CI — computed by
    reusing :meth:`ForecastLedger._paired_brier_summary` over the matched
    agent/market score pairs. Never scores or mutates anything.
    """

    n_pending = 0
    pairs: list[tuple[Any, Any]] = []
    agent_briers: list[float] = []
    market_briers: list[float] = []

    for snapshot in _pending_market_nightly_snapshots(ledger):
        qid = snapshot.question_id
        resolution = ledger.get_latest_resolution(qid, confirmed_only=True)
        agent_score = None
        if resolution is not None:
            agent_score = ledger._existing_score(snapshot.forecast_id, resolution.id)
        if agent_score is None or agent_score.brier_score is None:
            n_pending += 1
            continue

        market_score = _scored_market_baseline(ledger, qid)
        if market_score is None or market_score.brier_score is None:
            # Agent scored but the market baseline is not (yet) scored — count it as
            # pending for the paired comparison (an unpaired agent score cannot enter
            # the paired bootstrap honestly).
            n_pending += 1
            continue

        agent_briers.append(float(agent_score.brier_score))
        market_briers.append(float(market_score.brier_score))
        # _paired_brier_summary computes deltas as baseline_brier - agent_brier
        # (POSITIVE == agent better), exactly the agent-vs-market edge we want.
        pairs.append((agent_score, market_score))

    paired = ledger._paired_brier_summary(pairs) if pairs else _empty_paired()

    return {
        "n_pending": n_pending,
        "n_scored": len(pairs),
        "mean_agent_brier": (sum(agent_briers) / len(agent_briers)) if agent_briers else None,
        "mean_market_brier": (sum(market_briers) / len(market_briers)) if market_briers else None,
        "paired_agent_edge_mean_brier": paired.get("paired_agent_edge_mean_brier"),
        "paired_agent_edge_ci95_low": paired.get("paired_agent_edge_ci95_low"),
        "paired_agent_edge_ci95_high": paired.get("paired_agent_edge_ci95_high"),
        "paired_p_value": paired.get("paired_p_value"),
        "paired_agent_wins": paired.get("paired_agent_wins", 0),
        "paired_baseline_wins": paired.get("paired_baseline_wins", 0),
        "paired_ties": paired.get("paired_ties", 0),
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
