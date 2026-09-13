"""The collab DIRECTORY — who is in the org, and who is authorised.

M3 (the import pipeline) of the multiplayer-harness plan
(``docs/plans/2026-07-05-multiplayer-slack-harness.md``). Two facts a receiving
desk must resolve before it trusts a peer message:

* **who sent it** — the directory ``{home}/collab/directory.json`` maps a stable
  ``instance_id`` to ``{name, bot_user_id, team, first_seen, last_seen}``. It is
  updated on ANY received sfp message (:func:`record_agent`) — the federated,
  server-less way a facilitator discovers participants and a receiver resolves a
  sender's display name. A joining desk announces itself with a ``directory.hello``
  (:func:`build_hello_envelope` / :func:`emit_hello`).
* **whether it is authorised** — the ALLOWLIST is config, not a directory fact:
  ``COLLAB_ALLOWED_INSTANCES`` (a comma-separated list of instance_ids). It is
  CLOSED BY DEFAULT — an empty/unset value authorises NO one, so a fresh install
  imports nothing until an operator names its trusted counterparties. Authorisation
  is by instance_id (stable), never display name (spoofable).

The directory is a plain JSON file next to ``identity.json`` (same agent home). No
network here — the hello is BUILT here and POSTED by the caller through the Slack
tool, so this module stays import-light and unit-testable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from protocol.collab import (
    KIND_REQUEST,
    AckRequestBody,
    SfpEnvelope,
    SfpSender,
    build_metadata,
)

logger = logging.getLogger("forecasting.collab.directory")

# The well-known request_kind a joining desk announces itself with. Carried on an
# ``ack``/``request`` envelope (no new sfp KIND is minted — the protocol wire and
# its generated TS stay frozen), so a hello is a valid sfp/1 message any peer parses.
DIRECTORY_HELLO_REQUEST_KIND = "directory.hello"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cfg(cfg: Any = None) -> Any:
    if cfg is not None:
        return cfg
    from forecasting.appconfig import get_config

    return get_config()


# ── paths ─────────────────────────────────────────────────────────────────────

def collab_dir(home: Optional[Path | str] = None) -> Path:
    """The ``{home}/collab`` directory (created on demand)."""

    if home is not None:
        base = Path(home)
    else:
        from superforecasting_agent.constants import get_agent_home

        base = get_agent_home()
    path = base / "collab"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover — disk failure is non-fatal
        logger.warning("could not create collab dir %s: %s", path, exc)
    return path


def directory_path(home: Optional[Path | str] = None) -> Path:
    """The ``{home}/collab/directory.json`` path."""

    return collab_dir(home) / "directory.json"


# ── read / write ──────────────────────────────────────────────────────────────

def load_directory(home: Optional[Path | str] = None) -> dict[str, dict[str, Any]]:
    """The directory dict ``{instance_id: {...}}`` (``{}`` when absent/corrupt)."""

    try:
        raw = json.loads(directory_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_directory(data: dict[str, Any], home: Optional[Path | str] = None) -> None:
    from superforecasting_agent.storage.files import atomic_json_write

    try:
        atomic_json_write(directory_path(home), data)
    except OSError as exc:  # pragma: no cover — disk failure is non-fatal
        logger.warning("could not persist collab directory: %s", exc)


def record_agent(
    sender: SfpSender | dict[str, Any],
    *,
    bot_user_id: Optional[str] = None,
    team: Optional[str] = None,
    home: Optional[Path | str] = None,
    now: Optional[str] = None,
) -> dict[str, Any]:
    """Upsert an agent into the directory from a received sfp ``sender``.

    Preserves ``first_seen`` on an existing entry and always advances
    ``last_seen``. ``bot_user_id`` (the Slack user id, for @-mentions) comes from
    the Slack event envelope, not the sfp body, so it is passed in and only
    OVERWRITES a stored value when non-empty (a later message without it never
    erases a known id). Returns the stored entry."""

    if isinstance(sender, SfpSender):
        agent, instance_id, sender_team = sender.agent, sender.instance_id, sender.team
    else:
        agent = str(sender.get("agent") or "")
        instance_id = str(sender.get("instance_id") or "")
        sender_team = sender.get("team")
    if not instance_id:
        return {}
    stamp = now or _now_iso()
    data = load_directory(home)
    entry = dict(data.get(instance_id) or {})
    entry["name"] = agent or entry.get("name")
    entry["instance_id"] = instance_id
    entry["team"] = team or sender_team or entry.get("team")
    if bot_user_id:
        entry["bot_user_id"] = bot_user_id
    entry.setdefault("first_seen", stamp)
    entry["last_seen"] = stamp
    data[instance_id] = entry
    _write_directory(data, home)
    return entry


def get_agent(instance_id: str, home: Optional[Path | str] = None) -> Optional[dict[str, Any]]:
    return load_directory(home).get(str(instance_id or ""))


# ── allowlist (closed by default) ─────────────────────────────────────────────

def allowed_instances(cfg: Any = None) -> set[str]:
    """The authorised counterparty instance_ids from ``COLLAB_ALLOWED_INSTANCES``.

    Empty / unset ⇒ ``set()`` (CLOSED BY DEFAULT — accept none). Whitespace and
    empty entries are dropped so ``"a, b,"`` ⇒ ``{"a", "b"}``."""

    from forecasting.jobs.policy import COLLAB_ALLOWLIST_CONFIG_KEY

    raw = _cfg(cfg).get_str(COLLAB_ALLOWLIST_CONFIG_KEY, None) or ""
    return {part.strip() for part in raw.split(",") if part.strip()}


def is_allowed(instance_id: str | None, cfg: Any = None) -> bool:
    """Whether *instance_id* is an authorised counterparty (closed by default)."""

    ident = str(instance_id or "").strip()
    return bool(ident) and ident in allowed_instances(cfg)


# ── the directory.hello announce ──────────────────────────────────────────────

def build_hello_envelope(
    identity: Any,
    *,
    channels: Optional[list[str]] = None,
    note: Optional[str] = None,
    ts: Optional[str] = None,
) -> SfpEnvelope:
    """Build the ``directory.hello`` announce as an sfp/1 ``request`` envelope.

    The joining desk posts this on join to the well-known agents channel; every
    receiver :func:`record_agent`\\ s it (a hello IS just a received sfp message).
    Carried as ``request`` with ``request_kind='directory.hello'`` so no new wire
    kind is minted."""

    from forecasting.collab.cards import _as_sender  # local: cards owns the coercion

    sender = _as_sender(identity)
    body = AckRequestBody(
        correlation_id=f"hello:{sender.instance_id}",
        intent="request",
        request_kind=DIRECTORY_HELLO_REQUEST_KIND,
        note=note or (f"channels: {', '.join(channels)}" if channels else None),
    )
    return SfpEnvelope.of(KIND_REQUEST, sender, body, ts=ts)


def emit_hello(
    identity: Any,
    channel: str,
    *,
    poster: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    team_id: Optional[str] = None,
    channels: Optional[list[str]] = None,
    ts: Optional[str] = None,
) -> dict[str, Any]:
    """Post a ``directory.hello`` to *channel* via the Slack tool (``poster`` lets a
    test inject a capturing stub). Returns the poster's result dict."""

    from forecasting.collab.cards import _as_sender

    sender = _as_sender(identity)
    envelope = build_hello_envelope(identity, channels=channels, ts=ts)
    meta = build_metadata(envelope)
    team = f" · {sender.team}" if sender.team else ""
    blocks = [
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f":wave: *{sender.agent}*{team} joined · sfp/1 · `{sender.instance_id[:12]}`"}
            ],
        }
    ]

    def _default_poster(args: dict[str, Any]) -> dict[str, Any]:
        from forecasting.transports.slack import execute_slack_action

        return execute_slack_action(args)

    post = poster or _default_poster
    return post(
        {
            "action": "post_with_metadata",
            "team_id": team_id,
            "channel": channel,
            "text": f"{sender.agent} joined (sfp/1)",
            "blocks": blocks,
            "event_type": meta.event_type,
            "event_payload": meta.event_payload,
        }
    )


__all__ = [
    "DIRECTORY_HELLO_REQUEST_KIND",
    "collab_dir",
    "directory_path",
    "load_directory",
    "record_agent",
    "get_agent",
    "allowed_instances",
    "is_allowed",
    "build_hello_envelope",
    "emit_hello",
]
