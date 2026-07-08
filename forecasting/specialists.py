"""Deterministic specialists as quorum panelists (BLF A5).

The BLF paper (ForecastBench SOTA) routes temperature time-series questions to a
KNN that **bypasses the LLM entirely**, because the LLM measurably underperformed
there. We hold the same philosophy (Market Models, living models) but no
deterministic model sat in the quorum. This module supplies three:

* **climatology KNN** — the historical same-season distribution of the series
  (the observations nearest the target's day-of-year, across years). The honest
  outside view for a seasonal level.
* **seasonal-naive** — the last-k values at the same phase (period lag). The
  status-quo persistence forecast for a periodic series.
* **living-model passthrough** — where a committed Market Model already carries a
  projection distribution for the question's series, use it.

A specialist is NOT a new trust regime. It registers as a panelist with a stable
``model:*`` id (:data:`SPECIALIST_IDS`); the existing S7.5 track-record weighting
(:mod:`forecasting.track_record`) then reads that id and earns it pool share
EMPIRICALLY — if the KNN beats the LLM panelists on the questions it takes, its
Brier edge lifts its weight; if it does not, shrinkage keeps it at 1.0. It adds
seats; the pool weighs votes.

Three disciplines are load-bearing:

* **Honesty over coverage.** A specialist runs ONLY where its data exists. If it
  cannot fetch its series (network down, no key, series too thin, excessively
  stale per :mod:`forecasting.observation_freshness`), it DECLINES — it raises
  :class:`SpecialistDeclined` so :func:`forecasting.quorum.run_quorum` records a
  labeled, excluded seat and the panel proceeds on the survivors. It never
  fabricates a forecast to fill a seat.
* **Conservative selection.** A specialist on the wrong question class is worse
  than none, so :func:`specialist_seats_for` admits ONLY continuous / count /
  distribution question classes (:data:`_CONTINUOUS_OUTCOME_TYPES`). Binary and
  categorical questions never get one. And a continuous question with no
  derivable numeric threshold gets none either — without a threshold a
  distribution cannot cast the binary vote the pool aggregates, so silence beats
  noise.
* **The distribution is the product.** The specialist's native output is a
  :class:`Distribution` (quantiles / PMF), which is CRPS-scorable. To VOTE in the
  binary-scored quorum it maps that distribution onto the question's resolution
  threshold — ``P(series {operator} threshold)`` — a genuine, defensible number.

The estimators are pure functions of a :class:`Series`; the data plane enters
only through an injectable :class:`SeriesProvider`, so the math is unit-testable
and the network is never touched in a test.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Protocol, Sequence

# ── stable panelist ids — the S7.5 track record keys on these ─────────────────
CLIMATOLOGY_KNN = "model:climatology_knn"
SEASONAL_NAIVE = "model:seasonal_naive"
LIVING_MODEL = "model:living_model"
SPECIALIST_IDS: tuple[str, ...] = (CLIMATOLOGY_KNN, SEASONAL_NAIVE, LIVING_MODEL)

# The question classes a specialist may take. A continuous / count level or a
# distribution question — never a binary or categorical one.
_CONTINUOUS_OUTCOME_TYPES = frozenset({"numeric", "distribution"})

# Estimator thresholds. A specialist below its minimum sample DECLINES rather than
# extrapolate from too little history — the honest failure mode.
DEFAULT_KNN_K = 15
MIN_CLIMATOLOGY_OBS = 8
DEFAULT_SEASONAL_K = 8
MIN_SEASONAL_SAMPLES = 3

# Count-cadence unit cues (distinguish an integer count series from a real level
# so quantiles round honestly).
_COUNT_UNIT_CUES = ("count", "number", "earthquake", "events", "occurrences")


class SpecialistDeclined(RuntimeError):
    """A specialist declined its seat (no reachable series / no threshold).

    Raised by the specialist runner so :func:`forecasting.quorum.run_quorum`
    records the seat as an excluded, LABELED panelist error — never a fabricated
    forecast. The panel proceeds on the survivors.
    """


# ── value objects ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Observation:
    """One dated reading of a series (the honest ``as_of`` is its OWN date)."""

    as_of: date
    value: float


@dataclass(frozen=True)
class Series:
    """A historical series, oldest -> newest, with a freshness-honest ``as_of``.

    ``kind`` is ``"continuous"`` (a real level) or ``"count"`` (a non-negative
    integer count — quantiles round to integers). ``as_of`` is the newest honest
    observation date; a provider that finds the series excessively stale returns
    ``None`` rather than a stale ``Series``.
    """

    key: str
    unit: str
    observations: tuple[Observation, ...]
    as_of: date
    kind: str = "continuous"

    @property
    def values(self) -> tuple[float, ...]:
        return tuple(o.value for o in self.observations)


@dataclass(frozen=True)
class Distribution:
    """An empirical predictive distribution over a numeric outcome.

    Built from a SAMPLE (the KNN neighbours / same-phase values). Quantiles are
    the type-7 linear-interpolated order statistics — monotone by construction —
    so ``quantiles`` is always coherent. ``crps`` is the standard sample estimator
    ``E|X - y| - 0.5 E|X - X'|`` (>= 0). Tail probabilities are empirical
    fractions of the sample.
    """

    samples: tuple[float, ...]
    kind: str = "continuous"

    @classmethod
    def from_sample(cls, values: Sequence[float], *, kind: str = "continuous") -> "Distribution":
        clean = tuple(float(v) for v in values if v is not None and math.isfinite(float(v)))
        if not clean:
            raise ValueError("a distribution needs at least one finite sample")
        return cls(samples=clean, kind=kind)

    @property
    def _sorted(self) -> list[float]:
        return sorted(self.samples)

    def _round(self, value: float) -> float:
        return float(round(value)) if self.kind == "count" else float(value)

    def quantile(self, q: float) -> float:
        """The ``q``-quantile (type-7 interpolation); rounded for count kind."""

        if not 0.0 <= q <= 1.0:
            raise ValueError("quantile q must be in [0, 1]")
        ordered = self._sorted
        n = len(ordered)
        if n == 1:
            return self._round(ordered[0])
        pos = q * (n - 1)
        lo = int(math.floor(pos))
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        return self._round(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)

    def quantiles(self, qs: Sequence[float]) -> list[tuple[float, float]]:
        return [(q, self.quantile(q)) for q in qs]

    def median(self) -> float:
        return self.quantile(0.5)

    def mean(self) -> float:
        return self._round(sum(self.samples) / len(self.samples))

    def interval(self, p: float) -> tuple[float, float]:
        """Central ``p`` credible interval (e.g. ``p=0.8`` -> the 10th/90th)."""

        if not 0.0 < p < 1.0:
            raise ValueError("interval p must be in (0, 1)")
        return self.quantile((1.0 - p) / 2.0), self.quantile((1.0 + p) / 2.0)

    def prob_ge(self, x: float) -> float:
        return sum(1 for s in self.samples if s >= x) / len(self.samples)

    def prob_gt(self, x: float) -> float:
        return sum(1 for s in self.samples if s > x) / len(self.samples)

    def prob_le(self, x: float) -> float:
        return sum(1 for s in self.samples if s <= x) / len(self.samples)

    def prob_lt(self, x: float) -> float:
        return sum(1 for s in self.samples if s < x) / len(self.samples)

    def crps(self, observed: float) -> float:
        """Continuous Ranked Probability Score against a realized value (>= 0)."""

        y = float(observed)
        n = len(self.samples)
        term1 = sum(abs(s - y) for s in self.samples) / n
        if n == 1:
            return term1
        term2 = sum(abs(a - b) for a in self.samples for b in self.samples) / (n * n)
        return term1 - 0.5 * term2


# ── the estimators (pure functions of a Series) ───────────────────────────────


def _doy_distance(a: date, b: date) -> int:
    """Circular day-of-year distance (Dec 31 is 1 day from Jan 1), in [0, 182]."""

    da, db = a.timetuple().tm_yday, b.timetuple().tm_yday
    raw = abs(da - db)
    return min(raw, 366 - raw)


def climatology_knn(
    series: Series, *, target: date, k: int = DEFAULT_KNN_K
) -> Distribution | None:
    """Historical same-season distribution: the ``k`` observations whose calendar
    day is nearest the target's, across all years. Declines (``None``) on a series
    thinner than :data:`MIN_CLIMATOLOGY_OBS` — too little history to be a climatology.
    """

    obs = series.observations
    if len(obs) < MIN_CLIMATOLOGY_OBS:
        return None
    neighbours = sorted(obs, key=lambda o: _doy_distance(o.as_of, target))[: max(1, k)]
    return Distribution.from_sample([o.value for o in neighbours], kind=series.kind)


def seasonal_naive(
    series: Series, *, period: int, k: int = DEFAULT_SEASONAL_K
) -> Distribution | None:
    """The last ``k`` values at the same phase (lag ``period``): the status-quo
    persistence distribution for a periodic series. Declines (``None``) when the
    series holds fewer than :data:`MIN_SEASONAL_SAMPLES` same-phase points (not
    even a couple of full cycles).
    """

    obs = series.observations
    n = len(obs)
    if period <= 0:
        return None
    same_phase = [obs[i].value for i in range(n - 1, -1, -period)][: max(1, k)]
    if len(same_phase) < MIN_SEASONAL_SAMPLES:
        return None
    return Distribution.from_sample(same_phase, kind=series.kind)


def living_model(
    question: Any, *, projection_provider: Callable[[Any], Distribution | None] | None
) -> Distribution | None:
    """Pass through a committed Market Model's projection distribution when one
    exists for this question's series. ``projection_provider`` resolves the
    question to a :class:`Distribution` (or ``None`` — no committed model, so the
    specialist declines). Default ``None`` provider always declines.
    """

    if projection_provider is None:
        return None
    return projection_provider(question)


# ── question-class selection + threshold derivation ───────────────────────────


def outcome_type_of(question: Any) -> str:
    space = getattr(question, "outcome_space", None)
    return str(getattr(space, "type", "") or "").strip().lower()


def units_of(question: Any) -> str | None:
    space = getattr(question, "outcome_space", None)
    return getattr(space, "units", None)


def series_kind_of(question: Any) -> str:
    units = (units_of(question) or "").lower()
    return "count" if any(cue in units for cue in _COUNT_UNIT_CUES) else "continuous"


def specialist_applies(question: Any) -> bool:
    """True only for continuous / count / distribution question classes."""

    return outcome_type_of(question) in _CONTINUOUS_OUTCOME_TYPES


def specialist_seats_for(question: Any) -> tuple[str, ...]:
    """The specialist seat ids applicable to a question — all three for a
    continuous class, none otherwise (binary / categorical / thesis get one never).
    Each registered seat still DECLINES at run time if its own data is missing.
    """

    return SPECIALIST_IDS if specialist_applies(question) else ()


def derive_threshold(question: Any) -> tuple[float | None, str | None]:
    """Best-effort ``(threshold, operator)`` for mapping a distribution to a vote.

    Precedence: an explicit ``metadata['specialist']`` override (``threshold`` +
    ``operator``) → a structured ``metadata['resolution_rule']`` metric threshold
    (``threshold`` + ``comparator``). Returns ``(None, None)`` when no numeric
    threshold is derivable — the specialist then declines the seat rather than
    invent a binary vote.
    """

    meta = getattr(question, "metadata", None)
    if not isinstance(meta, dict):
        return None, None
    spec = meta.get("specialist")
    if isinstance(spec, dict) and spec.get("threshold") is not None:
        return _coerce_float(spec.get("threshold")), _norm_operator(spec.get("operator"))
    rule = meta.get("resolution_rule")
    if isinstance(rule, dict) and rule.get("threshold") is not None:
        return _coerce_float(rule.get("threshold")), _norm_operator(rule.get("comparator"))
    return None, None


def _coerce_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _norm_operator(raw: Any) -> str:
    """Normalize a comparator to one of ``>=  >  <=  <`` (default ``>=``)."""

    text = str(raw or "").strip().lower()
    if text in (">", "gt", "above", "over", "greater", "greater_than"):
        return ">"
    if text in ("<", "lt", "below", "under", "less", "less_than"):
        return "<"
    if text in ("<=", "le", "lte", "at_most", "no_more_than"):
        return "<="
    return ">="  # ">=" / "ge" / "at_least" / anything unrecognised


# ── the specialist forecast + its panelist rendering ──────────────────────────


@dataclass(frozen=True)
class SpecialistForecast:
    """The outcome of running one specialist: a produced distribution or a decline."""

    seat_id: str
    distribution: Distribution | None
    declined: bool
    reason: str
    series_key: str | None = None
    as_of: date | None = None
    method: str = ""

    @property
    def produced(self) -> bool:
        return not self.declined and self.distribution is not None

    def _threshold_probability(self, threshold: float, operator: str) -> float:
        dist = self.distribution
        assert dist is not None  # produced-path only
        if operator == ">":
            return dist.prob_gt(threshold)
        if operator == "<":
            return dist.prob_lt(threshold)
        if operator == "<=":
            return dist.prob_le(threshold)
        return dist.prob_ge(threshold)

    def to_panelist_json(self, *, threshold: float, operator: str) -> str:
        """Render the produced distribution as a panelist-protocol response.

        ``probability`` is ``P(series {operator} threshold)`` — the distribution's
        binary vote. The full distribution summary rides the rationale + reasons so
        the recorded artifact carries the specialist's provenance (a
        ``ModelForecast`` has no numeric-band field, so the value quantiles cannot
        live in ``confidence_low/high``, which are probability bounds).
        """

        if not self.produced:  # defensive — the runner declines before here
            raise SpecialistDeclined(f"{self.seat_id} {self.reason}")
        dist = self.distribution
        assert dist is not None
        prob = self._threshold_probability(threshold, operator)
        lo, hi = dist.interval(0.8)
        med = dist.median()
        summary = (
            f"{self.method}: median {med:g}, 80% interval [{lo:g}, {hi:g}] over "
            f"{len(dist.samples)} points from series {self.series_key!r} "
            f"as_of {self.as_of}. Vote = P(x {operator} {threshold:g}) = {prob:.3f}."
        )
        payload = {
            "probability": round(prob, 6),
            "rationale": summary,
            "reasons_up": [f"{dist.prob_ge(threshold):.2f} of the historical "
                           f"same-season mass sits at/above {threshold:g}"],
            "reasons_down": [f"lower-tail (10th pct) is {lo:g}"],
            "crux": "whether the recent regime matches the historical same-season "
                    "distribution this specialist projects",
            "specialist": {
                "seat_id": self.seat_id,
                "method": self.method,
                "median": med,
                "interval_80": [lo, hi],
                "quantiles": {str(q): v for q, v in
                              dist.quantiles((0.1, 0.25, 0.5, 0.75, 0.9))},
                "n": len(dist.samples),
                "series_key": self.series_key,
                "as_of": self.as_of.isoformat() if self.as_of else None,
                "threshold": threshold,
                "operator": operator,
            },
        }
        return json.dumps(payload)


# ── running a specialist against a data-plane series ──────────────────────────


class SeriesProvider(Protocol):
    """Resolves a question to its historical :class:`Series`, or ``None`` when the
    series is unreachable / excessively stale (the specialist then declines)."""

    def __call__(self, question: Any, *, as_of: date) -> Series | None: ...


def _resolution_target(question: Any, as_of: date) -> date:
    """The date the question resolves toward (for the climatology day-of-year).
    Best-effort from ``resolution_time`` / ``close_time``; falls back to ``as_of``."""

    for attr in ("resolution_time", "close_time"):
        raw = getattr(question, attr, None)
        parsed = _coerce_date(raw)
        if parsed is not None:
            return parsed
    return as_of


def _coerce_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    head = str(value).replace("Z", "").split("T", 1)[0].split(" ", 1)[0]
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None


def run_specialist(
    seat_id: str,
    question: Any,
    *,
    series_provider: SeriesProvider,
    as_of: date,
    projection_provider: Callable[[Any], Distribution | None] | None = None,
) -> SpecialistForecast:
    """Fetch the series and run one specialist, or DECLINE honestly.

    The living-model seat consults ``projection_provider`` (no data-plane fetch);
    the climatology and seasonal-naive seats consult ``series_provider`` and
    decline when it returns ``None`` (unreachable / stale) or the estimator finds
    the series too thin.
    """

    def _decline(reason: str) -> SpecialistForecast:
        return SpecialistForecast(seat_id=seat_id, distribution=None, declined=True,
                                  reason=reason, as_of=as_of)

    if seat_id == LIVING_MODEL:
        dist = living_model(question, projection_provider=projection_provider)
        if dist is None:
            return _decline("declined: no committed Market Model projection for this series")
        return SpecialistForecast(seat_id=seat_id, distribution=dist, declined=False,
                                  reason="ok", as_of=as_of, method="living-model passthrough")

    series = series_provider(question, as_of=as_of)
    if series is None:
        return _decline("declined: series unreachable or excessively stale (no data plane)")
    if not series.observations:
        return _decline("declined: series has no observations")

    if seat_id == CLIMATOLOGY_KNN:
        dist = climatology_knn(series, target=_resolution_target(question, as_of))
        method = "climatology KNN (same-season neighbours)"
    elif seat_id == SEASONAL_NAIVE:
        dist = seasonal_naive(series, period=_infer_period(series))
        method = "seasonal-naive (last-k same-phase)"
    else:
        return _decline(f"declined: unknown specialist seat {seat_id!r}")

    if dist is None:
        return _decline("declined: series too thin for this specialist's method")
    return SpecialistForecast(seat_id=seat_id, distribution=dist, declined=False,
                              reason="ok", series_key=series.key, as_of=series.as_of,
                              method=method)


def _infer_period(series: Series) -> int:
    """A conservative default seasonal period from the observation cadence.

    Daily-cadence series -> weekly (7). This is deliberately simple; a richer
    period estimator can replace it without touching the seat contract.
    """

    obs = series.observations
    if len(obs) < 2:
        return 7
    gaps = sorted((obs[i + 1].as_of - obs[i].as_of).days for i in range(len(obs) - 1))
    median_gap = gaps[len(gaps) // 2]
    return 7 if median_gap <= 1 else max(1, median_gap)


# ── registration: composing specialist seats into the quorum ──────────────────

QuorumRunner = Callable[[str, str, str], str]


def make_specialist_runner(
    *,
    base_runner: QuorumRunner,
    question: Any,
    series_provider: SeriesProvider,
    as_of: date,
    threshold: float | None = None,
    operator: str | None = None,
    projection_provider: Callable[[Any], Distribution | None] | None = None,
) -> QuorumRunner:
    """Wrap ``base_runner`` so ``model:*`` ids dispatch to deterministic specialists.

    A specialist id produces a panelist-protocol JSON string (its threshold vote);
    a decline RAISES :class:`SpecialistDeclined` so the quorum records an excluded,
    labeled seat. Every non-specialist id delegates unchanged to ``base_runner``,
    and the blind-then-reconcile ``two_turn`` capability is forwarded — a
    deterministic specialist ignores the market anchor (both turns return the same
    number), so the reconcile phase is a no-op for it.
    """

    if threshold is None:
        threshold, operator = derive_threshold(question)
    if operator is None:
        operator = ">="

    def _specialist_json(seat_id: str) -> str:
        forecast = run_specialist(
            seat_id, question, series_provider=series_provider, as_of=as_of,
            projection_provider=projection_provider,
        )
        if not forecast.produced:
            raise SpecialistDeclined(f"{seat_id} {forecast.reason}")
        if threshold is None:
            raise SpecialistDeclined(f"{seat_id} declined: no derivable numeric threshold")
        return forecast.to_panelist_json(threshold=threshold, operator=operator)

    def _runner(model: str, system: str, user: str) -> str:
        if model in SPECIALIST_IDS:
            return _specialist_json(model)
        return base_runner(model, system, user)

    base_two_turn = getattr(base_runner, "two_turn", None)

    def _two_turn(model: str, system: str, blind_user: str, build_reconcile):  # type: ignore[no-untyped-def]
        if model in SPECIALIST_IDS:
            text = _specialist_json(model)
            return text, text  # anchor cannot move a deterministic specialist
        if callable(base_two_turn):
            return base_two_turn(model, system, blind_user, build_reconcile)
        blind = base_runner(model, system, blind_user)
        return blind, base_runner(model, system, blind_user + build_reconcile(blind))

    _runner.two_turn = _two_turn  # type: ignore[attr-defined]
    return _runner


def attach_specialists(
    models: Sequence[str],
    base_runner: QuorumRunner,
    question: Any,
    *,
    series_provider: SeriesProvider | None = None,
    as_of: date | None = None,
    projection_provider: Callable[[Any], Distribution | None] | None = None,
) -> tuple[list[str], QuorumRunner]:
    """Append applicable specialist seats and wrap the runner — THE registration seam.

    A no-op (returns ``models`` + ``base_runner`` unchanged) unless the question is
    a continuous class AND a numeric threshold is derivable — so the binary path is
    byte-identical and a threshold-less numeric question adds no noise. Specialist
    seats already present in ``models`` are not duplicated.
    """

    models = list(models)
    seats = specialist_seats_for(question)
    if not seats:
        return models, base_runner
    threshold, operator = derive_threshold(question)
    if threshold is None:
        return models, base_runner  # no binary vote without a threshold — stay silent
    resolved_as_of = as_of or date.today()
    provider = series_provider if series_provider is not None else default_series_provider
    runner = make_specialist_runner(
        base_runner=base_runner,
        question=question,
        series_provider=provider,
        as_of=resolved_as_of,
        threshold=threshold,
        operator=operator,
        projection_provider=projection_provider,
    )
    for seat in seats:
        if seat not in models:
            models.append(seat)
    return models, runner


# ── the default (production) series provider ──────────────────────────────────


def default_series_provider(question: Any, *, as_of: date) -> Series | None:
    """Best-effort series from the market-data plane, honoring freshness honesty.

    Reads a ``metadata['series']`` hint (``{provider, symbol, unit}``) — the shape
    a watched-source question already carries — and fetches the trailing sparkline
    via :class:`forecasting.marketdata.service.MarketDataService`. Returns ``None``
    (decline) when there is no hint, the fetch fails, the value is blanked by the
    missing-observation rule (excessive staleness), or the history is empty. The
    ``Quote`` carries only a newest ``asOf`` + a values sparkline, so per-point
    dates are reconstructed by back-spacing one day per point — adequate for the
    seasonal phase and a coarse climatology; a richer historical provider can be
    injected without changing the seat contract.
    """

    meta = getattr(question, "metadata", None)
    hint = meta.get("series") if isinstance(meta, dict) else None
    if not isinstance(hint, dict) or not hint.get("provider") or not hint.get("symbol"):
        return None
    try:
        from forecasting.marketdata.model import SeriesRef
        from forecasting.marketdata.service import MarketDataService

        ref = SeriesRef(
            provider=str(hint["provider"]).strip(),
            symbol=str(hint["symbol"]).strip(),
            unit=str(hint.get("unit") or units_of(question) or ""),
        )
        quotes = MarketDataService().quotes([ref])
    except Exception:  # noqa: BLE001 — a data-plane failure is a decline, never a crash
        return None
    if not quotes:
        return None
    quote = quotes[0]
    history = list(quote.history or [])
    if quote.value is None or not history:  # blanked by staleness / empty
        return None
    newest = _epoch_ms_to_date(quote.asOf) or as_of
    observations = tuple(
        Observation(as_of=newest - timedelta(days=(len(history) - 1 - i)), value=float(v))
        for i, v in enumerate(history)
    )
    return Series(
        key=ref.symbol,
        unit=ref.unit or (units_of(question) or ""),
        observations=observations,
        as_of=newest,
        kind=series_kind_of(question),
    )


def _epoch_ms_to_date(epoch_ms: int) -> date | None:
    if not epoch_ms:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc).date()


__all__ = [
    "CLIMATOLOGY_KNN",
    "SEASONAL_NAIVE",
    "LIVING_MODEL",
    "SPECIALIST_IDS",
    "SpecialistDeclined",
    "Observation",
    "Series",
    "Distribution",
    "SpecialistForecast",
    "SeriesProvider",
    "climatology_knn",
    "seasonal_naive",
    "living_model",
    "outcome_type_of",
    "units_of",
    "series_kind_of",
    "specialist_applies",
    "specialist_seats_for",
    "derive_threshold",
    "run_specialist",
    "make_specialist_runner",
    "attach_specialists",
    "default_series_provider",
]
