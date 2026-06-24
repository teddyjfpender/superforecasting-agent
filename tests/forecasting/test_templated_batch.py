"""The templated-batch detector flags clusters of recent LIVE forecasts that share an
identical structural skeleton (same method + reasoning_methods + name-stripped
rationale tail) — the 'one template x N' tell of a script substituting a name into a
fixed shell, rather than N individually-reasoned forecasts. Read-only, heuristic,
never a block."""

from __future__ import annotations

from forecasting import ForecastLedger


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "tb.db"))
    lg.initialize_schema()
    return lg


def _components():
    return {"components": [
        {"name": "base_rate", "probability": 0.4, "weight": 2},
        {"name": "mkt", "source": "manifold:x", "probability": 0.6, "weight": 3},
    ]}


def _q(lg, title):
    q = lg.create_question(title=title, resolution_criteria="Resolves yes if it exceeds target; otherwise no.")
    lg.add_evidence(question_id=q.id, source_or_note="report", claim="reading")
    lg.add_reference_class(question_id=q.id, name="rc", inclusion_criteria="comparable", base_rate=0.5)
    return q


def _commit(lg, q, rationale, *, method, methods):
    return lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale=rationale, method=method,
        reasoning_methods=methods, ensemble_components=_components(),
        reasons_up=["a"], reasons_down=["b"], change_my_mind=["c"], require_panel=False,
    )


def test_templated_batch_is_flagged(tmp_path):
    lg = _ledger(tmp_path)
    # one template, three names substituted in -> identical skeleton + method + methods
    for name in ("Alice", "Bob", "Carol"):
        q = _q(lg, f"Will {name} win the contested primary?")
        _commit(
            lg, q,
            f"Outlook for the race. {name} leads on fundamentals and polling, and the "
            "outside view and base rate both support the committed share.",
            method="bulk_primary_template", methods=["outside_view", "base_rate"],
        )
    batches = lg.detect_templated_batches(window_days=2, min_cluster=3)
    assert len(batches) == 1
    assert batches[0]["count"] == 3
    assert batches[0]["method"] == "bulk_primary_template"


def test_distinct_rationales_not_flagged_even_with_shared_method(tmp_path):
    # SAME method + reasoning_methods, DISTINCT rationales -> isolates that the
    # rationale skeleton alone must keep genuinely-different forecasts apart.
    lg = _ledger(tmp_path)
    rationales = [
        "manufacturing orders softened and the yield curve steepened into the print here",
        "approval recovered while the turnout models point to a genuinely tight finish now",
        "reserve builds and the signaling dominate the near term balance for this contract",
    ]
    for i, text in enumerate(rationales):
        q = _q(lg, f"Distinct question number {i} about the world?")
        _commit(lg, q, text, method="shared_method", methods=["outside_view", "base_rate"])
    assert lg.detect_templated_batches(window_days=2, min_cluster=3) == []


def test_below_min_cluster_not_flagged(tmp_path):
    lg = _ledger(tmp_path)
    for name in ("Alice", "Bob"):  # only 2 < min_cluster 3
        q = _q(lg, f"Will {name} win the contested primary?")
        _commit(lg, q, f"Outlook for the race. {name} leads on fundamentals and the base rate supports it.",
                method="bulk_primary_template", methods=["outside_view", "base_rate"])
    assert lg.detect_templated_batches(window_days=2, min_cluster=3) == []


def test_malformed_metadata_or_timestamp_never_crashes(tmp_path):
    # A script can write arbitrary metadata / created_at (the scenario the detector
    # polices). The read-only detector must degrade, never raise.
    import sqlite3
    lg = _ledger(tmp_path)
    q = _q(lg, "Will the metric exceed target by the close date as reported?")
    s = _commit(lg, q, "outlook for the race leads on fundamentals and the base rate supports it",
                method="m", methods=["outside_view"])
    con = sqlite3.connect(str(tmp_path / "tb.db"))
    con.execute("UPDATE forecast_snapshots SET metadata='[1,2,3]', created_at='not-a-timestamp' WHERE forecast_id=?", (s.forecast_id,))
    con.commit(); con.close()
    assert lg.detect_templated_batches(window_days=30) == []  # no AttributeError/ValueError/TypeError


def test_tool_action_surfaces_the_batch(tmp_path):
    import json
    from tools.forecasting_tool import forecast_ledger_tool
    lg = _ledger(tmp_path)
    for name in ("Alice", "Bob", "Carol"):
        q = _q(lg, f"Will {name} win the contested primary?")
        _commit(lg, q, f"Outlook for the race. {name} leads on fundamentals and polling and the "
                "outside view and base rate both support the committed share.",
                method="bulk_primary_template", methods=["outside_view", "base_rate"])
    r = json.loads(forecast_ledger_tool({"action": "detect_templated_batches", "db": str(tmp_path / "tb.db"), "window_days": 2, "min_cluster": 3}))
    assert r["success"] is True
    assert r["templated_batches"][0]["count"] == 3
