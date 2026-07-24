"""Resolution-rule, proposal and scoring actions.

Carved from ``tools/forecasting_tool.py`` (Arc D tool-registry slice); each handler
takes ``(args, ledger)`` and returns the tool-result JSON string.  Bodies are moved
verbatim behind the unchanged ``forecast_ledger_tool`` facade; the only body edit is
the ``_ft.`` monkeypatch-forwarding hop for names tests patch on the facade module.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit, urlunsplit

from forecasting.models import ForecastingError
from tools.registry import tool_result
from typing import Any
from tools.forecasting_tool import _required

def set_resolution_rule(args: dict[str, Any], ledger) -> str:
    question_id = _required(args, "question_id")
    if args.get("threshold") is None:
        raise ForecastingError("threshold is required for set_resolution_rule")
    rule = ledger.set_resolution_rule(
        question_id,
        field=_required(args, "field"),
        comparator=_required(args, "comparator"),
        threshold=float(args["threshold"]),
        resolver=args.get("resolver") or "metric_threshold",
        source_role=args.get("source_role") or "resolver",
    )
    return tool_result(success=True, question_id=question_id, resolution_rule=rule)

def propose_resolution(args: dict[str, Any], ledger) -> str:
    question_id = _required(args, "question_id")
    proposal = ledger.propose_resolution(question_id)
    return tool_result(success=True, question_id=question_id, resolution_proposal=proposal)

def propose_resolutions(args: dict[str, Any], ledger) -> str:
    from forecasting import resolution_detector as _rd

    dry_run = bool(args.get("dry_run"))
    horizon_days = int(args.get("horizon_days") or _rd.DEFAULT_HORIZON_DAYS)
    limit = args.get("limit")
    market_reader = None
    try:
        market_reader = _rd.build_market_outcome_reader()
    except Exception:
        market_reader = None

    classifier = None
    runner = None
    model = ""
    if args.get("use_llm"):
        # Opt-in paid tier: wire the bounded cheap-model runner (mirrors the
        # triage labeler) + the reference classifier. Only reached on an
        # explicit use_llm=true, so the default path spends nothing.
        from forecasting.quorum import DEFAULT_JUDGE_MODEL, make_aiagent_runner

        model = args.get("model") or os.getenv("FORECAST_RESOLUTION_MODEL") or DEFAULT_JUDGE_MODEL
        runner = make_aiagent_runner(toolsets=(), max_iterations=2, quiet=True, timeout=180)
        classifier = _rd.classify_resolution

    summary = _rd.propose_detected_resolutions(
        ledger,
        now=args.get("now"),
        horizon_days=horizon_days,
        market_reader=market_reader,
        classifier=classifier,
        runner=runner,
        model=model,
        limit=int(limit) if limit is not None else None,
        dry_run=dry_run,
    )
    return tool_result(success=True, **summary)

def list_resolution_proposals(args: dict[str, Any], ledger) -> str:
    from forecasting.ledger import alerts as _alerts

    proposals = []
    for alert in ledger.list_alerts(unresolved_only=True):
        if getattr(alert, "scope_type", None) != "question":
            continue
        outcome = _alerts.resolution_proposal_outcome(getattr(alert, "reason", ""))
        if not outcome:
            continue
        proposals.append({
            "alert_id": alert.id,
            "question_id": alert.scope_ref,
            "outcome": outcome,
            "reason": alert.reason,
            "confirm_command": alert.recommended_action,
            "created_at": alert.created_at,
        })
    return tool_result(success=True, count=len(proposals), proposals=proposals)

def resolve(args: dict[str, Any], ledger) -> str:
    resolution = ledger.resolve_question(
        question_id=_required(args, "question_id"),
        outcome=_required(args, "outcome"),
        resolution_source=args.get("resolution_source"),
        resolution_source_snapshot_ref=args.get("resolution_source_snapshot_ref"),
        resolver_type=args.get("resolver_type") or "manual",
        resolution_status=args.get("resolution_status") or "confirmed",
        criteria_satisfied=bool(args.get("criteria_satisfied", True)),
        confidence=args.get("confidence"),
        confirmed_by=args.get("confirmed_by"),
        resolver_notes=args.get("resolver_notes"),
        correction_ref=args.get("correction_ref"),
        trusted_policy_id=args.get("trusted_policy_id"),
        scoreable=bool(args.get("scoreable", True)),
        auto_score=bool(args.get("auto_score", True)),
    )
    try:
        if resolution.resolution_status == "confirmed" and resolution.criteria_satisfied:
            from forecasting.writeup import write_retrospective

            _qid = args.get("question_id")
            write_retrospective(
                ledger,
                _qid,
                score=ledger.get_current_score(_qid),
                main_runtime=args.get("_main_runtime"),
            )
    except Exception:
        pass
    return tool_result(success=True, resolution=resolution.__dict__)

def score(args: dict[str, Any], ledger) -> str:
    score = ledger.score_question(_required(args, "question_id"))
    return tool_result(success=True, score=score.__dict__)

# ── backfill_market_ids: infer a STRUCTURED metadata.market_id for open ─────────
#    questions that reference a market only in prose (criteria/links) so the
#    resolution detector can read their terminal outcome. DETERMINISTIC only:
#    structured links first, then an UNAMBIGUOUS market URL in the criteria; a
#    question with zero or >1 distinct market references is SKIPPED (never guessed).

# host -> venue. A subdomain of any of these (e.g. www.) also matches.
_MARKET_HOSTS = {
    "polymarket.com": "polymarket",
    "manifold.markets": "manifold",
    "metaculus.com": "metaculus",
    "kalshi.com": "kalshi",
}
_URL_RE = re.compile(r"""https?://[^\s)>\]"'`}]+""")


def _market_venue_for_host(host: str) -> str | None:
    host = (host or "").lower()
    for suffix, venue in _MARKET_HOSTS.items():
        if host == suffix or host.endswith("." + suffix):
            return venue
    return None


def _normalize_market_url(url: str) -> str:
    """Canonical comparison key for a market URL: scheme+host+path, lowercased,
    trailing slash and trailing prose punctuation stripped, query/fragment
    dropped. Two prose mentions of the SAME market collapse to one key (so they
    are not mistaken for an ambiguous pair)."""
    trimmed = url.rstrip(".,);]}>\"'`")
    parts = urlsplit(trimmed)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def _extract_market_urls(text: str) -> list[tuple[str, str]]:
    """Distinct (venue, normalized_url) market references found in ``text``."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in _URL_RE.findall(text or ""):
        norm = _normalize_market_url(raw)
        venue = _market_venue_for_host(urlsplit(norm).netloc)
        if venue and norm not in seen:
            seen.add(norm)
            out.append((venue, norm))
    return out


def _canonicalize_market_ref(venue: str, ref: str) -> tuple[str, str]:
    """Resolve a (venue, URL-or-id) reference to a reader-usable canonical
    ``('<venue>:<id>', venue)``. Does a READ-ONLY network call through the venue
    adapter: it validates the market exists AND returns the exact id form the
    detector's reader dispatches on (e.g. a Manifold slug URL -> the contract id
    that ``load_manifold_market('id:...')`` accepts). Raises on any failure — the
    caller records a skip and never writes an unverified ref. Kept at module
    scope so tests can inject a fake without touching the network."""
    from forecasting import source_adapters as _sa

    if venue == "manifold":
        ident = _sa.load_manifold_market(ref).market_id
    elif venue == "polymarket":
        ident = _sa.load_polymarket_market(ref).market_id
    elif venue == "metaculus":
        ident = _sa.load_metaculus_question(ref).question_id
    elif venue == "kalshi":
        ident = _sa.load_kalshi_market(ref).ticker
    else:
        raise ForecastingError(f"unsupported market venue: {venue}")
    ident = str(ident or "").strip()
    if not ident:
        raise ForecastingError(f"{venue} market reference resolved to an empty id")
    return f"{venue}:{ident}", venue


def _infer_market_ref(ledger, question, *, canonicalize=None) -> dict[str, Any]:
    """Deterministically infer a structured market ref for ONE question, or record
    why nothing could be inferred. Priority: structured forecast_link metadata >
    ``metadata.market_url`` > an unambiguous market URL in the resolution
    source/criteria/description. Zero references -> skip; more than one DISTINCT
    reference -> skip as ambiguous (never guessed)."""
    canonicalize = canonicalize or _canonicalize_market_ref
    meta = question.metadata if isinstance(getattr(question, "metadata", None), dict) else {}
    if isinstance(meta.get("market_id"), str) and meta["market_id"].strip():
        return {"status": "skipped", "question_id": question.id, "reason": "already has a structured market_id"}

    # key -> (venue, reference, origin). Highest-priority origin wins the key.
    candidates: dict[str, tuple[str, str, str]] = {}

    def _add(venue: str, reference: str, origin: str, key: str | None = None) -> None:
        candidates.setdefault(key or reference, (venue, reference, origin))

    # 1. structured forecast-link metadata (both directions)
    try:
        for link in ledger.list_forecast_links(question.id, direction="both"):
            lm = link.get("metadata") if isinstance(link, dict) else None
            if not isinstance(lm, dict):
                continue
            mid = lm.get("market_id")
            if isinstance(mid, str) and ":" in mid and mid.split(":", 1)[1].strip():
                _add(mid.split(":", 1)[0].strip().lower(), mid.strip(), "forecast_link.market_id", key=mid.strip())
            elif isinstance(lm.get("market_url"), str):
                for v, u in _extract_market_urls(lm["market_url"]):
                    _add(v, u, "forecast_link.market_url")
    except Exception:
        pass

    # 2. a market_url already sitting in the question metadata
    if isinstance(meta.get("market_url"), str):
        for v, u in _extract_market_urls(meta["market_url"]):
            _add(v, u, "metadata.market_url")

    # 3. an unambiguous market URL in the prose fields
    text = " ".join(
        str(getattr(question, f, "") or "")
        for f in ("resolution_source", "resolution_criteria", "description")
    )
    for v, u in _extract_market_urls(text):
        _add(v, u, "criteria_url")

    if not candidates:
        return {"status": "skipped", "question_id": question.id, "reason": "no market reference found in links/criteria/metadata"}
    if len(candidates) > 1:
        return {
            "status": "skipped",
            "question_id": question.id,
            "reason": f"ambiguous: {len(candidates)} distinct market references",
            "references": sorted(candidates)[:6],
        }

    venue, reference, origin = next(iter(candidates.values()))
    if "://" not in reference:
        # a structured link/metadata already handed us a canonical <venue>:<id> —
        # trust it verbatim (no network round-trip, no re-derivation).
        market_id, source = reference, venue
    else:
        try:
            market_id, source = canonicalize(venue, reference)
        except Exception as exc:  # unreadable / deleted / venue error -> honest skip
            return {"status": "skipped", "question_id": question.id, "reason": f"market reference unreadable: {exc}", "reference": reference, "origin": origin}
    return {
        "status": "proposed",
        "question_id": question.id,
        "market_id": market_id,
        "market_source": source,
        "origin": origin,
        "reference": reference,
    }


def backfill_market_ids(args: dict[str, Any], ledger) -> str:
    """Scan OPEN questions lacking a structured ``metadata.market_id`` and, for
    each one whose criteria/links unambiguously reference a single market, infer
    the canonical ``<venue>:<id>`` ref. ``dry_run`` (DEFAULT TRUE) reports the
    proposed writes without touching the ledger; ``dry_run=false`` writes each ref
    through the gated :meth:`ForecastLedger.set_question_market_ref` path (fill-
    only, never overwrites, preserves other metadata)."""
    dry_run = args.get("dry_run")
    dry_run = True if dry_run is None else bool(dry_run)
    limit = args.get("limit")

    questions = [
        q for q in ledger.list_questions(status="active")
        if not (isinstance(getattr(q, "metadata", None), dict) and str((q.metadata or {}).get("market_id") or "").strip())
    ]
    if limit is not None:
        questions = questions[: max(0, int(limit))]

    proposals: list[dict[str, Any]] = []
    written: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for question in questions:
        result = _infer_market_ref(ledger, question)
        if result.get("status") != "proposed":
            skipped.append(result)
            continue
        entry = {k: result[k] for k in ("question_id", "market_id", "market_source", "origin", "reference")}
        if dry_run:
            proposals.append({**entry, "written": False})
            continue
        try:
            ledger.set_question_market_ref(
                question.id,
                market_id=result["market_id"],
                market_source=result["market_source"],
                actor="backfill_market_ids",
            )
            written.append({**entry, "written": True})
        except Exception as exc:
            errors.append({**entry, "error": str(exc)})

    return tool_result(
        success=True,
        dry_run=dry_run,
        scanned=len(questions),
        proposed_count=len(proposals),
        written_count=len(written),
        skipped_count=len(skipped),
        error_count=len(errors),
        proposals=proposals,
        written=written,
        errors=errors,
        # cap the (potentially long) skip list but keep every reason category
        skipped=skipped[:60],
    )


def list_scores(args: dict[str, Any], ledger) -> str:
    scores = ledger.list_scores(
        domain=args.get("domain"),
        forecast_origin=args.get("forecast_origin"),
        calibration_eligible=args.get("calibration_eligible"),
        horizon=args.get("horizon"),
        bucket=args.get("bucket"),
        include_invalidated=bool(args.get("include_invalidated", False)),
    )
    return tool_result(success=True, scores=[score.__dict__ for score in scores])


HANDLERS = {
    "set_resolution_rule": set_resolution_rule,
    "propose_resolution": propose_resolution,
    "propose_resolutions": propose_resolutions,
    "list_resolution_proposals": list_resolution_proposals,
    "backfill_market_ids": backfill_market_ids,
    "resolve": resolve,
    "score": score,
    "list_scores": list_scores,
}
