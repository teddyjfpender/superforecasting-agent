import atexit
import os
import sys


def _stop_audio_playback() -> None:
    """Best-effort, fast: terminate any in-flight TTS audio player + recorder so the
    agent's voice and the mic can't outlive the gateway. The player (afplay/ffplay) is a
    CHILD process that the kernel would otherwise orphan — it keeps speaking after the TUI
    is gone. Safe from a signal handler or atexit: lazy imports are cache hits once voice
    has run, and every error is swallowed."""
    try:
        from tools.voice_mode import stop_playback

        stop_playback()
    except Exception:
        pass
    try:
        from superforecasting_agent.runtime.voice import stop_continuous

        stop_continuous()
    except Exception:
        pass


def _first_env(names: tuple[str, ...]) -> str:
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _runtime_env(name: str) -> str:
    return _first_env((
        f"SUPERFORECASTING_AGENT_{name}",
        f"FORECAST_{name}",
        f"HERMES_{name}",
    ))


def _tui_env(name: str) -> str:
    return _first_env((
        f"SUPERFORECASTING_AGENT_TUI_{name}",
        f"FORECAST_TUI_{name}",
        f"HERMES_TUI_{name}",
    ))


# Guard against a local utils/ (or other package) in CWD shadowing installed
# runtime modules.  The launcher sets PYTHON_SRC_ROOT aliases before spawning
# this subprocess; inserting it first ensures the installed packages win.
_src_root = _runtime_env("PYTHON_SRC_ROOT")
if _src_root and _src_root not in sys.path:
    sys.path.insert(0, _src_root)
# Strip '' and '.' — both resolve to CWD at import time and can let a local
# directory shadow installed packages.
sys.path = [p for p in sys.path if p not in {"", "."}]

import json
import signal
import time
import traceback

from tui_gateway import server
from tui_gateway.server import _CRASH_LOG, dispatch, resolve_skin, write_json
from tui_gateway.transport import TeeTransport


def _install_sidecar_publisher() -> None:
    """Mirror every dispatcher emit to the dashboard sidebar via WS.

    Activated by the TUI sidecar URL env aliases, set by the dashboard's
    ``/api/pty`` endpoint when the Forecast Desk route passes a ``channel``
    query param.
    Best-effort: connect failure or runtime drop falls back to stdio-only.
    """
    url = _tui_env("SIDECAR_URL")

    if not url:
        return

    from tui_gateway.event_publisher import WsPublisherTransport

    server._stdio_transport = TeeTransport(
        server._stdio_transport, WsPublisherTransport(url)
    )


def _install_event_log() -> None:
    """Tee every dispatcher emit into the append-only per-session event log.

    The stdio path's convergence point is ``server._stdio_transport`` (both
    per-session async events — session["transport"] falls back to it — and
    sessionless events land here), so Tee'ing the log on top of it is the whole
    wiring: sessions become forensically replayable via ``events.replay`` with no
    change to the stdio contract. Fail-open (see EventLog); disable via
    ``*_TUI_EVENT_LOG=0``."""
    if _tui_env("EVENT_LOG").strip().lower() in {"0", "false", "off", "no"}:
        return
    from tui_gateway.event_log import EventLog

    server._stdio_transport = TeeTransport(server._stdio_transport, EventLog())


# How long to wait for orderly shutdown (atexit + finalisers) before
# falling back to ``os._exit(0)`` so a wedged worker mid-flush can't
# strand the process.  1s covers the gateway's own shutdown work
# (thread-pool drain + session finalize) on every machine we've
# tested; override via ``SUPERFORECASTING_AGENT_TUI_GATEWAY_SHUTDOWN_GRACE_S``
# or compatibility aliases if a
# slower environment needs more headroom (e.g. encrypted disks
# flushing checkpoints) and accept that a longer grace also means a
# longer wait when shutdown actually deadlocks.
_DEFAULT_SHUTDOWN_GRACE_S = 1.0


def _shutdown_grace_seconds() -> float:
    raw = _tui_env("GATEWAY_SHUTDOWN_GRACE_S")
    if not raw:
        return _DEFAULT_SHUTDOWN_GRACE_S
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_SHUTDOWN_GRACE_S
    return value if value > 0 else _DEFAULT_SHUTDOWN_GRACE_S


def _log_signal(signum: int, frame) -> None:
    """Capture WHICH thread and WHERE a termination signal hit us.

    SIG_DFL for SIGPIPE kills the process silently the instant any
    background thread (TTS playback, beep, voice status emitter, etc.)
    writes to a stdout the TUI has stopped reading.  Without this
    handler the gateway-exited banner in the TUI has no trace — the
    crash log never sees a Python exception because the kernel reaps
    the process before the interpreter runs anything.

    Termination semantics: ``sys.exit(0)`` here used to race the worker
    pool — a thread holding ``_stdout_lock`` mid-flush would block the
    interpreter shutdown indefinitely.  We now log the stack, give the
    process the configured shutdown grace
    (``SUPERFORECASTING_AGENT_TUI_GATEWAY_SHUTDOWN_GRACE_S``, default
    ``_DEFAULT_SHUTDOWN_GRACE_S``) to drain naturally on a background
    thread, and fall back to ``os._exit(0)`` so a wedged write/flush
    can never strand the process.
    """
    # Kill any in-flight TTS playback IMMEDIATELY so the agent's voice can't outlive the
    # gateway. Done synchronously here (not only via atexit) because the grace timer below
    # may os._exit(0) and skip atexit entirely — by then the orphaned player would already
    # be speaking on. Cheap + swallows errors, so it never blocks the shutdown path.
    _stop_audio_playback()

    # SIGPIPE and SIGHUP don't exist on Windows — build the lookup
    # dict from attributes that actually exist on the current platform.
    _signal_names: dict[int, str] = {}
    for _attr in ("SIGPIPE", "SIGTERM", "SIGHUP", "SIGINT", "SIGBREAK"):
        _sig = getattr(signal, _attr, None)
        if _sig is not None:
            _signal_names[int(_sig)] = _attr
    name = _signal_names.get(signum, f"signal {signum}")
    try:
        os.makedirs(os.path.dirname(_CRASH_LOG), exist_ok=True)
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"\n=== {name} received · {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
            )
            if frame is not None:
                f.write("main-thread stack at signal delivery:\n")
                traceback.print_stack(frame, file=f)
            # All live threads — signal may have been triggered by a
            # background thread (write to broken stdout from TTS, etc.).
            import threading as _threading
            for tid, th in _threading._active.items():
                f.write(f"\n--- thread {th.name} (id={tid}) ---\n")
                f.write("".join(traceback.format_stack(sys._current_frames().get(tid))))
    except Exception:
        pass
    print(f"[gateway-signal] {name}", file=sys.stderr, flush=True)

    _arm_shutdown_deadline()

    try:
        sys.exit(0)
    except SystemExit:
        # Re-raise so the main-thread interpreter unwinds and runs
        # atexit + finalisers inside the grace window.  Python signal
        # handlers always run on the main thread, but a worker thread
        # holding ``_stdout_lock`` mid-flush can keep that unwind
        # waiting indefinitely; the daemon timer above is the safety
        # net for that exact case.
        raise


def _arm_shutdown_deadline() -> None:
    """Bound shutdown even when executor workers block before atexit runs."""
    import threading

    timer = threading.Timer(_shutdown_grace_seconds(), lambda: os._exit(0))
    timer.daemon = True
    timer.start()


# SIGPIPE: ignore, don't exit. The old SIG_DFL killed the process
# silently whenever a *background* thread (TTS playback chain, voice
# debug stderr emitter, beep thread) wrote to a pipe the TUI had gone
# quiet on — even though the main thread was perfectly fine waiting on
# stdin.  Ignoring the signal lets Python raise BrokenPipeError on the
# offending write (write_json already handles that with a clean
# sys.exit(0) + _log_exit), which keeps the gateway alive as long as
# the main command pipe is still readable.  Terminal signals still
# route through _log_signal so kills and hangups are diagnosable.
#
# SIGPIPE and SIGHUP don't exist on Windows; guard each installation
# with hasattr so ``python -m tui_gateway.entry`` (spawned by
# ``superforecasting-agent tui``) imports cleanly there. SIGBREAK
# (Windows' Ctrl+Break) is installed when available as a weaker equivalent
# of SIGHUP.
if hasattr(signal, "SIGPIPE"):
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, _log_signal)
if hasattr(signal, "SIGHUP"):
    signal.signal(signal.SIGHUP, _log_signal)
elif hasattr(signal, "SIGBREAK"):
    # Windows-only: Ctrl+Break in a console window delivers SIGBREAK.
    # Route it through the same handler so kills are diagnosable.
    signal.signal(signal.SIGBREAK, _log_signal)
if hasattr(signal, "SIGINT"):
    signal.signal(signal.SIGINT, signal.SIG_IGN)

# Clean stdin-EOF shutdown (TUI closed the pipe) raises no signal — the read loop just
# returns and the interpreter exits. Register the same audio-cleanup on atexit so that
# path also stops the player instead of orphaning it.
atexit.register(_stop_audio_playback)


def _log_exit(reason: str) -> None:
    """Record why the gateway subprocess is shutting down.

    Three exit paths (startup write fail, parse-error-response write fail,
    dispatch-response write fail, stdin EOF) all collapse into a silent
    sys.exit(0) here.  Without this trail the TUI shows "gateway exited"
    with no actionable clue about WHICH broken pipe or WHICH message
    triggered it — the main reason voice-mode turns look like phantom
    crashes when the real story is "TUI read pipe closed on this event".
    """
    try:
        os.makedirs(os.path.dirname(_CRASH_LOG), exist_ok=True)
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"\n=== gateway exit · {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"· reason={reason} ===\n"
            )
    except Exception:
        pass
    print(f"[gateway-exit] {reason}", file=sys.stderr, flush=True)


def _split_host_port(spec: str, default_host: str, default_port: int) -> tuple[str, int]:
    """Parse a ``host:port`` / ``:port`` / bare-``port`` / bare-``host`` spec."""
    spec = (spec or "").strip()
    if ":" in spec:
        h, _, p = spec.rpartition(":")
        host = h or default_host
        try:
            port = int(p)
        except ValueError:
            port = default_port
        return host, port
    if spec.isdigit():
        return default_host, int(spec)
    if spec:
        return spec, default_port
    return default_host, default_port


def _parse_http_args(argv: list[str]) -> dict | None:
    """Return HTTP serve config when ``--http`` is present, else ``None``.

    ``--http [host:port]`` selects HTTP+SSE serve mode (instead of the stdio
    loop). ``--http-token <tok>`` / ``--http-gen-token`` supply or generate the
    bearer token required for non-loopback binds; ``--http-alongside-stdio``
    Tees events onto BOTH stdio and SSE (the fanout seam) rather than replacing
    the stdio sink.
    """
    if "--http" not in argv:
        return None
    host, port = "127.0.0.1", 8765
    token: str | None = None
    generate = False
    alongside = False
    # Hardened default: mint/read {home}/gateway.token and gate every route on it.
    token_file: object = True
    health_public = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--http":
            nxt = argv[i + 1] if i + 1 < len(argv) else None
            if nxt and not nxt.startswith("-"):
                host, port = _split_host_port(nxt, host, port)
                i += 1
        elif a == "--http-token":
            if i + 1 < len(argv):
                token = argv[i + 1]
                i += 1
        elif a == "--http-gen-token":
            generate = True
        elif a == "--http-token-file":
            # Explicit token-file path (default is {home}/gateway.token).
            if i + 1 < len(argv):
                token_file = argv[i + 1]
                i += 1
        elif a == "--http-no-token-file":
            # Legacy loopback-only, token-free mode.
            token_file = False
        elif a == "--http-health-public":
            health_public = True
        elif a == "--http-alongside-stdio":
            alongside = True
        i += 1
    return {
        "host": host,
        "port": port,
        "token": token,
        "generate_token": generate,
        "token_file": token_file,
        "health_public": health_public,
        "alongside_stdio": alongside,
    }


def _run_http(cfg: dict) -> None:
    # HTTP serve mode has no Ink parent to own Ctrl+C, so restore the default
    # SIGINT disposition (module import set it to SIG_IGN for the stdio TUI).
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    from tui_gateway.http_server import serve

    serve(
        cfg["host"],
        cfg["port"],
        token=cfg.get("token"),
        generate_token=cfg.get("generate_token", False),
        token_file=cfg.get("token_file", True),
        health_public=cfg.get("health_public", False),
        alongside_stdio=cfg.get("alongside_stdio", False),
    )


def main():
    http_cfg = _parse_http_args(sys.argv[1:])
    if http_cfg is not None:
        _run_http(http_cfg)
        return

    server.start_build_check()

    _install_sidecar_publisher()
    _install_event_log()

    # MCP tool discovery — inline is safe here: TUI entry is a plain
    # sync loop with no asyncio event loop to block.  Previously ran as
    # a superforecasting_agent/tooling/runtime.py module-level side effect; moved to explicit
    # startup calls to avoid freezing the gateway's loop on lazy import
    # (#16856).
    #
    # Cold-start guard: importing ``tools.mcp_tool`` transitively pulls the
    # full MCP SDK (mcp, pydantic, httpx, jsonschema, starlette parsers —
    # ~200ms on macOS), which runs on the TUI's critical path before
    # ``gateway.ready`` can be emitted.  The overwhelming majority of users
    # have no ``mcp_servers`` configured, in which case every byte of that
    # import is wasted.  Check the config first (cheap — it's already been
    # loaded once by ``_config_mtime`` elsewhere) and only pay the import
    # cost when there's actually MCP work to do.
    try:
        from superforecasting_agent.runtime.config import read_raw_config
        _mcp_servers = (read_raw_config() or {}).get("mcp_servers")
        _has_mcp_servers = isinstance(_mcp_servers, dict) and len(_mcp_servers) > 0
    except Exception:
        # Be conservative: if we can't decide, fall back to the old
        # behaviour and let the discovery path handle its own errors.
        _has_mcp_servers = True
    if _has_mcp_servers:
        try:
            from tools.mcp_tool import discover_mcp_tools
            discover_mcp_tools()
        except Exception:
            pass

    # A4 version handshake: advertise the wire PROTOCOL_VERSION on the hello frame.
    # The TUI compares it against its generated const and WARNS (never hard-fails)
    # on a mismatch — see ui-tui/src/gatewayClient.ts.
    #
    # ``build`` rides the same frame so the TUI knows which APPLICATION build it is
    # from its very first paint. server.build_info(0.0) never makes a network call
    # of its own — it harvests the already-scheduled, 6-hour-cached update check —
    # so this adds no latency here and degrades to just the version when offline.
    from protocol.version import PROTOCOL_VERSION

    if not write_json({
        "jsonrpc": "2.0",
        "method": "event",
        "params": {
            "type": "gateway.ready",
            "payload": {
                "skin": resolve_skin(),
                "protocol_version": PROTOCOL_VERSION,
                "build": server.build_info(),
            },
        },
    }):
        _log_exit("startup write failed (broken stdout pipe before first event)")
        sys.exit(0)

    # Fire scheduled cron jobs while the TUI is open.  Without this, a user
    # running only the TUI never sees their cron jobs trigger — and a manual
    # `cronjob run` (which just marks the job due for "the next scheduler
    # tick") never executes.  Safe alongside the full gateway: the scheduler
    # holds a cross-process file lock.  Started after gateway.ready so it never
    # delays first paint; disable via SUPERFORECASTING_AGENT_TUI_CRON_TICKER=0.
    try:
        server.start_cron_ticker()
    except Exception:
        pass

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            if not write_json({"jsonrpc": "2.0", "error": {"code": -32700, "message": "parse error"}, "id": None}):
                _log_exit("parse-error-response write failed (broken stdout pipe)")
                sys.exit(0)
            continue

        method = req.get("method") if isinstance(req, dict) else None
        resp = dispatch(req)
        if resp is not None:
            if not write_json(resp):
                _log_exit(f"response write failed for method={method!r} (broken stdout pipe)")
                sys.exit(0)

    _log_exit("stdin EOF (TUI closed the command pipe)")
    _arm_shutdown_deadline()
    _stop_audio_playback()


if __name__ == "__main__":
    main()
