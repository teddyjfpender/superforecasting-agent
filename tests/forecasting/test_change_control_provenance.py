from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl
from forecasting.change_control.trace_archive import (
    capture_trace_archive,
    pin_trace_archive,
    read_trace_archive,
    sweep_expired_traces,
)
from forecasting.change_control.transcripts import (
    MARKER_START,
    render_review_transcript,
    update_marked_section,
)
from forecasting.models import ValidationError


def _control(tmp_path):
    return ChangeControl(ForecastLedger(tmp_path / "forecasting.db"))


def _changeset(control):
    return control.create_changeset(
        workspace_id="desk_1",
        affected_question_ids=["q_policy"],
        metadata={"goal": "Update the policy launch forecast"},
    )


def test_bundle_links_multiple_local_sources_and_decision_records(tmp_path):
    control = _control(tmp_path)
    changeset = _changeset(control)
    first = control.link_session(
        changeset["id"],
        source_type="session_db",
        session_id="session_1",
        scope={"question_ids": ["q_policy"]},
    )
    second = control.link_session(
        changeset["id"],
        source_type="execution_store",
        session_id="session_1",
        run_id="run_1",
        scope={"thread_key": "slack:T:C:1"},
    )
    decision = control.add_decision_record(
        changeset["id"],
        conclusion="The new filing warrants a modest upward update.",
        alternatives=["Hold at the prior estimate"],
        evidence_refs=["ev_1"],
        assumptions=["The filing is authentic"],
        probability_changes=[{"question_id": "q_policy", "before": 0.4, "after": 0.46}],
        unresolved_uncertainty=["Implementation timing"],
        model="test-model",
        tools=["web_search"],
        tests=["preview passed"],
    )
    bundle = control.provenance_bundle(changeset["id"])

    assert first["bundle_id"] == second["bundle_id"] == bundle["id"]
    assert decision["prompt_version"] is None
    assert len(bundle["digest"]) == 64


def test_transcript_is_scoped_redacted_and_marker_update_is_idempotent():
    sessions = {
        "session_1": [
            {"role": "system", "content": "Hidden policy and sk-system-not-publishable-123456"},
            {"role": "user", "content": "Update q_policy using /Users/alice/private/notes.md"},
            {
                "role": "assistant",
                "content": "The policy evidence supports moving the estimate to 46%.",
                "reasoning": "private provider reasoning",
            },
            {"role": "user", "content": "Unrelated request about a dinner reservation."},
            {
                "role": "tool",
                "tool_name": "exec_command",
                "content": "raw output ghp_this_token_is_dropped_before_rendering",
            },
        ]
    }
    rendered = render_review_transcript(
        changeset_id="chg_1",
        goal="Update the policy forecast",
        sessions=sessions,
        branch="forecast/chg_1",
        changed_object_ids=["q_policy"],
    )

    assert rendered.safe is True
    assert "[LOCAL_PATH]" in rendered.markdown
    assert "private provider reasoning" not in rendered.markdown
    assert "ghp_this_token" not in rendered.markdown
    assert "dinner reservation" not in rendered.markdown
    assert rendered.html.startswith("<!doctype html>")
    first = update_marked_section("# Pull request\n", rendered.markdown)
    second = update_marked_section(first, rendered.markdown)
    assert second.count(MARKER_START) == 1


def test_transcript_fails_closed_without_echoing_secret_value():
    secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    rendered = render_review_transcript(
        changeset_id="chg_1",
        goal="policy forecast",
        sessions={"session_1": [{"role": "user", "content": f"Use {secret} for policy"}]},
    )
    assert rendered.safe is False
    assert rendered.markdown == ""
    assert rendered.status == "transcript_unavailable_safety_failure"
    assert rendered.findings == (
        {"class": "github_token", "location": "session:session_1:message:0"},
    )
    assert secret not in json.dumps(rendered.findings)


def test_consent_binds_exact_digest_repository_owner_and_changeset(tmp_path):
    control = _control(tmp_path)
    changeset = _changeset(control)
    control.record_transcript_consent(
        changeset["id"],
        transcript_digest="a" * 64,
        repository_slug="acme/forecasts",
        owner_id="owner_1",
        decision="include",
    )
    assert (
        control.transcript_publication_decision(
            changeset["id"],
            transcript_digest="a" * 64,
            repository_slug="acme/forecasts",
            owner_id="owner_1",
        )
        == "include"
    )
    assert (
        control.transcript_publication_decision(
            changeset["id"],
            transcript_digest="b" * 64,
            repository_slug="acme/forecasts",
            owner_id="owner_1",
        )
        is None
    )


def test_private_trace_is_envelope_encrypted_and_access_audited(tmp_path):
    control = _control(tmp_path)
    changeset = _changeset(control)
    key = base64.urlsafe_b64encode(b"k" * 32).decode()
    trace = {
        "session_messages": [{"role": "assistant", "reasoning": "returned provider trace"}],
        "events": [{"event": "tool.complete", "result": "sensitive result"}],
    }
    record = capture_trace_archive(
        control.ledger,
        changeset["id"],
        trace,
        workspace_key=key,
        object_dir=tmp_path / "private-objects",
        authorization={"roles": ["auditor"]},
    )
    ciphertext = Path(record["object_locator"]).read_text()
    assert "returned provider trace" not in ciphertext
    assert "sensitive result" not in ciphertext
    assert record["retention_deadline"] > record["created_at"]

    with pytest.raises(PermissionError):
        read_trace_archive(
            control.ledger,
            record["id"],
            actor_id="intruder",
            reason="test denied access",
            authorize=lambda _record, _actor: False,
            workspace_key=key,
        )
    restored = read_trace_archive(
        control.ledger,
        record["id"],
        actor_id="auditor_1",
        reason="review disputed forecast",
        authorize=lambda _record, actor: actor == "auditor_1",
        workspace_key=key,
    )
    assert restored == trace
    with control.ledger._connect() as conn:
        actions = [
            row["action"]
            for row in conn.execute(
                "SELECT action FROM provenance_access_events WHERE archive_id = ? ORDER BY occurred_at",
                (record["id"],),
            ).fetchall()
        ]
    assert actions == ["read_denied", "read"]


def test_retention_sweep_is_idempotent_and_honors_pins(tmp_path):
    control = _control(tmp_path)
    changeset = _changeset(control)
    key = b"z" * 32
    expired = capture_trace_archive(
        control.ledger,
        changeset["id"],
        {"trace": "expired"},
        workspace_key=key,
        retention_days=0,
        object_dir=tmp_path / "objects",
    )
    pinned = capture_trace_archive(
        control.ledger,
        changeset["id"],
        {"trace": "pinned"},
        workspace_key=key,
        retention_days=0,
        object_dir=tmp_path / "objects",
    )
    pin_trace_archive(
        control.ledger,
        pinned["id"],
        reason="Active audit",
        expires_at="2100-01-01T00:00:00Z",
    )

    deleted = sweep_expired_traces(control.ledger, now="2099-01-01T00:00:00Z")
    assert deleted == [expired["id"]]
    assert sweep_expired_traces(control.ledger, now="2099-01-01T00:00:00Z") == []
    assert not Path(expired["object_locator"]).exists()
    assert Path(pinned["object_locator"]).exists()
    with pytest.raises(ValidationError, match="administrator legal hold"):
        pin_trace_archive(control.ledger, pinned["id"], reason="Forever")
