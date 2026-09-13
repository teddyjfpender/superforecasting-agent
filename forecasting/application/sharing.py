"""Governed forecast-card sharing shared by CLI and agent adapters."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("forecasting.collab.share")

# Posting a card is a NETWORK side effect; it rides the existing policy matrix's
# network cell under the interactive run mode (a human drove the share).
_SHARE_ACTION_CLASS = "network"


def _resolve_share_policy() -> dict[str, Any]:
    """Resolve the share decision from the policy matrix (ctx-free) + log it."""

    from forecasting.jobs.policy import (
        ActionClass,
        RunMode,
        config_key,
        resolve_decision,
    )

    run_mode, action_class = RunMode.INTERACTIVE, ActionClass.NETWORK
    decision = resolve_decision(run_mode, action_class)
    key = config_key(run_mode, action_class)
    logger.info(
        "share policy: %s in %s mode = %s (key %s)",
        action_class.value,
        run_mode.value,
        decision.value,
        key,
    )
    return {
        "decision": decision.value,
        "action_class": action_class.value,
        "run_mode": run_mode.value,
        "config_key": key,
    }


def _default_poster(args: dict[str, Any]) -> dict[str, Any]:
    """Post via the shared Slack transport, returning its result dict."""

    from forecasting.transports.slack import execute_slack_action

    return execute_slack_action(args)


def execute_share(
    ledger: Any,
    question_id: str,
    channel: str,
    *,
    thread_ts: Optional[str] = None,
    identity: Any = None,
    poster: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    team_id: Optional[str] = None,
    ts: Optional[str] = None,
) -> dict[str, Any]:
    """Render + post the current forecast card. Returns a result dict (never raises
    for a normal refusal — the policy/verdict is data).

    *poster* lets tests inject a capturing stub; it defaults to the Slack transport."""

    if not question_id:
        return {
            "success": False,
            "shared": False,
            "error": "missing required arg: question_id",
        }
    if not channel:
        return {
            "success": False,
            "shared": False,
            "error": "missing required arg: channel",
        }

    from forecasting.collab.cards import render_forecast_card

    try:
        question = ledger.get_question(question_id)
    except Exception as exc:  # noqa: BLE001 — a bad id is a naming error, not a crash
        return {
            "success": False,
            "shared": False,
            "error": f"no question for question_id {question_id!r}: {exc}",
        }

    snapshot = ledger.get_current_snapshot(question_id)
    if snapshot is None:
        return {
            "success": False,
            "shared": False,
            "error": f"question {question_id!r} has no current snapshot to share",
        }

    if identity is None:
        from forecasting.identity import resolve_identity

        identity = resolve_identity(team_id=team_id)

    policy = _resolve_share_policy()
    card = render_forecast_card(snapshot, question, identity, ledger=ledger, ts=ts)

    base = {
        "question_id": question_id,
        "channel": channel,
        "thread_ts": thread_ts,
        "event_type": card.event_type,
        "criteria_hash": card.envelope.body.get("criteria_hash"),
        "overflow": bool(card.file_content),
        "policy": policy,
    }

    if policy["decision"] == "never":
        return {
            **base,
            "success": False,
            "shared": False,
            "error": (
                f"share refused by policy ({policy['config_key']} = never); "
                "loosen that key to auto to allow sharing"
            ),
        }
    if policy["decision"] == "ask":
        return {
            **base,
            "success": True,
            "shared": False,
            "reason": (
                f"share requires approval ({policy['config_key']} = ask); "
                "nothing was posted"
            ),
        }

    post = poster or _default_poster
    upload_result: Optional[dict[str, Any]] = None
    if card.file_content:
        # The body overflowed 8 KB metadata: upload it as a file first so the
        # pointer's sha256 has a real artifact to reference.
        upload_result = post({
            "action": "upload_file",
            "team_id": team_id,
            "channel": channel,
            "content": card.file_content,
            "filename": card.filename,
            "title": f"sfp {card.event_type} body",
            "thread_ts": thread_ts,
        })

    if upload_result is not None and not _post_succeeded(upload_result):
        error = str(upload_result.get("error") or "upload was not confirmed")
        return {
            **base,
            "success": False,
            "shared": False,
            "upload_ok": False,
            "slack_ok": False,
            "slack_error": error,
            "error": f"forecast body upload failed: {error}",
        }

    result = post({
        "action": "post_with_metadata",
        "team_id": team_id,
        "channel": channel,
        "text": card.fallback_text,
        "blocks": card.blocks,
        "event_type": card.event_type,
        "event_payload": card.event_payload,
        "thread_ts": thread_ts,
    })

    ok = _post_succeeded(result)
    return {
        **base,
        "success": ok,
        "shared": ok,
        "slack_ts": result.get("ts"),
        "slack_ok": ok,
        "slack_error": result.get("error") if not ok else None,
        "upload_ok": _post_succeeded(upload_result)
        if upload_result is not None
        else None,
    }


def _post_succeeded(result: dict[str, Any]) -> bool:
    """Honor canonical transport status, accepting legacy boolean ok responses."""
    return result.get("success", result.get("ok")) is True
