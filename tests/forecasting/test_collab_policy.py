"""The COLLAB share/accept governed classes + counterparty allowlist (M3, pillar 5).

The allowlist is the FIRST gate and it is closed by default; only an authorised
counterparty reaches the auto|ask|never cell. Defaults per the plan: share/accept
evidence auto, forecast auto, lesson ask; document ask.
"""

from __future__ import annotations

import pytest

from forecasting.jobs.policy import (
    COLLAB_DEFAULTS,
    CollabPolicyRefused,
    Decision,
    ShareClass,
    ShareDirection,
    collab_config_key,
    resolve_collab_action,
    resolve_collab_decision,
    resolve_collab_policy,
    share_class_for_kind,
)

ALLOW = {"inst-ada"}


def test_defaults_match_the_plan():
    for direction in (ShareDirection.SHARE, ShareDirection.ACCEPT):
        cells = COLLAB_DEFAULTS[direction]
        assert cells[ShareClass.EVIDENCE] is Decision.AUTO
        assert cells[ShareClass.FORECAST] is Decision.AUTO
        assert cells[ShareClass.LESSON] is Decision.ASK
        assert cells[ShareClass.DOCUMENT] is Decision.ASK


def test_accept_mirrors_share():
    assert COLLAB_DEFAULTS[ShareDirection.ACCEPT] == COLLAB_DEFAULTS[ShareDirection.SHARE]


def test_kind_to_class_mapping():
    assert share_class_for_kind("forecast.card") is ShareClass.FORECAST
    assert share_class_for_kind("evidence.share") is ShareClass.EVIDENCE
    assert share_class_for_kind("lesson.share") is ShareClass.LESSON
    assert share_class_for_kind("ack") is None
    assert share_class_for_kind("thesis.round") is None


def test_allowlisted_counterparty_gets_the_cell_decision():
    assert resolve_collab_action(
        ShareDirection.ACCEPT, ShareClass.EVIDENCE,
        counterparty_instance_id="inst-ada", allowlist=ALLOW,
    ) is Decision.AUTO
    assert resolve_collab_action(
        ShareDirection.ACCEPT, ShareClass.LESSON,
        counterparty_instance_id="inst-ada", allowlist=ALLOW,
    ) is Decision.ASK


def test_non_allowlisted_is_refused_with_a_teaching_error():
    with pytest.raises(CollabPolicyRefused) as exc:
        resolve_collab_action(
            ShareDirection.ACCEPT, ShareClass.FORECAST,
            counterparty_instance_id="inst-mallory", allowlist=ALLOW,
        )
    # The error NAMES the knob to authorise it.
    assert "COLLAB_ALLOWED_INSTANCES" in str(exc.value)
    assert "inst-mallory" in str(exc.value)


def test_empty_allowlist_accepts_no_one():
    with pytest.raises(CollabPolicyRefused):
        resolve_collab_action(
            ShareDirection.ACCEPT, ShareClass.EVIDENCE,
            counterparty_instance_id="inst-ada", allowlist=set(),
        )


def test_missing_instance_id_is_refused():
    with pytest.raises(CollabPolicyRefused):
        resolve_collab_action(
            ShareDirection.ACCEPT, ShareClass.EVIDENCE,
            counterparty_instance_id="", allowlist=ALLOW,
        )


def test_config_overlay_tightens_a_cell(monkeypatch):
    key = collab_config_key(ShareDirection.ACCEPT, ShareClass.EVIDENCE)
    assert key == "FORECAST_POLICY_ACCEPT_EVIDENCE"
    monkeypatch.setenv(key, "never")
    assert resolve_collab_decision(ShareDirection.ACCEPT, ShareClass.EVIDENCE) is Decision.NEVER
    # And an allowlisted counterparty now hits the never cell (still authorised, but refused-by-cell).
    assert resolve_collab_action(
        ShareDirection.ACCEPT, ShareClass.EVIDENCE,
        counterparty_instance_id="inst-ada", allowlist=ALLOW,
    ) is Decision.NEVER


def test_config_overlay_can_loosen_lesson_to_auto(monkeypatch):
    monkeypatch.setenv("FORECAST_POLICY_ACCEPT_LESSON", "auto")
    assert resolve_collab_decision(ShareDirection.ACCEPT, ShareClass.LESSON) is Decision.AUTO


def test_bad_override_falls_safe_to_default(monkeypatch):
    monkeypatch.setenv("FORECAST_POLICY_ACCEPT_LESSON", "banana")
    assert resolve_collab_decision(ShareDirection.ACCEPT, ShareClass.LESSON) is Decision.ASK


def test_resolve_collab_policy_snapshot():
    snap = resolve_collab_policy(ShareDirection.ACCEPT)
    assert snap["direction"] == "accept"
    assert snap["decisions"]["forecast"] == "auto"
    assert snap["decisions"]["lesson"] == "ask"
