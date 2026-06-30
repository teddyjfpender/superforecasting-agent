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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen

__all__ = [
    "ForecastBenchError",
    "load_forecastbench_cases",
    "load_forecastbench_open_questions",
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

# ``latest-llm.json`` is NOT a question set — it is a tiny POINTER file whose body
# is the FILENAME of the newest dated set (e.g. ``2026-06-21-llm.json``). It must
# be fetched as raw TEXT and resolved to a date; json.loads()-ing it raises (and
# caching it as a question set poisons the cache). See ``_resolve_latest_date``.
_LATEST_POINTER_URL = _RAW_BASE + "/question_sets/latest-llm.json"

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


def _fetch_text(url: str) -> str:
    """Fetch one document over HTTP as raw TEXT (NO json.loads).

    Same Request/urlopen/timeout/``_MAX_BYTES`` boundary + ``ForecastBenchError``
    surface as :func:`_fetch_json`, but returns the undecoded body text. Used for
    the ``latest-llm.json`` POINTER file, whose body is a bare filename, not JSON.
    """

    try:
        request = Request(url, headers={"User-Agent": _USER_AGENT})
        with urlopen(request, timeout=_FETCH_TIMEOUT_SECONDS) as response:
            body = response.read(_MAX_BYTES)
            charset = response.headers.get_content_charset() or "utf-8"
            return body.decode(charset, errors="replace")
    except (OSError, URLError, ValueError) as exc:
        raise ForecastBenchError(f"could not fetch ForecastBench document: {url}") from exc


def _resolve_latest_date() -> str:
    """Resolve ``latest-llm.json`` (a POINTER file) to the newest set's BARE date.

    The pointer body is the FILENAME of the newest dated question set (e.g.
    ``2026-06-21-llm.json``, sometimes quoted / newline-terminated). We strip
    whitespace + surrounding quotes, take the basename, and strip the
    ``-llm.json`` (tolerating ``_llm.json`` / a bare ``.json``) suffix to recover
    the immutable date (``2026-06-21``). The caller then keys every dated URL +
    cache file off this resolved date, NEVER off the literal ``latest``.
    """

    raw = _fetch_text(_LATEST_POINTER_URL).strip()
    # Strip a surrounding pair of matching quotes (the pointer is occasionally a
    # JSON string literal rather than a bare filename).
    if len(raw) >= 2 and raw[0] in {'"', "'"} and raw[-1] == raw[0]:
        raw = raw[1:-1].strip()
    # The body may be a full path; keep only the filename.
    basename = raw.rsplit("/", 1)[-1].strip()
    date = basename
    for suffix in ("-llm.json", "_llm.json", ".json"):
        if date.endswith(suffix):
            date = date[: -len(suffix)]
            break
    date = date.strip()
    if not date or len(date) < 8 or date.lower() == "latest":
        raise ForecastBenchError(
            f"could not resolve ForecastBench latest question-set date from pointer: {raw!r}"
        )
    return date


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
    hide_market_baseline: bool = False,
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
        # source), distinct from organic live desk forecasts. The market-hidden arm
        # additionally carries "market_hidden" so it is trivially separable from the
        # market-visible arm (same titles/sources/dataset label otherwise).
        "tags": [
            t for t in (
                "bench", "forecastbench",
                "market_hidden" if hide_market_baseline else None,
                source,
            ) if t
        ],
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
        market_baseline: dict[str, Any] = {
            "source": source or "forecastbench",
            "baseline_type": "market",
            "probability": market_probability,
            "as_of": as_of,
        }
        # MARKET-HIDDEN ARM: when requested, mark the freeze market price hidden
        # from the agent. It is STILL carried (and so still scored as a
        # baseline_comparison for the head-to-head + P1.3 complementarity), but
        # agent_protocol._pre_cutoff_baselines drops it from the agent prompt so no
        # market price is shown to the agent (pair with --closed-book for a true
        # intrinsic-only forecast). Default (False) leaves the baseline byte-identical.
        if hide_market_baseline:
            market_baseline["hidden_from_agent"] = True
        baselines.append(market_baseline)
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
    hide_market_baseline: bool = False,
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

    ``hide_market_baseline`` (default False) marks the freeze ``market`` baseline
    ``hidden_from_agent`` so the agent forecasts INTRINSICALLY from the question
    text only (no market price to anchor on), while the market baseline is STILL
    carried and scored for the agent-vs-market head-to-head + P1.3
    complementarity. Default False keeps produced cases byte-identical.
    """

    # ``latest`` is a POINTER, not a dated set: resolve it to the immutable dated
    # filename FIRST so the dated URL + cache files below (and the produced cases'
    # dataset label) all key off the real date, never the literal ``latest``.
    question_set_date = str(question_set_date or "").strip()
    if not question_set_date or question_set_date.lower() == _LATEST_DATE:
        question_set_date = _resolve_latest_date()

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
            question,
            resolution,
            question_set_date=question_set_date,
            hide_market_baseline=hide_market_baseline,
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


# ── OPEN (future-resolving) question feed for the LIVE / forward harness ─────────
#
# The functions above ingest a HISTORICAL (question set + resolution set) pair for
# CLOSED-BOOK backtests: every question is already resolved, so live search would
# leak the answer and the live source URL is sealed. The feed below is the
# OPPOSITE: it serves the still-OPEN (future-resolving) MARKET questions from a
# question set so the foreknowledge-proof LIVE harness
# (``market_nightly_forecaster``) can forecast curated, serious questions WITH live
# search instead of random Manifold junk. Live search is LEGITIMATE here because
# the outcome does not exist yet (it cannot be looked up), and — unlike the
# backtest path — the live source ``url`` IS carried so the agent can reference the
# venue. No resolution set is fetched (the questions are unresolved by construction).

# ``"latest"`` is a SENTINEL: it is resolved (via the ``latest-llm.json`` POINTER
# file) to the newest IMMUTABLE dated question set BEFORE any fetch — we never
# fetch ``latest-llm.json`` as a question set (it is a 19-byte filename pointer,
# not JSON). See ``_resolve_latest_date``.
_LATEST_DATE = "latest"


def _question_set_resolution_instant(question: dict[str, Any]) -> datetime | None:
    """Derive the question's RESOLUTION instant as an aware UTC datetime.

    This is the moment the OUTCOME settles: the MAX of ``resolution_dates`` (the
    last/final date the question can settle on); fall back to
    ``market_info_close_datetime`` only when no resolution date is parseable.
    Returns ``None`` when neither yields a parseable, non-sentinel timestamp — the
    caller treats an underivable resolution as "cannot confirm OPEN" and drops the
    question. The OPEN/foreknowledge filter keys off THIS instant (the outcome,
    not the market close, must be in the future for live search to be legitimate).
    """

    candidates: list[str] = []
    resolution_dates = question.get("resolution_dates")
    if isinstance(resolution_dates, (list, tuple)):
        for value in resolution_dates:
            cleaned = _clean_close_time(value)
            if cleaned:
                candidates.append(cleaned)
    elif resolution_dates is not None:
        cleaned = _clean_close_time(resolution_dates)
        if cleaned:
            candidates.append(cleaned)

    chosen: datetime | None = None
    for cleaned in candidates:
        dt = _to_utc_datetime(cleaned)
        if dt is not None and (chosen is None or dt > chosen):
            chosen = dt
    if chosen is not None:
        return chosen

    fallback = _clean_close_time(question.get("market_info_close_datetime"))
    return _to_utc_datetime(fallback)


def _question_set_close_instant(question: dict[str, Any]) -> datetime | None:
    """Derive the market CLOSE instant as an aware UTC datetime.

    This is when the underlying market stops trading (``market_info_close_datetime``),
    which can PRECEDE the resolution instant (a market may close, then resolve days
    later). Falls back to the resolution instant when no market close is parseable.
    """

    close = _to_utc_datetime(_clean_close_time(question.get("market_info_close_datetime")))
    if close is not None:
        return close
    return _question_set_resolution_instant(question)


def _normalize_now(now: datetime | None) -> datetime:
    """Return an aware-UTC ``now`` so comparisons are always aware-vs-aware.

    ``None`` -> the current UTC instant. A tz-NAIVE ``now`` is treated as UTC
    (tzinfo attached) so callers passing a naive ``datetime.utcnow()`` do not
    trip a ``TypeError`` on the aware-vs-naive comparison.
    """

    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _to_utc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        from forecasting.models import timestamp_to_datetime

        return timestamp_to_datetime(value)
    except Exception:
        return None


def load_forecastbench_open_questions(
    date: str = _LATEST_DATE,
    *,
    sources: Sequence[str] = ("manifold", "metaculus", "polymarket", "infer"),
    limit: int | None = None,
    cache_dir: str | Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch the OPEN (future-resolving) MARKET questions of a ForecastBench set.

    Reuses the closed-book module's :data:`QUESTION_SET_URL_TEMPLATE`
    (``{date}-llm.json``) and :func:`_fetch_json` network boundary (so tests
    monkeypatch ``_fetch_json`` with a tiny fixture and nothing here touches the
    network). ``date="latest"`` is FIRST resolved (via the ``latest-llm.json``
    POINTER file — :func:`_resolve_latest_date`) to the newest IMMUTABLE dated set
    (e.g. ``2026-06-21``); we NEVER fetch/cache the literal ``latest-llm.json`` as
    a question set (it is a bare-filename pointer, not JSON).

    A question survives ONLY when it is:

      * a MARKET source in ``sources`` (default the four market-probability
        sources — dataset sources like ``acled``/``fred``/``dbnomics`` carry a raw
        level, not a probability, and are dropped),
      * has a non-empty, 0..1-parseable ``freeze_datetime_value`` (its freeze
        market probability — used as the stale baseline below), AND
      * is still OPEN: a RESOLUTION instant derived from ``resolution_dates``
        (max) or ``market_info_close_datetime`` (fallback) that is STRICTLY in
        the future (``> now``). The OUTCOME, not the market close, must be in the
        future — a market that has stopped trading but resolves later is still
        admissible. A question whose resolution cannot be derived is dropped (we
        cannot confirm it is open).

    Each survivor maps to the market-dict shape the live harness consumes
    (mirroring ``market_nightly_forecaster._manifold_open_markets``)::

        {
          "id": "forecastbench:<id>",
          "source": <source>,
          "question": <question>,
          "description": <background>,
          "resolution_criteria": <resolution_criteria>,
          "probability": float(freeze_datetime_value),
          "close_time": <ISO market close>,        # market_info_close (fallback resolution)
          "resolution_time": <ISO resolution>,     # max(resolution_dates) (fallback close)
          "url": <live source url>,
        }

    FOREKNOWLEDGE NOTE: these are OPEN questions that resolve in the FUTURE, so a
    live web search is LEGITIMATE — the outcome does not exist yet and cannot be
    looked up. The ``probability`` is the freeze market price as of the question
    SET's date, i.e. a slightly-STALE baseline (the set may be days/weeks old by
    the time the harness runs); treat it as a coarse prior, not the live price.
    The live source ``url`` is intentionally carried (the live harness may show
    the venue) — there is no resolved outcome to seal.

    ``limit`` caps the number of returned questions (applied after filtering).
    ``now`` is the reference instant for the OPEN filter; ``None`` uses the
    current UTC time and a tz-naive ``now`` is treated as UTC (so the aware
    resolution instants are always compared aware-vs-aware).
    """

    question_set_date = str(date or _LATEST_DATE).strip() or _LATEST_DATE
    # ``latest`` is a POINTER, not a fetchable set: resolve it to the IMMUTABLE
    # dated filename FIRST, so every dated URL + cache file below keys off the real
    # date (e.g. ``2026-06-21``) and we NEVER fetch/cache the literal
    # ``latest-llm.json`` (a 19-byte pointer that is not valid JSON).
    if not question_set_date or question_set_date.lower() == _LATEST_DATE:
        question_set_date = _resolve_latest_date()
    allowed: frozenset[str] = frozenset(
        str(s).strip().lower() for s in sources if str(s or "").strip()
    )

    root = _cache_root(cache_dir)
    q_cache = (root / f"question_set_{question_set_date}.json") if root else None
    payload = _fetch_cached(
        QUESTION_SET_URL_TEMPLATE.format(date=question_set_date), cache_path=q_cache
    )
    if not isinstance(payload, dict):
        raise ForecastBenchError("ForecastBench question set must be a JSON object")

    # The OPEN feed reads the question set's ``question_set`` array (the closed-book
    # path reads ``questions``); accept either key defensively so a schema rename
    # does not silently empty the feed.
    questions = payload.get("question_set")
    if not isinstance(questions, list):
        questions = payload.get("questions")
    if not isinstance(questions, list):
        raise ForecastBenchError(
            "ForecastBench question set is missing a 'question_set'/'questions' array"
        )

    now = _normalize_now(now)

    out: list[dict[str, Any]] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        source = _normalized_source(question)
        if source not in allowed:
            continue  # dataset source / source not requested
        probability = _freeze_market_probability(question)
        if probability is None:
            continue  # no usable 0..1 freeze baseline
        # The OPEN/foreknowledge filter keys off the RESOLUTION instant (the
        # outcome must be in the future); a market whose trading has closed but
        # whose outcome resolves later is still admissible as open.
        resolution_dt = _question_set_resolution_instant(question)
        if resolution_dt is None or resolution_dt <= now:
            continue  # resolved / past / underivable -> not OPEN
        # ``close_time`` is the market-close instant (when present); ``resolution_time``
        # is the outcome instant. They can differ (market closes, then resolves later).
        close_dt = _question_set_close_instant(question) or resolution_dt
        close_iso = close_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        resolution_iso = (
            resolution_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )

        qid = str(question.get("id"))
        question_text = str(
            question.get("question") or f"ForecastBench {source} question {qid}"
        )
        resolution_criteria = str(
            question.get("resolution_criteria")
            or "Resolves YES/NO per the linked ForecastBench source's published criteria."
        )
        # PRICE PROVENANCE: the carried ``probability`` is the FROZEN freeze-market
        # price as of the question SET's freeze instant (``freeze_datetime``, the set's
        # date — e.g. 2026-06-11), NOT a live quote. We stamp ``price_asof`` with that
        # true vintage and flag ``baseline_is_frozen=True`` so the live-edge roll-up can
        # quarantine these stale baselines from the agent-vs-market edge claim. Fall
        # back to the resolved question-set DATE when the per-question freeze instant is
        # absent/garbage (still a frozen vintage, never the live forecast instant).
        price_asof = (
            _clean_close_time(question.get("freeze_datetime"))
            or _clean_close_time(question_set_date)
            or f"{question_set_date}T00:00:00Z"
        )
        out.append(
            {
                "id": f"forecastbench:{qid}",
                "source": source,
                "question": question_text,
                "description": str(question.get("background") or ""),
                "resolution_criteria": resolution_criteria,
                "probability": probability,
                "close_time": close_iso,
                "resolution_time": resolution_iso,
                "url": question.get("url"),
                # The frozen-baseline provenance the live harness records honestly.
                "price_asof": price_asof,
                "baseline_is_frozen": True,
            }
        )
        if limit is not None and len(out) >= limit:
            break

    return out
