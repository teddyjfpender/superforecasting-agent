"""The collab DIRECTORY + allowlist (M3): agents recorded on any received sfp
message, the closed-by-default allowlist, and the directory.hello announce."""

from __future__ import annotations

import json

from forecasting.collab import directory
from forecasting.collab.directory import (
    DIRECTORY_HELLO_REQUEST_KIND,
    allowed_instances,
    build_hello_envelope,
    emit_hello,
    is_allowed,
    load_directory,
    record_agent,
)
from forecasting.identity import AgentIdentity
from protocol.collab import KIND_REQUEST, SfpSender, parse_body


def _sender(agent="Ada", instance="inst-ada", team="T012ABC") -> SfpSender:
    return SfpSender(agent=agent, instance_id=instance, team=team)


def test_record_agent_upserts_and_preserves_first_seen(tmp_path):
    home = tmp_path / "home"
    e1 = record_agent(_sender(), bot_user_id="U_ADA", home=home, now="2026-07-05T10:00:00Z")
    assert e1["name"] == "Ada" and e1["bot_user_id"] == "U_ADA"
    assert e1["first_seen"] == "2026-07-05T10:00:00Z"

    e2 = record_agent(_sender(), home=home, now="2026-07-05T11:00:00Z")
    # first_seen preserved, last_seen advanced, bot_user_id NOT erased by a later
    # message that lacked it.
    assert e2["first_seen"] == "2026-07-05T10:00:00Z"
    assert e2["last_seen"] == "2026-07-05T11:00:00Z"
    assert e2["bot_user_id"] == "U_ADA"

    stored = load_directory(home)
    assert set(stored) == {"inst-ada"}


def test_record_agent_ignores_empty_instance(tmp_path):
    home = tmp_path / "home"
    assert record_agent(SfpSender(agent="X", instance_id=""), home=home) == {}
    assert load_directory(home) == {}


def test_allowlist_is_closed_by_default(monkeypatch):
    monkeypatch.delenv("COLLAB_ALLOWED_INSTANCES", raising=False)
    assert allowed_instances() == set()
    assert is_allowed("inst-ada") is False


def test_allowlist_parses_comma_list(monkeypatch):
    monkeypatch.setenv("COLLAB_ALLOWED_INSTANCES", "inst-ada, inst-bernard ,")
    assert allowed_instances() == {"inst-ada", "inst-bernard"}
    assert is_allowed("inst-ada") is True
    assert is_allowed("inst-mallory") is False
    assert is_allowed("") is False


def test_build_hello_envelope_is_a_valid_request(tmp_path):
    identity = AgentIdentity(name="Ada", instance_id="inst-ada", team="T012ABC")
    env = build_hello_envelope(identity, channels=["#forecast-agents"])
    assert env.kind == KIND_REQUEST
    body = parse_body(env)
    assert body.request_kind == DIRECTORY_HELLO_REQUEST_KIND
    assert env.sender.agent == "Ada" and env.sender.instance_id == "inst-ada"


def test_emit_hello_posts_metadata(tmp_path):
    identity = AgentIdentity(name="Ada", instance_id="inst-ada", team="T012ABC")
    calls = []

    def poster(args):
        calls.append(args)
        return {"ok": True, "ts": "1700000000.000100"}

    out = emit_hello(identity, "C_AGENTS", poster=poster, channels=["#forecast-agents"])
    assert out["ok"] is True
    assert len(calls) == 1
    call = calls[0]
    assert call["action"] == "post_with_metadata"
    assert call["channel"] == "C_AGENTS"
    assert call["event_type"] == "sfp.request"
    assert call["event_payload"]["body"]["request_kind"] == DIRECTORY_HELLO_REQUEST_KIND
