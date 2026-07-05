"""The collab ROUTER — a Slack metadata event → the right honest handler.

M3 (the import pipeline) of the multiplayer-harness plan
(``docs/plans/2026-07-05-multiplayer-slack-harness.md``). Peer sfp/1 messages
arrive as Slack message events carrying ``metadata`` (``event_type`` starting
``sfp.`` + an ``event_payload``). The gateway Slack adapter hands such an event
here (`route_slack_metadata_event`) INSTEAD of the human chat loop; this module
parses the envelope and classifies it (plan "Routing & sessions"):

* ``forecast.card`` / ``evidence.share`` / ``lesson.share`` → the policy-gated
  import pipeline (:func:`forecasting.collab.imports.accept_envelope`);
* ``request`` → the ``directory.hello`` announce (record the peer) or a share-back
  request (STUB for M4 — logged + acked, honestly marked);
* ``thesis.round`` / ``thesis.aggregate`` → the Delphi-in-Slack flows (STUB for M4
  — logged + acked, honestly marked);
* ``ack`` → recorded.

TWO hard rules, both about not being a liability: (1) a per-channel/hour RATE
LIMIT (a malicious channel can't drain the desk via inbound messages), and
(2) it NEVER raises into the platform adapter — every failure fails open (logged,
returned as data). Emoji reactions are protocol signals (📥 imported, ⚠️ concern)
posted best-effort when a poster is supplied.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from protocol.collab import (
    KIND_ACK,
    KIND_EVIDENCE_SHARE,
    KIND_FORECAST_CARD,
    KIND_LESSON_SHARE,
    KIND_REQUEST,
    KIND_THESIS_AGGREGATE,
    KIND_THESIS_ROUND,
    SfpEnvelope,
    parse_body,
    parse_envelope,
)

logger = logging.getLogger("forecasting.collab.router")

_IMPORT_KINDS = frozenset({KIND_FORECAST_CARD, KIND_EVIDENCE_SHARE, KIND_LESSON_SHARE})
_ROUND_KINDS = frozenset({KIND_THESIS_ROUND, KIND_THESIS_AGGREGATE})

# The reaction (Slack emoji name, no colons) posted per import outcome — a fixed-
# meaning protocol signal humans read the same as agents.
_REACTION_BY_OUTCOME = {
    "imported": "inbox_tray",   # 📥 imported into my ledger
    "refused": "warning",       # ⚠️ provenance / authorisation concern
    "error": "warning",
}


@dataclass
class RouteResult:
    """The outcome of routing one event (data, never an exception)."""

    handled: bool
    kind: Optional[str] = None
    outcome: str = ""
    import_result: Any = None
    reason: Optional[str] = None
    detail: dict[str, Any] = field(default_factory=dict)


def extract_sfp_metadata(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Pull the ``{event_type, event_payload}`` sfp metadata out of a Slack event
    (top-level, or nested under ``message`` for the ``message_changed`` subtype), or
    ``None`` when the event carries no sfp metadata."""

    md = event.get("metadata") or (event.get("message") or {}).get("metadata")
    if not isinstance(md, dict):
        return None
    event_type = str(md.get("event_type") or "")
    payload = md.get("event_payload")
    if not event_type.startswith("sfp.") or not isinstance(payload, dict):
        return None
    return {"event_type": event_type, "event_payload": payload}


class CollabRouter:
    """Routes parsed sfp/1 envelopes to the import pipeline / stubs, rate-limited
    per channel and fail-open."""

    def __init__(
        self,
        *,
        ledger: Any = None,
        ledger_factory: Optional[Callable[[], Any]] = None,
        home: Optional[Path | str] = None,
        cfg: Any = None,
        poster: Optional[Callable[[dict[str, Any]], Any]] = None,
        question_resolver: Optional[Callable[[dict[str, Any]], Optional[str]]] = None,
        rate_limit_per_hour: Optional[int] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ledger_obj = ledger
        self._ledger_factory = ledger_factory
        self._home = home
        self._cfg = cfg
        self._poster = poster
        self._question_resolver = question_resolver
        self._rate_limit = rate_limit_per_hour
        self._clock = clock
        self._channel_hits: dict[str, list[float]] = {}

    # ── ledger + config lazy access ───────────────────────────────────────────

    def _ledger(self) -> Any:
        if self._ledger_obj is not None:
            return self._ledger_obj
        if self._ledger_factory is not None:
            self._ledger_obj = self._ledger_factory()
            return self._ledger_obj
        from forecasting import ForecastLedger

        self._ledger_obj = ForecastLedger()
        return self._ledger_obj

    def _rate_limit_value(self) -> int:
        if self._rate_limit is not None:
            return int(self._rate_limit)
        try:
            from forecasting import appconfig

            self._rate_limit = int(appconfig.get_int("COLLAB_RATE_LIMIT_PER_HOUR", 240) or 240)
        except Exception:  # noqa: BLE001
            self._rate_limit = 240
        return self._rate_limit

    # ── rate limit (per channel / hour, sliding window) ───────────────────────

    def _rate_limited(self, channel: Optional[str]) -> bool:
        limit = self._rate_limit_value()
        if limit <= 0:
            return False
        key = str(channel or "_")
        now = self._clock()
        window = [t for t in self._channel_hits.get(key, []) if now - t < 3600.0]
        if len(window) >= limit:
            self._channel_hits[key] = window
            return True
        window.append(now)
        self._channel_hits[key] = window
        return False

    # ── the Slack-event entry point ───────────────────────────────────────────

    def handle_slack_event(self, event: dict[str, Any]) -> Optional[RouteResult]:
        """Route a raw Slack message event. Returns ``None`` when the event carries
        no sfp metadata (the caller then lets the normal chat loop handle it)."""

        md = extract_sfp_metadata(event)
        if md is None:
            return None
        try:
            envelope = parse_envelope(md["event_payload"])
        except Exception as exc:  # noqa: BLE001 — a malformed peer payload is data, not a crash
            logger.warning("collab router: could not parse sfp envelope: %s", exc)
            return RouteResult(handled=True, outcome="parse_error", reason=str(exc))

        channel = event.get("channel")
        if self._rate_limited(channel):
            from forecasting.collab.imports import append_collab_event

            append_collab_event(
                {"event": "collab.rate_limited", "kind": envelope.kind, "channel": channel,
                 "sender": {"agent": envelope.sender.agent, "instance_id": envelope.sender.instance_id}},
                self._home,
            )
            return RouteResult(handled=True, kind=envelope.kind, outcome="rate_limited")

        return self.route(envelope, event=event)

    # ── classification ────────────────────────────────────────────────────────

    def route(self, envelope: SfpEnvelope, *, event: Optional[dict[str, Any]] = None) -> RouteResult:
        event = event or {}
        kind = envelope.kind
        try:
            if kind in _IMPORT_KINDS:
                return self._route_import(envelope, event)
            if kind == KIND_REQUEST:
                return self._route_request(envelope, event)
            if kind == KIND_ACK:
                self._record(envelope, event)
                self._log_event("collab.ack", envelope, event)
                return RouteResult(handled=True, kind=kind, outcome="ack")
            if kind in _ROUND_KINDS:
                self._record(envelope, event)
                # STUB for M4 (Delphi-in-Slack) — honestly marked: logged + acked,
                # no round machinery yet.
                self._log_event("collab.round_stub", envelope, event)
                return RouteResult(handled=True, kind=kind, outcome="round_stub_m4",
                                   reason="thesis round flows land in M4 (Delphi-in-Slack)")
            return RouteResult(handled=False, kind=kind, outcome="unknown_kind")
        except Exception as exc:  # noqa: BLE001 — fail-open: NEVER crash the platform adapter
            logger.warning("collab router failed for kind %s (fail-open)", kind, exc_info=True)
            return RouteResult(handled=True, kind=kind, outcome="error", reason=str(exc))

    def _route_import(self, envelope: SfpEnvelope, event: dict[str, Any]) -> RouteResult:
        from forecasting.collab.imports import accept_envelope

        question_id = self._resolve_question(envelope.kind, event)
        result = accept_envelope(
            self._ledger(), envelope, home=self._home, cfg=self._cfg, question_id=question_id,
        )
        self._maybe_react(event, result.outcome)
        return RouteResult(handled=True, kind=envelope.kind, outcome=result.outcome, import_result=result)

    def _route_request(self, envelope: SfpEnvelope, event: dict[str, Any]) -> RouteResult:
        from forecasting.collab.directory import DIRECTORY_HELLO_REQUEST_KIND

        self._record(envelope, event)
        body = parse_body(envelope)
        request_kind = str(getattr(body, "request_kind", "") or "")
        if request_kind == DIRECTORY_HELLO_REQUEST_KIND:
            self._log_event("collab.directory_hello", envelope, event)
            return RouteResult(handled=True, kind=envelope.kind, outcome="directory_hello")
        # A share-back request ("share your evidence for Q") is a policy-checked
        # response flow — STUB for M4, honestly marked (logged + acked, no work run).
        self._log_event("collab.request_stub", envelope, event, detail={"request_kind": request_kind})
        return RouteResult(handled=True, kind=envelope.kind, outcome="request_ack_stub",
                           reason="share-back request flows land in M4", detail={"request_kind": request_kind})

    # ── helpers ───────────────────────────────────────────────────────────────

    def _resolve_question(self, kind: str, event: dict[str, Any]) -> Optional[str]:
        # forecast.card resolves its own question by criteria-hash; evidence/lesson
        # need the thread's question context (resolved by the injected resolver).
        if kind in {KIND_EVIDENCE_SHARE, KIND_LESSON_SHARE} and self._question_resolver is not None:
            try:
                return self._question_resolver(event)
            except Exception:  # noqa: BLE001
                logger.warning("collab router: question resolver failed", exc_info=True)
        return None

    def _record(self, envelope: SfpEnvelope, event: dict[str, Any]) -> None:
        from forecasting.collab.directory import record_agent

        try:
            record_agent(
                envelope.sender, bot_user_id=event.get("user"), team=event.get("team"), home=self._home,
            )
        except Exception:  # noqa: BLE001
            logger.warning("collab router: could not record peer", exc_info=True)

    def _log_event(self, name: str, envelope: SfpEnvelope, event: dict[str, Any], *, detail: Optional[dict] = None) -> None:
        from forecasting.collab.imports import append_collab_event

        append_collab_event(
            {
                "event": name,
                "kind": envelope.kind,
                "channel": event.get("channel"),
                "sender": {"agent": envelope.sender.agent, "instance_id": envelope.sender.instance_id,
                           "team": envelope.sender.team},
                **({"detail": detail} if detail else {}),
            },
            self._home,
        )

    def _maybe_react(self, event: dict[str, Any], outcome: str) -> None:
        """Post the fixed-meaning protocol reaction for *outcome* (best-effort; only
        when a poster is supplied — the gateway seam runs without one to stay
        non-blocking)."""

        if self._poster is None:
            return
        emoji = _REACTION_BY_OUTCOME.get(outcome)
        channel, ts = event.get("channel"), event.get("ts")
        if not emoji or not channel or not ts:
            return
        try:
            self._poster({"action": "add_reaction", "channel": channel, "timestamp": ts,
                          "name": emoji, "team_id": event.get("team")})
        except Exception:  # noqa: BLE001 — a reaction hiccup never affects the import
            logger.warning("collab router: could not post reaction", exc_info=True)


def route_slack_metadata_event(
    event: dict[str, Any],
    *,
    home: Optional[Path | str] = None,
    poster: Optional[Callable[[dict[str, Any]], Any]] = None,
    question_resolver: Optional[Callable[[dict[str, Any]], Optional[str]]] = None,
) -> Optional[RouteResult]:
    """The gateway seam's entry point: build a router (ledger from env) and route a
    peer sfp metadata event. Fail-open — never raises into the adapter."""

    try:
        router = CollabRouter(home=home, poster=poster, question_resolver=question_resolver)
        return router.handle_slack_event(event)
    except Exception:  # noqa: BLE001 — the adapter must never crash on a peer message
        logger.warning("collab router: route_slack_metadata_event failed (fail-open)", exc_info=True)
        return None


__all__ = [
    "RouteResult",
    "CollabRouter",
    "extract_sfp_metadata",
    "route_slack_metadata_event",
]
