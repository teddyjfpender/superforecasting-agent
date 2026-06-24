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


def test_distinct_forecasts_are_not_flagged(tmp_path):
    lg = _ledger(tmp_path)
    rationales = [
        "Manufacturing orders softened and the yield curve steepened into the print.",
        "The incumbent's approval recovered while turnout models point to a tight finish.",
        "Reserve builds and OPEC signaling dominate the near-term balance for this contract.",
    ]
    for i, text in enumerate(rationales):
        q = _q(lg, f"Distinct question number {i} about the world?")
        _commit(lg, q, text, method=f"bespoke_method_{i}", methods=["outside_view"])
    batches = lg.detect_templated_batches(window_days=2, min_cluster=3)
    assert batches == []


def test_below_min_cluster_not_flagged(tmp_path):
    lg = _ledger(tmp_path)
    for name in ("Alice", "Bob"):  # only 2 < min_cluster 3
        q = _q(lg, f"Will {name} win the contested primary?")
        _commit(lg, q, f"Outlook for the race. {name} leads on fundamentals and the base rate supports it.",
                method="bulk_primary_template", methods=["outside_view", "base_rate"])
    assert lg.detect_templated_batches(window_days=2, min_cluster=3) == []
