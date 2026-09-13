"""``forecast connect <surface>`` + ``forecast notify`` — one guided UX for
wiring the desk to a chat surface, and the CLI over the notification router.

P2.1/P2.2/P2.3 of the Hetzner productionization plan. ``connect`` is a per-surface
guided flow built from existing seams (token capture + validation, the 0600
``.env`` writer in :mod:`forecasting.api_keys`, the pairing/identity machinery,
and the router's binding store). ``notify`` lists bindings, proves one live
(``notify test``), and adds/removes bindings by hand.

Design for testability: every flow's logic lives in a pure ``run_*_connect``
function with its transports / token-writer / router injected, so the state
machine (validate → bind → test) is driven in a unit test without argparse, a
network, or a live bot. The ``_cmd_*`` handlers are thin adapters that wire the
real defaults. Registered via the shared ``register(forecast_sub)`` hook; heavy
deps are lazy-imported inside handlers (no load-time edge to ``cli.core``).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Optional

from forecasting import notify as notify_mod

# ── surfaces + status ─────────────────────────────────────────────────────────

#: Surfaces we productize a guided flow for.
PRODUCTIZED: tuple[str, ...] = ("telegram", "slack")

#: Surfaces intentionally left as expert-documented paths (P2.5). One honest line
#: each — the guided-flow build cost never cleared the bar for a single operator.
DEFERRED: dict[str, str] = {
    "signal": (
        "expert-only — the signal-cli adapter is real but a guided flow would own a "
        "Java daemon, phone-number + captcha registration, and signal-cli's churn "
        "against Signal's servers, for ~zero capability delta over Telegram. "
        "Wire it by hand: run signal-cli in JSON-RPC daemon mode and set "
        "SIGNAL_* in {home}/.env (see the gateway signal adapter)."
    ),
    "whatsapp": (
        "expert-only — the Baileys bridge works but is an unofficial-API account-ban "
        "risk running a second Node process. Wire it by hand: start "
        "scripts/whatsapp-bridge and point WHATSAPP_* at it (see the gateway "
        "whatsapp adapter)."
    ),
}


def parse_events(value: Optional[str]) -> tuple[str, ...]:
    """Parse an ``--events`` CSV into a validated event-class tuple.

    ``all`` (or empty) → the wildcard. Unknown classes raise so a typo can't
    silently subscribe a binding to nothing.
    """
    raw = (value or "").strip()
    if not raw or raw.lower() == notify_mod.ALL:
        return (notify_mod.ALL,)
    classes = tuple(c.strip() for c in raw.split(",") if c.strip())
    bad = [c for c in classes if c not in notify_mod.EVENT_CLASSES]
    if bad:
        raise ValueError(
            f"unknown event class(es): {', '.join(bad)}. "
            f"Choose from {', '.join(notify_mod.EVENT_CLASSES)} or 'all'."
        )
    return classes or (notify_mod.ALL,)


# ── connect listing (pure) ────────────────────────────────────────────────────


def build_connect_listing(*, router: Optional[notify_mod.NotifyRouter] = None) -> list[dict[str, Any]]:
    """The surface status table for bare ``forecast connect`` (pure + testable)."""
    from forecasting.transports import telegram as tg

    r = router or notify_mod.NotifyRouter()
    rows = r.status_rows()

    def _bound(surface: str) -> list[dict[str, Any]]:
        return [row for row in rows if row["surface"] == surface]

    listing: list[dict[str, Any]] = []

    tg_token = bool(tg.resolve_bot_token())
    tg_routes = _bound("telegram")
    listing.append({
        "surface": "telegram",
        "status": "connected" if (tg_token and tg_routes) else ("token set — no chat bound" if tg_token else "available"),
        "bound": [f"{row['target']}" for row in tg_routes],
        "note": "guided: `forecast connect telegram`",
    })

    try:
        from forecasting.transports.slack import resolve_bot_token as _resolve_bot_token
        slack_token = bool(_resolve_bot_token(None))
    except Exception:
        slack_token = False
    slack_routes = _bound("slack")
    listing.append({
        "surface": "slack",
        "status": "connected" if slack_token else "available",
        "bound": [f"{row['target']}" for row in slack_routes],
        "note": "guided: `forecast connect slack`",
    })

    for surface, reason in DEFERRED.items():
        listing.append({"surface": surface, "status": "expert-only", "bound": [], "note": reason})

    return listing


def render_connect_listing(listing: list[dict[str, Any]]) -> str:
    out = ["forecast connect — messaging surfaces", "=" * 44]
    for row in listing:
        bound = f"  → {', '.join(row['bound'])}" if row.get("bound") else ""
        out.append(f"{row['surface']:<10} {row['status']}{bound}")
        out.append(f"           {row['note']}")
    return "\n".join(out)


def build_deferred_notice(surface: str) -> str:
    reason = DEFERRED.get(surface, "no guided flow for this surface")
    return f"{surface}: {reason}"


# ── telegram connect flow (pure core) ─────────────────────────────────────────

_BOTFATHER_STEPS = (
    "Telegram bot setup:\n"
    "  1. In Telegram, open @BotFather → /newbot → pick a name + username.\n"
    "  2. BotFather replies with an HTTP API token (looks like 123456:ABC-DEF...).\n"
    "  3. Paste that token below (or pass --token).\n"
    "  4. Then send any message to your new bot so it can learn your chat id."
)


def run_telegram_connect(
    *,
    token: Optional[str],
    chat_id: Optional[str],
    events: tuple[str, ...],
    do_test: bool = True,
    interactive: bool = True,
    tg: Any = None,
    router: Optional[notify_mod.NotifyRouter] = None,
    store: Optional[notify_mod.RouteStore] = None,
    set_token: Optional[Callable[[str], None]] = None,
    emit: Callable[[str], None] = print,
    prompt: Callable[[str], str] = input,
    poll_attempts: int = 12,
    sleep: Callable[[float], None] = lambda _s: None,
) -> dict[str, Any]:
    """Drive the Telegram connect state machine (validate → bind → test).

    All I/O is injected so a test can prove the whole path against a stub bot.
    Returns a result dict; raises no exceptions for expected failures (they are
    reported in ``result["error"]`` with ``result["ok"] is False``).
    """
    if tg is None:
        from forecasting.transports import telegram as _tg
        tg = _tg
    if router is None:
        router = notify_mod.NotifyRouter(store=store) if store is not None else notify_mod.NotifyRouter()
    store = store or router.store
    set_token = set_token or _default_set_env("TELEGRAM_BOT_TOKEN")

    # 1. token
    tok = (token or "").strip()
    if not tok and interactive:
        emit(_BOTFATHER_STEPS)
        tok = (prompt("Bot token: ") or "").strip()
    if not tok:
        return {"ok": False, "stage": "token", "error": "no bot token provided"}

    # 2. validate
    me = tg.get_me(tok)
    if not me.get("ok"):
        return {"ok": False, "stage": "validate", "error": me.get("error") or "token rejected by getMe"}
    set_token(tok)
    emit(f"validated bot @{me.get('username')} (id {me.get('id')}); token saved to .env")

    # 3. chat binding
    cid = (chat_id or "").strip()
    if not cid:
        if not interactive:
            return {"ok": False, "stage": "bind", "error": "no --chat-id and non-interactive; DM the bot first"}
        emit("Now send any message to your bot in Telegram, then press Enter to capture the chat…")
        prompt("")
        captured = None
        for _ in range(max(1, poll_attempts)):
            captured = tg.capture_chat(tok)
            if captured:
                break
            sleep(2.0)
        if not captured:
            return {"ok": False, "stage": "capture",
                    "error": "no message from you yet — send the bot a message, then re-run"}
        cid = str(captured["chat_id"])
        emit(f"captured chat {cid} ({captured.get('chat_type') or 'private'})")

    # 4. bind (persist the route)
    route = notify_mod.NotifyRoute(
        surface="telegram", target=cid, events=events,
        label=f"@{me.get('username')}", source="connect",
    )
    store.upsert(route)
    emit(f"bound telegram:{cid} for events [{', '.join(events)}]")

    result: dict[str, Any] = {"ok": True, "surface": "telegram", "route_id": route.id,
                              "chat_id": cid, "bot": me.get("username"), "events": list(events)}

    # 5. prove it live
    if do_test:
        test = router.test_route(route)
        result["test_ok"] = test.ok
        result["test_error"] = test.error
        if test.ok:
            emit(f"test message delivered to telegram:{cid} — you're connected.")
        else:
            result["ok"] = False
            emit(f"bound, but the test delivery failed: {test.error}")
    return result


# ── slack connect flow (pure core) ────────────────────────────────────────────


def run_slack_connect(
    *,
    token: Optional[str],
    channel: Optional[str],
    events: tuple[str, ...],
    do_test: bool = True,
    interactive: bool = True,
    fmt: str = "yaml",
    name: Optional[str] = None,
    auth_test: Optional[Callable[[str], dict]] = None,
    router: Optional[notify_mod.NotifyRouter] = None,
    store: Optional[notify_mod.RouteStore] = None,
    set_token: Optional[Callable[[str], None]] = None,
    emit: Callable[[str], None] = print,
    prompt: Callable[[str], str] = input,
) -> dict[str, Any]:
    """Drive the Slack connect flow: manifest → paste token → whoami → bind → test.

    Sequences the shipped machinery (the manifest emitter, the OAuth/token
    capture, ``auth.test`` verification) into one flow. Acceptance is ``whoami``
    green — a live ``auth.test`` — before any binding is written.
    """
    from forecasting.cli.slack_admin import build_app_manifest, render_manifest

    router = router or (notify_mod.NotifyRouter(store=store) if store else notify_mod.NotifyRouter())
    store = store or router.store
    set_token = set_token or _default_set_env("SLACK_BOT_TOKEN")
    if auth_test is None:
        from forecasting.transports.slack import api_call as _slack_api_call
        auth_test = lambda t: _slack_api_call("auth.test", t)  # noqa: E731

    if name is None:
        try:
            from forecasting.identity import resolve_agent_name
            name = resolve_agent_name()
        except Exception:
            name = "Bernard"

    # 1. manifest + instructions (Slack requires a manual paste — say so, don't fake it)
    if interactive:
        manifest = render_manifest(build_app_manifest(name), fmt=fmt)
        emit("Slack app setup (the manifest paste is a Slack platform constraint):")
        emit("  1. https://api.slack.com/apps → Create New App → From an app manifest.")
        emit("  2. Pick the workspace, paste the manifest below, create the app.")
        emit("  3. Install to Workspace, then copy the Bot User OAuth Token (xoxb-…).")
        emit("\n--- manifest ---\n" + manifest + "\n--- end manifest ---")

    # 2. token
    tok = (token or "").strip()
    if not tok and interactive:
        tok = (prompt("Bot User OAuth Token (xoxb-…): ") or "").strip()
    if not tok:
        return {"ok": False, "stage": "token", "error": "no bot token provided"}
    set_token(tok)

    # 3. verify — whoami green
    info = auth_test(tok)
    if not info.get("ok"):
        return {"ok": False, "stage": "verify", "error": info.get("error") or "auth.test failed"}
    emit(f"whoami: @{info.get('user')} in {info.get('team')} ({info.get('team_id')}) — verified.")
    result: dict[str, Any] = {"ok": True, "surface": "slack", "team": info.get("team"),
                              "team_id": info.get("team_id"), "bot_user": info.get("user")}

    # 4. bind channel
    chan = (channel or "").strip()
    if not chan and interactive:
        chan = (prompt("Channel id to post digests into (e.g. C0123ABC): ") or "").strip()
    if not chan:
        result["bound"] = False
        emit("verified, but no channel bound — re-run with --channel to receive digests.")
        return result
    route = notify_mod.NotifyRoute(surface="slack", target=chan, events=events,
                                   label=f"{info.get('team')}", source="connect")
    store.upsert(route)
    result.update({"route_id": route.id, "channel": chan, "events": list(events), "bound": True})
    emit(f"bound slack:{chan} for events [{', '.join(events)}]")

    # 5. prove it live
    if do_test:
        test = router.test_route(route)
        result["test_ok"] = test.ok
        result["test_error"] = test.error
        if test.ok:
            emit(f"test card delivered to {chan} — you're connected.")
        else:
            result["ok"] = False
            emit(f"bound, but the test delivery failed: {test.error}")
    return result


def _default_set_env(env_var: str) -> Callable[[str], None]:
    def _setter(value: str) -> None:
        from forecasting import api_keys
        api_keys.set_api_key(env_var, value)
    return _setter


# ── argparse registration ─────────────────────────────────────────────────────


def register(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``connect`` and ``notify`` command groups."""
    _register_connect(forecast_sub)
    _register_notify(forecast_sub)


def _register_connect(forecast_sub: argparse._SubParsersAction) -> None:
    connect = forecast_sub.add_parser(
        "connect", help="Wire the desk to a chat surface (telegram / slack) in one guided flow",
    )
    connect.set_defaults(_forecast_handler=_cmd_connect_list)
    csub = connect.add_subparsers(dest="connect_surface")

    tg = csub.add_parser("telegram", help="Guided Telegram bot connect (token → chat bind → test)")
    tg.add_argument("--token", default=None, help="BotFather token (skips the interactive prompt)")
    tg.add_argument("--chat-id", dest="chat_id", default=None, help="Bind this chat id directly (skips capture)")
    tg.add_argument("--events", default="cycle_digest,alert", help="Event classes to deliver (CSV or 'all')")
    tg.add_argument("--non-interactive", dest="non_interactive", action="store_true",
                    help="Fail instead of prompting (requires --token + --chat-id)")
    tg.add_argument("--skip-test", dest="skip_test", action="store_true", help="Do not send a test message")
    tg.add_argument("--json", action="store_true", help="Emit the result as JSON")
    tg.set_defaults(_forecast_handler=_cmd_connect_telegram)

    sl = csub.add_parser("slack", help="Guided Slack connect (manifest → token → whoami → bind → test)")
    sl.add_argument("--token", default=None, help="Bot User OAuth token (xoxb-…); skips the prompt")
    sl.add_argument("--channel", default=None, help="Channel id to bind digests to")
    sl.add_argument("--events", default="cycle_digest,alert", help="Event classes to deliver (CSV or 'all')")
    sl.add_argument("--format", default="yaml", choices=["yaml", "json"], help="Manifest format")
    sl.add_argument("--non-interactive", dest="non_interactive", action="store_true",
                    help="Fail instead of prompting (requires --token)")
    sl.add_argument("--skip-test", dest="skip_test", action="store_true", help="Do not send a test card")
    sl.add_argument("--json", action="store_true", help="Emit the result as JSON")
    sl.set_defaults(_forecast_handler=_cmd_connect_slack)

    for surface in DEFERRED:
        d = csub.add_parser(surface, help=f"{surface}: expert-only (deferred) — prints the manual path")
        d.set_defaults(_forecast_handler=_cmd_connect_deferred, _deferred_surface=surface)


def _register_notify(forecast_sub: argparse._SubParsersAction) -> None:
    notify = forecast_sub.add_parser(
        "notify", help="Inspect + test notification bindings (the delivery router)",
    )
    notify.set_defaults(_forecast_handler=_cmd_notify_list)
    nsub = notify.add_subparsers(dest="notify_command")

    lst = nsub.add_parser("list", help="List bindings with their last-delivery status")
    lst.add_argument("--json", action="store_true")
    lst.set_defaults(_forecast_handler=_cmd_notify_list)

    test = nsub.add_parser("test", help="Send a live test to a binding (route id or surface:target)")
    test.add_argument("target", help="A route id (telegram:123) or destination (slack:C0123)")
    test.add_argument("--json", action="store_true")
    test.set_defaults(_forecast_handler=_cmd_notify_test)

    add = nsub.add_parser("add", help="Register a binding by hand")
    add.add_argument("surface", choices=list(PRODUCTIZED))
    add.add_argument("target", help="Chat id (telegram) or channel id (slack)")
    add.add_argument("--events", default="all", help="Event classes (CSV or 'all')")
    add.add_argument("--thread", default=None, help="Thread/topic id (optional)")
    add.add_argument("--label", default="", help="Human label")
    add.add_argument("--json", action="store_true")
    add.set_defaults(_forecast_handler=_cmd_notify_add)

    rm = nsub.add_parser("remove", help="Remove a binding by route id")
    rm.add_argument("route_id", help="The route id (from `forecast notify list`)")
    rm.set_defaults(_forecast_handler=_cmd_notify_remove)


# ── handlers (thin adapters) ──────────────────────────────────────────────────


def _cmd_connect_list(args: argparse.Namespace) -> None:
    listing = build_connect_listing()
    print(render_connect_listing(listing))


def _progress_emitter(args: argparse.Namespace) -> Callable[[str], None]:
    """Progress goes to stderr under --json so stdout carries only the JSON."""
    if getattr(args, "json", False):
        return lambda msg: print(msg, file=sys.stderr)
    return print


def _cmd_connect_telegram(args: argparse.Namespace) -> None:
    events = parse_events(getattr(args, "events", None))
    result = run_telegram_connect(
        token=getattr(args, "token", None),
        chat_id=getattr(args, "chat_id", None),
        events=events,
        do_test=not getattr(args, "skip_test", False),
        interactive=not getattr(args, "non_interactive", False),
        emit=_progress_emitter(args),
    )
    _report_connect(args, result)


def _cmd_connect_slack(args: argparse.Namespace) -> None:
    events = parse_events(getattr(args, "events", None))
    result = run_slack_connect(
        token=getattr(args, "token", None),
        channel=getattr(args, "channel", None),
        events=events,
        do_test=not getattr(args, "skip_test", False),
        interactive=not getattr(args, "non_interactive", False),
        fmt=getattr(args, "format", "yaml"),
        emit=_progress_emitter(args),
    )
    _report_connect(args, result)


def _report_connect(args: argparse.Namespace, result: dict[str, Any]) -> None:
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, sort_keys=True))
    if not result.get("ok"):
        if not getattr(args, "json", False):
            print(f"connect failed at {result.get('stage', '?')}: {result.get('error')}", file=sys.stderr)
        raise SystemExit(1)


def _cmd_connect_deferred(args: argparse.Namespace) -> None:
    surface = getattr(args, "_deferred_surface", "")
    print(build_deferred_notice(surface))


def _cmd_notify_list(args: argparse.Namespace) -> None:
    rows = notify_mod.NotifyRouter().status_rows()
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2, sort_keys=True))
        return
    if not rows:
        print("no notification bindings — run `forecast connect telegram` or `forecast connect slack`.")
        return
    print(f"notification bindings ({len(rows)}):")
    for row in rows:
        status = row.get("last_status") or "never delivered"
        fails = row.get("consecutive_failures") or 0
        warn = f"  ⚠ {fails} consecutive failures ({row.get('last_error')})" if fails else ""
        print(f"  {row['id']:<28} events=[{', '.join(row['events'])}]  last={status}{warn}")


def _cmd_notify_test(args: argparse.Namespace) -> None:
    target = str(getattr(args, "target", "") or "")
    router = notify_mod.NotifyRouter()
    route = router.store.get(target) or notify_mod.parse_destination(target)
    if route is None:
        print(f"notify test: {target!r} is neither a known route id nor a routable destination", file=sys.stderr)
        raise SystemExit(1)
    result = router.test_route(route)
    if getattr(args, "json", False):
        print(json.dumps({"route_id": result.route_id, "ok": result.ok, "error": result.error,
                          "detail": result.detail}, indent=2, sort_keys=True))
    elif result.ok:
        print(f"delivered a test to {result.route_id} ({result.detail})")
    else:
        print(f"test delivery to {result.route_id} FAILED: {result.error}", file=sys.stderr)
    if not result.ok:
        raise SystemExit(1)


def _cmd_notify_add(args: argparse.Namespace) -> None:
    events = parse_events(getattr(args, "events", None))
    route = notify_mod.NotifyRoute(
        surface=str(args.surface), target=str(args.target), events=events,
        thread_id=getattr(args, "thread", None), label=getattr(args, "label", "") or "", source="notify-add",
    )
    notify_mod.RouteStore().upsert(route)
    if getattr(args, "json", False):
        print(json.dumps(route.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"added binding {route.id} for events [{', '.join(events)}]")


def _cmd_notify_remove(args: argparse.Namespace) -> None:
    rid = str(getattr(args, "route_id", "") or "")
    removed = notify_mod.RouteStore().remove(rid)
    if removed:
        print(f"removed binding {rid}")
    else:
        print(f"no binding with id {rid!r}", file=sys.stderr)
        raise SystemExit(1)
