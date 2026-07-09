"""Unified notification routing — the reader for the destination the desk has
been writing into the void.

Background (the gap this closes): ``forecast autopilot enable --notify <dest>``
has been persisting ``notification_policy["destination"]`` and *nothing read it*;
``forecasting/scheduler.py`` threads ``deliver="local"`` everywhere. Alerts,
digests, and cycle results only reached a human if the agent explicitly posted.
This module is the routing layer the plan (P2.4) specifies: it takes a
:class:`NotifyEvent` (a cycle digest, an alert escalation, a job completion, a
quorum verdict, a resolution) and delivers it to every *connected* surface whose
binding accepts that event class — riding the existing transports (the Slack
toolset for Block Kit cards; the stdlib Telegram client for compact markdown).

Delivery is honest, by construction:
  * failures are isolated per destination (one dead binding never sinks the fan-out
    or the sweep that triggered it),
  * every attempt's status is recorded (``deliveries.json``) and surfaced in
    ``forecast config doctor`` + ``forecast notify list`` — never silently dropped,
  * a persistently dead destination raises a ledger alert within one cycle,
  * ``forecast notify test`` proves a single binding live end-to-end.

Storage is a small JSON pair under ``{home}/notify/`` (0600), mirroring the
pairing store's on-disk discipline rather than adding a ledger migration:
``routes.json`` (the bindings) and ``deliveries.json`` (per-binding last status).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# ── event taxonomy ────────────────────────────────────────────────────────────

#: The event classes a binding can subscribe to. ``ALL`` is the wildcard.
EVENT_CLASSES: tuple[str, ...] = (
    "cycle_digest",     # nightly self-check / reforecast sweep summary
    "alert",            # watched-source / escalation alerts
    "job_completion",   # a background job (or connect test) finished
    "quorum_verdict",   # a forecast-quorum panel reached a verdict
    "resolution",       # a question resolved / was scored
)
ALL = "all"

#: The productized surfaces the router can reach today.
SURFACES: tuple[str, ...] = ("telegram", "slack")

_PERSISTENT_FAILURE_THRESHOLD = 3


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── data model ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NotifyEvent:
    """One thing worth telling the operator about, surface-agnostic.

    *body* is the plain/markdown fallback every surface can render. *card* is an
    optional :class:`forecasting.collab.cards.RenderedCard` (or any object
    exposing ``.blocks``/``.fallback_text``/``.event_type``/``.event_payload``)
    used for the richer Slack Block Kit surface. *event_id*, when set, makes a
    (route, event) pair idempotent — the same digest is never delivered twice to
    the same destination, which is what makes "one digest per destination, not
    per question" true.
    """

    event_class: str
    title: str
    body: str = ""
    card: Any = None
    event_id: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event_class not in EVENT_CLASSES:
            raise ValueError(
                f"unknown event_class {self.event_class!r}; expected one of {', '.join(EVENT_CLASSES)}"
            )


@dataclass
class NotifyRoute:
    """A delivery binding: a surface + a chat/channel + an event-class filter."""

    surface: str
    target: str
    events: tuple[str, ...] = (ALL,)
    thread_id: Optional[str] = None
    enabled: bool = True
    label: str = ""
    source: str = ""  # provenance: "connect" | "notify-add" | "autopilot:<qid>" | ...
    created_at: str = field(default_factory=_utcnow)

    @property
    def id(self) -> str:
        return route_id(self.surface, self.target, self.thread_id)

    def accepts(self, event_class: str) -> bool:
        if not self.enabled:
            return False
        return ALL in self.events or event_class in self.events

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["events"] = list(self.events)
        data["id"] = self.id
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NotifyRoute":
        events = tuple(data.get("events") or (ALL,))
        return cls(
            surface=str(data["surface"]),
            target=str(data["target"]),
            events=events,
            thread_id=(str(data["thread_id"]) if data.get("thread_id") else None),
            enabled=bool(data.get("enabled", True)),
            label=str(data.get("label") or ""),
            source=str(data.get("source") or ""),
            created_at=str(data.get("created_at") or _utcnow()),
        )


@dataclass(frozen=True)
class DeliveryResult:
    """The outcome of one (route, event) delivery attempt."""

    route_id: str
    surface: str
    target: str
    ok: bool
    skipped: bool = False
    error: Optional[str] = None
    detail: str = ""


@dataclass(frozen=True)
class DeliveryReport:
    """The fan-out result for one event."""

    event_class: str
    results: list[DeliveryResult]

    @property
    def delivered(self) -> list[DeliveryResult]:
        return [r for r in self.results if r.ok and not r.skipped]

    @property
    def failures(self) -> list[DeliveryResult]:
        return [r for r in self.results if not r.ok and not r.skipped]

    @property
    def ok(self) -> bool:
        return not self.failures


def route_id(surface: str, target: str, thread_id: Optional[str] = None) -> str:
    base = f"{surface.strip().lower()}:{target.strip()}"
    return f"{base}:{thread_id}" if thread_id else base


# ── destination grammar (the autopilot / cli --notify path) ───────────────────


def parse_destination(dest: str) -> Optional[NotifyRoute]:
    """Parse a ``<surface>:<target>[:<thread>]`` destination string into a route.

    This is the grammar ``forecast autopilot enable --notify`` and
    ``forecast notify test`` speak, mirroring the cron delivery-target grammar
    (``telegram:<chat>[:<thread>]``, ``slack:<channel>``). Returns ``None`` for
    an unroutable / unknown-surface string.
    """
    raw = (dest or "").strip()
    if not raw or ":" not in raw:
        return None
    surface, _, rest = raw.partition(":")
    surface = surface.strip().lower()
    if surface not in SURFACES or not rest.strip():
        return None
    target = rest.strip()
    thread: Optional[str] = None
    if surface == "telegram" and ":" in target:
        chat, _, thr = target.partition(":")
        if thr.strip().lstrip("-").isdigit():
            target, thread = chat.strip(), thr.strip()
    return NotifyRoute(surface=surface, target=target, events=(ALL,), thread_id=thread, source="destination")


# ── on-disk stores ────────────────────────────────────────────────────────────


def _notify_dir() -> Path:
    from hermes_constants import get_hermes_home

    d = get_hermes_home() / "notify"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _secure_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover — non-POSIX fs
            pass
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class RouteStore:
    """The bindings store — ``{home}/notify/routes.json`` (0600)."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path or (_notify_dir() / "routes.json")

    def load(self) -> list[NotifyRoute]:
        p = self.path
        if not p.exists():
            return []
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        rows = raw.get("routes") if isinstance(raw, dict) else raw
        out: list[NotifyRoute] = []
        for row in rows or []:
            try:
                out.append(NotifyRoute.from_dict(row))
            except Exception:  # a malformed row never sinks the rest
                continue
        return out

    def save(self, routes: list[NotifyRoute]) -> None:
        _secure_write_json(self.path, {"version": 1, "routes": [r.to_dict() for r in routes]})

    def get(self, rid: str) -> Optional[NotifyRoute]:
        return next((r for r in self.load() if r.id == rid), None)

    def upsert(self, route: NotifyRoute) -> NotifyRoute:
        """Add or replace a binding by id (re-binding the same chat updates it)."""
        routes = [r for r in self.load() if r.id != route.id]
        routes.append(route)
        self.save(routes)
        return route

    def remove(self, rid: str) -> bool:
        routes = self.load()
        kept = [r for r in routes if r.id != rid]
        if len(kept) == len(routes):
            return False
        self.save(kept)
        return True


class DeliveryLog:
    """Per-binding last-delivery status — ``{home}/notify/deliveries.json``.

    The honesty ledger for the router: doctor and ``notify list`` read it so a
    dead binding is *visible*, never a silent drop.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path or (_notify_dir() / "deliveries.json")

    def load(self) -> dict[str, Any]:
        p = self.path
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def record(self, result: DeliveryResult, *, event: NotifyEvent) -> dict[str, Any]:
        data = self.load()
        entry = data.get(result.route_id) or {}
        consecutive = int(entry.get("consecutive_failures") or 0)
        if result.skipped:
            pass  # a dedupe skip is not a delivery — leave the last real status alone
        elif result.ok:
            consecutive = 0
        else:
            consecutive += 1
        entry.update(
            {
                "surface": result.surface,
                "target": result.target,
                "last_event_class": event.event_class,
                "last_event_id": event.event_id,
                "last_status": "skipped" if result.skipped else ("ok" if result.ok else "failed"),
                "last_error": result.error,
                "last_at": _utcnow(),
                "consecutive_failures": consecutive,
                "total_ok": int(entry.get("total_ok") or 0) + (1 if result.ok and not result.skipped else 0),
                "total_failed": int(entry.get("total_failed") or 0) + (1 if (not result.ok and not result.skipped) else 0),
            }
        )
        data[result.route_id] = entry
        _secure_write_json(self.path, data)
        return entry

    def already_delivered(self, route_id: str, event_id: Optional[str]) -> bool:
        if not event_id:
            return False
        entry = self.load().get(route_id) or {}
        return entry.get("last_event_id") == event_id and entry.get("last_status") == "ok"


# ── surface senders (ride the existing transports) ────────────────────────────


def _render_telegram(event: NotifyEvent) -> str:
    title = (event.title or "").strip()
    body = (event.body or "").strip()
    if title and body:
        return f"*{title}*\n\n{body}"
    return title or body or "(no content)"


def send_telegram(route: NotifyRoute, event: NotifyEvent) -> DeliveryResult:
    from forecasting.transports import telegram as tg

    token = tg.resolve_bot_token()
    if not token:
        return DeliveryResult(
            route_id=route.id, surface=route.surface, target=route.target,
            ok=False, error="no Telegram bot token (run `forecast connect telegram`)",
        )
    res = tg.send_message(token, route.target, _render_telegram(event), thread_id=route.thread_id)
    if res.get("ok"):
        return DeliveryResult(
            route_id=route.id, surface=route.surface, target=route.target,
            ok=True, detail=f"message_id={res.get('message_id')}",
        )
    return DeliveryResult(
        route_id=route.id, surface=route.surface, target=route.target,
        ok=False, error=str(res.get("error") or "sendMessage failed"),
    )


def send_slack(route: NotifyRoute, event: NotifyEvent) -> DeliveryResult:
    from tools.slack_tool import slack_tool

    card = event.card
    if card is not None and getattr(card, "blocks", None):
        args = {
            "action": "post_with_metadata",
            "channel": route.target,
            "text": getattr(card, "fallback_text", "") or event.title,
            "blocks": list(card.blocks),
            "event_type": getattr(card, "event_type", "sfp_notification"),
            "event_payload": getattr(card, "event_payload", {}) or {},
            "thread_ts": route.thread_id,
        }
    else:
        text = (f"*{event.title}*\n{event.body}" if event.title and event.body else (event.title or event.body))
        args = {"action": "post_message", "channel": route.target, "text": text, "thread_ts": route.thread_id}
    try:
        raw = json.loads(slack_tool(args))
    except Exception as exc:  # pragma: no cover — slack_tool already guards
        return DeliveryResult(route_id=route.id, surface=route.surface, target=route.target,
                              ok=False, error=f"slack tool error: {exc}")
    if raw.get("success") or raw.get("ok"):
        return DeliveryResult(route_id=route.id, surface=route.surface, target=route.target,
                              ok=True, detail=f"ts={raw.get('ts')}")
    return DeliveryResult(route_id=route.id, surface=route.surface, target=route.target,
                          ok=False, error=str(raw.get("error") or "slack post failed"))


#: The default sender registry. Tests inject stubs to prove routing without a wire.
DEFAULT_SENDERS: dict[str, Callable[[NotifyRoute, NotifyEvent], DeliveryResult]] = {
    "telegram": send_telegram,
    "slack": send_slack,
}


# ── the router ────────────────────────────────────────────────────────────────


class NotifyRouter:
    """Fan an event out to the connected surfaces that subscribe to its class."""

    def __init__(
        self,
        *,
        store: Optional[RouteStore] = None,
        log: Optional[DeliveryLog] = None,
        senders: Optional[dict[str, Callable[[NotifyRoute, NotifyEvent], DeliveryResult]]] = None,
    ) -> None:
        self.store = store or RouteStore()
        self.log = log or DeliveryLog()
        self.senders = dict(DEFAULT_SENDERS)
        if senders:
            self.senders.update(senders)

    def _deliver_one(self, route: NotifyRoute, event: NotifyEvent, *, dedupe: bool) -> DeliveryResult:
        if dedupe and self.log.already_delivered(route.id, event.event_id):
            result = DeliveryResult(route_id=route.id, surface=route.surface, target=route.target,
                                    ok=True, skipped=True, detail="deduped (already delivered)")
            self.log.record(result, event=event)
            return result
        sender = self.senders.get(route.surface)
        if sender is None:
            result = DeliveryResult(route_id=route.id, surface=route.surface, target=route.target,
                                    ok=False, error=f"no transport for surface {route.surface!r}")
        else:
            try:
                result = sender(route, event)
            except Exception as exc:  # a transport blowup is isolated to its binding
                result = DeliveryResult(route_id=route.id, surface=route.surface, target=route.target,
                                        ok=False, error=f"{exc.__class__.__name__}: {exc}")
        self.log.record(result, event=event)
        return result

    def route(
        self,
        event: NotifyEvent,
        *,
        routes: Optional[list[NotifyRoute]] = None,
        dedupe: bool = True,
    ) -> DeliveryReport:
        """Deliver *event* to every stored binding that accepts its class."""
        candidates = routes if routes is not None else self.store.load()
        selected = [r for r in candidates if r.accepts(event.event_class)]
        results = [self._deliver_one(r, event, dedupe=dedupe) for r in selected]
        return DeliveryReport(event_class=event.event_class, results=results)

    def deliver_to_destinations(self, event: NotifyEvent, destinations: list[str]) -> DeliveryReport:
        """Deliver to ad-hoc ``surface:target`` strings (the ``--notify`` path)."""
        routes: list[NotifyRoute] = []
        results: list[DeliveryResult] = []
        for dest in destinations:
            route = parse_destination(dest)
            if route is None:
                results.append(DeliveryResult(route_id=str(dest), surface="?", target=str(dest),
                                              ok=False, error=f"unroutable destination {dest!r}"))
            else:
                routes.append(route)
        results.extend(self._deliver_one(r, event, dedupe=False) for r in routes)
        return DeliveryReport(event_class=event.event_class, results=results)

    def test_route(self, route: NotifyRoute) -> DeliveryResult:
        """Send a live test to a single binding (bypasses the class filter)."""
        event = NotifyEvent(
            event_class="job_completion",
            title="Notification test",
            body="Your forecasting desk is wired to this chat. Digests and alerts will arrive here.",
            event_id=f"test-{int(time.time())}",
        )
        return self._deliver_one(route, event, dedupe=False)

    def status_rows(self) -> list[dict[str, Any]]:
        """Join stored bindings with their last-delivery status (for doctor / list)."""
        deliveries = self.log.load()
        rows: list[dict[str, Any]] = []
        for route in self.store.load():
            entry = deliveries.get(route.id) or {}
            rows.append(
                {
                    "id": route.id,
                    "surface": route.surface,
                    "target": route.target,
                    "thread_id": route.thread_id,
                    "events": list(route.events),
                    "enabled": route.enabled,
                    "label": route.label,
                    "source": route.source,
                    "last_status": entry.get("last_status"),
                    "last_at": entry.get("last_at"),
                    "last_error": entry.get("last_error"),
                    "consecutive_failures": int(entry.get("consecutive_failures") or 0),
                }
            )
        return rows


# ── module-level convenience (the caller-facing API) ──────────────────────────


def register_destination(
    dest: str,
    *,
    events: tuple[str, ...] = (ALL,),
    label: str = "",
    source: str = "",
    store: Optional[RouteStore] = None,
) -> NotifyRoute:
    """Persist a ``surface:target`` destination as a binding.

    This is how the autopilot ``--notify`` dead-end is closed: enabling autopilot
    with ``--notify telegram:<chat>`` now registers a real binding the router
    reads on the next digest, instead of writing a string nobody consumes.
    """
    route = parse_destination(dest)
    if route is None:
        raise ValueError(f"unroutable destination {dest!r} (expected e.g. telegram:<chat_id> or slack:<channel>)")
    route.events = tuple(events)
    route.label = label
    route.source = source or "destination"
    return (store or RouteStore()).upsert(route)


def deliver_event(event: NotifyEvent, *, router: Optional[NotifyRouter] = None) -> DeliveryReport:
    return (router or NotifyRouter()).route(event)


def deliver_digest(
    text: str,
    *,
    title: str = "Forecast self-check",
    event_id: Optional[str] = None,
    db_path: Optional[str] = None,
    router: Optional[NotifyRouter] = None,
) -> DeliveryReport:
    """Fan a cycle-digest text out to connected surfaces. No-op with zero routes.

    Safe to call unconditionally from a sweep: any per-binding failure is
    isolated and recorded; a persistently dead binding raises a ledger alert
    (best-effort) so the operator learns their bot token was revoked without the
    nightly loop ever crashing.
    """
    r = router or NotifyRouter()
    if not r.store.load():
        return DeliveryReport(event_class="cycle_digest", results=[])
    event = NotifyEvent(event_class="cycle_digest", title=title, body=text or "", event_id=event_id)
    report = r.route(event)
    _maybe_alert_dead_destinations(report, db_path=db_path, log=r.log)
    return report


def _maybe_alert_dead_destinations(
    report: DeliveryReport,
    *,
    db_path: Optional[str],
    log: DeliveryLog,
) -> None:
    """Raise a ledger alert for any binding now persistently failing."""
    dead = [
        f for f in report.failures
        if int((log.load().get(f.route_id) or {}).get("consecutive_failures") or 0) >= _PERSISTENT_FAILURE_THRESHOLD
    ]
    if not dead:
        return
    try:
        from forecasting.ledger import ForecastLedger, allow_ledger_writes

        ledger = ForecastLedger(db_path)
        with allow_ledger_writes(reason="notify_dead_destination"):
            for f in dead:
                ledger.create_alert(
                    severity="warning",
                    scope_type="global",
                    scope_ref=f.route_id,
                    reason=f"notification_delivery_failed:{f.surface}",
                    recommended_action=(
                        f"Notification delivery to {f.route_id} has failed "
                        f">= {_PERSISTENT_FAILURE_THRESHOLD} times ({f.error}). "
                        f"Re-run `forecast connect {f.surface}` or `forecast notify test {f.route_id}`."
                    ),
                )
    except Exception:  # never let alerting break the sweep
        pass


def connections_report(router: Optional[NotifyRouter] = None) -> dict[str, Any]:
    """The ``connections`` section for ``forecast config doctor``."""
    from forecasting.transports import telegram as tg
    from tools.slack_tool import _resolve_bot_token

    r = router or NotifyRouter()
    rows = r.status_rows()
    surfaces = {
        "telegram": {"token_present": bool(tg.resolve_bot_token())},
        "slack": {"token_present": bool(_resolve_bot_token(None))},
    }
    for surface, info in surfaces.items():
        bound = [row for row in rows if row["surface"] == surface]
        info["bound_count"] = len(bound)
        info["healthy"] = all(row.get("last_status") in (None, "ok") for row in bound)
    return {"surfaces": surfaces, "routes": rows}


__all__ = [
    "EVENT_CLASSES",
    "ALL",
    "SURFACES",
    "NotifyEvent",
    "NotifyRoute",
    "DeliveryResult",
    "DeliveryReport",
    "RouteStore",
    "DeliveryLog",
    "NotifyRouter",
    "route_id",
    "parse_destination",
    "register_destination",
    "deliver_event",
    "deliver_digest",
    "connections_report",
    "send_telegram",
    "send_slack",
    "DEFAULT_SENDERS",
]
