"""Agent identity — the name and stable instance id that make this desk a
distinct, @-taggable collaborator in a multiplayer Slack channel.

This is M1 (identity & voice) of the multiplayer-harness plan
(``docs/plans/2026-07-05-multiplayer-slack-harness.md``). Two facts define the
identity:

* **name** — the human name (e.g. "Ada"). Configured via :mod:`appconfig`
  (``AGENT_NAME``; env or the config.yaml ``env:`` section). Defaults to
  **Bernard**, the desk's historical name, so an un-configured install is
  byte-identical to before — Bernard stays the default.
* **instance_id** — a stable uuid generated ONCE and persisted to
  ``{home}/identity.json`` so it survives restarts. An operator may pin it
  explicitly via ``appconfig`` (``AGENT_INSTANCE_ID``); otherwise it is minted
  on first read and written back.

The identity flows into (a) the soul / system prompt as ``"You are <name>, …"``
(see :func:`apply_agent_name`, called from
``agent.prompt_builder.load_soul_md``) and (b) the sfp/1 wire sender dict
``{agent, instance_id, team}`` that every cross-instance payload carries
(:meth:`AgentIdentity.sfp_sender`).

Nothing here touches the network: ``team`` is resolved offline from the
OAuth-written ``slack_tokens.json`` (its team-id keys), never by calling Slack.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("forecasting.identity")

# The desk's historical name. Kept as the default so an install that never sets
# AGENT_NAME renders exactly as it always has.
DEFAULT_AGENT_NAME = "Bernard"

# Where the minted instance id (and the name it was minted under) persists.
IDENTITY_FILE_NAME = "identity.json"


# ── persistence helpers ──────────────────────────────────────────────────────

def identity_path(home: Optional[Path | str] = None) -> Path:
    """Resolve the ``identity.json`` path under the agent home (or *home*)."""
    if home is not None:
        return Path(home) / IDENTITY_FILE_NAME
    from hermes_constants import get_hermes_home

    return get_hermes_home() / IDENTITY_FILE_NAME


def _read_identity(home: Optional[Path | str] = None) -> dict[str, Any]:
    """Read the persisted identity dict, or ``{}`` when absent/corrupt."""
    import json

    path = identity_path(home)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_identity(data: dict[str, Any], home: Optional[Path | str] = None) -> None:
    """Persist the identity dict atomically (best-effort — never raises)."""
    from utils import atomic_json_write

    try:
        atomic_json_write(identity_path(home), data)
    except OSError as exc:  # pragma: no cover — disk failure is non-fatal
        logger.warning("could not persist agent identity to %s: %s", identity_path(home), exc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cfg(cfg: Any = None) -> Any:
    if cfg is not None:
        return cfg
    from forecasting.appconfig import get_config

    return get_config()


# ── name resolution ──────────────────────────────────────────────────────────

def configured_agent_name(cfg: Any = None) -> Optional[str]:
    """The EXPLICITLY-configured agent name, or ``None`` when unset.

    Precedence: ``AGENT_NAME`` (env / config.yaml) → persisted
    ``identity.json`` name → ``None``. Distinct from :func:`resolve_agent_name`,
    which applies the ``Bernard`` default. Callers that must leave an existing
    default untouched when the name is unset (e.g. the TUI skin banner, whose
    own default is "Superforecasting Agent") use this.
    """
    conf = _cfg(cfg)
    val = (conf.get_str("AGENT_NAME") or "").strip()
    if val:
        return val
    persisted = str(_read_identity().get("name") or "").strip()
    return persisted or None


def resolve_agent_name(cfg: Any = None) -> str:
    """The effective agent name — configured value, else :data:`DEFAULT_AGENT_NAME`."""
    return configured_agent_name(cfg) or DEFAULT_AGENT_NAME


# ── instance id (minted once, persisted) ─────────────────────────────────────

def resolve_instance_id(cfg: Any = None, home: Optional[Path | str] = None) -> str:
    """The stable instance id for this install.

    Precedence: ``AGENT_INSTANCE_ID`` (an operator pin) → the persisted value in
    ``identity.json`` → a freshly-minted uuid4 that is written back so the next
    read is stable. Minting also records the name-at-mint and a ``created_at``
    timestamp (informational only; the name's source of truth stays
    :func:`resolve_agent_name`).
    """
    conf = _cfg(cfg)
    configured = (conf.get_str("AGENT_INSTANCE_ID") or "").strip()
    if configured:
        return configured

    data = _read_identity(home)
    existing = str(data.get("instance_id") or "").strip()
    if existing:
        return existing

    new_id = str(uuid.uuid4())
    data = dict(data)
    data["instance_id"] = new_id
    data.setdefault("name", resolve_agent_name(conf))
    data.setdefault("created_at", _now_iso())
    _write_identity(data, home)
    return new_id


# ── team resolution (offline) ────────────────────────────────────────────────

def resolve_team(team_id: Optional[str] = None, home: Optional[Path | str] = None) -> Optional[str]:
    """Resolve the Slack team id WITHOUT a network call.

    Returns *team_id* when given, else the first team-id key in the
    OAuth-written ``slack_tokens.json`` (shape ``{team_id: {token, team_name}}``),
    else ``None``.
    """
    if team_id:
        return team_id
    import json

    try:
        path = (Path(home) if home is not None else _hermes_home()) / "slack_tokens.json"
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for key in data:
        return str(key)
    return None


def _hermes_home() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home()


# ── the resolved identity ────────────────────────────────────────────────────

@dataclass(frozen=True)
class AgentIdentity:
    """A resolved agent identity — the sfp/1 sender and the desk's public name."""

    name: str
    instance_id: str
    persona: Optional[str] = None
    team: Optional[str] = None

    def sfp_sender(self) -> dict[str, Any]:
        """The sfp/1 ``sender`` dict: ``{agent, instance_id, team}``.

        This is the shape every cross-instance payload carries
        (``protocol/collab.py`` in M2 models the envelope around it)."""
        return {"agent": self.name, "instance_id": self.instance_id, "team": self.team}

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "instance_id": self.instance_id,
            "persona": self.persona,
            "team": self.team,
        }


def resolve_identity(
    cfg: Any = None,
    home: Optional[Path | str] = None,
    team_id: Optional[str] = None,
) -> AgentIdentity:
    """Resolve the full identity: name, minted-and-persisted instance id,
    optional persona, and offline-resolved team."""
    conf = _cfg(cfg)
    return AgentIdentity(
        name=resolve_agent_name(conf),
        instance_id=resolve_instance_id(conf, home),
        persona=(conf.get_str("AGENT_PERSONA") or None),
        team=resolve_team(team_id, home),
    )


# ── soul name injection ──────────────────────────────────────────────────────

def apply_agent_name(soul_content: Optional[str], name: Optional[str] = None) -> Optional[str]:
    """Rewrite the soul's opening identity to the configured agent name.

    The default soul opens ``"You are Bernard, the superforecasting agent: …"``.
    When a non-default *name* is configured this rewrites that opener to
    ``"You are <name>, …"``; when the name is unset (or is ``Bernard``) the soul
    is returned **byte-identical**, so a default install is unchanged.

    Graceful cases:
      * A customised soul that already opens ``"You are <name>"`` is returned
        unchanged (no double-injection).
      * A customised soul that doesn't carry the ``Bernard`` marker still gets
        the configured name via a short authoritative line prepended to it, so
        the name always reaches the prompt.
    """
    if not soul_content:
        return soul_content
    if name is None:
        name = resolve_agent_name()
    name = (name or "").strip()
    if not name or name == DEFAULT_AGENT_NAME:
        return soul_content

    # Already renamed by hand → leave it alone.
    if f"You are {name}" in soul_content:
        return soul_content

    marker = f"You are {DEFAULT_AGENT_NAME},"
    if marker in soul_content:
        return soul_content.replace(marker, f"You are {name},", 1)

    # Customised soul without the default marker: prepend an authoritative line.
    return f"You are {name}, the superforecasting agent.\n\n{soul_content}"


__all__ = [
    "DEFAULT_AGENT_NAME",
    "IDENTITY_FILE_NAME",
    "AgentIdentity",
    "identity_path",
    "configured_agent_name",
    "resolve_agent_name",
    "resolve_instance_id",
    "resolve_team",
    "resolve_identity",
    "apply_agent_name",
]
