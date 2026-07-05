"""``forecast slack`` admin — manifest emitter (scopes pinned, name baked) +
whoami report (token / no-token fail-open)."""

from __future__ import annotations

from forecasting.cli import slack_admin as sa
from forecasting.identity import AgentIdentity


# ── manifest ─────────────────────────────────────────────────────────────────

def test_manifest_bakes_name():
    m = sa.build_app_manifest("Ada")
    assert m["display_information"]["name"] == "Ada"
    assert m["features"]["bot_user"]["display_name"] == "Ada"


def test_manifest_scopes_pinned_exactly():
    m = sa.build_app_manifest("Ada")
    assert m["oauth_config"]["scopes"]["bot"] == [
        "app_mentions:read",
        "chat:write",
        "reactions:read",
        "reactions:write",
        "files:read",
        "files:write",
        "channels:history",
        "im:history",
        "metadata.message:read",
    ]
    # And the module constant is the single source of that pin.
    assert list(sa.MANIFEST_BOT_SCOPES) == m["oauth_config"]["scopes"]["bot"]


def test_manifest_bot_events_minimal():
    m = sa.build_app_manifest("Ada")
    assert m["settings"]["event_subscriptions"]["bot_events"] == ["app_mention", "message.im"]


def test_manifest_blank_name_falls_back():
    assert sa.build_app_manifest("")["display_information"]["name"] == "Bernard"


def test_render_manifest_yaml_and_json_round_trip():
    import json

    import yaml

    m = sa.build_app_manifest("Ada")
    parsed_yaml = yaml.safe_load(sa.render_manifest(m, "yaml"))
    parsed_json = json.loads(sa.render_manifest(m, "json"))
    assert parsed_yaml == m == parsed_json
    assert parsed_yaml["oauth_config"]["scopes"]["bot"][0] == "app_mentions:read"


# ── whoami ───────────────────────────────────────────────────────────────────

def _ident(**kw) -> AgentIdentity:
    base = {"name": "Ada", "instance_id": "iid-1", "persona": None, "team": None}
    base.update(kw)
    return AgentIdentity(**base)


def test_whoami_no_token_fail_open():
    payload = sa.build_whoami_payload(_ident(), token_present=False, slack_info=None)
    assert payload["name"] == "Ada" and payload["instance_id"] == "iid-1"
    assert payload["token_present"] is False
    text = sa.render_whoami(payload)
    assert "Ada" in text and "iid-1" in text
    assert "no bot token" in text  # guides the operator to provision


def test_whoami_with_live_token():
    slack_info = {"ok": True, "team": "Acme", "team_id": "T042", "user": "ada", "user_id": "U1"}
    payload = sa.build_whoami_payload(_ident(), token_present=True, slack_info=slack_info)
    assert payload["team"] == "T042"
    assert payload["slack"]["bot_user"] == "ada"
    text = sa.render_whoami(payload)
    assert "Acme" in text and "@ada" in text and "T042" in text


def test_whoami_auth_error_is_surfaced():
    payload = sa.build_whoami_payload(
        _ident(team="T1"), token_present=True, slack_info={"ok": False, "error": "invalid_auth"}
    )
    assert payload["slack_error"] == "invalid_auth"
    assert payload["team"] == "T1"  # falls back to the offline-resolved team
    assert "invalid_auth" in sa.render_whoami(payload)
