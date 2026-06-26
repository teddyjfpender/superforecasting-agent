from __future__ import annotations

import json

import pytest

from forecasting import ForecastLedger
from forecasting.cli import main as forecast_main
from forecasting.dashboard import build_workspace_payload
from forecasting.models import LedgerNotFoundError, ValidationError
from forecasting.protocol import build_context_packet

CRITERIA = "Resolves to the official value reported by the named source on the close date."


def _q(ledger: ForecastLedger, title: str, topics: list[str], domain: str = "macro"):
    return ledger.create_question(
        title=title, resolution_criteria=CRITERIA, domain=domain, topics=topics,
        close_time="2026-07-01T00:00:00Z",
    )


def test_add_link_normalizes_symmetric_and_is_idempotent(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    a = _q(ledger, "CPI YoY?", ["inflation", "cpi"])
    b = _q(ledger, "CPI MoM?", ["inflation", "cpi"])
    lo, hi = sorted([a.id, b.id])
    link = ledger.add_forecast_link(b.id, a.id, link_type="related")
    assert link["from_question_id"] == lo and link["to_question_id"] == hi
    # Either ordering returns the same row (idempotent).
    assert ledger.add_forecast_link(a.id, b.id, link_type="related")["id"] == link["id"]
    assert len(ledger.list_forecast_links(a.id)) == 1


def test_link_validation(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    a = _q(ledger, "A?", ["x"])
    b = _q(ledger, "B?", ["x"])
    with pytest.raises(ValidationError):
        ledger.add_forecast_link(a.id, a.id)  # self-link
    with pytest.raises(ValidationError):
        ledger.add_forecast_link(a.id, b.id, link_type="bogus")
    with pytest.raises(LedgerNotFoundError):
        ledger.add_forecast_link(a.id, "fq_missing")


def test_component_of_direction_is_bidirectional(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    parent = _q(ledger, "House control?", ["midterms"], domain="politics")
    child = _q(ledger, "Seat AZ-01?", ["midterms", "arizona"], domain="politics")
    ledger.add_forecast_link(child.id, parent.id, link_type="component_of")  # from=child, to=parent
    child_rel, _ = ledger.related_forecast_views(child.id)
    assert any(r["id"] == parent.id and r["relationship"] == "parent" for r in child_rel)
    parent_rel, _ = ledger.related_forecast_views(parent.id)
    assert any(r["id"] == child.id and r["relationship"] == "child" for r in parent_rel)


def test_remove_link_by_pair_either_ordering(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    a = _q(ledger, "A?", ["x"])
    b = _q(ledger, "B?", ["x"])
    ledger.add_forecast_link(a.id, b.id, link_type="related")
    assert ledger.remove_forecast_link(b.id, a.id) == 1
    assert ledger.list_forecast_links(a.id) == []


def test_cascade_on_question_delete(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    a = _q(ledger, "A?", ["x"])
    b = _q(ledger, "B?", ["x"])
    ledger.add_forecast_link(a.id, b.id, link_type="related")
    # No public delete path; verify the ON DELETE CASCADE DDL via a raw delete
    # (foreign_keys=ON is set inside _connect()).
    with ledger._connect() as conn:
        conn.execute("DELETE FROM forecast_questions WHERE id = ?", (a.id,))
    assert ledger.list_forecast_links(b.id) == []


def test_related_views_union_explicit_and_auto_with_worldviews(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    a = _q(ledger, "CPI YoY?", ["inflation", "cpi"])
    b = _q(ledger, "CPI MoM?", ["inflation", "cpi", "energy"])
    c = _q(ledger, "Unrelated GDP?", ["gdp"])
    ledger.create_snapshot(question_id=a.id, probability_or_distribution=0.61, rationale="r",
                           reasons_up=["fundamentals"], reasons_down=["energy"])
    ledger.add_analyst_note(question_id=a.id, body="x", headline="tracking ~4.2", be_aware="energy risk", stance="lean_no")
    # b auto-relates to a (shared domain+topics); c does not (low overlap).
    related, _ = ledger.related_forecast_views(b.id)
    ids = {r["id"] for r in related}
    assert a.id in ids and c.id not in ids
    rel_a = next(r for r in related if r["id"] == a.id)
    assert rel_a["link_type"] == "auto"
    assert rel_a["probability_or_distribution"] == 0.61
    assert rel_a["headline"] == "tracking ~4.2"
    assert rel_a["reasons_up"] == ["fundamentals"]


def test_shared_sources_and_cross_refs(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    a = _q(ledger, "CPI YoY?", ["inflation", "cpi"])
    b = _q(ledger, "CPI MoM?", ["inflation", "cpi"])
    ledger.add_watched_source(scope_type="question", scope_ref=a.id, source="GASREGW", source_type="fred")
    ledger.add_watched_source(scope_type="question", scope_ref=b.id, source="GASREGW", source_type="fred")
    ledger.add_watched_source(scope_type="question", scope_ref=b.id, source="DCOILWTICO", source_type="fred")
    shared = ledger.shared_sources(a.id, b.id)
    assert [s["signature"] for s in shared] == ["fred:gasregw"]
    refs = ledger.build_cross_refs(b.id)
    assert a.id in refs["informed_by"]
    assert any(s["source"] == "fred:gasregw" for s in refs["shared_sources"])
    assert refs["advisory_only"] is False


def test_context_packet_renders_related_block(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    a = _q(ledger, "CPI YoY?", ["inflation", "cpi"])
    b = _q(ledger, "CPI MoM?", ["inflation", "cpi"])
    ledger.create_snapshot(question_id=a.id, probability_or_distribution=0.61, rationale="r")
    ledger.add_analyst_note(question_id=a.id, body="x", headline="tracking ~4.2", be_aware="energy")
    ledger.add_watched_source(scope_type="question", scope_ref=a.id, source="GASREGW", source_type="fred")
    ledger.add_watched_source(scope_type="question", scope_ref=b.id, source="GASREGW", source_type="fred")
    packet = build_context_packet(ledger, ledger.get_question(b.id), None)
    assert "## Related Forecasts" in packet
    assert "tracking ~4.2" in packet
    assert "independence note" in packet
    assert "fred:gasregw" in packet
    # A lone question with no relatives renders the "none" fallback.
    lonely = _q(ledger, "Lonely?", ["solo"], domain="other")
    assert "## Related Forecasts\nnone" in build_context_packet(ledger, lonely, None)


def test_links_round_trip_export_import(tmp_path):
    src = ForecastLedger(tmp_path / "src.db")
    a = _q(src, "CPI YoY?", ["inflation", "cpi"])
    b = _q(src, "CPI MoM?", ["inflation", "cpi"])
    src.add_forecast_link(a.id, b.id, link_type="related", rationale="both CPI")
    # Export both endpoints into one bundle, import to a fresh ledger.
    target = ForecastLedger(tmp_path / "tgt.db")
    target.import_packet(json.loads(src.export_question(a.id, fmt="json")))
    target.import_packet(json.loads(src.export_question(b.id, fmt="json")))
    assert len(target.list_forecast_links(a.id)) == 1


def test_dangling_link_endpoint_is_skipped_not_crashed(tmp_path):
    src = ForecastLedger(tmp_path / "src.db")
    a = _q(src, "A?", ["x"])
    b = _q(src, "B?", ["x"])
    src.add_forecast_link(a.id, b.id, link_type="related")
    # Import only A's packet (whose forecast_links references B, which is absent).
    target = ForecastLedger(tmp_path / "tgt.db")
    target.import_packet(json.loads(src.export_question(a.id, fmt="json")))  # must not raise
    assert target.list_forecast_links(a.id) == []  # dangling edge skipped


def test_workspace_payload_exposes_related(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    a = _q(ledger, "CPI YoY?", ["inflation", "cpi"])
    b = _q(ledger, "CPI MoM?", ["inflation", "cpi"])
    ledger.create_snapshot(question_id=a.id, probability_or_distribution=0.61, rationale="r")
    ledger.create_snapshot(
        question_id=b.id, probability_or_distribution=0.36, rationale="r2",
        metadata={"cross_refs": ledger.build_cross_refs(b.id)},
    )
    bp = next(f for f in build_workspace_payload(ledger=ledger)["forecasts"] if f["id"] == b.id)
    assert bp["related"] is not None
    assert a.id in bp["related"]["informed_by"]
    rel = bp["related"]["forecasts"][0]
    assert rel["id"] == a.id and rel["probability_display"] == "61%"


def test_workspace_payload_gates_related_and_lessons_for_speed(tmp_path):
    # The navigable LIST gates the expensive per-question related/lessons walks
    # (the detail RPC carries them instead); default keeps them for other callers.
    ledger = ForecastLedger(tmp_path / "f.db")
    a = _q(ledger, "CPI YoY?", ["inflation", "cpi"])
    b = _q(ledger, "CPI MoM?", ["inflation", "cpi"])
    ledger.create_snapshot(question_id=a.id, probability_or_distribution=0.61, rationale="r")
    ledger.create_snapshot(
        question_id=b.id, probability_or_distribution=0.36, rationale="r2",
        metadata={"cross_refs": ledger.build_cross_refs(b.id)},
    )
    gated = build_workspace_payload(ledger=ledger, include_related=False, include_lessons=False)
    bp = next(f for f in gated["forecasts"] if f["id"] == b.id)
    assert bp["related"] is None
    assert bp["relevant_lessons"] == [] and bp["lessons_count"] == 0


def test_cli_link_commands(tmp_path, capsys):
    db = str(tmp_path / "f.db")
    ledger = ForecastLedger(db)
    a = _q(ledger, "CPI YoY?", ["inflation", "cpi"])
    b = _q(ledger, "CPI MoM?", ["inflation", "cpi"])
    # --db is a forecast-level flag, so it precedes the subcommand.
    forecast_main(["--db", db, "link", "add", a.id, b.id, "--rationale", "both CPI"])
    out = capsys.readouterr().out
    assert "forecast link fl_" in out and "type: related" in out
    forecast_main(["--db", db, "links", a.id])
    assert "CPI MoM?" in capsys.readouterr().out
    forecast_main(["--db", db, "unlink", a.id, b.id])
    assert "removed 1 link" in capsys.readouterr().out
