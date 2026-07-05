"""Crux promotion (audit finding #4): the free-text ``crux`` each panelist names is
lifted into the first-class, queryable ``question_cruxes`` table on panel record —
deduped by text-hash, never clobbering an operator's hand-set status — plus a
dry-run-default backfill for the cruxes already trapped inside historical panels."""

from __future__ import annotations

from forecasting import ForecastLedger


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "crux.db"))
    lg.initialize_schema()
    return lg


def _question(lg, **over):
    defaults = dict(
        title="Will the metric exceed target by close?",
        resolution_criteria="Resolves yes if the metric exceeds target by close; otherwise no.",
    )
    defaults.update(over)
    return lg.create_question(**defaults)


def _estimates(cruxes):
    perspectives = ["outside", "inside", "market", "red_team", "sanity"]
    out = []
    for i, persp in enumerate(perspectives):
        crux = cruxes[i] if i < len(cruxes) else None
        out.append({"perspective": persp, "probability": 0.5, "rationale": "r", "crux": crux})
    return out


# ── promotion on new panels ───────────────────────────────────────────────────
def test_record_panel_run_promotes_distinct_cruxes(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    panel = lg.record_panel_run(
        question_id=q.id,
        estimates=_estimates(["Fed cuts rates", "Turnout surges", "Filing is approved", None, None]),
    )
    cruxes = lg.list_cruxes(q.id)
    variables = sorted(c["crux_variable"] for c in cruxes)
    assert variables == ["Fed cuts rates", "Filing is approved", "Turnout surges"]
    # Each promoted crux is LINKED to the originating panel run via notes.
    assert all(c["notes"] == f"promoted from panel {panel['id']}" for c in cruxes)


def test_empty_cruxes_promote_nothing(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    lg.record_panel_run(question_id=q.id, estimates=_estimates([None, "", "   ", None, None]))
    assert lg.list_cruxes(q.id) == []


# ── dedupe by text-hash ───────────────────────────────────────────────────────
def test_promotion_dedupes_within_panel_by_text_hash(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    # Same uncertainty, different casing / trailing punctuation across panelists.
    lg.record_panel_run(
        question_id=q.id,
        estimates=_estimates(["The Fed cuts rates.", "the fed cuts rates", "THE FED CUTS RATES!", None, None]),
    )
    cruxes = lg.list_cruxes(q.id)
    assert len(cruxes) == 1  # collapsed to one row


def test_rerun_promotes_nothing_new_and_preserves_operator_status(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    lg.record_panel_run(question_id=q.id, estimates=_estimates(["Fed cuts rates", None, None, None, None]))
    crux_id = lg.list_cruxes(q.id)[0]["id"]
    # Operator confirms the crux's evidence status.
    lg.set_crux_status(crux_id, "current")

    # A second panel names the SAME crux — it must NOT create a duplicate nor reset
    # the operator's status back to the promotion default ("missing").
    lg.record_panel_run(question_id=q.id, estimates=_estimates(["Fed cuts rates", None, None, None, None]))
    cruxes = lg.list_cruxes(q.id)
    assert len(cruxes) == 1
    assert cruxes[0]["status"] == "current"


# ── promote helper: dry-run counting ──────────────────────────────────────────
def test_promote_panel_cruxes_dry_run_counts_without_writing(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    panel = lg.record_panel_run(
        question_id=q.id, estimates=_estimates(["a crux", "b crux", None, None, None])
    )
    # Wipe the auto-promoted rows to simulate a legacy un-promoted panel.
    with lg._connect() as conn:
        conn.execute("DELETE FROM question_cruxes WHERE question_id = ?", (q.id,))
    res = lg.promote_panel_cruxes(
        question_id=q.id, panel_run_id=panel["id"], dry_run=True
    )
    assert res["candidates"] == 2
    assert res["promoted"] == 2
    assert res["skipped_existing"] == 0
    assert lg.list_cruxes(q.id) == []  # dry-run wrote nothing


# ── backfill dry-run default / apply / idempotency ────────────────────────────
def test_backfill_dry_run_default_then_apply(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    panel = lg.record_panel_run(
        question_id=q.id, estimates=_estimates(["c1", "c2", "c3", None, None])
    )
    # Simulate the historical "trapped in the panel blob" state (finding #4: 271
    # panel cruxes, 0 question_cruxes rows).
    with lg._connect() as conn:
        conn.execute("DELETE FROM question_cruxes WHERE question_id = ?", (q.id,))

    dry = lg.backfill_panel_cruxes()  # dry_run defaults True
    assert dry["dry_run"] is True
    assert dry["promoted"] == 3
    assert dry["panels_with_cruxes"] == 1
    assert lg.list_cruxes(q.id) == []  # nothing written

    applied = lg.backfill_panel_cruxes(dry_run=False)
    assert applied["promoted"] == 3
    assert {c["crux_variable"] for c in lg.list_cruxes(q.id)} == {"c1", "c2", "c3"}

    # Idempotent: a second apply promotes nothing new.
    again = lg.backfill_panel_cruxes(dry_run=False)
    assert again["promoted"] == 0
    assert again["skipped_existing"] == 3
    _ = panel


# ── stats surface (doctor/readiness) ──────────────────────────────────────────
def test_crux_promotion_stats(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    lg.record_panel_run(question_id=q.id, estimates=_estimates(["s1", "s2", None, None, None]))
    stats = lg.crux_promotion_stats()
    assert stats["promoted_total"] == 2
    assert stats["promoted_from_panels"] == 2
    assert stats["panel_embedded_distinct"] == 2
    assert stats["unpromoted_panel_cruxes"] == 0  # auto-promotion kept them in sync
