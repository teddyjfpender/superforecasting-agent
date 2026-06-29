"""AIA P2.1 — the LIVE, SEARCH-ENABLED informed forecaster for MarketNightly.

:mod:`forecasting.market_nightly` is deliberately PURE: it takes the agent
forecaster as an injected ``Callable[[market], float]`` seam and never reaches a
network. This module supplies the OTHER half — the real, search-enabled informed
agent that the foreknowledge-proof live benchmark runs FORWARD on currently-OPEN
markets.

Why search is LEGITIMATE here (and forbidden in the historical backtest):

  * The market-hidden ForecastBench experiment proved the *closed-book* LLM has
    NO intrinsic edge over the market (agent Brier 0.279 vs market 0.164). The
    only path to beating the market is FRESH information the market has not yet
    priced in.
  * You cannot prove that on a HISTORICAL question: searching a resolved
    question leaks the answer (the web already says how it resolved). So the
    backtest runner (``_backtest_agent_protocol_runner``) runs CLOSED-BOOK.
  * The proof must run FORWARD: forecast an OPEN market WITH live search NOW,
    score it when it RESOLVES. The outcome does not exist yet, so foreknowledge
    is impossible BY CONSTRUCTION and the search is honest — exactly the
    out-of-sample, overfit-proof record we want.

So this forecaster does the OPPOSITE of the closed-book backtest runner: it
builds a search-enabled agent (``enabled_toolsets`` INCLUDES ``"web"`` so it can
research the live world), prompts it with the OPEN market's question +
resolution criteria using the SAME agent-protocol prompt packet the backtest
uses, runs it, and parses a probability in ``[0, 1]``.

Robustness contract: ANY failure (agent error, non-JSON, missing probability)
returns ``None``. ``forecasting.market_nightly.record_pending`` already SKIPS a
market whose forecaster returns a non-probability, so a single flaky market never
aborts a sweep and is never stored with a bogus number.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from forecasting.agent_protocol import parse_agent_protocol_response
from forecasting.market_nightly import (
    market_close_time,
    market_id,
    market_yes_price,
)

# The default agent budget for a single market forecast. Modest: one informed
# pass with web search is enough to surface fresh, market-unpriced information;
# the benchmark's value is BREADTH (many markets over time), not depth per market.
DEFAULT_MAX_ITERATIONS = 20
DEFAULT_TIMEOUT_SECONDS = 300
# Minimum distinct bettors for a Manifold market to be an admissible study target:
# below this the market is a thin/personal question, not an objective skill test or a
# meaningful price baseline.
MIN_MARKET_TRADERS = 8

# This is the LIVE / future-resolving path, so search is LEGITIMATE (see module
# docstring). "web" MUST be present so the agent researches the open question — and
# it is the ONLY toolset here, BY DESIGN. This forecaster's whole job is to (a)
# research an OPEN market and (b) return a JSON probability that
# ``forecasting.market_nightly.record_pending`` records under a ``forecastbench:``
# id against a proper de-vigged market baseline. It must therefore be a PURE
# RESEARCH agent with NO ledger-mutating capability whatsoever.
#
# The "forecasting" toolset is DELIBERATELY EXCLUDED: it exposes the
# ``forecast_ledger`` tool (create_question / update_forecast / record_panel /
# self_check / record-quorum …), i.e. the FULL desk ledger-write surface. Handing
# those to the live one-shot forecaster made it fumble through the desk's
# ledger-write flow and POLLUTE THE LIVE LEDGER (it manufactured garbage ``fq_``
# questions + stray snapshots, and under ``--parallel`` several agents RACED on the
# ledger) instead of simply emitting a probability. "file" is likewise excluded:
# the prompt (``build_live_market_messages``) only asks for a JSON object and the
# parse path (``parse_agent_protocol_response``) reads the final response text — no
# file read/write is on the agent-protocol forecast path, so read_file/write_file/
# patch/search_files are dead weight that only widen the blast radius. Web search
# alone is necessary and sufficient. This is also the DELIBERATE inverse of the
# closed-book backtest runner's EMPTY toolset (no search at all).
LIVE_ENABLED_TOOLSETS = ["web"]


def _market_to_case(market: Mapping[str, Any]) -> dict[str, Any]:
    """Build an agent-protocol ``case`` dict for a single OPEN market.

    The case carries ONLY admissible, forecast-time inputs: the question text,
    the resolution criteria, the description, and the market id. It intentionally
    does NOT carry the market's own YES price as a baseline — the agent's edge has
    to come from fresh INFORMATION, not from copying the market it is being scored
    against (the de-vigged market price is recorded separately as the baseline to
    beat). There is no resolution to leak: the market is open."""

    mid = market_id(market)
    title = ""
    for key in ("question", "title", "name"):
        value = market.get(key) if isinstance(market, Mapping) else None
        if value:
            title = str(value).strip()
            break
    if not title:
        title = f"Market {mid}"

    criteria = ""
    for key in ("resolution_criteria", "description"):
        value = market.get(key) if isinstance(market, Mapping) else None
        if value:
            criteria = str(value).strip()
            break
    if not criteria:
        criteria = "Resolves YES/NO according to the linked market's settlement rules."

    return {
        "id": mid or title,
        "title": title,
        "question": title,
        "resolution_criteria": criteria,
        "description": str(market.get("description") or "") if isinstance(market, Mapping) else "",
        "close_time": market_close_time(market),
        # evidence_cutoff = NOW (the agent uses fresh search up to the present);
        # the sanitizer keys off this but for a live market there is nothing to
        # withhold — the outcome does not exist yet.
        "evidence_cutoff": None,
        "market_source": str(market.get("source") or market.get("platform") or "")
        if isinstance(market, Mapping)
        else "",
    }


def build_live_market_messages(case: Mapping[str, Any]) -> list[dict[str, str]]:
    """Forward/LIVE prompt for an OPEN market — the inverse of the backtest packet.

    It tells the agent it is forecasting a real, currently-OPEN question that
    resolves in the FUTURE and INSTRUCTS it to use the web search tool to gather the
    most current evidence. (Reusing ``build_backtest_agent_protocol_messages`` — "you
    are operating in a historical backtest, use ONLY the supplied case data, do not
    infer from later information" — would suppress the very fresh search that is this
    experiment's whole point, biasing the live arm toward the closed-book null.) The
    market's own price is deliberately absent so the estimate is independent. The
    output schema matches :func:`parse_agent_protocol_response`."""

    title = str(case.get("question") or case.get("title") or "").strip()
    criteria = str(case.get("resolution_criteria") or "").strip()
    close_time = str(case.get("close_time") or "").strip()
    source = str(case.get("market_source") or "").strip()

    parts = [f"## Open Forecast Question\n\n**Question:** {title}"]
    if criteria:
        parts.append(f"\n\n**Resolution criteria:** {criteria}")
    if close_time:
        parts.append(f"\n\n**Market closes:** {close_time}")
    if source:
        parts.append(f"\n\n**Venue:** {source}")
    parts.append(
        "\n\nThis is a REAL, currently-OPEN question that resolves in the future. "
        "Use the web search tool to gather the most current evidence available today "
        "— recent news, polls, data releases, expert ratings, relevant base rates — "
        "then reason to an independent probability. You are NOT given the market's own "
        "price; do not try to guess it — form your estimate from the evidence you find.\n\n"
        "Return ONLY a JSON object with these fields:\n"
        "- probability: number between 0 and 1 for YES\n"
        "- confidence: optional number between 0 and 1\n"
        "- rationale: concise audit trail citing the fresh evidence you found, base "
        "rates, key assumptions, and uncertainty\n"
        "- components: optional object or list of component probabilities"
    )
    return [
        {
            "role": "system",
            "content": (
                "You are Superforecasting Agent producing a LIVE, auditable binary "
                "forecast of an OPEN prediction-market question that resolves in the "
                "FUTURE. Actively use your web search tool to gather the most current "
                "evidence before forecasting; the outcome is not yet known. Form an "
                "INDEPENDENT estimate — you are not shown the market price. Output "
                "strict JSON only."
            ),
        },
        {"role": "user", "content": "".join(parts)},
    ]


def _ensure_plugins_discovered() -> None:
    """Register web-search providers once (idempotent) so the live search path
    has its tools available. A discovery failure is non-fatal — the agent simply
    runs with whatever toolsets are already registered."""

    try:
        from hermes_cli.plugins import discover_plugins

        discover_plugins()  # idempotent
    except Exception:  # noqa: BLE001 — discovery is best-effort, never fatal
        pass


def build_informed_market_forecaster(
    *,
    model: str | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    agent_factory: Callable[..., Any] | None = None,
    discover: bool = True,
    fresh_agent_per_call: bool = False,
) -> Callable[[Mapping[str, Any]], float | None]:
    """Return a SEARCH-ENABLED informed ``AgentForecaster`` for MarketNightly.

    The returned callable maps ``market dict -> float in [0, 1] | None``:

      1. Build a search-enabled agent via :func:`agent.agent_factory.build_agent`
         with ``enabled_toolsets`` INCLUDING ``"web"`` (the live/future path, so
         search is legitimate — NOT closed-book). The agent is built lazily on the
         FIRST market and reused for the rest of the sweep.
      2. Prompt it with the market question + resolution criteria via the
         agent-protocol prompt packet (the same prompt the ForecastBench backtest
         used), run it, and parse the JSON forecast with
         :func:`parse_agent_protocol_response` into a probability.
      3. ANY failure -> ``None`` (record_pending then skips the market).

    ``model`` is the resolved active model-id STRING (resolve it from
    ``config["model"]`` with the same ``_resolve_active_model_id`` logic the
    quorum uses — ``config["model"]`` is a dict). ``agent_factory`` is an injection
    seam for tests so no live agent is constructed; it defaults to ``build_agent``.

    ``fresh_agent_per_call`` (default ``False``) controls agent REUSE. The default
    builds ONE agent on the first market and reuses it across the sweep — fine for
    the SEQUENTIAL path, but that single agent carries conversation state and is
    NOT thread-safe. When the caller forecasts markets CONCURRENTLY (e.g.
    :func:`forecasting.market_nightly.record_pending` with ``max_workers > 1``),
    pass ``fresh_agent_per_call=True`` so each forecast builds its OWN isolated
    agent — no shared state can race between worker threads. This is the correct
    fix for parallel use (isolation, not a lock: the agent call is the whole cost,
    so locking it would serialize the slow part and defeat the parallelism).
    """

    if not model:
        # Robustness: resolve the active model id ourselves when not given one, rather
        # than passing "" to the provider (codex rejects an empty model). The CLI path
        # already resolves it; this covers programmatic callers.
        try:
            from hermes_cli.config import load_config

            from forecasting.cli import _resolve_active_model_id

            model = _resolve_active_model_id(load_config().get("model"))
        except Exception:  # noqa: BLE001 — leave model unset; the factory may still default it
            model = model or None

    if discover:
        _ensure_plugins_discovered()

    factory = agent_factory
    if factory is None:
        from agent.agent_factory import build_agent as factory  # type: ignore[no-redef]

    # The agent is expensive to construct; by default build it once on the first
    # market and reuse it across the sweep (one search-enabled agent forecasts
    # every market). Under ``fresh_agent_per_call`` we skip the cache and build a
    # NEW agent on every forecast so concurrent workers never share one agent's
    # (non-thread-safe) conversation state.
    _agent_cell: dict[str, Any] = {}

    # ``timeout`` is part of the public budget contract (callers may pass it) but
    # AIAgent's constructor has NO ``timeout`` kwarg — forwarding it would crash
    # construction — so it is accepted-and-held here, NOT passed to the factory.
    del timeout

    def _build_agent() -> Any:
        return factory(
            model=model or "",
            enabled_toolsets=LIVE_ENABLED_TOOLSETS,
            max_iterations=max_iterations,
            platform="cli",
        )

    def _get_agent() -> Any:
        if fresh_agent_per_call:
            return _build_agent()  # isolated per call — safe for parallel workers
        if "agent" not in _agent_cell:
            _agent_cell["agent"] = _build_agent()
        return _agent_cell["agent"]

    def forecaster(market: Mapping[str, Any]) -> float | None:
        try:
            case = _market_to_case(market)
            # FORWARD/LIVE prompt (encourages fresh web search) — NOT the backtest
            # packet, whose "historical backtest / use only supplied data" framing
            # would suppress the search this experiment exists to measure.
            messages = build_live_market_messages(case)
            agent = _get_agent()
            result = agent.run_conversation(
                messages[1]["content"],
                system_message=messages[0]["content"],
            )
            if isinstance(result, dict):
                response = result.get("final_response") or result
            else:
                response = result
            parsed = parse_agent_protocol_response(response)
            probability = parsed.get("probability")
            if probability is None:
                return None
            return float(probability)
        except Exception:  # noqa: BLE001 — any failure -> None; record_pending skips it
            return None

    return forecaster


# ── live open-market source (used by the CLI; NOT imported by the pure module) ──


def _looks_personal(question: str) -> bool:
    """Heuristic quality gate: a self-referential / personal / meta market that the
    agent cannot research and whose price is just the creator's whim — e.g. "Will I
    go to the gym this week?", "Will my novel be published?", "Will this market get
    20 traders?". Excluded from the study so the sample is objective, researchable
    real-world questions. Imperfect by design (documented as a sample limitation)."""

    q = str(question or "").strip().lower()
    if q.startswith(("will i ", "will my ", "will we ", "i'll ", "i will ", "am i ", "do i ")):
        return True
    if "this market" in q or "this question" in q:  # meta markets about themselves
        return True
    return " i'll " in q or " will i " in q


def _manifold_open_markets(*, limit: int, min_traders: int = MIN_MARKET_TRADERS) -> list[dict[str, Any]]:
    """Fetch a batch of currently-OPEN Manifold binary markets as market dicts.

    Read-only. Reuses the existing Manifold adapter payload mapping; keeps only
    UNRESOLVED binary markets and maps each into the market-dict shape the pure
    sampler/record_pending consume (id, question, probability, close_time,
    resolution_criteria). The strictly-future-close foreknowledge filter is
    applied later by :func:`forecasting.market_nightly.sample_open_markets`.

    QUALITY GATE: Manifold is open-creation play-money, so its tail is dominated by
    subjective *personal* markets ("Will I go to the gym this week?") that are neither
    researchable skill tests nor meaningful price baselines. We keep only markets with
    at least ``min_traders`` distinct bettors (``uniqueBettorCount``) — an objective,
    liquid question — and carry the liquidity metadata (n_traders, volume) for the
    study's sample-quality reporting."""

    from urllib.parse import urlencode

    from forecasting.source_adapters import (
        _manifold_market_from_payload,
        _read_json_endpoint,
    )

    api_base_url = "https://api.manifold.markets/v0"
    # Fetch a wide batch (we filter hard on liquidity below) sorted soonest-close-first,
    # so the survivors are both objective AND likely to resolve within the study window.
    query = urlencode(
        {
            "term": "",
            "filter": "open",
            "contractType": "BINARY",
            "limit": min(max(int(limit), 1) * 12, 1000),
            "sort": "close-date",
        }
    )
    endpoint = f"{api_base_url}/search-markets?{query}"
    payload = _read_json_endpoint(endpoint, "manifold open markets")
    rows = payload if isinstance(payload, list) else (payload.get("markets") if isinstance(payload, dict) else None)
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            market = _manifold_market_from_payload(row, str(row.get("url") or api_base_url))
        except Exception:  # noqa: BLE001 — a single bad row never aborts the batch
            continue
        if market.is_resolved or market.outcome_space.type != "binary":
            continue
        if market.probability is None or market.close_time is None:
            continue
        try:
            n_traders = int(row.get("uniqueBettorCount") or 0)
        except (TypeError, ValueError):
            n_traders = 0
        if n_traders < int(min_traders):
            continue  # quality gate: too thin to be an objective question / price baseline
        if _looks_personal(market.question):
            continue  # quality gate: self-referential / personal / meta market
        try:
            volume = float(row.get("volume") or 0.0)
        except (TypeError, ValueError):
            volume = 0.0
        out.append(
            {
                "id": f"manifold:{market.market_id or market.slug or market.question}",
                "source": "manifold",
                "question": market.question,
                "description": market.description,
                "resolution_criteria": market.resolution_criteria,
                "probability": market.probability,
                "close_time": market.close_time,
                "resolution_time": market.resolution_time,
                "url": market.url,
                "n_traders": n_traders,
                "volume": volume,
            }
        )
    return out


def _metaculus_open_questions(*, limit: int) -> list[dict[str, Any]]:
    """Fetch a batch of currently-OPEN Metaculus binary questions as market dicts."""

    from urllib.parse import urlencode

    from forecasting.source_adapters import (
        _metaculus_question_from_payload,
        _read_json_endpoint,
    )

    api_base_url = "https://www.metaculus.com/api"
    query = urlencode({"status": "open", "type": "binary", "limit": min(max(int(limit), 1) * 4, 1000)})
    endpoint = f"{api_base_url}/questions/?{query}"
    payload = _read_json_endpoint(endpoint, "metaculus open questions")
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("results") or payload.get("questions") or payload.get("data")
    else:
        rows = None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            question = _metaculus_question_from_payload(row, str(row.get("url") or api_base_url))
        except Exception:  # noqa: BLE001
            continue
        if question.outcome_space.type != "binary":
            continue
        if question.probability is None or question.close_time is None:
            continue
        # Foreknowledge guard (mirror the Manifold is_resolved drop): never sample a
        # question that already carries a resolution / is not open, even if the API's
        # status=open filter returned a stale or annulled row — a resolved question's
        # outcome is known and would leak. Defensive getattr: a missing attr -> no drop.
        if getattr(question, "resolution", None) not in (None, ""):
            continue
        _status = str(getattr(question, "status", "") or "").strip().lower()
        if _status and _status != "open":
            continue
        out.append(
            {
                "id": f"metaculus:{question.question_id or question.title}",
                "source": "metaculus",
                "question": question.title,
                "description": question.description,
                "resolution_criteria": question.resolution_criteria,
                "probability": question.probability,
                "close_time": question.close_time,
                "resolution_time": question.resolution_time,
                "url": question.url,
            }
        )
    return out


def _forecastbench_open_questions(*, limit: int) -> list[dict[str, Any]]:
    """Serve the OPEN (future-resolving) MARKET questions of the latest
    ForecastBench question set as market dicts for the live harness.

    This routes the live forward benchmark at a CURATED, serious question set
    (the four ForecastBench market sources — manifold/metaculus/polymarket/infer)
    instead of the raw Manifold tail. The questions are still OPEN, so a live
    web search is legitimate; the carried ``probability`` is the freeze market
    price as of the question SET's date — a slightly-STALE baseline (documented in
    ``forecastbench.load_forecastbench_open_questions``). Read-only; the
    foreknowledge strictly-future-close filter is applied both here (open check)
    and again by ``forecasting.market_nightly.sample_open_markets``."""

    from forecasting.forecastbench import load_forecastbench_open_questions

    return load_forecastbench_open_questions(date="latest", limit=max(int(limit), 1))


_OPEN_MARKET_SOURCES: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "manifold": _manifold_open_markets,
    "metaculus": _metaculus_open_questions,
    "forecastbench": _forecastbench_open_questions,
}


def load_open_markets(source: str, *, limit: int) -> list[dict[str, Any]]:
    """Fetch a batch of currently-OPEN markets from ``source`` as market dicts.

    The CLI ``run`` path wires this as the market source for
    :func:`forecasting.market_nightly.sample_open_markets`. Read-only; raises
    ``ValueError`` for an unknown source. (Tests inject a fake source instead, so
    this never reaches a live API under test.)"""

    loader = _OPEN_MARKET_SOURCES.get(str(source).strip().lower())
    if loader is None:
        known = ", ".join(sorted(_OPEN_MARKET_SOURCES))
        raise ValueError(f"unknown market source {source!r} (known: {known})")
    return loader(limit=limit)


def available_open_market_sources() -> list[str]:
    return sorted(_OPEN_MARKET_SOURCES)


# Re-export the de-vig + price helpers so the CLI imports a single module.
__all__ = [
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_TIMEOUT_SECONDS",
    "LIVE_ENABLED_TOOLSETS",
    "available_open_market_sources",
    "build_informed_market_forecaster",
    "load_open_markets",
    "market_yes_price",
]
