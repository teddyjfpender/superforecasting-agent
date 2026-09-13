"""``forecast slack …`` — provision this named agent's own Slack app and report
its identity.

M1 (identity & voice) of the multiplayer-harness plan
(``docs/plans/2026-07-05-multiplayer-slack-harness.md``). Slack has no full
app-creation API without an org manifest token, so provisioning is a guided
flow: ``forecast slack provision`` emits an **app manifest** (the agent's name
baked in, the plan's scope list pinned) that the operator pastes into
"Create New App › From an app manifest". The existing OAuth install writer then
captures the resulting bot token. ``forecast slack whoami`` reports the resolved
identity (name / instance / team).

Registered via the shared ``register(forecast_sub)`` hook (the CLI-assembler
pattern, mirroring :mod:`forecasting.cli.jobs_admin`); handlers reach the
identity + Slack tool by lazy import so this module has no load-time edge to
``forecasting.cli.core``.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

# The bot scopes this agent's Slack app requests, pinned exactly to the plan's
# scope list (M1). Tests assert equality, so a change here is a deliberate,
# reviewed wire change.
MANIFEST_BOT_SCOPES: tuple[str, ...] = (
    "app_mentions:read",
    "chat:write",
    "reactions:read",
    "reactions:write",
    "files:read",
    "files:write",
    "channels:history",
    "im:history",
    "metadata.message:read",
)

# Bot events the app subscribes to. Kept minimal for M1 (mentions + operator
# DMs); the collab router (M3) adds message.channels when it lands.
MANIFEST_BOT_EVENTS: tuple[str, ...] = (
    "app_mention",
    "message.im",
)

_DEFAULT_DESCRIPTION = (
    "A superforecasting desk that collaborates in Slack: shares forecasts, "
    "evidence, and lessons as scoreable, provenance-tracked artifacts."
)


def build_app_manifest(name: str, *, description: Optional[str] = None) -> dict[str, Any]:
    """Build a Slack app manifest dict for a named agent.

    The name is baked into ``display_information.name`` and the bot user's
    display name so ``@<name>`` is a genuinely distinct, taggable identity.
    Scopes are pinned to :data:`MANIFEST_BOT_SCOPES`.
    """
    clean_name = (name or "").strip() or "Bernard"
    return {
        "display_information": {
            "name": clean_name,
            "description": (description or _DEFAULT_DESCRIPTION),
        },
        "features": {
            "bot_user": {
                "display_name": clean_name,
                "always_online": True,
            },
        },
        "oauth_config": {
            "scopes": {
                "bot": list(MANIFEST_BOT_SCOPES),
            },
        },
        "settings": {
            "event_subscriptions": {
                "bot_events": list(MANIFEST_BOT_EVENTS),
            },
            "interactivity": {"is_enabled": False},
            "org_deploy_enabled": False,
            "socket_mode_enabled": False,
            "token_rotation_enabled": False,
        },
    }


def render_manifest(manifest: dict[str, Any], fmt: str = "yaml") -> str:
    """Render a manifest dict as ``yaml`` (Slack's default paste format) or ``json``."""
    if fmt == "json":
        return json.dumps(manifest, indent=2)
    try:
        import yaml  # PyYAML — already a dependency (config.yaml)

        return yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False).rstrip("\n")
    except Exception:  # pragma: no cover — degrade to JSON if yaml is unavailable
        return json.dumps(manifest, indent=2)


def _provision_guidance(name: str) -> str:
    """Operator-facing next steps (printed to stderr so stdout stays pipeable)."""
    return (
        f"# Provision {name}'s Slack identity\n"
        "1. Go to https://api.slack.com/apps → Create New App → From an app manifest.\n"
        "2. Pick the workspace, then paste the manifest above.\n"
        "3. Create the app, then Install to Workspace to authorize the bot.\n"
        "4. Capture the bot token via the OAuth install flow (or set SLACK_BOT_TOKEN),\n"
        "   then run `forecast slack whoami` to confirm, and invite the bot to a channel.\n"
        f"Once installed, `@{name}` is a distinct, taggable member of the workspace."
    )


def build_whoami_payload(
    identity: Any,
    *,
    token_present: bool,
    slack_info: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Assemble the whoami report (pure + testable).

    *identity* is an :class:`forecasting.identity.AgentIdentity`. *slack_info* is
    an ``auth.test`` response when a token was live, else ``None``.
    """
    payload: dict[str, Any] = {
        "name": identity.name,
        "instance_id": identity.instance_id,
        "team": identity.team,
        "persona": identity.persona,
        "token_present": bool(token_present),
    }
    if slack_info:
        if slack_info.get("ok"):
            payload["slack"] = {
                "team": slack_info.get("team"),
                "team_id": slack_info.get("team_id"),
                "bot_user": slack_info.get("user"),
                "bot_user_id": slack_info.get("user_id"),
                "url": slack_info.get("url"),
            }
            if slack_info.get("team_id"):
                payload["team"] = slack_info.get("team_id")
        else:
            payload["slack_error"] = slack_info.get("error") or "auth.test failed"
    return payload


def render_whoami(payload: dict[str, Any]) -> str:
    """Human-readable whoami rendering."""
    out = [
        f"name:        {payload.get('name')}",
        f"instance_id: {payload.get('instance_id')}",
        f"team:        {payload.get('team') or '(none)'}",
    ]
    if payload.get("persona"):
        out.append(f"persona:     {payload['persona']}")
    slack = payload.get("slack")
    if slack:
        out.append("slack:")
        out.append(f"  workspace:   {slack.get('team')} ({slack.get('team_id')})")
        out.append(f"  bot user:    @{slack.get('bot_user')} ({slack.get('bot_user_id')})")
    elif payload.get("slack_error"):
        out.append(f"slack:       error — {payload['slack_error']}")
    elif not payload.get("token_present"):
        out.append("slack:       no bot token — run `forecast slack provision`, install the app, "
                   "then re-check.")
    return "\n".join(out)


def register(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``slack`` command group onto the forecast subparsers."""
    slack_parser = forecast_sub.add_parser(
        "slack",
        help="Provision this agent's Slack identity and report who it is",
    )
    slack_sub = slack_parser.add_subparsers(dest="slack_command")

    provision = slack_sub.add_parser(
        "provision",
        help="Emit a Slack app manifest (this agent's name baked in) + guided setup steps",
    )
    provision.add_argument("--format", choices=["yaml", "json"], default="yaml",
                           help="Manifest format (default yaml — Slack's paste format)")
    provision.add_argument("--name", default=None,
                           help="Override the agent name for this manifest (defaults to AGENT_NAME)")
    provision.add_argument("--description", default=None, help="Override the app description")
    provision.add_argument("--out", default=None, help="Write the manifest to this file instead of stdout")
    provision.add_argument("--quiet", action="store_true",
                           help="Emit only the manifest (suppress the guided-setup notes)")
    provision.set_defaults(_forecast_handler=_cmd_slack_provision)

    whoami = slack_sub.add_parser("whoami", help="Report this agent's name, instance id, and Slack team")
    whoami.add_argument("--team-id", dest="team_id", default=None, help="Workspace to check (defaults to first installed)")
    whoami.add_argument("--json", action="store_true", help="Emit the identity as JSON")
    whoami.set_defaults(_forecast_handler=_cmd_slack_whoami)

    share = slack_sub.add_parser(
        "share",
        help="Post a question's current forecast as an sfp/1 card into a channel",
    )
    share.add_argument("question", help="Question id whose CURRENT snapshot to share")
    share.add_argument("--channel", required=True, help="Slack channel id to post the card into")
    share.add_argument("--thread-ts", dest="thread_ts", default=None,
                       help="Post the card as a reply in this thread (thread = question/round)")
    share.add_argument("--team-id", dest="team_id", default=None,
                       help="Workspace to post in (defaults to first installed)")
    share.add_argument("--json", action="store_true", help="Emit the share result as JSON")
    share.set_defaults(_forecast_handler=_cmd_slack_share)


def _cmd_slack_provision(args: argparse.Namespace) -> None:
    """`forecast slack provision` — emit the app manifest + guided instructions."""
    from forecasting.identity import resolve_agent_name

    name = (getattr(args, "name", None) or resolve_agent_name()).strip()
    manifest = build_app_manifest(name, description=getattr(args, "description", None))
    rendered = render_manifest(manifest, fmt=getattr(args, "format", "yaml"))

    out_path = getattr(args, "out", None)
    if out_path:
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(rendered + "\n")
        except OSError as exc:
            print(f"forecast: could not write manifest to {out_path}: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"wrote {name}'s Slack app manifest to {out_path}")
    else:
        print(rendered)

    if not getattr(args, "quiet", False):
        print("\n" + _provision_guidance(name), file=sys.stderr)


def _cmd_slack_whoami(args: argparse.Namespace) -> None:
    """`forecast slack whoami` — report the resolved identity (fail-open with no token)."""
    from forecasting.identity import resolve_identity

    identity = resolve_identity(team_id=getattr(args, "team_id", None))

    slack_info: Optional[dict[str, Any]] = None
    token_present = False
    try:
        from forecasting.transports.slack import resolve_bot_token as _resolve_bot_token, api_call as _slack_api_call

        token = _resolve_bot_token(getattr(args, "team_id", None))
        token_present = bool(token)
        if token:
            try:
                slack_info = _slack_api_call("auth.test", token)
            except Exception as exc:  # network / transport — fail open
                slack_info = {"ok": False, "error": str(exc)}
    except Exception:  # pragma: no cover — slack tool import optional
        token_present = False

    payload = build_whoami_payload(identity, token_present=token_present, slack_info=slack_info)
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_whoami(payload))


def _cmd_slack_share(args: argparse.Namespace) -> None:
    """`forecast slack share <question> --channel` — render + post the current
    forecast card over the same path as the ``share_forecast`` tool action."""
    from forecasting.ledger import ForecastLedger
    from forecasting.application.sharing import execute_share

    ledger = ForecastLedger(getattr(args, "db", None))
    outcome = execute_share(
        ledger,
        str(getattr(args, "question", "") or ""),
        str(getattr(args, "channel", "") or ""),
        thread_ts=getattr(args, "thread_ts", None),
        team_id=getattr(args, "team_id", None),
    )

    if getattr(args, "json", False):
        print(json.dumps(outcome, indent=2, sort_keys=True))
    else:
        if outcome.get("shared"):
            where = f" in thread {outcome['thread_ts']}" if outcome.get("thread_ts") else ""
            print(f"shared {outcome['event_type']} for {outcome['question_id']} to {outcome['channel']}{where}")
            print(f"  criteria hash: {outcome.get('criteria_hash')}")
            if outcome.get("slack_ts"):
                print(f"  slack ts:      {outcome['slack_ts']}")
        else:
            reason = outcome.get("error") or outcome.get("reason") or "not shared"
            print(f"not shared: {reason}", file=sys.stderr)

    if not outcome.get("success"):
        raise SystemExit(1)
