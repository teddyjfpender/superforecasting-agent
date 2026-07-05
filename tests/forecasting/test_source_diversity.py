"""Source-diversity metrics — the monoculture guard (per-question + ledger-level)."""

from __future__ import annotations

from forecasting.ledger import ForecastLedger
from forecasting.ledger.evidence import _source_domain
from forecasting.models import OutcomeSpace


def _binary(ledger, title):
    return ledger.create_question(
        title=title,
        resolution_criteria="Resolved yes if the event occurs before the stated deadline.",
        outcome_space=OutcomeSpace(type="binary"),
    )


def _ev(ledger, qid, note=None, **kw):
    return ledger.add_evidence(question_id=qid, source_or_note=(note or ""), **kw)


def test_source_domain_strips_www():
    assert _source_domain("https://www.reuters.com/world/foo") == "reuters.com"
    assert _source_domain("http://fred.stlouisfed.org/x") == "fred.stlouisfed.org"
    assert _source_domain("not a url") is None
    assert _source_domain(None) is None


def test_question_diversity_counts_distinct_sources_and_types(tmp_path):
    ledger = ForecastLedger(tmp_path / "d.db")
    q = _binary(ledger, "Will the diverse-source question count its sources correctly?")
    _ev(ledger, q.id, "note one", source_name="Reuters", source_type="news")
    _ev(ledger, q.id, "note two", source_name="Bloomberg", source_type="news")
    _ev(ledger, q.id, "note three", source_name="FRED", source_type="adapter:fred")
    div = ledger.question_source_diversity(q.id)
    assert div["evidence_count"] == 3
    assert div["distinct_sources"] == 3
    assert div["distinct_source_types"] == 2  # news, adapter:fred
    assert div["single_source"] is False


def test_question_diversity_flags_single_source(tmp_path):
    ledger = ForecastLedger(tmp_path / "d.db")
    q = _binary(ledger, "Will the single-source question be flagged as monoculture?")
    _ev(ledger, q.id, "a", source_name="FRED", source_type="adapter:fred")
    _ev(ledger, q.id, "b", source_name="FRED", source_type="adapter:fred")
    div = ledger.question_source_diversity(q.id)
    assert div["evidence_count"] == 2
    assert div["distinct_sources"] == 1
    assert div["single_source"] is True


def test_question_diversity_uses_url_domain_when_name_missing(tmp_path):
    ledger = ForecastLedger(tmp_path / "d.db")
    q = _binary(ledger, "Will the URL-only evidence dedupe by its domain host?")
    _ev(ledger, q.id, source_url="https://www.reuters.com/a", claim="x", summary="y")
    _ev(ledger, q.id, source_url="https://reuters.com/b", claim="x", summary="y")
    div = ledger.question_source_diversity(q.id)
    # Same host → one distinct source.
    assert div["distinct_sources"] == 1
    assert div["single_source"] is True


def test_ledger_monoculture_summary(tmp_path):
    ledger = ForecastLedger(tmp_path / "d.db")
    mono = _binary(ledger, "Will the monoculture question drag the median toward one?")
    _ev(ledger, mono.id, "a", source_name="FRED", source_type="adapter:fred")
    _ev(ledger, mono.id, "b", source_name="FRED", source_type="adapter:fred")
    diverse = _binary(ledger, "Will the diverse question lift the mean above one source?")
    _ev(ledger, diverse.id, "a", source_name="Reuters", source_type="news")
    _ev(ledger, diverse.id, "b", source_name="Bloomberg", source_type="news")
    _ev(ledger, diverse.id, "c", source_name="AP", source_type="news")
    # A question with NO evidence is excluded from the summary entirely.
    _binary(ledger, "Will the evidence-free question be excluded from the summary?")

    summary = ledger.source_diversity_summary()
    assert summary["questions_with_evidence"] == 2
    assert summary["median_sources_per_question"] == 2.0  # median of {1, 3}
    assert summary["single_source_question_count"] == 1
    assert summary["single_source_pct"] == 0.5


def test_ledger_monoculture_summary_empty(tmp_path):
    ledger = ForecastLedger(tmp_path / "d.db")
    summary = ledger.source_diversity_summary()
    assert summary["questions_with_evidence"] == 0
    assert summary["median_sources_per_question"] is None
    assert summary["single_source_pct"] is None


def test_readiness_payload_carries_source_diversity(tmp_path):
    ledger = ForecastLedger(tmp_path / "d.db")
    q = _binary(ledger, "Will the readiness payload surface per-question source diversity?")
    _ev(ledger, q.id, "a", source_name="Reuters", source_type="news")
    payload = ledger.build_question_readiness(q.id) if hasattr(ledger, "build_question_readiness") else None
    if payload is None:
        from forecasting.readiness_lens import build_question_readiness

        payload = build_question_readiness(ledger, q.id)
    assert payload["source_diversity"]["distinct_sources"] == 1
