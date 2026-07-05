"""The collab ROUTER (M3): a Slack metadata event → the right honest handler,
rate-limited per channel and fail-open. Non-sfp events pass through (None)."""

from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.collab.cards import criteria_hash
from forecasting.collab.router import (
    CollabRouter,
    extract_sfp_metadata,
    route_slack_metadata_event,
)
from protocol.collab import (
    KIND_FORECAST_CARD,
    KIND_THESIS_ROUND,
    ForecastCardBody,
    SfpEnvelope,
    SfpSender,
    ThesisRoundBody,
    build_metadata,
)
from forecasting.collab.directory import build_hello_envelope
from forecasting.identity import AgentIdentity

CRIT = "BLS CPI-U YoY for the July 2026 release exceeds 3.0 percent per the official BLS table."
ADA = SfpSender(agent="Ada", instance_id="inst-ada", team="T012ABC")


def _event(envelope: SfpEnvelope, *, channel="C1", ts="1700.1", user="U_ADA"):
    meta = build_metadata(envelope)
    return {
        "channel": channel, "ts": ts, "user": user, "team": "T012ABC",
        "metadata": {"event_type": meta.event_type, "event_payload": meta.event_payload},
    }


def _card_env(probability=0.34):
    body = ForecastCardBody(
        question_title="Will CPI YoY exceed 3.0%?", criteria_hash=criteria_hash(CRIT),
        outcome_type="binary", as_of="2026-07-05T09:00:00Z", probability=probability,
    )
    return SfpEnvelope.of(KIND_FORECAST_CARD, ADA, body)


def _ledger(tmp_path):
    ledger = ForecastLedger(str(tmp_path / "recv.db"))
    ledger.create_question(title="Will CPI YoY exceed 3.0%?", resolution_criteria=CRIT,
                           close_time="2026-12-31T00:00:00Z", domain="macro")
    return ledger


# ── metadata extraction ────────────────────────────────────────────────────────

def test_extract_sfp_metadata_top_level_and_nested():
    env = _card_env()
    ev = _event(env)
    md = extract_sfp_metadata(ev)
    assert md and md["event_type"] == "sfp.forecast.card"
    # nested under message (message_changed shape)
    nested = {"message": {"metadata": ev["metadata"]}}
    assert extract_sfp_metadata(nested)["event_type"] == "sfp.forecast.card"


def test_extract_ignores_non_sfp_and_bare_events():
    assert extract_sfp_metadata({"text": "hello"}) is None
    assert extract_sfp_metadata({"metadata": {"event_type": "other.thing", "event_payload": {}}}) is None
    assert extract_sfp_metadata({"metadata": {"event_type": "sfp.forecast.card"}}) is None  # no payload


# ── import routing ──────────────────────────────────────────────────────────────

def test_router_imports_forecast_card(tmp_path, monkeypatch):
    monkeypatch.setenv("COLLAB_ALLOWED_INSTANCES", "inst-ada")
    ledger = _ledger(tmp_path)
    reactions = []
    router = CollabRouter(ledger=ledger, home=tmp_path, poster=lambda a: reactions.append(a) or {"ok": True})

    result = router.handle_slack_event(_event(_card_env()))
    assert result.handled and result.outcome == "imported"
    assert result.import_result.peer_question_id
    # 📥 protocol reaction posted.
    assert reactions and reactions[0]["action"] == "add_reaction" and reactions[0]["name"] == "inbox_tray"


def test_router_refuses_non_allowlisted(tmp_path, monkeypatch):
    monkeypatch.delenv("COLLAB_ALLOWED_INSTANCES", raising=False)
    ledger = _ledger(tmp_path)
    result = CollabRouter(ledger=ledger, home=tmp_path).handle_slack_event(_event(_card_env()))
    assert result.outcome == "refused"


def test_router_evidence_uses_question_resolver(tmp_path, monkeypatch):
    monkeypatch.setenv("COLLAB_ALLOWED_INSTANCES", "inst-ada")
    from protocol.collab import KIND_EVIDENCE_SHARE, EvidenceShareBody, sha256_hex

    ledger = ForecastLedger(str(tmp_path / "recv.db"))
    q = ledger.create_question(title="Q", resolution_criteria=CRIT, close_time="2026-12-31T00:00:00Z")
    excerpt = "peer excerpt for the thread"
    body = EvidenceShareBody(source_type="url", captured_at="2026-06-30T12:00:00Z", claim="c",
                             sha256=sha256_hex(excerpt), excerpt=excerpt, source_url="https://x")
    env = SfpEnvelope.of(KIND_EVIDENCE_SHARE, ADA, body)
    router = CollabRouter(ledger=ledger, home=tmp_path, question_resolver=lambda ev: q.id)
    result = router.handle_slack_event(_event(env))
    assert result.outcome == "imported"
    assert ledger.list_evidence(q.id)[0].metadata["origin"] == "peer:Ada@T012ABC"


# ── stubs (M4) ──────────────────────────────────────────────────────────────────

def test_thesis_round_is_an_honest_m4_stub(tmp_path):
    body = ThesisRoundBody(round=1, participants=["Ada", "Bernard"])
    env = SfpEnvelope.of(KIND_THESIS_ROUND, ADA, body)
    result = CollabRouter(ledger=None, home=tmp_path).route(env, event={"channel": "C1"})
    assert result.handled and result.outcome == "round_stub_m4"


def test_directory_hello_is_recorded(tmp_path):
    identity = AgentIdentity(name="Ada", instance_id="inst-ada", team="T012ABC")
    env = build_hello_envelope(identity)
    result = CollabRouter(ledger=None, home=tmp_path).handle_slack_event(_event(env, user="U_ADA"))
    assert result.outcome == "directory_hello"
    from forecasting.collab.directory import load_directory
    assert "inst-ada" in load_directory(tmp_path)


# ── rate limit + robustness ──────────────────────────────────────────────────────

def test_rate_limit_per_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("COLLAB_ALLOWED_INSTANCES", "inst-ada")
    ledger = _ledger(tmp_path)
    clock = {"t": 0.0}
    router = CollabRouter(ledger=ledger, home=tmp_path, rate_limit_per_hour=2, clock=lambda: clock["t"])
    assert router.handle_slack_event(_event(_card_env(), ts="1")).outcome == "imported"
    assert router.handle_slack_event(_event(_card_env(), ts="2")).outcome == "imported"
    # third within the hour → dropped.
    assert router.handle_slack_event(_event(_card_env(), ts="3")).outcome == "rate_limited"
    # after the window rolls, accepted again.
    clock["t"] = 3601.0
    assert router.handle_slack_event(_event(_card_env(), ts="4")).outcome == "imported"


def test_non_sfp_event_returns_none(tmp_path):
    router = CollabRouter(ledger=None, home=tmp_path)
    assert router.handle_slack_event({"text": "hi there", "channel": "C1"}) is None


def test_malformed_payload_is_fail_open(tmp_path):
    router = CollabRouter(ledger=None, home=tmp_path)
    bad = {"channel": "C1", "metadata": {"event_type": "sfp.forecast.card", "event_payload": {"v": 99}}}
    result = router.handle_slack_event(bad)
    assert result.handled and result.outcome == "parse_error"


def test_route_slack_metadata_event_convenience(tmp_path, monkeypatch):
    monkeypatch.setenv("COLLAB_ALLOWED_INSTANCES", "inst-ada")
    monkeypatch.setenv("FORECAST_LEDGER_DB", str(tmp_path / "env.db"))
    ledger = ForecastLedger(str(tmp_path / "env.db"))
    ledger.create_question(title="Will CPI YoY exceed 3.0%?", resolution_criteria=CRIT,
                           close_time="2026-12-31T00:00:00Z", domain="macro")
    result = route_slack_metadata_event(_event(_card_env()), home=tmp_path)
    assert result is not None and result.outcome == "imported"
