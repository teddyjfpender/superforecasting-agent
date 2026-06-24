"""The freshness escape hatch must be explained. `acknowledge_stale_evidence` lets a
live re-run skip the fresh-evidence gate; on its own that's a silent bypass (the agent
scripts abused it). Now: acknowledging stale evidence WITHOUT a `stale_evidence_reason`
raises the `stale_evidence_justified` WARN (visible on the saturation report, never
blocking); WITH a reason it commits clean and the reason is recorded."""

from __future__ import annotations

from forecasting import ForecastLedger


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "stale.db"))
    lg.initialize_schema()
    return lg


def _q(lg):
    q = lg.create_question(
        title="Will the indicator exceed target by close?",
        resolution_criteria="Resolves yes if the indicator exceeds target by close; otherwise no.",
    )
    lg.add_evidence(question_id=q.id, source_or_note="quarterly report", claim="indicator rose")
    lg.add_reference_class(question_id=q.id, name="historical moves", inclusion_criteria="comparable regimes", base_rate=0.5)
    return q


def _components():
    return {"components": [
        {"name": "base_rate", "probability": 0.4, "weight": 2},
        {"name": "mkt", "source": "manifold:x", "probability": 0.6, "weight": 3},
    ]}


def _commit(lg, q, prob, **kw):
    return lg.create_snapshot(
        question_id=q.id, probability_or_distribution=prob, rationale="indicator rose this quarter",
        method="m", ensemble_components=_components(), reasons_up=["a"], reasons_down=["b"],
        change_my_mind=["c"], require_panel=False, **kw,
    )


def _verdict(snapshot, rule_id: str):
    sat = (snapshot.metadata or {}).get("saturation") or {}
    for v in sat.get("verdicts", []):
        if v.get("rule_id") == rule_id:
            return v.get("passed")
    return None


def test_ack_stale_without_reason_warns_but_commits(tmp_path):
    lg = _ledger(tmp_path)
    q = _q(lg)
    _commit(lg, q, 0.5)  # first forecast -> establishes a prior
    # re-run, acknowledge stale evidence, NO reason (panel skip recorded so the
    # re-commit panel rule is satisfied — isolates the stale-evidence behavior)
    snap = _commit(lg, q, 0.55, acknowledge_stale_evidence=True, panel_skipped_reason="test re-commit")
    assert snap is not None  # WARN, not a block
    assert _verdict(snap, "stale_evidence_justified") is False  # fired
    assert "stale_evidence_reason" not in (snap.metadata or {})
    assert (snap.metadata or {}).get("acknowledge_stale_evidence") is True


def test_ack_stale_with_reason_is_clean_and_recorded(tmp_path):
    lg = _ledger(tmp_path)
    q = _q(lg)
    _commit(lg, q, 0.5)
    reason = "Re-checked all drivers; nothing material changed since the prior forecast."
    snap = _commit(lg, q, 0.55, acknowledge_stale_evidence=True, stale_evidence_reason=reason,
                   panel_skipped_reason="test re-commit")
    assert snap is not None
    assert _verdict(snap, "stale_evidence_justified") is not False  # did not fire
    assert (snap.metadata or {}).get("stale_evidence_reason") == reason


def test_fresh_rerun_never_triggers_the_warn(tmp_path):
    # No acknowledgement at all -> the rule does not apply.
    lg = _ledger(tmp_path)
    q = _q(lg)
    _commit(lg, q, 0.5)
    lg.add_evidence(question_id=q.id, source_or_note="fresh update", claim="new reading")
    snap = _commit(lg, q, 0.55, panel_skipped_reason="test re-commit")
    assert _verdict(snap, "stale_evidence_justified") is None


def test_lint_reread_surfaces_unjustified_stale_ack(tmp_path):
    # The WARN must also show on a later read-only re-read (build_context_from_ledger
    # reconstructs the signal from the stored acknowledge marker + absent reason).
    from forecasting.hooks.sweep import lint_forecast
    lg = _ledger(tmp_path)
    q = _q(lg)
    _commit(lg, q, 0.5)
    _commit(lg, q, 0.55, acknowledge_stale_evidence=True, panel_skipped_reason="test re-commit")
    report = lint_forecast(lg, q.id)
    verdicts = {v.get("rule_id"): v.get("passed") for v in (report.to_dict().get("verdicts") or [])}
    assert verdicts.get("stale_evidence_justified") is False  # fires on re-read too


def test_lint_reread_clean_when_reason_recorded(tmp_path):
    from forecasting.hooks.sweep import lint_forecast
    lg = _ledger(tmp_path)
    q = _q(lg)
    _commit(lg, q, 0.5)
    _commit(lg, q, 0.55, acknowledge_stale_evidence=True, stale_evidence_reason="nothing changed",
            panel_skipped_reason="test re-commit")
    report = lint_forecast(lg, q.id)
    verdicts = {v.get("rule_id"): v.get("passed") for v in (report.to_dict().get("verdicts") or [])}
    assert verdicts.get("stale_evidence_justified") is not False
