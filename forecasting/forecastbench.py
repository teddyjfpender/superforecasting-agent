"""ForecastBench ingestion adapter — honestly-scored CLOSED-BOOK backtest cases.

ForecastBench (Forecasting Research Institute) publishes dated *question sets*
and paired *resolution sets*. Each question set freezes a forecast-due date and
a list of questions across many real sources. Those sources fall into two very
different families and MIXING them produces garbage calibration data:

* **Market-probability sources** — ``manifold``, ``metaculus``, ``polymarket``,
  ``infer``. Their ``freeze_datetime_value`` IS a genuine 0..1 *probability*
  (the market/community's YES probability at the freeze), and their
  ``resolved_to`` is a clean binary 0.0/1.0 outcome. These are the ONLY sources
  we ingest: a freeze value usable as a real market baseline + a clean binary
  outcome to score against.

* **Dataset sources** — ``acled``, ``fred``, ``dbnomics``, ``wikipedia``,
  ``yfinance``. Their ``freeze_datetime_value`` is a raw *level* (a CPI index, a
  share price, an event count), NOT a probability; their ``resolved_to`` is
  frequently FRACTIONAL; and they carry sentinel
  ``market_info_close_datetime == "N/A"`` and unsubstituted
  ``{resolution_date}`` / ``{forecast_due_date}`` placeholder titles. We DROP
  every dataset source outright.

The module fetches a question set + its paired resolution set, joins them by
``(source, id)``, and keeps only SINGLE (``direction is None``) + RESOLVED +
MARKET-SOURCE questions whose ``resolved_to`` is within 1e-6 of 0.0 or 1.0 (a
clean binary resolution — fractional resolutions are dropped honestly). Each
survivor maps into OUR backtest case dict (the exact shape
``ForecastLedger._run_backtest_case`` consumes — see ``forecasting/benchmarks``
for the canonical template).

The freeze (``freeze_datetime``) becomes the as_of / evidence_cutoff so a
replay can only see information available at the freeze, and the freeze market
probability (``freeze_datetime_value``) is carried as an external ``market``
baseline for honest agent-vs-market comparison.

CLOSED-BOOK SEAL: a historical question must NOT be answerable by fetching its
now-known outcome. The live market URL is therefore NEVER exposed to the agent —
it is stored ONLY in ``metadata`` (not in ``resolution_source`` and not in the
context-evidence row's ``url``/``source``), so neither
``agent_protocol.sanitize_backtest_case_for_agent`` nor ``_pre_cutoff_evidence``
can hand the agent a slug that reveals the resolution.

Network fetch is isolated behind ``_fetch_json`` (mockable + on-disk cached);
``load_forecastbench_cases`` never re-fetches when a cached copy exists.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

__all__ = [
    "ForecastBenchError",
    "load_forecastbench_cases",
    "build_forecastbench_case",
    "forecastbench_dataset_label",
    "QUESTION_SET_URL_TEMPLATE",
    "RESOLUTION_SET_URL_TEMPLATE",
]

_RAW_BASE = (
    "https://raw.githubusercontent.com/forecastingresearch/"
    "forecastbench-datasets/main/datasets"
)
QUESTION_SET_URL_TEMPLATE = _RAW_BASE + "/question_sets/{date}-llm.json"
RESOLUTION_SET_URL_TEMPLATE = _RAW_BASE + "/resolution_sets/{date}_resolution_set.json"

_USER_AGENT = "superforecasting-agent/forecastbench"
_FETCH_TIMEOUT_SECONDS = 30
_MAX_BYTES = 64 * 1024 * 1024

# The ONLY ForecastBench sources whose ``freeze_datetime_value`` is a genuine
# 0..1 YES *probability* and whose ``resolved_to`` is a clean binary outcome.
# Every other ("dataset") source carries a raw level as its freeze value and a
# frequently-fractional resolution, so we drop them outright (see module docstring).
MARKET_SOURCES: frozenset[str] = frozenset({"manifold", "metaculus", "polymarket", "infer"})

# Tolerance for treating a ``resolved_to`` value as a clean binary outcome.
_BINARY_OUTCOME_TOL = 1e-6

# Sentinel close-datetime that ForecastBench writes for dataset sources; treat it
# (and any other unparseable/empty value) as ABSENT.
_CLOSE_TIME_SENTINELS = frozenset({"n/a", "na", "none", "null", "tbd", ""})


class ForecastBenchError(RuntimeError):
    """Raised when a ForecastBench dataset cannot be fetched or parsed."""


def forecastbench_dataset_label(question_set_date: str) -> str:
    """Stable dataset label used on backtest runs for a ForecastBench date."""

    return f"forecastbench:{question_set_date}"


def _cache_root(cache_dir: str | Path | None) -> Path | None:
    """Resolve the on-disk cache directory (None disables caching)."""

    if cache_dir is not None:
        root = Path(cache_dir).expanduser()
    else:
        try:
            from hermes_constants import get_hermes_home

            root = get_hermes_home() / "cache" / "forecastbench"
        except Exception:
            return None
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return root


def _fetch_json(url: str) -> Any:
    """Fetch + parse one JSON document over HTTP.

    The single network boundary for this module: tests monkeypatch THIS to
    return canned question/resolution payloads, and the on-disk cache wraps it
    so a real run hits the network at most once per date.
    """

    try:
        request = Request(url, headers={"User-Agent": _USER_AGENT})
        with urlopen(request, timeout=_FETCH_TIMEOUT_SECONDS) as response:
            body = response.read(_MAX_BYTES)
            charset = response.headers.get_content_charset() or "utf-8"
            text = body.decode(charset, errors="replace")
    except (OSError, URLError, ValueError) as exc:
        raise ForecastBenchError(f"could not fetch ForecastBench document: {url}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ForecastBenchError(f"ForecastBench document is not valid JSON: {url}") from exc


def _fetch_cached(url: str, *, cache_path: Path | None) -> Any:
    """Fetch ``url`` honoring an on-disk cache; never re-fetch if cached."""

    if cache_path is not None and cache_path.is_file():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass  # corrupt cache -> refetch
    payload = _fetch_json(url)
    if cache_path is not None:
        try:
            tmp = cache_path.with_name(f"{cache_path.name}.tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(cache_path)
        except OSError:
            pass  # caching is best-effort
    return payload


def _normalized_source(question_or_resolution: dict[str, Any]) -> str:
    return str(question_or_resolution.get("source") or "").strip().lower()


def _is_market_source(question: dict[str, Any]) -> bool:
    """True only for the four market-probability sources we ingest.

    Dataset sources (acled/fred/dbnomics/wikipedia/yfinance) carry a raw LEVEL as
    ``freeze_datetime_value`` (not a probability) and a frequently-fractional
    ``resolved_to``; restricting to ``MARKET_SOURCES`` is the dominant fix that
    keeps the produced set honest. It also incidentally excludes the "N/A"
    close_time sources and the ACLED ``{resolution_date}`` placeholder titles.
    """

    return _normalized_source(question) in MARKET_SOURCES


def _is_binary_question(question: dict[str, Any]) -> bool:
    """A ForecastBench question is admissible when it is a MARKET source whose
    freeze value is a genuine 0..1 probability.

    Source-gating (``_is_market_source``) is the primary filter: only the market
    sources store ``freeze_datetime_value`` as a YES probability. We additionally
    require that value to parse into [0, 1] (defensive — a market row missing or
    corrupting its freeze value cannot ride as a fake baseline).
    """

    if not _is_market_source(question):
        return False
    raw = question.get("freeze_datetime_value")
    if raw is None:
        return False
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return False
    return 0.0 <= value <= 1.0


def _freeze_market_probability(question: dict[str, Any]) -> float | None:
    raw = question.get("freeze_datetime_value")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not 0.0 <= value <= 1.0:
        return None
    return value


def _resolved_to_float(resolution: dict[str, Any]) -> float | None:
    raw = resolution.get("resolved_to")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _resolved_outcome_label(resolution: dict[str, Any]) -> str | None:
    """Map a CLEAN binary ``resolved_to`` (within 1e-6 of 0.0/1.0) to yes/no.

    Critically this does NOT coerce a fractional outcome via ``>= 0.5``: a
    metaculus 0.49 or infer 0.5677 is a genuinely fractional community/market
    resolution, NOT a binary yes/no, and silently rounding it would fabricate a
    bogus ground-truth label and poison the Brier scoring. Fractional values
    return ``None`` and are dropped honestly by the caller.
    """

    value = _resolved_to_float(resolution)
    if value is None:
        return None
    if abs(value - 1.0) <= _BINARY_OUTCOME_TOL:
        return "yes"
    if abs(value - 0.0) <= _BINARY_OUTCOME_TOL:
        return "no"
    return None  # fractional resolution -> not a clean binary outcome


def _is_clean_binary_resolution(resolution: dict[str, Any]) -> bool:
    return _resolved_outcome_label(resolution) is not None


def _is_fractional_resolution(resolution: dict[str, Any]) -> bool:
    """True when ``resolved_to`` is present, numeric, but not within tol of 0/1."""

    value = _resolved_to_float(resolution)
    if value is None:
        return False
    return not (
        abs(value - 1.0) <= _BINARY_OUTCOME_TOL or abs(value - 0.0) <= _BINARY_OUTCOME_TOL
    )


def _clean_close_time(value: Any) -> str | None:
    """Return ``value`` only if it is a usable timestamp, else ``None``.

    ForecastBench writes ``"N/A"`` (and friends) for dataset-source close times;
    treat those — and anything ``parse_timestamp`` would reject — as ABSENT so a
    downstream ``create_question`` never receives a non-ISO string. Belt-and-
    braces: source-gating already drops every "N/A" source.
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in _CLOSE_TIME_SENTINELS:
        return None
    try:
        from forecasting.models import parse_timestamp

        return parse_timestamp(text, field_name="close_time")
    except Exception:
        return None


def _join_key(source: Any, qid: Any) -> tuple[str, str]:
    return (str(source or ""), str(qid))


def build_forecastbench_case(
    question: dict[str, Any],
    resolution: dict[str, Any],
    *,
    question_set_date: str,
) -> dict[str, Any]:
    """Map a joined (question, resolution) pair to OUR backtest case dict.

    The returned dict matches the keys ``_run_backtest_case`` consumes
    (mirroring ``benchmarks.py``'s Manifold/Kalshi template): ``title``,
    ``resolution_criteria``, ``description``, ``as_of`` ==
    ``simulated_forecast_time`` == ``evidence_cutoff`` == ``freeze_datetime``,
    ``close_time``, ``resolution_time`` == the resolution_date, ``outcome`` ==
    ``resolved_to`` mapped to yes/no, plus the freeze market probability carried
    as a ``market`` baseline (and a ``naive_0_5`` baseline).

    CLOSED-BOOK SEAL: ``source``/``url`` ride ONLY in ``metadata`` — never in
    ``resolution_source`` and never in the context-evidence row's ``url``/
    ``source`` — so the live market slug (which often reveals the resolution)
    cannot reach the agent through ``sanitize_backtest_case_for_agent`` or
    ``_pre_cutoff_evidence``.
    """

    source = str(question.get("source") or "")
    qid = str(question.get("id"))
    # Every timestamp routes through _clean_close_time so a non-ISO sentinel
    # ("N/A"/"unknown"/garbage) on ANY field becomes None instead of crashing
    # create_question's parse_timestamp. A case with no valid freeze (as_of) is
    # dropped at admission (load_forecastbench_cases), since it can carry no
    # evidence/baselines pinned to the forecast instant.
    as_of = _clean_close_time(question.get("freeze_datetime"))
    resolution_time = _clean_close_time(resolution.get("resolution_date")) or _clean_close_time(
        question.get("market_info_close_datetime")
    )
    close_time = _clean_close_time(question.get("market_info_close_datetime")) or resolution_time
    outcome = _resolved_outcome_label(resolution)
    market_probability = _freeze_market_probability(question)
    url = question.get("url")
    background = str(question.get("background") or "")
    question_text = str(question.get("question") or f"ForecastBench {source} question {qid}")
    resolution_criteria = str(
        question.get("resolution_criteria")
        or "Resolved by the linked ForecastBench source per its published resolution criteria."
    )

    case: dict[str, Any] = {
        "id": f"forecastbench-{question_set_date}-{source}-{qid}",
        "title": question_text,
        "description": background,
        "resolution_criteria": resolution_criteria,
        # CLOSED-BOOK: no live source URL here — it is an answer leak. Stored in
        # metadata only (and resolution_source is NOT an _ANSWER_SIDE_FIELD, so a
        # URL here would be handed to the agent verbatim).
        "resolution_source": None,
        "domain": "forecastbench",
        # Explicit tags so the desk can carve out a separate "bench" view: every
        # ForecastBench replay question carries "bench" + "forecastbench" (+ its
        # source), distinct from organic live desk forecasts.
        "tags": [t for t in ("bench", "forecastbench", source) if t],
        "topics": [source] if source else ["forecastbench"],
        "as_of": as_of,
        "simulated_forecast_time": as_of,
        "evidence_cutoff": as_of,
        "close_time": close_time,
        "resolution_time": str(resolution_time) if resolution_time else None,
        "outcome": outcome,
        "notes": (
            "Imported from the ForecastBench "
            f"{question_set_date} question set and paired resolution set. "
            "The freeze market probability is carried as an external baseline; "
            "the agent forecasts closed-book from the question text only (the "
            "live source URL is withheld to seal the now-known outcome)."
        ),
        "metadata": {
            "source_dataset": forecastbench_dataset_label(question_set_date),
            "forecastbench_source": source,
            "forecastbench_id": qid,
            "forecastbench_url": url,
            "question_set_date": question_set_date,
            "external_id": qid,
        },
    }

    # One context evidence row, pinned at the freeze so the cutoff filter keeps
    # it. It carries the question text + background but NO source URL: the live
    # market slug is an answer leak (is_leak_domain() does not flag
    # manifold.markets / metaculus.com, so it would otherwise reach the agent).
    # claim_type MUST be a member of EVIDENCE_CLAIM_TYPES {fact,estimate,rumor,
    # opinion,assumption}; "context" is NOT a claim_type (it is a *stance*) and
    # made add_evidence raise for every case. Use "fact".
    if as_of:
        case["evidence"] = [
            {
                "source": f"forecastbench:{source}" if source else "forecastbench",
                "source_name": f"ForecastBench ({source})" if source else "ForecastBench",
                "source_type": f"adapter:forecastbench:{source}" if source else "adapter:forecastbench",
                # No "url" key: withholding the live source slug seals the outcome.
                "claim": question_text,
                "summary": background or question_text,
                "available_at": as_of,
                "claim_type": "fact",
                "stance": "context",
            }
        ]

    baselines: list[dict[str, Any]] = []
    if market_probability is not None and as_of:
        baselines.append(
            {
                "source": source or "forecastbench",
                "baseline_type": "market",
                "probability": market_probability,
                "as_of": as_of,
            }
        )
        baselines.append(
            {
                "source": "auto",
                "baseline_type": "naive_0_5",
                "probability": 0.5,
                "as_of": as_of,
            }
        )
    if baselines:
        case["baselines"] = baselines

    return case


def load_forecastbench_cases(
    question_set_date: str,
    *,
    limit: int | None = None,
    binary_only: bool = True,
    resolved_only: bool = True,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Load + map ForecastBench cases for ``question_set_date``.

    Fetches the dated question set and its paired resolution set (caching the
    raw JSON under the agent cache dir), joins them by ``(source, id)``, and
    maps each surviving SINGLE (``direction is None``) + RESOLVED + MARKET-SOURCE
    question whose ``resolved_to`` is a CLEAN binary 0.0/1.0 to OUR backtest case
    dict. Dataset sources and fractional resolutions are dropped honestly.

    Returns a report dict::

        {
          "cases": [<case dict>, ...],
          "question_set_date": str,
          "resolution_set_date": str | None,
          "counts": {
            "questions": int,            # questions in the set
            "resolutions": int,          # resolutions in the paired set
            "produced": int,             # cases returned
            "dropped_combination": int,  # direction != null (conditional pairs)
            "dropped_unresolved": int,   # no resolution / resolved == false
            "dropped_non_binary": int,   # non-market source / freeze not a 0..1 prob
            "dropped_fractional": int,   # resolved_to numeric but not ~0/1
            "dropped_no_outcome": int,   # resolved but resolved_to missing/non-numeric
            "dropped_limit": int,        # trimmed by ``limit``
          },
          "produced_by_source": {<source>: int, ...},  # per-source produced counts
          "dataset": "forecastbench:<date>",
        }

    ``limit`` caps the number of produced cases (applied after filtering).
    ``binary_only`` gates on market-source + 0..1 freeze probability; with it
    off, source-gating and the fractional-outcome drop still apply so the
    produced set stays honestly binary-scorable. ``resolved_only`` toggles the
    ``resolved`` flag requirement.
    """

    root = _cache_root(cache_dir)
    q_cache = (root / f"question_set_{question_set_date}.json") if root else None
    r_cache = (root / f"resolution_set_{question_set_date}.json") if root else None

    question_payload = _fetch_cached(
        QUESTION_SET_URL_TEMPLATE.format(date=question_set_date), cache_path=q_cache
    )
    resolution_payload = _fetch_cached(
        RESOLUTION_SET_URL_TEMPLATE.format(date=question_set_date), cache_path=r_cache
    )

    if not isinstance(question_payload, dict):
        raise ForecastBenchError("ForecastBench question set must be a JSON object")
    if not isinstance(resolution_payload, dict):
        raise ForecastBenchError("ForecastBench resolution set must be a JSON object")

    questions = question_payload.get("questions")
    if not isinstance(questions, list):
        raise ForecastBenchError("ForecastBench question set is missing a 'questions' array")
    resolutions = resolution_payload.get("resolutions")
    if not isinstance(resolutions, list):
        raise ForecastBenchError("ForecastBench resolution set is missing a 'resolutions' array")

    resolution_set_date = (
        resolution_payload.get("forecast_due_date")
        or question_payload.get("forecast_due_date")
    )

    # Index resolutions by (source, id). SINGLE questions have direction null;
    # a non-null direction marks a COMBINATION / conditional pair which we drop
    # outright (we never match it into a single-question case).
    resolution_index: dict[tuple[str, str], dict[str, Any]] = {}
    dropped_combination = 0
    for row in resolutions:
        if not isinstance(row, dict):
            continue
        if row.get("direction") is not None:
            dropped_combination += 1
            continue
        key = _join_key(row.get("source"), row.get("id"))
        # Keep the first single resolution per id (resolution sets are 1:1 for
        # single questions); ignore later duplicates defensively.
        resolution_index.setdefault(key, row)

    cases: list[dict[str, Any]] = []
    dropped_unresolved = 0
    dropped_non_binary = 0
    dropped_fractional = 0
    dropped_no_outcome = 0
    dropped_no_freeze = 0
    dropped_limit = 0
    produced_by_source: dict[str, int] = {}

    for question in questions:
        if not isinstance(question, dict):
            continue
        key = _join_key(question.get("source"), question.get("id"))
        resolution = resolution_index.get(key)

        if resolved_only:
            if resolution is None or not resolution.get("resolved"):
                dropped_unresolved += 1
                continue
        # Source-gating + freeze-probability check. ``binary_only`` toggles only
        # the freeze-value requirement; the MARKET-SOURCE restriction always
        # holds (a dataset-source level is never a probability), so with
        # binary_only off we still gate on source to keep the set honest.
        if binary_only:
            if not _is_binary_question(question):
                dropped_non_binary += 1
                continue
        elif not _is_market_source(question):
            dropped_non_binary += 1
            continue
        # Even when resolved_only is False we still need *some* resolution to
        # produce a scorable outcome; a question with no single resolution can
        # only ride as an unresolved (unscored) case, which we drop here so the
        # produced set is always honestly scorable.
        if resolution is None:
            dropped_unresolved += 1
            continue
        # Fractional resolutions (metaculus 0.49, infer 0.5677) are NOT a clean
        # binary outcome; drop them honestly rather than rounding to a fake label.
        if _is_fractional_resolution(resolution):
            dropped_fractional += 1
            continue
        if _resolved_outcome_label(resolution) is None:
            dropped_no_outcome += 1
            continue
        # A question with no valid freeze timestamp has no as_of to pin evidence /
        # baselines to, so the produced case would fail scoring — drop it honestly.
        if _clean_close_time(question.get("freeze_datetime")) is None:
            dropped_no_freeze += 1
            continue

        if limit is not None and len(cases) >= limit:
            dropped_limit += 1
            continue

        case = build_forecastbench_case(
            question, resolution, question_set_date=question_set_date
        )
        cases.append(case)
        src = _normalized_source(question) or "forecastbench"
        produced_by_source[src] = produced_by_source.get(src, 0) + 1

    return {
        "cases": cases,
        "question_set_date": question_set_date,
        "resolution_set_date": resolution_set_date,
        "dataset": forecastbench_dataset_label(question_set_date),
        "produced_by_source": produced_by_source,
        "counts": {
            "questions": len(questions),
            "resolutions": len(resolutions),
            "produced": len(cases),
            "dropped_combination": dropped_combination,
            "dropped_unresolved": dropped_unresolved,
            "dropped_non_binary": dropped_non_binary,
            "dropped_fractional": dropped_fractional,
            "dropped_no_outcome": dropped_no_outcome,
            "dropped_no_freeze": dropped_no_freeze,
            "dropped_limit": dropped_limit,
        },
    }
