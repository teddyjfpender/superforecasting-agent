"""Slice 6 — EVIDENCE_COLLECTION runner (the no-evidence / no-snapshot bucket).

The reasons ``no_evidence`` / ``no_forecast_snapshot`` used to be bucketed into
REFORECAST, whose runner hard-blocks on zero evidence (``update gated``) and so
never collected anything. They now route to their own ResolutionKind whose
AGENT-tier runner SEARCHES FOR + IMPORTS evidence — and the load-bearing rule
holds: it acks ONLY when >= 1 NEW evidence row is imported (never on an empty or
dup-only fetch).
"""

from __future__ import annotations

from forecasting.cron_runner import build_warning_runners, gated_evidence_collection
from forecasting.ledger import ForecastLedger
from forecasting.warnings import (
    ResolutionKind,
    ResolutionRunners,
    classify_warning,
    expand_tier,
    resolve_alert,
    select_open_warnings,
)


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "ev.db"))
    lg.initialize_schema()
    return lg


def _question(lg) -> str:
    q = lg.create_question(
        title="Will the metric clear its threshold by the close date?",
        resolution_criteria="Resolves yes if the reported value exceeds the stated threshold at close.",
    )
    return q.id


def _alert(lg, qid, *, reason: str):
    return lg.create_alert(
        severity="warning", scope_type="question", scope_ref=qid,
        reason=reason, recommended_action="Collect evidence.",
    )


def _dedupe_search(candidates):
    """A fake AGENT-tier evidence search that mirrors the CLI import dedupe gate:
    it imports each candidate reading unless an identical (source_type, entry_id)
    reading is already on file (so a dup-only fetch imports NOTHING)."""

    def _search(led, warning):
        qid = warning.scope_ref
        seen = led.existing_evidence_keys(qid)
        imported = 0
        for c in candidates:
            payload = dict(c)
            entry_id = (payload.get("metadata") or {}).get("entry_id")
            key = (payload.get("source_type") or "", str(entry_id)) if entry_id else None
            if key and key in seen:
                continue
            led.add_evidence(question_id=qid, archive_url_snapshot=False, **payload)
            if key:
                seen.add(key)
            imported += 1
        return {"imported": imported}

    return _search


_READING = {
    "source_or_note": "Official series print: value 4.2 as of the latest release.",
    "source_type": "fred",
    "metadata": {"entry_id": "obs_2026_06"},
}


# ---------------------------------------------------------------------------
# Classification — no_evidence / no_forecast_snapshot now route to EVIDENCE_COLLECTION
# ---------------------------------------------------------------------------

def test_no_evidence_reasons_route_to_evidence_collection_not_reforecast():
    assert classify_warning("no_evidence") is ResolutionKind.EVIDENCE_COLLECTION
    assert classify_warning("no_forecast_snapshot") is ResolutionKind.EVIDENCE_COLLECTION
    # new_evidence / staleness still mean "you HAVE evidence, re-forecast".
    assert classify_warning("new_evidence:ev_1") is ResolutionKind.REFORECAST
    assert classify_warning("evidence_stale_7d_plus") is ResolutionKind.REFORECAST


def test_evidence_collection_is_in_the_agent_tier():
    # It shares the heavy "reforecast"/"agent" bulk tier with REFORECAST.
    assert ResolutionKind.EVIDENCE_COLLECTION in expand_tier("reforecast")
    assert ResolutionKind.EVIDENCE_COLLECTION in expand_tier("agent")


# ---------------------------------------------------------------------------
# The >= 1-new-row truthy gate
# ---------------------------------------------------------------------------

def _is_open(lg, alert_id: str) -> bool:
    return any(a.id == alert_id for a in lg.list_alerts(unresolved_only=True))


def test_acks_only_when_a_new_evidence_row_is_imported(tmp_path):
    lg = _ledger(tmp_path)
    qid = _question(lg)
    a = _alert(lg, qid, reason="no_evidence")

    runners = ResolutionRunners(evidence_runner=lambda led, w: gated_evidence_collection(
        led, w, evidence_search=_dedupe_search([_READING])
    ))
    res = resolve_alert(lg, a, runners=runners)

    assert res["status"] == "resolved"
    assert res["acknowledged"] is True
    assert res["runner_result"]["new_evidence"] == 1
    assert not _is_open(lg, a.id)              # acked as the natural consequence
    assert len(lg.list_evidence(qid)) == 1     # the reading really landed


def test_empty_fetch_does_not_ack(tmp_path):
    lg = _ledger(tmp_path)
    qid = _question(lg)
    a = _alert(lg, qid, reason="no_forecast_snapshot")

    runners = ResolutionRunners(evidence_runner=lambda led, w: gated_evidence_collection(
        led, w, evidence_search=_dedupe_search([])
    ))
    res = resolve_alert(lg, a, runners=runners)

    assert res["status"] == "failed"           # no real gated work → left OPEN
    assert res["acknowledged"] is False
    assert _is_open(lg, a.id)
    assert len(lg.list_evidence(qid)) == 0


def test_dup_only_fetch_does_not_ack(tmp_path):
    """The load-bearing rule: a fetch that finds ONLY a reading already on file
    imports zero NEW rows, so the alert must stay OPEN (never a bare ack)."""
    lg = _ledger(tmp_path)
    qid = _question(lg)
    # Pre-seed the exact reading the search will re-fetch.
    lg.add_evidence(question_id=qid, archive_url_snapshot=False, **_READING)
    a = _alert(lg, qid, reason="no_evidence")

    before = len(lg.list_evidence(qid))
    runners = ResolutionRunners(evidence_runner=lambda led, w: gated_evidence_collection(
        led, w, evidence_search=_dedupe_search([_READING])
    ))
    res = resolve_alert(lg, a, runners=runners)

    assert res["status"] == "failed"
    assert res["acknowledged"] is False
    assert _is_open(lg, a.id)
    assert len(lg.list_evidence(qid)) == before  # dedupe imported nothing new


def test_failing_search_does_not_ack(tmp_path):
    lg = _ledger(tmp_path)
    qid = _question(lg)
    a = _alert(lg, qid, reason="no_evidence")

    def boom(_led, _w):
        raise RuntimeError("model/network unavailable")

    runners = ResolutionRunners(evidence_runner=lambda led, w: gated_evidence_collection(
        led, w, evidence_search=boom
    ))
    res = resolve_alert(lg, a, runners=runners)

    assert res["status"] == "failed"
    assert res["acknowledged"] is False
    assert _is_open(lg, a.id)


def test_partial_import_that_landed_a_row_counts_as_success(tmp_path):
    """A multi-source research pass can land >= 1 NEW evidence row and THEN raise
    (mid-stream model/network drop). The gated work is the row that actually landed,
    so the alert must resolve cleanly — re-surfacing it would just re-research
    evidence we already hold. Only a raise that landed NOTHING stays OPEN."""
    lg = _ledger(tmp_path)
    qid = _question(lg)
    a = _alert(lg, qid, reason="no_evidence")

    def import_then_boom(led, warning):
        # Import a genuine NEW reading through the gated path, THEN fail.
        led.add_evidence(question_id=warning.scope_ref, archive_url_snapshot=False, **_READING)
        raise RuntimeError("model/network dropped after the row landed")

    runners = ResolutionRunners(evidence_runner=lambda led, w: gated_evidence_collection(
        led, w, evidence_search=import_then_boom
    ))
    res = resolve_alert(lg, a, runners=runners)

    assert res["status"] == "resolved"                 # the real gated work happened
    assert res["acknowledged"] is True
    assert res["runner_result"]["new_evidence"] == 1
    assert res["runner_result"]["partial_import"] is True
    assert not _is_open(lg, a.id)                       # acked, not left OPEN on the raise
    assert len(lg.list_evidence(qid)) == 1             # the reading really landed


# ---------------------------------------------------------------------------
# Wiring — the runner is opt-in (AGENT tier), only present when a search is injected
# ---------------------------------------------------------------------------

def test_evidence_runner_unwired_without_a_search(tmp_path):
    lg = _ledger(tmp_path)
    runners = build_warning_runners(lg)
    assert runners.evidence_runner is None
    # …but present once an evidence_search is injected (the --agent / paid tier).
    wired = build_warning_runners(lg, evidence_search=_dedupe_search([_READING]))
    assert wired.evidence_runner is not None


def test_unwired_evidence_collection_alert_is_skipped_not_bare_acked(tmp_path):
    lg = _ledger(tmp_path)
    qid = _question(lg)
    a = _alert(lg, qid, reason="no_evidence")

    res = resolve_alert(lg, a, runners=ResolutionRunners())  # no evidence_runner
    assert res["status"] == "skipped"
    assert res["acknowledged"] is False
    assert _is_open(lg, a.id)


def test_select_open_warnings_agent_tier_includes_evidence_collection(tmp_path):
    lg = _ledger(tmp_path)
    qid = _question(lg)
    _alert(lg, qid, reason="no_evidence")
    _alert(lg, qid, reason="evidence_stale_7d_plus")

    got = select_open_warnings(lg, tier="reforecast")
    kinds = {w.kind for w in got}
    assert kinds == {ResolutionKind.EVIDENCE_COLLECTION, ResolutionKind.REFORECAST}
