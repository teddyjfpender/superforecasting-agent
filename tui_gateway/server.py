import atexit
import contextlib
import contextvars
import copy
import io
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from superforecasting_agent.configuration.goals import configured_goal_turn_budget

from superforecasting_agent.constants import get_agent_home
from superforecasting_agent.runtime.env_loader import load_forecast_dotenv
from superforecasting_agent.environment import INTERACTIVE_ENV_NAMES, is_truthy_value
from tui_gateway.transport import (
    StdioTransport,
    Transport,
    bind_transport,
    current_transport,
    reset_transport,
)

logger = logging.getLogger(__name__)

# Path() because get_agent_home() returns a str when HERMES_HOME is set (e.g. the
# per-test tempdir) — the workspace-dir mkdir below does Path / subdir, which would
# TypeError on a str. Fix at the callsite, per tests/conftest.py.
_hermes_home = Path(get_agent_home())
load_forecast_dotenv(
    hermes_home=_hermes_home, project_env=Path(__file__).parent.parent / ".env"
)

# Anchor the agent's workspace to its home directory. Ensure the docs vault +
# latex dirs exist (so the scoped vault tools resolve and the agent always has
# somewhere to write), and default TERMINAL_CWD to the home so the agent's
# file/terminal tools and relative paths land in ~/.superforecasting-agent/
# instead of wherever the gateway happened to start — keeping all of its notes,
# documents, and scratch work aggregated in one place. setdefault honors an
# explicit override.
for _workspace_subdir in ("docs/vault", "docs/latex"):
    try:
        (_hermes_home / _workspace_subdir).mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.debug("could not create workspace dir %s", _workspace_subdir)
os.environ.setdefault("TERMINAL_CWD", str(_hermes_home))


def _tui_env(name: str, default: str = "") -> str:
    """Read a TUI value: the per-session toggle (TUI_<name>) wins, else the
    fork-native/legacy os.environ aliases."""

    toggle = _session_toggle_value(f"TUI_{name}")
    if toggle is not None:
        return toggle
    for key in (
        f"SUPERFORECASTING_AGENT_TUI_{name}",
        f"FORECAST_TUI_{name}",
        f"HERMES_TUI_{name}",
    ):
        value = os.environ.get(key)
        if value is not None:
            return value
    return default


def _runtime_env(name: str, default: str = "") -> str:
    """Read a runtime value: the per-session toggle (seeded into the contextvar on this
    run thread) wins; else the fork-native/legacy os.environ aliases."""

    toggle = _session_toggle_value(name)
    if toggle is not None:
        return toggle
    for key in (
        f"SUPERFORECASTING_AGENT_{name}",
        f"FORECAST_{name}",
        f"HERMES_{name}",
    ):
        value = os.environ.get(key)
        if value is not None:
            return value
    return default


def _runtime_env_value(name: str, default: str = "") -> str:
    toggle = _session_toggle_value(name)
    if toggle and toggle.strip():
        return toggle.strip()
    for key in (
        f"SUPERFORECASTING_AGENT_{name}",
        f"FORECAST_{name}",
        f"HERMES_{name}",
    ):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    return default


def _first_runtime_env_value(names: tuple[str, ...], default: str = "") -> str:
    for name in names:
        value = _runtime_env_value(name)
        if value:
            return value
    return default


def _set_runtime_env(name: str, value: str) -> None:
    """Set fork-native and legacy runtime aliases for in-process state."""

    os.environ[f"SUPERFORECASTING_AGENT_{name}"] = value
    os.environ[f"FORECAST_{name}"] = value
    os.environ[f"HERMES_{name}"] = value


# Per-session runtime toggles (the model a session switched to), keyed by session_key.
# They deliberately never write os.environ: doing so lets one TUI/Slack session become
# another session's startup default. _set_session_context seeds this state into the
# tenant_runtime contextvar on each run thread.
_session_toggles: dict[str, dict[str, str]] = {}


def _store_session_toggle(session_key: str, name: str, value: str) -> None:
    """Store a runtime toggle for exactly one session."""
    if session_key:
        _session_toggles.setdefault(session_key, {})[name] = value


def _session_toggle_value(name: str) -> str | None:
    """This run thread's per-session toggle value (seeded from _session_toggles), or
    None when unset — then the reader falls back to the os.environ aliases."""
    try:
        from agent.tenant_runtime import get_toggle

        return get_toggle(name)
    except Exception:
        return None


# ── Panic logger ─────────────────────────────────────────────────────
# Gateway crashes in a TUI session leave no forensics: stdout is the
# JSON-RPC pipe (TUI side parses it, doesn't log raw), the root logger
# only catches handled warnings, and the subprocess exits before stderr
# flushes through the stderr->gateway.stderr event pump. This hook
# appends every unhandled exception to the active home logs/tui_gateway_crash.log
# AND re-emits a one-line summary to stderr so the TUI can surface it in
# Activity — exactly what was missing when the voice-mode turns started
# exiting the gateway mid-TTS.
_CRASH_LOG = os.path.join(_hermes_home, "logs", "tui_gateway_crash.log")


def _panic_hook(exc_type, exc_value, exc_tb):
    import traceback

    trace = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        os.makedirs(os.path.dirname(_CRASH_LOG), exist_ok=True)
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"\n=== unhandled exception · {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
            )
            f.write(trace)
    except Exception:
        pass
    # Stderr goes through to the TUI as a gateway.stderr Activity line —
    # the first line here is what the user will see without opening any
    # log files.  Rest of the stack is still in the log for full context.
    first = (
        str(exc_value).strip().splitlines()[0]
        if str(exc_value).strip()
        else exc_type.__name__
    )
    print(f"[gateway-crash] {exc_type.__name__}: {first}", file=sys.stderr, flush=True)
    # Chain to the default hook so the process still terminates normally.
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _panic_hook


def _thread_panic_hook(args):
    # threading.excepthook signature: SimpleNamespace(exc_type, exc_value, exc_traceback, thread)
    import traceback

    trace = "".join(
        traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
    )
    try:
        os.makedirs(os.path.dirname(_CRASH_LOG), exist_ok=True)
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"\n=== thread exception · {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"· thread={args.thread.name} ===\n"
            )
            f.write(trace)
    except Exception:
        pass
    first_line = (
        str(args.exc_value).strip().splitlines()[0]
        if str(args.exc_value).strip()
        else args.exc_type.__name__
    )
    print(
        f"[gateway-crash] thread {args.thread.name} raised {args.exc_type.__name__}: {first_line}",
        file=sys.stderr,
        flush=True,
    )


threading.excepthook = _thread_panic_hook

def start_build_check() -> None:
    """Schedule the non-blocking update check when a transport starts."""
    try:
        from superforecasting_agent.runtime.banner import prefetch_update_check

        prefetch_update_check()
    except Exception:
        pass

from tui_gateway.render import make_stream_renderer, render_diff, render_message

_methods: dict[str, callable] = {}
_pending: dict[str, tuple[str, threading.Event]] = {}
_answers: dict[str, str] = {}
_stdout_lock = threading.Lock()
try:
    _slash_timeout = float(_tui_env("SLASH_TIMEOUT_S") or "45")
except (ValueError, TypeError):
    _slash_timeout = 45.0
_SLASH_WORKER_TIMEOUT_S = max(5.0, _slash_timeout)
_DETAIL_SECTION_NAMES = ("thinking", "tools", "subagents", "activity")
_DETAIL_MODES = frozenset({"hidden", "collapsed", "expanded"})

# ── Async RPC dispatch (#12546) ──────────────────────────────────────
# A handful of handlers block the dispatcher loop in entry.py for seconds
# to minutes (slash.exec, cli.exec, shell.exec, session.resume,
# session.branch, session.compress, skills.manage).  While they're running, inbound RPCs —
# notably approval.respond and session.interrupt — sit unread in the
# stdin pipe.  We route only those slow handlers onto a small thread pool;
# everything else stays on the main thread so ordering stays sane for the
# fast path.  write_json is already _stdout_lock-guarded, so concurrent
# response writes are safe.
_LONG_HANDLERS = frozenset(
    {
        "auth.start",
        "browser.manage",
        "cli.exec",
        "forecast.bench",
        "forecast.calibration",
        "forecast.command",
        "forecast.onboard_commit",
        "forecast.theses",
        "forecast.workspace",
        "llm.oneshot",
        "market.quotes",
        "market.search",
        "markets.model.renarrate",
        "news.search",
        "pm.book",
        "pm.detail",
        "pm.history",
        "pm.list",
        "pm.stream.start",
        "pm.stream.stop",
        "session.branch",
        "session.branch_replace",
        "session.compress",
        "session.resume",
        "shell.exec",
        "skills.manage",
        "slash.exec",
    }
)

try:
    _rpc_pool_workers = max(
        2, int(_tui_env("RPC_POOL_WORKERS") or "4")
    )
except (ValueError, TypeError):
    _rpc_pool_workers = 4
from superforecasting_agent.hosting.workers import HostStopping
from superforecasting_agent.hosting.runtime import RuntimeHost
from superforecasting_agent.hosting.sessions import SessionBusy, dispose_session, finalize_session, in_use, replacement, use_session

_host = RuntimeHost(max_workers=_rpc_pool_workers)


# Embedded hosts retain their process streams. The stdio entrypoint explicitly
# owns redirection while serving its JSON-RPC command pipe.
_real_stdout = sys.stdout

# Module-level stdio transport — fallback sink when no transport is bound via
# contextvar or session. Stream resolved through a lambda so runtime monkey-
# patches of `_real_stdout` (used extensively in tests) still land correctly.
_stdio_transport = StdioTransport(lambda: _real_stdout, _stdout_lock)


class _SlashWorker:
    """Persistent classic CLI subprocess for slash commands."""

    def __init__(self, session_key: str, model: str):
        self._lock = threading.Lock()
        self._seq = 0
        self._close_lock = threading.Lock()
        self._readers = []
        self.stderr_tail: list[str] = []
        self.stdout_queue: queue.Queue[dict | None] = queue.Queue()

        argv = [
            sys.executable,
            "-m",
            "tui_gateway.slash_worker",
            "--session-key",
            session_key,
        ]
        if model:
            argv += ["--model", model]

        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=os.getcwd(),
            env=os.environ.copy(),
        )
        try:
            for target in (self._drain_stdout, self._drain_stderr):
                reader = threading.Thread(target=target, daemon=True)
                reader.start()
                self._readers.append(reader)
        except BaseException:
            self.close()
            raise

    def _drain_stdout(self):
        try:
            with self.proc.stdout as stream:
                for line in stream:
                    try:
                        self.stdout_queue.put(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        finally:
            self.stdout_queue.put(None)

    def _drain_stderr(self):
        with self.proc.stderr as stream:
            for line in stream:
                if text := line.rstrip("\n"):
                    self.stderr_tail = (self.stderr_tail + [text])[-80:]

    def run(self, command: str) -> str:
        if self.proc.poll() is not None:
            raise RuntimeError("slash worker exited")

        with self._lock:
            self._seq += 1
            rid = self._seq
            self.proc.stdin.write(json.dumps({"id": rid, "command": command}) + "\n")
            self.proc.stdin.flush()

            while True:
                try:
                    msg = self.stdout_queue.get(timeout=_SLASH_WORKER_TIMEOUT_S)
                except queue.Empty:
                    raise RuntimeError("slash worker timed out")
                if msg is None:
                    break
                if msg.get("id") != rid:
                    continue
                if not msg.get("ok"):
                    raise RuntimeError(msg.get("error", "slash worker failed"))
                return str(msg.get("output", "")).rstrip()

            raise RuntimeError(
                f"slash worker closed pipe{': ' + chr(10).join(self.stderr_tail[-8:]) if self.stderr_tail else ''}"
            )

    def close(self):
        with self._close_lock:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=1)
            if self.proc.stdin is not None:
                self.proc.stdin.close()
            for reader in self._readers:
                reader.join(timeout=1)
            if any(reader.is_alive() for reader in self._readers):
                raise RuntimeError("slash worker pipe readers did not stop")
            # Also covers construction failure before a reader started.
            for stream in (self.proc.stdout, self.proc.stderr):
                if stream is not None:
                    stream.close()


def _load_busy_input_mode() -> str:
    display = _load_cfg().get("display")
    if not isinstance(display, dict):
        display = {}
    raw = str(display.get("busy_input_mode", "") or "").strip().lower()
    return raw if raw in {"queue", "steer", "interrupt"} else "interrupt"


def _notify_session_boundary(event_type: str, session_id: str | None) -> None:
    """Fire session lifecycle hooks with CLI parity."""
    try:
        from superforecasting_agent.runtime.plugins import invoke_hook as _invoke_hook

        _invoke_hook(event_type, session_id=session_id, platform="tui")
    except Exception:
        pass


def _finalize_session(
    session: dict | None,
    end_reason: str = "tui_close",
    *,
    mark_ended: bool = True,
) -> None:
    if not session:
        return

    def end_session(session_id: str, reason: str) -> None:
        db = _get_db()
        if db is None:
            raise RuntimeError("Session store unavailable; session close can be retried")
        db.end_session(session_id, reason)

    finalize_session(
        session, end_session=end_session, notify=_notify_session_boundary,
        end_reason=end_reason, mark_ended=mark_ended,
    )


# ── Cron ticker ───────────────────────────────────────────────────────
#
# The full gateway (gateway/run.py) runs a background thread that ticks the
# cron scheduler every 60s so scheduled jobs fire automatically.  The TUI
# gateway is a separate, lighter process and historically had NO ticker — so
# a user running only the TUI never saw their cron jobs fire, and a manual
# `cronjob run` (which just sets next_run_at=now and waits for "the next
# scheduler tick") silently never executed.  Run the same ticker here.
#
# The scheduler holds a cross-process file lock (.tick.lock), so this is safe
# even if the full gateway is also running — only one tick executes at a time.
# Off-switch: SUPERFORECASTING_AGENT_TUI_CRON_TICKER=0 (or FORECAST_/HERMES_
# aliases). Interval override: ..._TUI_CRON_TICKER_INTERVAL (seconds).
_cron_ticker_stop = threading.Event()
_cron_ticker_thread: threading.Thread | None = None


def _cron_ticker_disabled() -> bool:
    return _tui_env("CRON_TICKER", "1").strip().lower() in {"0", "off", "false", "no"}


def _cron_ticker_interval() -> int:
    raw = _tui_env("CRON_TICKER_INTERVAL", "").strip()
    if raw:
        try:
            value = int(float(raw))
            if value > 0:
                return value
        except ValueError:
            pass
    return 60


def _cron_ticker_loop(stop_event: threading.Event, interval: int) -> None:
    # Deferred import: the cron scheduler pulls in croniter/agent machinery we
    # don't want on the TUI's cold-start critical path.
    from cron.scheduler import tick as cron_tick

    while not stop_event.is_set():
        try:
            # No adapters/loop: local-only jobs save their output to disk; jobs
            # configured to deliver to a platform use the scheduler's standalone
            # send path (asyncio.run in a worker thread).
            count = cron_tick(verbose=False)
            if count:
                # Sessionless notification — lands on the stdio transport so the
                # TUI can surface "N cron job(s) fired" if it chooses to.
                write_json({
                    "jsonrpc": "2.0",
                    "method": "event",
                    "params": {"type": "cron.fired", "payload": {"count": count}},
                })
        except Exception:
            # A single bad tick must never kill the ticker — keep looping.
            pass
        # Ride the SAME tick for the review due-sweeper: close the gap between a
        # review going "due" on the Desk and something actually acting on it (only
        # the nightly cron did, historically). Gated to its own cadence internally,
        # cheap when nothing is due, and fully fail-open — a bad sweep never kills
        # the ticker.
        try:
            _maybe_run_review_sweep()
        except Exception:
            pass
        stop_event.wait(interval)


def start_cron_ticker() -> None:
    """Start the background cron ticker once per process (idempotent)."""
    global _cron_ticker_thread
    if _cron_ticker_thread is not None or _cron_ticker_disabled():
        return
    _cron_ticker_thread = _host.workers.start(
        lambda: _cron_ticker_loop(_cron_ticker_stop, _cron_ticker_interval()),
        name="forecast-cron-ticker",
    )


def _stop_cron_ticker() -> None:
    _cron_ticker_stop.set()


# ── Review due-sweeper ────────────────────────────────────────────────
#
# Rides the cron ticker above (no new thread subsystem). Every ticker iteration
# calls _maybe_run_review_sweep(); it runs the deterministic sweep AT MOST once
# per forecasting.reviews.sweep_interval_minutes (default 10; 0 disables). The
# sweep itself is run_due_reviews() with its defaults — the SAME work the nightly
# self-check cron does, minus any agent/LLM runner. Guards: never two concurrent
# sweeps (an in-flight flag), and never sweep when the nightly cron fired within
# the interval (dedupe against the cron job's last_run_at). Fully fail-open.
_review_sweep_state_lock = threading.Lock()
_review_sweep_running = False
# The wall-clock (ISO-Z) the sweeper is next ELIGIBLE to run; None = run on the
# next tick. Read by the forecast.reviews.next RPC for the TUI countdown.
_review_sweep_next_tick_at: str | None = None


def _review_sweep_now_iso() -> str:
    from forecasting.models import utc_now_iso

    return utc_now_iso()


def _iso_add_minutes(ts: str, minutes: int) -> str:
    try:
        base = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        base = datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return (
        (base + timedelta(minutes=minutes))
        .astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _emit_review_sweep(phase: str, payload: dict) -> None:
    """Emit a sessionless ``review.sweep`` event (mirrors the ``cron.fired`` frame)."""
    body = {"phase": phase}
    body.update(payload or {})
    write_json({
        "jsonrpc": "2.0",
        "method": "event",
        "params": {"type": "review.sweep", "payload": body},
    })


def _nightly_self_check_job() -> dict | None:
    try:
        from forecasting.scheduler import forecast_self_check_job

        return forecast_self_check_job()
    except Exception:
        return None


def _nightly_ran_within(now_iso: str, minutes: int) -> bool:
    """True when the nightly self-check cron's ``last_run_at`` is within ``minutes``
    of now — the dedupe guard so a catch-up sweep never doubles the nightly work."""
    job = _nightly_self_check_job()
    last = (job or {}).get("last_run_at")
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    if (last_dt.tzinfo is None) != (now_dt.tzinfo is None):
        last_dt = last_dt.replace(tzinfo=None)
        now_dt = now_dt.replace(tzinfo=None)
    age_min = (now_dt - last_dt).total_seconds() / 60.0
    # A future last_run_at (age negative) is degenerate; treat it as "just ran"
    # and skip — fail-closed toward avoiding double work.
    return age_min < minutes


def _persist_review_sweep_state(result: dict) -> None:
    try:
        from forecasting.cron_runner import (
            read_review_sweeper_state,
            write_review_sweeper_state,
        )

        prior = read_review_sweeper_state()
        write_review_sweeper_state({
            "last_tick_at": result.get("last_tick_at"),
            # Preserve the last time a sweep ACTUALLY ran across skip-writes.
            "last_sweep_at": result.get("last_sweep_at") or prior.get("last_sweep_at"),
            "last_sweep_started_at": (
                result.get("started_at") or prior.get("last_sweep_started_at")
            ),
            "last_sweep_completed_at": (
                result.get("completed_at") or prior.get("last_sweep_completed_at")
            ),
            # Persist the in-flight edge, not just the terminal result. A long
            # deterministic sweep can otherwise look indistinguishable from a
            # dead ticker to `forecast doctor` in another process.
            "running": bool(result.get("running")),
            "ran": bool(result.get("ran")),
            "due_count": int(result.get("due_count") or 0),
            "proposals": int(result.get("proposals") or 0),
            "alerts": int(result.get("alerts") or 0),
            "duration_ms": int(result.get("duration_ms") or 0),
            "skipped_reason": result.get("skipped_reason"),
        })
    except Exception:
        pass


def _run_review_sweep(now: str | None = None) -> dict:
    """Run the deterministic due-review sweep IF anything is due AND the nightly
    cron did not just run. NO agent/LLM (``run_due_reviews`` defaults). Fail-open:
    any error degrades to a skipped result and never propagates to the ticker."""
    from forecasting.cron_runner import (
        parse_review_sweep_report,
        resolve_review_sweep_interval_minutes,
        run_due_reviews,
    )

    now_iso = now or _review_sweep_now_iso()
    interval = resolve_review_sweep_interval_minutes()
    result: dict = {
        "ran": False,
        "due_count": 0,
        "skipped_reason": None,
        "proposals": 0,
        "alerts": 0,
        "duration_ms": 0,
        "last_tick_at": now_iso,
        "started_at": None,
        "completed_at": None,
        "running": False,
    }

    if interval <= 0:
        result["skipped_reason"] = "disabled"
        return result

    # Cheap due check — one indexed COUNT. The common "nothing due" case is free.
    try:
        from forecasting.ledger import ForecastLedger

        from forecasting.lifecycle import lifecycle_status

        ledger = ForecastLedger()
        due_count = ledger.count_due_scheduled_reviews(now=now_iso)
        lifecycle = lifecycle_status(ledger, now=now_iso)["counts"]
        result["lifecycle"] = lifecycle
        finalization_due = lifecycle["ready_tasks"] + lifecycle["missing_tasks"] + lifecycle.get("review_reminders_due", 0)
    except Exception:
        logger.exception("review sweep: due check failed")
        result["skipped_reason"] = "due_check_failed"
        return result
    result["due_count"] = int(due_count)
    if due_count <= 0 and finalization_due <= 0:
        result["skipped_reason"] = "none_due"
        _persist_review_sweep_state(result)
        return result

    # Nightly dedupe: don't double the work the nightly cron just did.
    if finalization_due <= 0 and _nightly_ran_within(now_iso, interval):
        result["skipped_reason"] = "nightly_recent"
        _persist_review_sweep_state(result)
        return result

    # No-concurrent guard — atomic test-and-set on the in-flight flag.
    global _review_sweep_running
    with _review_sweep_state_lock:
        if _review_sweep_running:
            result["skipped_reason"] = "already_running"
            return result
        _review_sweep_running = True

    started = time.monotonic()
    result["started_at"] = now_iso
    result["running"] = True
    _persist_review_sweep_state(result)
    _emit_review_sweep("started", {"due_count": int(due_count)})
    try:
        # The SAME sweep the nightly runs — NO reforecast_runner → no LLM/agent.
        report = run_due_reviews()
        counts = parse_review_sweep_report(report)
        result["proposals"] = int(counts.get("proposals", 0))
        result["alerts"] = int(counts.get("alerts", 0))
        result["ran"] = True
        result["last_sweep_at"] = now_iso
    except Exception:
        logger.exception("review sweep: run_due_reviews failed")
        result["skipped_reason"] = "sweep_error"
    finally:
        with _review_sweep_state_lock:
            _review_sweep_running = False
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    result["running"] = False
    result["completed_at"] = _review_sweep_now_iso()
    _emit_review_sweep(
        "done",
        {
            "proposals": result["proposals"],
            "alerts": result["alerts"],
            "duration_ms": result["duration_ms"],
        },
    )
    _persist_review_sweep_state(result)
    return result


def _maybe_run_review_sweep() -> dict | None:
    """Ride one cron-ticker iteration: run the due-sweep at most once per configured
    interval (the ticker itself fires every ~60s). Returns the sweep result, or
    None when disabled / not yet time."""
    from forecasting.cron_runner import resolve_review_sweep_interval_minutes

    interval = resolve_review_sweep_interval_minutes()
    if interval <= 0:
        return None
    global _review_sweep_next_tick_at
    now_iso = _review_sweep_now_iso()
    if _review_sweep_next_tick_at is not None and now_iso < _review_sweep_next_tick_at:
        return None  # not yet time for the next sweep
    _review_sweep_next_tick_at = _iso_add_minutes(now_iso, interval)
    return _run_review_sweep(now=now_iso)


def _reset_runtime_services() -> None:
    global _cron_ticker_stop, _cron_ticker_thread
    _cron_ticker_stop = threading.Event()
    _cron_ticker_thread = None


def start_runtime() -> None:
    _host.start(reset_services=_reset_runtime_services)


def _stop_runtime_services() -> None:
    _stop_cron_ticker()


def _release_runtime_prompts(sid: str, session: dict) -> None:
    _clear_pending(sid)
    from tools.approval import resolve_gateway_approval
    resolve_gateway_approval(session["session_key"], "deny", resolve_all=True)


def _interrupt_runtime_delegations() -> None:
    from tools.async_delegation import interrupt_all
    interrupt_all(reason="runtime_shutdown")


def _close_drained_session(sid: str, session: dict, db) -> None:
    _close_runtime_session(sid, mark_ended=False, drained=True)


def shutdown_runtime(timeout: float = 5.0) -> bool:
    return _host.shutdown(
        timeout,
        stop_services=_stop_runtime_services,
        release_prompts=_release_runtime_prompts,
        interrupt_delegations=_interrupt_runtime_delegations,
        close_session=_close_drained_session,
    )


atexit.register(shutdown_runtime, 0)


# ── Plumbing ──────────────────────────────────────────────────────────


def _get_db():
    return _host.store.get()


def _db_unavailable_error(rid, *, code: int):
    detail = _host.store.last_error or "state.db unavailable"
    return _err(rid, code, f"state.db unavailable: {detail}")


def write_json(obj: dict) -> bool:
    """Emit one JSON frame. Routes via the most-specific transport available.

    Precedence:

    1. Event frames with a session id → the transport stored on that session,
       so async events land with the client that owns the session even if
       the emitting thread has no contextvar binding.
    2. Otherwise the transport bound on the current context (set by
       :func:`dispatch` for the lifetime of a request).
    3. Otherwise the module-level stdio transport, matching the historical
       behaviour and keeping tests that monkey-patch ``_real_stdout`` green.
    """
    if obj.get("method") == "event":
        sid = ((obj.get("params") or {}).get("session_id")) or ""
        if sid and (t := (_host.sessions.get(sid) or {}).get("transport")) is not None:
            return t.write(obj)

    return (current_transport() or _stdio_transport).write(obj)


def _turn_recovery(db, session_key, *, recover=False):
    from superforecasting_agent.storage import turns as turn_journal
    if not callable(getattr(db, "_execute_write", None)):
        return None
    result = turn_journal.latest(db, session_key, recover=recover)
    return result if isinstance(result, dict) else None


def _emit(event: str, sid: str, payload: dict | None = None):
    session = _host.sessions.get(sid, {})
    turn_id = session.get("turn_id")
    if turn_id and event in ("message.start", "message.delta", "message.complete", "error"):
        payload = dict(payload or {})
        if payload.get("turn_id", turn_id) != turn_id:
            return
        payload["turn_id"] = turn_id
        try:
            from superforecasting_agent.storage import turns as turn_journal
            status = "error" if event == "error" else payload.get("status", "running")
            receipt = turn_journal.transition(_get_db(), turn_id, status,
                delta=payload.get("text", "") if event == "message.delta" else None,
                text=(payload.get("text") or None) if event == "message.complete" else None,
                error=payload.get("message") if event == "error" else None)
            if event in ("message.start", "message.delta") and receipt["status"] in turn_journal.TERMINAL:
                return
            payload["durable_status"] = receipt["status"]
        except Exception:
            logger.exception("Turn receipt could not be persisted")
            payload["durable_status"] = "unavailable"
            payload["warning"] = "Turn recovery state could not be saved; keep this response before exiting."
    elif session.get("turn_persistence_unavailable") and event in ("message.start", "message.delta", "message.complete", "error"):
        payload = {**(payload or {}), "durable_status": "unavailable",
                   "warning": "Session storage is unavailable; keep this response before exiting."}
    params = {"type": event, "session_id": sid}
    if payload is not None:
        params["payload"] = payload
    write_json({"jsonrpc": "2.0", "method": "event", "params": params})


def _status_update(sid: str, kind: str, text: str | None = None):
    body = (text if text is not None else kind).strip()
    if not body:
        return
    _emit(
        "status.update",
        sid,
        {"kind": kind if text is not None else "status", "text": body},
    )


def _estimate_image_tokens(width: int, height: int) -> int:
    """Very rough UI estimate for image prompt cost.

    Uses 512px tiles at ~85 tokens/tile as a lightweight cross-provider hint.
    This is intentionally approximate and only used for attachment display.
    """
    if width <= 0 or height <= 0:
        return 0
    return max(1, (width + 511) // 512) * max(1, (height + 511) // 512) * 85


def _image_meta(path: Path) -> dict:
    meta = {"name": path.name}
    try:
        from PIL import Image

        with Image.open(path) as img:
            width, height = img.size
        meta["width"] = int(width)
        meta["height"] = int(height)
        meta["token_estimate"] = _estimate_image_tokens(int(width), int(height))
    except Exception:
        pass
    return meta


def _ok(rid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid, code: int, msg: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}


def register_method(name: str, fn: "callable") -> "callable":
    """Register an RPC handler at runtime into the same dispatch dict the
    ``@method`` decorator populates.

    Lets a plugin / extension add (or override) a JSON-RPC handler after import
    time without the static decorator. Returns *fn* so it can be used as a
    decorator too. The decorator below now routes through here, so both paths
    stay byte-identical in behavior.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("register_method: name must be a non-empty string")
    if not callable(fn):
        raise TypeError("register_method: fn must be callable")
    _methods[name] = fn
    return fn


def method(name: str):
    def dec(fn):
        return register_method(name, fn)

    return dec


def rpc_validated(name: str):
    """``@method`` + Arc-A protocol-model validation for the ``forecast.*`` family.

    VALIDATE-ONLY semantics — deliberately safer than the pm/market re-dump path:
    the request is checked against the registered request model and the SUCCESS
    result against the response model, but the handler's ORIGINAL result is ALWAYS
    returned UNCHANGED. This family's responses are big, partial builder payloads;
    re-serialising them would risk dropping/adding keys, so we validate for DRIFT
    only (a genuine handler/model disagreement is logged) and the wire can never
    regress — the JSON on the wire is byte-for-byte what the handler emitted.

    The request is validated-and-LOGGED but NEVER short-circuits: the forecast
    handlers own a richer error taxonomy (4003 / 4004 / 5008 / 5009) than pm/market's
    uniform -32602, so the handler's own field checks stay the sole gate and no error
    code changes. Falls back to a plain ``@method`` registration if the method has no
    registered spec (it always does — every wrapped method is in ``RPC_SPECS``)."""

    try:
        from pydantic import ValidationError

        from protocol import RPC_BY_METHOD
    except Exception:  # pragma: no cover - the protocol package is always importable
        return method(name)

    spec = RPC_BY_METHOD.get(name)
    if spec is None:  # pragma: no cover - every wrapped method is registered
        return method(name)

    def dec(fn):
        def wrapped(rid, params):
            data = params if isinstance(params, dict) else {}
            try:
                spec.request.model_validate(data)
            except ValidationError as exc:
                logger.debug(
                    "rpc %s request did not validate (passing to handler unchanged): %s",
                    name, exc,
                )
            resp = fn(rid, params)
            if isinstance(resp, dict) and isinstance(resp.get("result"), dict):
                try:
                    spec.response.model_validate(resp["result"])
                except ValidationError as exc:
                    logger.debug(
                        "rpc %s response did not validate (wire returned UNCHANGED): %s",
                        name, exc,
                    )
            return resp

        wrapped.__name__ = getattr(fn, "__name__", "rpc_" + name.replace(".", "_"))
        return register_method(name, wrapped)

    return dec


def _normalize_request(req: Any) -> tuple[Any, str, dict] | dict:
    """Validate a JSON-RPC request enough for safe local dispatch."""
    if not isinstance(req, dict):
        return _err(None, -32600, "invalid request: expected an object")

    rid = req.get("id")
    method = req.get("method")
    if not isinstance(method, str) or not method:
        return _err(rid, -32600, "invalid request: method must be a non-empty string")

    params = req.get("params", {})
    if params is None:
        params = {}
    elif not isinstance(params, dict):
        return _err(rid, -32602, "invalid params: expected an object")

    return rid, method, params


def handle_request(req: dict) -> dict | None:
    normalized = _normalize_request(req)
    if isinstance(normalized, dict):
        return normalized

    rid, method, params = normalized
    fn = _methods.get(method)
    if not fn:
        return _err(rid, -32601, f"unknown method: {method}")
    session = _host.sessions.get(params.get("session_id")) if isinstance(params.get("session_id"), str) else None
    try:
        if session is not None and method not in {"session.close", "session.resume", "session.branch_replace", "tools.configure"}:
            with use_session(session):
                return fn(rid, params)
        return fn(rid, params)
    except SessionBusy as exc:
        return _err(rid, 4009, str(exc))
    except HostStopping:
        return _err(rid, 5030, "runtime host is stopping")


def dispatch(req: dict, transport: Optional[Transport] = None) -> dict | None:
    try:
        with _host.workers.operation():
            return _dispatch(req, transport)
    except HostStopping:
        return _err(req.get("id") if isinstance(req, dict) else None, 5030, "runtime host is stopping")


def _dispatch(req: dict, transport: Optional[Transport] = None) -> dict | None:
    """Route inbound RPCs — long handlers to the pool, everything else inline.

    Returns a response dict when handled inline. Returns None when the
    handler was scheduled on the pool; the worker writes its own response
    via the bound transport when done.

    *transport* (optional): pins every write produced by this request —
    including any events emitted by the handler — to the given transport.
    Omitting it falls back to the module-level stdio transport, preserving
    the original behaviour for ``tui_gateway.entry``.
    """
    t = transport or _stdio_transport
    token = bind_transport(t)
    try:
        normalized = _normalize_request(req)
        if isinstance(normalized, dict):
            return normalized

        _rid, method, _params = normalized
        if method not in _LONG_HANDLERS:
            return handle_request(req)

        # Snapshot the context so the pool worker sees the bound transport.
        ctx = contextvars.copy_context()

        def run():
            try:
                resp = handle_request(req)
            except Exception as exc:
                resp = _err(req.get("id"), -32000, f"handler error: {exc}")
            if resp is not None:
                t.write(resp)

        _host.workers.submit(lambda: ctx.run(run))

        return None
    finally:
        reset_transport(token)


def _wait_agent(session: dict, rid: str, timeout: float = 30.0) -> dict | None:
    ready = session.get("agent_ready")
    if ready is not None and not ready.wait(timeout=timeout):
        return _err(rid, 5032, "agent initialization timed out")
    err = session.get("agent_error")
    return _err(rid, 5032, err) if err else None


def _initialize_built_agent(sid: str, session: dict, agent) -> None:
    key = session["session_key"]
    try:
        from tools.approval import register_gateway_notify, load_permanent_allowlist

        register_gateway_notify(key, lambda data: _emit("approval.request", sid, data))
        session.pop("_build_notifications_released", None)
        load_permanent_allowlist()
    except Exception:
        pass

    _wire_callbacks(sid)
    _notify_session_boundary("on_session_reset", key)

    info = _session_info(agent)
    warn = _probe_credentials(agent)
    if warn:
        info["credential_warning"] = warn
    cfg_warn = _probe_config_health(_load_cfg())
    if cfg_warn:
        info["config_warning"] = cfg_warn
        logger.warning(cfg_warn)
    _emit("session.info", sid, info)

    session["_notif_stop"] = _start_notification_poller(sid, session)


def _start_agent_build(sid: str, session: dict) -> None:
    """Start building the real AIAgent for a TUI session, once.

    Classic `hermes` shows the prompt before constructing AIAgent; the TUI used
    to eagerly build it during session.create, making startup feel blocked on
    tool discovery/model metadata even though the composer was visible.  Keep
    the shell responsive by deferring this work until the first prompt (or any
    command that actually needs the agent), while retaining the same ready/error
    event contract for the frontend.
    """
    from superforecasting_agent.hosting.builds import execute_build, start_build

    if session.get("agent_ready") is None:
        return
    host = _host
    key = session["session_key"]

    @contextlib.contextmanager
    def construction_scope():
        if host.sessions.get(sid) is not session:
            raise RuntimeError("session closed during agent initialization")
        tokens = _set_session_context(key)
        try:
            yield
        finally:
            _clear_session_context(tokens)


    start_build(
        session,
        build=lambda ready: execute_build(
            session, ready, construct=lambda: _make_agent(sid, key),
            initialize=lambda agent: _initialize_built_agent(sid, session, agent),
            construction_scope=construction_scope,
            report_error=lambda message: _emit("error", sid, {"message": f"agent init failed: {message}"}),
        ),
        start=lambda build: host.workers.start(build, name="forecast-agent-build"),
    )


def _sess_nowait(params, rid):
    s = _host.sessions.get(params.get("session_id") or "")
    return (s, None) if s else (None, _err(rid, 4001, "session not found"))


def _sess(params, rid):
    s, err = _sess_nowait(params, rid)
    if err:
        return (None, err)
    _start_agent_build(params.get("session_id") or "", s)
    return (s, _wait_agent(s, rid))


def _normalize_completion_path(path_part: str) -> str:
    expanded = os.path.expanduser(path_part)
    if os.name != "nt":
        normalized = expanded.replace("\\", "/")
        if (
            len(normalized) >= 3
            and normalized[1] == ":"
            and normalized[2] == "/"
            and normalized[0].isalpha()
        ):
            return f"/mnt/{normalized[0].lower()}/{normalized[3:]}"
    return expanded


# ── Config I/O ────────────────────────────────────────────────────────


# Keep aligned with `INDICATOR_STYLES` / `DEFAULT_INDICATOR_STYLE` in
# ``ui-tui/src/app/interfaces.ts`` — both ends validate against the
# same shape so `config.get indicator` and the live TUI render agree.
_INDICATOR_STYLES: tuple[str, ...] = ("ascii", "emoji", "markers", "unicode")
_INDICATOR_ALIASES: dict[str, str] = {"kaomoji": "markers"}
_INDICATOR_DEFAULT = "unicode"


def _normalize_indicator_style(value: object) -> str:
    raw = str(value).strip().lower()
    return _INDICATOR_ALIASES.get(raw, raw)


def _load_cfg() -> dict:
    return _host.configuration.load(_hermes_home / "config.yaml")


def _save_cfg(cfg: dict):
    _host.configuration.save(_hermes_home / "config.yaml", cfg)


def _set_session_context(session_key: str):
    """Establish this run thread's session context: the gateway session vars AND the
    per-session runtime toggles (seeded into the tenant_runtime contextvar from
    _session_toggles), so a toggle read during this thread's work returns THIS session's
    value. Returns an opaque token bundle for _clear_session_context."""
    session_tokens: list = []
    try:
        from superforecasting_agent.session_context import set_session_vars

        session_tokens = set_session_vars(session_key=session_key)
    except Exception:
        session_tokens = []
    tenant_token = None
    try:
        toggles = _session_toggles.get(session_key)
        if toggles:
            from agent.tenant_runtime import set_tenant_runtime

            tenant_token = set_tenant_runtime(toggles=dict(toggles))
    except Exception:
        tenant_token = None
    return (session_tokens, tenant_token)


def _clear_session_context(tokens) -> None:
    if not tokens:
        return
    session_tokens, tenant_token = tokens if isinstance(tokens, tuple) else (tokens, None)
    if tenant_token is not None:
        try:
            from agent.tenant_runtime import clear_tenant_runtime

            clear_tenant_runtime(tenant_token)
        except Exception:
            pass
    if session_tokens:
        try:
            from superforecasting_agent.session_context import clear_session_vars

            clear_session_vars(session_tokens)
        except Exception:
            pass


def _enable_gateway_prompts() -> None:
    """Route approvals through gateway callbacks instead of CLI input()."""
    os.environ["HERMES_GATEWAY_SESSION"] = "1"
    _set_runtime_env("EXEC_ASK", "1")
    for name in INTERACTIVE_ENV_NAMES:
        os.environ[name] = "1"


# ── Blocking prompt factory ──────────────────────────────────────────


def _block(event: str, sid: str, payload: dict, timeout: int = 300) -> str:
    rid = uuid.uuid4().hex[:8]
    ev = threading.Event()
    _pending[rid] = (sid, ev)
    payload["request_id"] = rid
    _emit(event, sid, payload)
    ev.wait(timeout=timeout)
    _pending.pop(rid, None)
    return _answers.pop(rid, "")


def _clear_pending(sid: str | None = None) -> None:
    """Release pending prompts with an empty answer.

    When *sid* is provided, only prompts owned by that session are
    released — critical for session.interrupt, which must not
    collaterally cancel clarify/sudo/secret prompts on unrelated
    sessions sharing the same tui_gateway process.  When *sid* is
    None, every pending prompt is released (used during shutdown).
    """
    for rid, (owner_sid, ev) in list(_pending.items()):
        if sid is None or owner_sid == sid:
            _answers[rid] = ""
            ev.set()


# ── Agent factory ────────────────────────────────────────────────────


def resolve_skin() -> dict:
    try:
        from superforecasting_agent.runtime.skin_engine import init_skin_from_config, get_active_skin

        init_skin_from_config(_load_cfg())
        skin = get_active_skin()
        appearance = str(
            (_load_cfg().get("display") or {}).get("appearance", "auto")
        ).strip().lower()
        if appearance not in {"light", "dark", "auto"}:
            appearance = "auto"
        return {
            "name": skin.name,
            "colors": skin.colors,
            "branding": skin.branding,
            "banner_logo": skin.banner_logo,
            "banner_hero": skin.banner_hero,
            "tool_prefix": skin.tool_prefix,
            "help_header": (skin.branding or {}).get("help_header", ""),
            "appearance": appearance,
        }
    except Exception:
        return {}


def _resolve_model(cfg: dict | None = None) -> str:
    env = _first_runtime_env_value(("MODEL", "INFERENCE_MODEL"))
    if env:
        return env
    m = (cfg if cfg is not None else _load_cfg()).get("model", "")
    if isinstance(m, dict):
        return str(m.get("default", "") or "").strip()
    if isinstance(m, str) and m:
        return m.strip()
    return "anthropic/claude-sonnet-4"


def _resolve_startup_runtime(cfg: dict | None = None) -> tuple[str, str | None]:
    model = _resolve_model(cfg) if cfg is not None else _resolve_model()
    explicit_provider = _tui_env("PROVIDER").strip()
    if explicit_provider:
        return model, explicit_provider

    explicit_model = _first_runtime_env_value(("MODEL", "INFERENCE_MODEL"))
    if not explicit_model:
        return model, None

    try:
        from superforecasting_agent.runtime.models import detect_static_provider_for_model

        cfg = (cfg if cfg is not None else _load_cfg()).get("model") or {}
        current_provider = (
            (
                str(cfg.get("provider") or "").strip().lower()
                if isinstance(cfg, dict)
                else ""
            )
            or _runtime_env_value("INFERENCE_PROVIDER").lower()
            or "auto"
        )
        detected = detect_static_provider_for_model(explicit_model, current_provider)
        if detected:
            provider, detected_model = detected
            return detected_model, provider
    except Exception:
        pass
    return model, None


def _write_config_key(key_path: str, value):
    """Merge a single setting into the latest profile, preserving user comments."""
    _host.configuration.update(_hermes_home / "config.yaml", key_path, value)


_STATUSBAR_MODES = frozenset({"off", "top", "bottom"})


def _coerce_statusbar(raw) -> str:
    if raw is False:
        return "off"
    if isinstance(raw, str) and (s := raw.strip().lower()) in _STATUSBAR_MODES:
        return s
    return "top"


def _display_mouse_tracking(display: dict) -> bool:
    """Return canonical display.mouse_tracking with legacy tui_mouse fallback."""
    if not isinstance(display, dict):
        return True
    if "mouse_tracking" in display:
        raw = display.get("mouse_tracking")
    else:
        raw = display.get("tui_mouse", True)
    if raw is False or raw == 0:
        return False
    if isinstance(raw, str):
        return raw.strip().lower() not in {"0", "false", "no", "off"}
    return True


def _load_reasoning_config(cfg: dict | None = None) -> dict | None:
    from superforecasting_agent.constants import parse_reasoning_effort

    effort = str(
        ((cfg if cfg is not None else _load_cfg()).get("agent") or {}).get("reasoning_effort", "") or ""
    ).strip()
    return parse_reasoning_effort(effort)


def _load_service_tier(cfg: dict | None = None) -> str | None:
    from superforecasting_agent.constants import parse_service_tier
    return parse_service_tier(((cfg if cfg is not None else _load_cfg()).get("agent") or {}).get("service_tier"))


def _load_show_reasoning() -> bool:
    return bool((_load_cfg().get("display") or {}).get("show_reasoning", False))


def _load_tool_progress_mode(cfg: dict | None = None) -> str:
    env = _tui_env("TOOL_PROGRESS").strip().lower()
    if env in {"off", "new", "all", "verbose"}:
        return env
    raw = ((cfg if cfg is not None else _load_cfg()).get("display") or {}).get("tool_progress", "all")
    if raw is False:
        return "off"
    if raw is True:
        return "all"
    mode = str(raw or "all").strip().lower()
    return mode if mode in {"off", "new", "all", "verbose"} else "all"


def _load_enabled_toolsets(cfg: dict | None = None) -> list[str] | None:
    from superforecasting_agent.tooling.startup_selection import resolve_startup_toolsets

    return resolve_startup_toolsets(
        _tui_env("TOOLSETS"), setting_label="SUPERFORECASTING_AGENT_TUI_TOOLSETS", config=cfg,
        warn=lambda message: print(f"[tui] {message}", file=sys.stderr, flush=True),
    )


def _session_tool_progress_mode(sid: str) -> str:
    return str(_host.sessions.get(sid, {}).get("tool_progress_mode", "all") or "all")


def _tool_progress_enabled(sid: str) -> bool:
    return _session_tool_progress_mode(sid) != "off"


def _restart_slash_worker(session: dict):
    # Compatibility name: invalidate now; recreate only if a legacy command runs.
    from superforecasting_agent.hosting.legacy_commands import invalidate_worker

    try:
        invalidate_worker(session)
    except Exception:
        # Model/config changes already succeeded. Retain the retiring worker and
        # let the next legacy command retry cleanup, without misreporting them.
        logger.exception("legacy command worker cleanup pending")


def _persist_model_switch(result) -> None:
    from superforecasting_agent.runtime.config import save_config

    cfg = _load_cfg()
    model_cfg = cfg.get("model")
    if not isinstance(model_cfg, dict):
        model_cfg = {}
        cfg["model"] = model_cfg

    model_cfg["default"] = result.new_model
    model_cfg["provider"] = result.target_provider
    if result.base_url:
        model_cfg["base_url"] = result.base_url
    else:
        model_cfg.pop("base_url", None)
    save_config(cfg)


def _apply_model_switch(sid: str, session: dict, raw_input: str) -> dict:
    from superforecasting_agent.runtime.model_switch import parse_model_flags, switch_model
    from superforecasting_agent.runtime.runtime_provider import resolve_runtime_provider

    model_input, explicit_provider, persist_global, _force_refresh = parse_model_flags(raw_input)
    if not model_input:
        raise ValueError("model value required")

    agent = session.get("agent")
    if agent:
        current_provider = getattr(agent, "provider", "") or ""
        current_model = getattr(agent, "model", "") or ""
        current_base_url = getattr(agent, "base_url", "") or ""
        current_api_key = getattr(agent, "api_key", "") or ""
    else:
        # No live agent — e.g. the primary provider's sign-in died, so the
        # session never built one.  We only need the CURRENT provider as
        # *context* for switch_model; the TARGET provider's credentials are
        # resolved inside switch_model.  Resolving the current runtime must
        # therefore NEVER abort the switch: a dead current provider (an
        # unauthenticated codex) would otherwise raise "No Codex credentials
        # stored" and trap the user on the very provider they are leaving —
        # the same trap-class as the setup Ctrl+C and copilot dead-token bugs.
        current_model = _resolve_model()
        try:
            runtime = resolve_runtime_provider(requested=None)
            current_provider = str(runtime.get("provider", "") or "")
            current_base_url = str(runtime.get("base_url", "") or "")
            # Preserve a callable api_key (Azure Foundry Entra ID bearer
            # provider) unchanged — ``str(...)`` would produce
            # ``"<function ...>"`` and poison downstream switch_model
            # validation. Match the agent-present branch's behavior above.
            _runtime_key = runtime.get("api_key", "")
            if callable(_runtime_key) and not isinstance(_runtime_key, str):
                current_api_key = _runtime_key
            else:
                current_api_key = str(_runtime_key or "")
        except Exception:
            # Current provider is unauthenticated / unresolvable.  Learn only
            # its slug from config/env (non-raising) so switch_model can still
            # detect a provider change; leave creds empty — switch_model
            # resolves the TARGET fresh and validates ONLY that provider.
            from superforecasting_agent.runtime.runtime_provider import resolve_requested_provider

            current_provider = resolve_requested_provider(None)
            if current_provider == "auto":
                current_provider = ""
            current_base_url = ""
            current_api_key = ""

    # Load user-defined providers so switch_model can resolve named custom
    # endpoints (e.g. "ollama-launch") and validate against saved model lists.
    user_provs = None
    custom_provs = None
    try:
        from superforecasting_agent.runtime.config import get_compatible_custom_providers, load_config

        cfg = load_config()
        user_provs = cfg.get("providers")
        custom_provs = get_compatible_custom_providers(cfg)
    except Exception:
        pass

    result = switch_model(
        raw_input=model_input,
        current_provider=current_provider,
        current_model=current_model,
        current_base_url=current_base_url,
        current_api_key=current_api_key,
        is_global=persist_global,
        explicit_provider=explicit_provider,
        user_providers=user_provs,
        custom_providers=custom_provs,
    )
    if not result.success:
        raise ValueError(result.error_message or "model switch failed")

    if agent:
        agent.switch_model(
            new_model=result.new_model,
            new_provider=result.target_provider,
            api_key=result.api_key,
            base_url=result.base_url,
            api_mode=result.api_mode,
        )
        _restart_slash_worker(session)
        _emit("session.info", sid, _session_info(agent))

    # The switched model belongs to this session. New sessions use the persisted
    # config default; they must never inherit whichever session switched most recently.
    _sess_key = (session or {}).get("session_key")
    _store_session_toggle(_sess_key, "MODEL", result.new_model)
    _store_session_toggle(_sess_key, "INFERENCE_MODEL", result.new_model)
    if result.target_provider:
        _store_session_toggle(_sess_key, "TUI_PROVIDER", result.target_provider)
        _store_session_toggle(_sess_key, "INFERENCE_PROVIDER", result.target_provider)
    if persist_global:
        _persist_model_switch(result)
    return {"value": result.new_model, "warning": result.warning_message or ""}


def _compress_session_history(
    session: dict,
    focus_topic: str | None = None,
    approx_tokens: int | None = None,
    before_messages: list | None = None,
    history_version: int | None = None,
) -> tuple[int, dict]:
    from agent.model_metadata import estimate_request_tokens_rough

    agent = session["agent"]
    # Snapshot history under the lock so the LLM-bound compression call
    # below does NOT hold history_lock for the duration of the request —
    # otherwise other handlers acquiring the lock (prompt.submit etc.)
    # block on the dispatcher loop while compaction runs.
    if before_messages is None or history_version is None:
        with session["history_lock"]:
            before_messages = list(session.get("history", []))
            history_version = int(session.get("history_version", 0))
    history = before_messages
    if len(history) < 4:
        usage = _get_usage(agent)
        return 0, usage
    if approx_tokens is None:
        # Include system prompt + tool schemas so the figure reflects real
        # request pressure, not a transcript-only underestimate (#6217).
        _sys_prompt = getattr(agent, "_cached_system_prompt", "") or ""
        _tools = getattr(agent, "tools", None) or None
        approx_tokens = estimate_request_tokens_rough(
            history, system_prompt=_sys_prompt, tools=_tools
        )
    # Pass system_message=None so AIAgent._compress_context rebuilds the
    # system prompt cleanly via _build_system_prompt(None). Passing the
    # cached prompt (which already contains the agent identity block)
    # makes the rebuild append the identity a second time. Mirrors the
    # CLI's _manual_compress fix for issue #15281.
    compressed, _ = agent._compress_context(
        history,
        None,
        approx_tokens=approx_tokens,
        focus_topic=focus_topic or None,
    )
    with session["history_lock"]:
        current = session.get("history", []) or []
        if int(session.get("history_version", 0)) != history_version:
            # External mutation during compaction (CAS miss). We can only
            # safely OR-merge — fold the concurrent tail onto the new
            # compressed baseline — when the concurrent mutation was
            # APPEND-ONLY, i.e. our snapshot `before_messages` is a genuine
            # prefix of `current`. That holds for prompt.submit / tool
            # results (they only append, never rewrite in place), and there
            # the messages in `current` past the snapshot length are the
            # tail to preserve. But TRUNCATE/REWRITE mutators (session
            # retry/rewind, /new) ALSO bump history_version; for those
            # `before_messages` is NOT a prefix of `current`, and folding
            # the compressed prefix back on would corrupt history. So guard
            # the fold with an explicit prefix check and otherwise fall back
            # to the original safe behaviour: DISCARD the compaction result,
            # leave the concurrent `current` intact, and report no removal.
            # Done under the lock so no new tail can slip in between the read
            # and the write (no race).
            snap_len = len(before_messages)
            is_prefix = (
                len(current) >= snap_len
                and current[:snap_len] == before_messages
            )
            if not is_prefix:
                # Concurrent mutation truncated/rewrote history. Keep the
                # concurrent state and drop our now-stale compaction work.
                usage = _get_usage(agent)
                return 0, usage
            tail = list(current[snap_len:])
            merged = list(compressed) + tail
            session["history"] = merged
            # Adopt the concurrent writer's version + 1 so this compaction is
            # recorded as the latest mutation (the writer bumped to
            # >= history_version + 1; advancing past current keeps the
            # counter monotonic and lets later CAS checks see our write).
            session["history_version"] = (
                int(session.get("history_version", 0)) + 1
            )
            usage = _get_usage(agent)
            # True net removal relative to the snapshot: the snapshot held
            # len(before_messages) messages; the session now holds len(merged)
            # (compressed prefix + folded tail). `len(history) - len(compressed)`
            # would OVER-report by len(tail) because it ignores the tail we
            # re-appended (the caller's after_count = len(merged), so removed
            # must be before_count - after_count for the surfaced numbers to
            # reconcile). Clamp at 0 in case the tail outgrew the compaction.
            return max(0, len(before_messages) - len(merged)), usage
        session["history"] = compressed
        session["history_version"] = history_version + 1
    usage = _get_usage(agent)
    return len(history) - len(compressed), usage


def _sync_session_key_after_compress(
    sid: str,
    session: dict,
    *,
    clear_pending_title: bool = True,
    restart_slash_worker: bool = True,
) -> None:
    """Re-anchor session_key when AIAgent._compress_context rotates session_id.

    AIAgent._compress_context ends the current SessionDB session and creates
    a new continuation session, rotating ``agent.session_id``.  The TUI
    gateway keeps the gateway-side ``session_key`` separate (used for
    approval routing, slash worker init, DB title/history lookups, yolo
    state).  Without this sync, those operations would target the ended
    parent session while the agent writes to the new continuation session.

    Policy flags:
        clear_pending_title: True for manual /compress (title belongs to old
            session). False for post-turn auto-compression (preserve user
            intent so pending_title can be applied to the continuation).
        restart_slash_worker: True for manual /compress and post-turn
            auto-compression (worker holds stale session key). False only
            if the caller manages the worker lifecycle separately.
    """
    agent = session.get("agent")
    new_session_id = getattr(agent, "session_id", None) or ""
    old_key = session.get("session_key", "") or ""
    if not new_session_id or new_session_id == old_key:
        return

    try:
        from tools.approval import (
            disable_session_yolo,
            enable_session_yolo,
            is_session_yolo_enabled,
            register_gateway_notify,
            unregister_gateway_notify,
        )

        try:
            unregister_gateway_notify(old_key)
        except Exception:
            pass
        session["session_key"] = new_session_id
        try:
            yolo_was_on = is_session_yolo_enabled(old_key)
        except Exception:
            yolo_was_on = False
        if yolo_was_on:
            try:
                enable_session_yolo(new_session_id)
                disable_session_yolo(old_key)
            except Exception:
                pass
        try:
            register_gateway_notify(
                new_session_id,
                lambda data: _emit("approval.request", sid, data),
            )
        except Exception:
            pass
    except Exception:
        # Even if the approval module fails to import, still anchor the
        # session_key on the new continuation id so downstream lookups
        # don't keep targeting the ended row.
        session["session_key"] = new_session_id

    if session.get("turn_id"):
        from superforecasting_agent.storage import turns as turn_journal
        turn_journal.reanchor(_get_db(), session["turn_id"], new_session_id)

    if clear_pending_title:
        session["pending_title"] = None
    if restart_slash_worker:
        try:
            _restart_slash_worker(session)
        except Exception:
            pass

    _emit("session.info", sid, _session_info(agent))


def _get_usage(agent) -> dict:
    g = lambda k, fb=None: getattr(agent, k, 0) or (getattr(agent, fb, 0) if fb else 0)
    usage = {
        "model": getattr(agent, "model", "") or "",
        "input": g("session_input_tokens", "session_prompt_tokens"),
        "output": g("session_output_tokens", "session_completion_tokens"),
        "cache_read": g("session_cache_read_tokens"),
        "cache_write": g("session_cache_write_tokens"),
        "reasoning": g("session_reasoning_tokens"),
        "prompt": g("session_prompt_tokens"),
        "completion": g("session_completion_tokens"),
        "total": g("session_total_tokens"),
        "calls": g("session_api_calls"),
    }
    comp = getattr(agent, "context_compressor", None)
    if comp:
        ctx_used = getattr(comp, "last_prompt_tokens", 0) or usage["total"] or 0
        ctx_max = getattr(comp, "context_length", 0) or 0
        if ctx_max:
            usage["context_used"] = ctx_used
            usage["context_max"] = ctx_max
            usage["context_percent"] = max(0, min(100, round(ctx_used / ctx_max * 100)))
        usage["compressions"] = getattr(comp, "compression_count", 0) or 0
    try:
        from agent.usage_pricing import CanonicalUsage, estimate_usage_cost

        cost = estimate_usage_cost(
            usage["model"],
            CanonicalUsage(
                input_tokens=usage["input"],
                output_tokens=usage["output"],
                cache_read_tokens=usage["cache_read"],
                cache_write_tokens=usage["cache_write"],
            ),
            provider=getattr(agent, "provider", None),
            base_url=getattr(agent, "base_url", None),
        )
        usage["cost_status"] = cost.status
        if cost.amount_usd is not None:
            usage["cost_usd"] = float(cost.amount_usd)
    except Exception:
        pass
    return usage


def _probe_credentials(agent) -> str:
    """Light credential check at session creation — returns warning or ''."""
    try:
        key = getattr(agent, "api_key", "") or ""
        provider = getattr(agent, "provider", "") or ""
        # The resolver deliberately returns this sentinel for keyless endpoints.
        if not key:
            return f"No API key configured for provider '{provider}'. Check provider configuration if requests fail."
    except Exception:
        pass
    return ""


def _probe_config_health(cfg: dict) -> str:
    """Flag bare YAML keys (`agent:` with no value → None) that silently
    drop nested settings. Returns warning or ''."""
    if not isinstance(cfg, dict):
        return ""
    warnings: list[str] = []
    null_keys = sorted(k for k, v in cfg.items() if v is None)
    if not null_keys:
        pass
    else:
        keys = ", ".join(f"`{k}`" for k in null_keys)
        warnings.append(
            f"config.yaml has empty section(s): {keys}. "
            f"Remove the line(s) or set them to `{{}}` — "
            f"empty sections silently drop nested settings."
        )
    display_cfg = cfg.get("display")
    agent_cfg = cfg.get("agent")
    if isinstance(display_cfg, dict):
        personality = str(display_cfg.get("personality", "") or "").strip().lower()
        if (
            personality
            and personality not in {"default", "none", "neutral"}
            and isinstance(agent_cfg, dict)
            and agent_cfg.get("personalities") is None
        ):
            warnings.append(
                "`display.personality` is set but `agent.personalities` is empty/null; "
                "forecast style overlay will be skipped."
            )
    return " ".join(warnings).strip()


def _current_profile_name() -> str:
    try:
        from superforecasting_agent.constants import get_active_profile_name

        return get_active_profile_name() or "default"
    except Exception:
        return "default"


def build_info(timeout: float = 0.0) -> dict:
    """The ``BuildInfo`` payload for ``gateway.ready`` / ``session.info``.

    ``timeout=0.0`` (the startup default) makes this a pure memory + tiny-file
    read: it only harvests whatever the startup-scheduled ``prefetch_update_check()``
    background thread has already produced, so it can never delay first paint and
    never touches the network itself. Offline it degrades to just the version.
    """
    try:
        from superforecasting_agent.runtime.banner import get_update_state

        return get_update_state(timeout=timeout)
    except Exception:
        # Last-resort: the version alone still beats showing nothing at all.
        try:
            from superforecasting_agent.runtime import __release_date__, __version__

            return {"version": __version__, "release_date": __release_date__}
        except Exception:
            return {}


def _session_info(agent) -> dict:
    reasoning_config = getattr(agent, "reasoning_config", None)
    reasoning_effort = ""
    if (
        isinstance(reasoning_config, dict)
        and reasoning_config.get("enabled") is not False
    ):
        reasoning_effort = str(reasoning_config.get("effort", "") or "")
    service_tier = getattr(agent, "service_tier", None) or ""
    info: dict = {
        "durable_session_id": getattr(agent, "session_id", None) or "",
        "model": getattr(agent, "model", ""),
        "reasoning_effort": reasoning_effort,
        "service_tier": service_tier,
        "fast": service_tier == "priority",
        "tools": {},
        "skills": {},
        "cwd": os.getenv("TERMINAL_CWD", os.getcwd()),
        "version": "",
        "release_date": "",
        "update_behind": None,
        "update_command": "",
        "usage": _get_usage(agent),
        "profile_name": _current_profile_name(),
    }
    try:
        # A4 version handshake — echo the wire version on session.info too, so a
        # resume/steer path that never re-saw gateway.ready can still revalidate.
        from protocol.version import PROTOCOL_VERSION

        info["protocol_version"] = PROTOCOL_VERSION
    except Exception:
        pass
    try:
        from superforecasting_agent.runtime import __version__, __release_date__

        info["version"] = __version__
        info["release_date"] = __release_date__
    except Exception:
        pass
    try:
        from superforecasting_agent.tooling.runtime import get_toolset_for_tool

        for t in getattr(agent, "tools", []) or []:
            name = t["function"]["name"]
            info["tools"].setdefault(get_toolset_for_tool(name) or "other", []).append(
                name
            )
    except Exception:
        pass
    try:
        from superforecasting_agent.runtime.banner import get_available_skills

        info["skills"] = get_available_skills()
    except Exception:
        pass
    try:
        from tools.mcp_tool import get_mcp_status

        info["mcp_servers"] = get_mcp_status()
    except Exception:
        info["mcp_servers"] = []
    try:
        info["system_prompt"] = getattr(agent, "_cached_system_prompt", "") or ""
    except Exception:
        pass
    try:
        from superforecasting_agent.runtime.banner import get_update_result
        from superforecasting_agent.runtime.config import recommended_update_command

        info["update_behind"] = get_update_result(timeout=0.5)
        info["update_command"] = recommended_update_command()
    except Exception:
        pass
    try:
        # session.info lands well after gateway.ready, by which point the
        # background update check has usually finished — so this frame upgrades a
        # cold-cache "version only" build into a real staleness verdict. The 0.5s
        # budget is the one get_update_result already spent above, so it costs
        # nothing extra.
        info["build"] = build_info(timeout=0.5)
    except Exception:
        pass
    return info


def _tool_ctx(name: str, args: dict) -> str:
    try:
        from agent.display import build_tool_preview

        return build_tool_preview(name, args, max_len=80) or ""
    except Exception:
        return ""


def _fmt_tool_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{round(seconds)}s"
    mins, secs = divmod(int(round(seconds)), 60)
    return f"{mins}m {secs}s" if secs else f"{mins}m"


def _count_list(obj: object, *path: str) -> int | None:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return len(cur) if isinstance(cur, list) else None


def _tool_summary(name: str, result: str, duration_s: float | None) -> str | None:
    try:
        data = json.loads(result)
    except Exception:
        data = None

    dur = _fmt_tool_duration(duration_s)
    suffix = f" in {dur}" if dur else ""
    text = None

    if name == "web_search" and isinstance(data, dict):
        n = _count_list(data, "data", "web")
        if n is not None:
            text = f"Did {n} {'search' if n == 1 else 'searches'}"

    elif name == "web_extract" and isinstance(data, dict):
        n = _count_list(data, "results") or _count_list(data, "data", "results")
        if n is not None:
            text = f"Extracted {n} {'page' if n == 1 else 'pages'}"

    if isinstance(data, dict) and data.get("fallback_warning"):
        warning = str(data.get("fallback_warning") or "").strip()
        if warning:
            return f"{warning}{suffix}"

    return f"{text}{suffix}" if text else None


def _on_tool_start(sid: str, tool_call_id: str, name: str, args: dict):
    session = _host.sessions.get(sid)
    if session is not None:
        try:
            from agent.display import capture_local_edit_snapshot

            snapshot = capture_local_edit_snapshot(name, args)
            if snapshot is not None:
                session.setdefault("edit_snapshots", {})[tool_call_id] = snapshot
        except Exception:
            pass
        session.setdefault("tool_started_at", {})[tool_call_id] = time.time()
    if _tool_progress_enabled(sid):
        # tool.complete is the source of truth for todos (full list from the
        # tool result). args.todos here may be a partial merge update.
        _emit(
            "tool.start",
            sid,
            {"tool_id": tool_call_id, "name": name, "context": _tool_ctx(name, args)},
        )


def _on_tool_complete(sid: str, tool_call_id: str, name: str, args: dict, result: str):
    payload = {"tool_id": tool_call_id, "name": name}
    session = _host.sessions.get(sid)
    snapshot = None
    started_at = None
    if session is not None:
        snapshot = session.setdefault("edit_snapshots", {}).pop(tool_call_id, None)
        started_at = session.setdefault("tool_started_at", {}).pop(tool_call_id, None)
    duration_s = time.time() - started_at if started_at else None
    if duration_s is not None:
        payload["duration_s"] = duration_s
    summary = _tool_summary(name, result, duration_s)
    if summary:
        payload["summary"] = summary
    if name == "todo":
        try:
            data = json.loads(result)
            if isinstance(data, dict) and isinstance(data.get("todos"), list):
                payload["todos"] = data.get("todos")
        except Exception:
            pass
    try:
        from agent.display import render_edit_diff_with_delta

        rendered: list[str] = []
        if render_edit_diff_with_delta(
            name,
            result,
            function_args=args,
            snapshot=snapshot,
            print_fn=rendered.append,
        ):
            payload["inline_diff"] = "\n".join(rendered)
    except Exception:
        pass
    # Ship the CUMULATIVE session usage on every tool.complete so the TUI's
    # liveness counter climbs mid-turn instead of only at message.complete. By
    # the time this callback fires, conversation_loop has already folded the API
    # call that produced THIS tool call into the session_* counters (the fold at
    # response time precedes _execute_tool_calls), so _get_usage(agent) is fresh
    # and monotonic — never a stale pre-fold number.
    agent = session.get("agent") if session is not None else None
    if agent is not None:
        try:
            payload["usage"] = _get_usage(agent)
        except Exception:
            pass
    if _tool_progress_enabled(sid) or payload.get("inline_diff"):
        _emit("tool.complete", sid, payload)


def _on_tool_progress(
    sid: str,
    event_type: str,
    name: str | None = None,
    preview: str | None = None,
    _args: dict | None = None,
    **_kwargs,
):
    if not _tool_progress_enabled(sid):
        return
    if event_type == "tool.started" and name:
        _emit("tool.progress", sid, {"name": name, "preview": preview or ""})
        return
    if event_type == "reasoning.available" and preview:
        _emit("reasoning.available", sid, {"text": str(preview)})
        return
    if event_type.startswith("subagent."):
        payload = {
            "goal": str(_kwargs.get("goal") or ""),
            "task_count": int(_kwargs.get("task_count") or 1),
            "task_index": int(_kwargs.get("task_index") or 0),
        }
        # Identity fields for the TUI spawn tree.  All optional — older
        # emitters that omit them fall back to flat rendering client-side.
        if _kwargs.get("subagent_id"):
            payload["subagent_id"] = str(_kwargs["subagent_id"])
        if _kwargs.get("parent_id"):
            payload["parent_id"] = str(_kwargs["parent_id"])
        if _kwargs.get("depth") is not None:
            payload["depth"] = int(_kwargs["depth"])
        if _kwargs.get("model"):
            payload["model"] = str(_kwargs["model"])
        if _kwargs.get("tool_count") is not None:
            payload["tool_count"] = int(_kwargs["tool_count"])
        if _kwargs.get("toolsets"):
            payload["toolsets"] = [str(t) for t in _kwargs["toolsets"]]
        # Per-branch rollups emitted on subagent.complete (features 1+2+4).
        for int_key in (
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "api_calls",
        ):
            val = _kwargs.get(int_key)
            if val is not None:
                try:
                    payload[int_key] = int(val)
                except (TypeError, ValueError):
                    pass
        if _kwargs.get("cost_usd") is not None:
            try:
                payload["cost_usd"] = float(_kwargs["cost_usd"])
            except (TypeError, ValueError):
                pass
        if _kwargs.get("files_read"):
            payload["files_read"] = [str(p) for p in _kwargs["files_read"]]
        if _kwargs.get("files_written"):
            payload["files_written"] = [str(p) for p in _kwargs["files_written"]]
        if _kwargs.get("output_tail"):
            payload["output_tail"] = list(_kwargs["output_tail"])  # list of dicts
        if name:
            payload["tool_name"] = str(name)
        if preview:
            payload["text"] = str(preview)
        if _kwargs.get("status"):
            payload["status"] = str(_kwargs["status"])
        if _kwargs.get("summary"):
            payload["summary"] = str(_kwargs["summary"])
        if _kwargs.get("duration_seconds") is not None:
            payload["duration_seconds"] = float(_kwargs["duration_seconds"])
        if preview and event_type == "subagent.tool":
            payload["tool_preview"] = str(preview)
            payload["text"] = str(preview)
        _emit(event_type, sid, payload)


def _agent_cbs(sid: str) -> dict:
    return {
        "tool_start_callback": lambda tc_id, name, args: _on_tool_start(
            sid, tc_id, name, args
        ),
        "tool_complete_callback": lambda tc_id, name, args, result: _on_tool_complete(
            sid, tc_id, name, args, result
        ),
        "tool_progress_callback": lambda event_type, name=None, preview=None, args=None, **kwargs: _on_tool_progress(
            sid, event_type, name, preview, args, **kwargs
        ),
        "tool_gen_callback": lambda name: _tool_progress_enabled(sid)
        and _emit("tool.generating", sid, {"name": name}),
        "thinking_callback": lambda text: _emit("thinking.delta", sid, {"text": text}),
        "reasoning_callback": lambda text: _emit("reasoning.delta", sid, {"text": text}),
        "status_callback": lambda kind, text=None: _status_update(
            sid, str(kind), None if text is None else str(text)
        ),
        "clarify_callback": lambda q, c: _block(
            "clarify.request", sid, {"question": q, "choices": c}
        ),
    }


def _wire_callbacks(sid: str):
    from tools.terminal_tool import set_sudo_password_callback
    from tools.skills_tool import set_secret_capture_callback

    set_sudo_password_callback(lambda: _block("sudo.request", sid, {}, timeout=120))

    def secret_cb(env_var, prompt, metadata=None):
        pl = {"prompt": prompt, "env_var": env_var}
        if metadata:
            pl["metadata"] = metadata
        val = _block("secret.request", sid, pl)
        if not val:
            return {
                "success": True,
                "stored_as": env_var,
                "validated": False,
                "skipped": True,
                "message": "skipped",
            }
        from superforecasting_agent.runtime.config import save_env_value_secure

        return {
            **save_env_value_secure(env_var, val),
            "skipped": False,
            "message": "ok",
        }

    set_secret_capture_callback(secret_cb)


def _render_personality_prompt(value) -> str:
    if isinstance(value, dict):
        parts = [value.get("system_prompt", "")]
        if value.get("tone"):
            parts.append(f'Tone: {value["tone"]}')
        if value.get("style"):
            parts.append(f'Style: {value["style"]}')
        return "\n".join(p for p in parts if p)
    return str(value)


def _available_personalities(cfg: dict | None = None) -> dict:
    try:
        from superforecasting_agent.runtime.interactive_config import read_cli_config

        ignore_config = next((os.environ[name] for name in (
            "SUPERFORECASTING_AGENT_IGNORE_USER_CONFIG", "FORECAST_IGNORE_USER_CONFIG",
            "HERMES_IGNORE_USER_CONFIG",
        ) if name in os.environ), "") == "1"
        settings = read_cli_config(
            _hermes_home, Path(__file__).resolve().parents[1] / "cli-config.yaml", ignore_config,
        )
        return (settings.get("agent") or {}).get("personalities", {}) or {}
    except Exception:
        try:
            from superforecasting_agent.runtime.config import load_config as _load_full_cfg

            return (_load_full_cfg().get("agent") or {}).get("personalities", {}) or {}
        except Exception:
            cfg = cfg or _load_cfg()
            return (cfg.get("agent") or {}).get("personalities", {}) or {}


def _validate_personality(value: str, cfg: dict | None = None) -> tuple[str, str]:
    raw = str(value or "").strip()
    name = raw.lower()
    if not name or name in {"none", "default", "neutral"}:
        return "", ""

    personalities = _available_personalities(cfg)
    if name not in personalities:
        names = sorted(personalities)
        available = ", ".join(f"`{n}`" for n in names)
        base = f"Unknown forecast style: `{raw}`."
        if available:
            base += f"\n\nAvailable: `none`, {available}"
        else:
            base += "\n\nNo forecast styles configured."
        raise ValueError(base)

    return name, _render_personality_prompt(personalities[name])


def _apply_personality_to_session(
    sid: str, session: dict, new_prompt: str
) -> tuple[bool, dict | None]:
    """Apply a personality change to an existing session without resetting history.

    Updates the agent's ephemeral system prompt in-place so the new personality
    takes effect on the next turn.  The cached base system prompt is left intact
    (ephemeral_system_prompt is appended at API-call time, not baked into the
    cache), which preserves prompt-cache hits.

    Also injects a system-role marker into the conversation history so the model
    knows to pivot its style from this point forward (without this, LLMs tend to
    continue the tone established by earlier messages in the transcript).

    Returns (history_reset, info) — history_reset is always False since we
    preserve the conversation.
    """
    if not session:
        return False, None

    agent = session.get("agent")
    if agent:
        from forecasting.protocol import build_forecast_chat_system_prompt

        agent.ephemeral_system_prompt = build_forecast_chat_system_prompt(new_prompt)
        # Inject a pivot marker into history so the model sees the change point.
        # This prevents it from pattern-matching its prior style.
        if new_prompt:
            marker = (
                "[System: The user has changed the forecast agent's style. "
                "From this point forward, adopt the following persona and respond "
                f"accordingly: {new_prompt}]"
            )
        else:
            marker = (
                "[System: The user has cleared the forecast style overlay. "
                "From this point forward, keep the default forecasting-desk behavior.]"
            )
        with session["history_lock"]:
            session["history"].append({"role": "user", "content": marker})
            session["history_version"] = int(session.get("history_version", 0)) + 1
        info = _session_info(agent)
        _emit("session.info", sid, info)
        return False, info
    return False, None


def _cfg_max_turns(cfg: dict, default: int) -> int:
    from superforecasting_agent.configuration.agent_limits import agent_turn_budget

    return agent_turn_budget(cfg, override=_tui_env("MAX_TURNS"), default=default)


def _parse_tui_skills_env() -> list[str]:
    raw = _tui_env("SKILLS")
    skills: list[str] = []
    seen: set[str] = set()
    for part in raw.replace("\n", ",").split(","):
        item = part.strip()
        if item and item not in seen:
            seen.add(item)
            skills.append(item)
    return skills


def _background_agent_kwargs(agent, task_id: str) -> dict:
    from agent.background_options import background_agent_options

    return background_agent_options(agent, task_id, {
        "model": _resolve_model(),
        "max_iterations": _cfg_max_turns(_load_cfg(), 25),
        "enabled_toolsets": _load_enabled_toolsets(),
        "reasoning_config": _load_reasoning_config(),
        "service_tier": _load_service_tier(),
        "platform": "tui",
        "session_db": _get_db(),
    })


def _reset_session_agent(sid: str, session: dict, *, reserved: bool = False) -> dict:
    if not reserved:
        with replacement(session):
            return _reset_session_agent(sid, session, reserved=True)
    from superforecasting_agent.hosting.builds import execute_build
    from tools.approval import unregister_gateway_notify

    stop = session.get("_notif_stop")
    if stop is not None:
        stop.set()
    dispose_session(session, release_notifications=lambda: unregister_gateway_notify(session["session_key"]))
    session["agent"] = None
    session["slash_worker"] = None
    session.pop("_disposed_resources", None)
    session.pop("_notifications_released", None)
    session["agent_error"] = None
    ready = threading.Event()
    session["agent_ready"] = ready
    session["agent_build_started"] = True

    @contextlib.contextmanager
    def scope():
        tokens = _set_session_context(session["session_key"])
        try:
            yield
        finally:
            _clear_session_context(tokens)

    execute_build(
        session, ready,
        construct=lambda: _make_agent(sid, session["session_key"], session_id=session["session_key"]),
        construction_scope=scope,
        initialize=lambda agent: _initialize_built_agent(sid, session, agent),
        report_error=lambda message: logger.error("session reset failed: %s", message),
    )
    if session.get("agent_error"):
        raise RuntimeError(f"Agent reset failed; history preserved: {session['agent_error']}")
    updates = {
        "attached_images": [], "edit_snapshots": {}, "image_counter": 0,
        "show_reasoning": _load_show_reasoning(),
        "tool_progress_mode": _load_tool_progress_mode(), "tool_started_at": {},
    }
    info = _session_info(session["agent"])
    with session["history_lock"]:
        session.update(updates)
        session["history"] = []
        session["history_version"] = int(session.get("history_version", 0)) + 1
    return info


def _session_runtime(sid: str) -> dict:
    """Resolve provider credentials for a session's Market Model build agent so it
    authenticates EXACTLY like the live session — a fresh config-resolved agent can
    land on a different/unconfigured provider and get an HTML auth page. Uses the
    same resolve_runtime_provider path as _make_agent (carries OAuth credential
    pools, not just API keys), seeded by the session's CURRENT provider/model."""
    sess = _host.sessions.get(sid) or {}
    agent = sess.get("agent")
    try:
        from superforecasting_agent.runtime.runtime_provider import resolve_runtime_provider

        if agent is not None:
            model = getattr(agent, "model", "") or ""
            requested = getattr(agent, "provider", None)
        else:
            model, requested = _resolve_startup_runtime()
        rt = resolve_runtime_provider(requested=requested, target_model=model or None)
        out = {
            "model": model, "provider": rt.get("provider"), "base_url": rt.get("base_url"),
            "api_key": rt.get("api_key"), "api_mode": rt.get("api_mode"),
            "credential_pool": rt.get("credential_pool"), "command": rt.get("command"), "args": rt.get("args"),
            "parent_session_id": sid or None,
            # Opt-in: the sandboxed code_execution + browser toolset variant. Off
            # by default (plain market-models); enable for richer custom pipelines.
            "interactive": str(os.environ.get("HERMES_MARKET_INTERACTIVE", "")).strip().lower() in ("1", "true", "yes", "on"),
        }
        # Provider failover chain from config — the real resilience fix for a
        # stalled/erroring upstream provider (the timeout band-aid only delays).
        try:
            from superforecasting_agent.runtime.config import load_config_readonly
            from superforecasting_agent.runtime.fallback_cmd import _read_chain

            chain = _read_chain(load_config_readonly())
            if chain:
                out["fallback_model"] = chain
        except Exception:
            pass
        return out
    except Exception:
        if agent is not None:
            return {
                "model": getattr(agent, "model", "") or "", "provider": getattr(agent, "provider", None),
                "base_url": getattr(agent, "base_url", None), "api_key": getattr(agent, "api_key", None),
                "api_mode": getattr(agent, "api_mode", None),
            }
        return {}


def _make_agent(sid: str, key: str, session_id: str | None = None):

    from superforecasting_agent.configuration import resolve_config

    cfg = resolve_config(_load_cfg())
    agent_cfg = cfg.get("agent") or {}
    from agent.startup_prompt import prepare_startup_prompt

    system_prompt, _loaded_skills = prepare_startup_prompt(
        agent_cfg.get("system_prompt"), _parse_tui_skills_env(),
        session_id=session_id or key,
    )
    model, requested_provider = _resolve_startup_runtime(cfg=cfg)
    from agent.agent_factory import build_agent
    from forecasting.protocol import build_forecast_chat_system_prompt

    # Single resolve->construct path: build_agent resolves the runtime provider and
    # maps provider/base_url/api_key/api_mode/acp_*/credential_pool onto the AIAgent
    # kwargs (behaviour-identical to the hand-written mapping it replaces).
    return build_agent(
        model=model,
        requested_provider=requested_provider,
        configuration=cfg,
        max_iterations=_cfg_max_turns(cfg, 90),
        quiet_mode=True,
        verbose_logging=_load_tool_progress_mode(cfg=cfg) == "verbose",
        reasoning_config=_load_reasoning_config(cfg=cfg),
        service_tier=_load_service_tier(cfg=cfg),
        enabled_toolsets=_load_enabled_toolsets(cfg=cfg),
        platform="tui",
        session_id=session_id or key,
        session_db=_get_db(),
        ephemeral_system_prompt=build_forecast_chat_system_prompt(system_prompt),
        checkpoints_enabled=is_truthy_value(_tui_env("CHECKPOINTS")),
        pass_session_id=is_truthy_value(_tui_env("PASS_SESSION_ID")),
        skip_context_files=is_truthy_value(_runtime_env("IGNORE_RULES")),
        skip_memory=is_truthy_value(_runtime_env("IGNORE_RULES")),
        **_agent_cbs(sid),
    )


def _init_session(sid: str, key: str, agent, history: list, cols: int = 80, *, pending_handoff: bool = False):
    _host.sessions.register(sid, {
        "agent": agent,
        "session_key": key,
        "history": history,
        "history_lock": threading.Lock(),
        "history_version": 0,
        "running": pending_handoff,
        "_replacing": pending_handoff,
        "attached_images": [],
        "image_counter": 0,
        "cols": cols,
        "slash_worker": None,
        "show_reasoning": _load_show_reasoning(),
        "tool_progress_mode": _load_tool_progress_mode(),
        "edit_snapshots": {},
        "tool_started_at": {},
        # Pin async event emissions to whichever transport created the
        # session (stdio for Ink, JSON-RPC WS for the dashboard sidebar).
        "transport": current_transport() or _stdio_transport,
    })
    try:
        from tools.approval import register_gateway_notify, load_permanent_allowlist

        register_gateway_notify(key, lambda data: _emit("approval.request", sid, data))
        load_permanent_allowlist()
    except Exception:
        pass
    # Surface the self-improvement background review's "💾 …" summary as a
    # review.summary event so Ink can render it as a persistent system line
    # in the transcript. In the CLI path this message is printed via
    # prompt_toolkit; the TUI has no equivalent print surface, so without
    # this callback the review would write the skill/memory change silently.
    try:
        agent.background_review_callback = lambda message, _sid=sid: _emit(
            "review.summary", _sid, {"text": str(message)}
        )
    except Exception:
        # Bare AIAgents that don't expose the attribute (unlikely, but keep
        # session startup resilient).
        pass
    _wire_callbacks(sid)
    _host.sessions[sid]["_notif_stop"] = _start_notification_poller(sid, _host.sessions[sid])
    _notify_session_boundary("on_session_reset", key)
    _emit("session.info", sid, _session_info(agent))


def _new_session_key() -> str:
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def _with_checkpoints(session, fn):
    return fn(session["agent"]._checkpoint_mgr, os.getenv("TERMINAL_CWD", os.getcwd()))


def _resolve_checkpoint_hash(mgr, cwd: str, ref: str) -> str:
    try:
        checkpoints = mgr.list_checkpoints(cwd)
        idx = int(ref) - 1
    except ValueError:
        return ref
    if 0 <= idx < len(checkpoints):
        return checkpoints[idx].get("hash", ref)
    raise ValueError(f"Invalid checkpoint number. Use 1-{len(checkpoints)}.")


def _enrich_with_attached_images(user_text: str, image_paths: list[str]) -> str:
    """Pre-analyze attached images via vision and prepend descriptions to user text."""
    import asyncio, json as _json
    from tools.vision_tools import vision_analyze_tool

    prompt = (
        "Describe everything visible in this image in thorough detail. "
        "Include any text, code, data, objects, people, layout, colors, "
        "and any other notable visual information."
    )

    parts: list[str] = []
    for path in image_paths:
        p = Path(path)
        if not p.exists():
            continue
        hint = f"[You can examine it with vision_analyze using image_url: {p}]"
        try:
            r = _json.loads(
                asyncio.run(vision_analyze_tool(image_url=str(p), user_prompt=prompt))
            )
            desc = r.get("analysis", "") if r.get("success") else None
            parts.append(
                f"[The user attached an image:\n{desc}]\n{hint}"
                if desc
                else f"[The user attached an image but analysis failed.]\n{hint}"
            )
        except Exception:
            parts.append(f"[The user attached an image but analysis failed.]\n{hint}")

    text = user_text or ""
    prefix = "\n\n".join(parts)
    if prefix:
        return f"{prefix}\n\n{text}" if text else prefix
    return text or "What do you see in this image?"


def _content_display_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (int, float)):
        return str(content)
    if isinstance(content, list):
        parts = []
        for part in content:
            text = _content_display_text(part).strip()
            if text:
                parts.append(text)
        return "\n".join(parts)
    if isinstance(content, dict):
        kind = content.get("type")
        if kind in {"text", "input_text", "output_text"}:
            return str(content.get("text") or content.get("content") or "")
        if kind in {"image_url", "input_image", "image"}:
            return "[image]"
        if kind in {"input_audio", "audio"}:
            return "[audio]"
        if kind:
            return f"[{kind}]"
        if "text" in content:
            return str(content.get("text") or "")
        return "[structured content]"
    return str(content)


def _history_to_messages(history: list[dict]) -> list[dict]:
    messages = []
    tool_call_args = {}

    for m in history:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role not in {"user", "assistant", "tool", "system"}:
            continue
        content_text = _content_display_text(m.get("content"))
        if role == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                tc_id = tc.get("id", "")
                if tc_id and fn.get("name"):
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    tool_call_args[tc_id] = (fn["name"], args)
            if not content_text.strip():
                continue
        if role == "tool":
            tc_id = m.get("tool_call_id", "")
            tc_info = tool_call_args.get(tc_id) if tc_id else None
            name = (tc_info[0] if tc_info else None) or m.get("tool_name") or "tool"
            args = (tc_info[1] if tc_info else None) or {}
            messages.append(
                {"role": "tool", "name": name, "context": _tool_ctx(name, args)}
            )
            continue
        if not content_text.strip():
            continue
        messages.append({"role": role, "text": content_text})

    return messages


# ── Methods: session ─────────────────────────────────────────────────


@rpc_validated("session.create")
def _(rid, params: dict) -> dict:
    sid = uuid.uuid4().hex[:8]
    key = _new_session_key()
    cols = int(params.get("cols", 80))
    _enable_gateway_prompts()

    ready = threading.Event()

    _host.sessions.register(sid, {
        "agent": None,
        "agent_error": None,
        "agent_ready": ready,
        "attached_images": [],
        "cols": cols,
        "edit_snapshots": {},
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "image_counter": 0,
        "pending_title": None,
        "running": False,
        "session_key": key,
        "show_reasoning": _load_show_reasoning(),
        "slash_worker": None,
        "tool_progress_mode": _load_tool_progress_mode(),
        "tool_started_at": {},
        "transport": current_transport() or _stdio_transport,
    })

    # Return the lightweight session immediately so Ink can paint the composer
    # + skeleton panel, then build the real AIAgent just after this response is
    # flushed.  This keeps startup responsive while still hydrating tools/skills
    # without requiring the user to submit a first prompt.
    def _deferred_build() -> None:
        session = _host.sessions.get(sid)
        if session is not None:
            _start_agent_build(sid, session)

    def delayed_build() -> None:
        time.sleep(0.05)
        if not _host.workers.stopping:
            _deferred_build()
    _host.workers.start(delayed_build, name="forecast-deferred-build")

    return _ok(
        rid,
        {
            "session_id": sid,
            "info": {
                "durable_session_id": key,
                "model": _resolve_model(),
                "tools": {},
                "skills": {},
                "cwd": os.getenv("TERMINAL_CWD", os.getcwd()),
                "lazy": True,
                "profile_name": _current_profile_name(),
            },
        },
    )


@rpc_validated("session.list")
def _(rid, params: dict) -> dict:
    db = _get_db()
    if db is None:
        return _db_unavailable_error(rid, code=5006)
    try:
        from superforecasting_agent.application.sessions import list_resumable_sessions

        limit = params.get("limit", 200)
        if limit is None:
            limit = 200
        active_keys = {
            session.get("session_key")
            for session in list(_host.sessions.values())
            if session.get("session_key")
        }
        rows = list_resumable_sessions(db, limit=limit, exclude_ids=active_keys)
        return _ok(
            rid,
            {
                "sessions": [
                    {
                        "id": s["id"],
                        "title": s.get("title") or "",
                        "preview": s.get("preview") or "",
                        "started_at": s.get("started_at") or 0,
                        "message_count": s.get("message_count") or 0,
                        "source": s.get("source") or "",
                    }
                    for s in rows
                ]
            },
        )
    except ValueError as e:
        return _err(rid, 4003, str(e))
    except Exception as e:
        return _err(rid, 5006, str(e))


@rpc_validated("session.most_recent")
def _(rid, params: dict) -> dict:
    """Return the most recent human-facing session id, or ``None``.

    Mirrors ``session.list``'s deny-list behaviour (drops ``tool``
    sub-agent rows).  Used by TUI auto-resume when
    ``display.tui_auto_resume_recent`` is on; the field is also handy
    for any CLI tooling that wants "latest session" without paginating
    the full list.

    A null session_id means the durable query found no eligible conversation.
    Storage failures remain errors so clients cannot mistake them for empty
    history and silently start a replacement session.
    """
    db = _get_db()
    if db is None:
        return _db_unavailable_error(rid, code=5006)
    try:
        from superforecasting_agent.application.sessions import list_resumable_sessions

        active_keys = {
            session.get("session_key")
            for session in list(_host.sessions.values())
            if session.get("session_key")
        }
        for row in list_resumable_sessions(db, limit=1, exclude_ids=active_keys):
            return _ok(
                rid,
                {
                    "session_id": row.get("id"),
                    "title": row.get("title") or "",
                    "started_at": row.get("started_at") or 0,
                    "source": row.get("source") or "",
                },
            )
        return _ok(rid, {"session_id": None})
    except Exception as exc:
        logger.exception("session.most_recent failed")
        return _err(rid, 5006, f"session history unavailable: {exc}")


@rpc_validated("session.resume")
def _(rid, params: dict) -> dict:
    target = params.get("session_id", "")
    if not target:
        return _err(rid, 4006, "session_id required")
    db = _get_db()
    if db is None:
        return _db_unavailable_error(rid, code=5000)
    found = db.get_session(target)
    if not found:
        found = db.get_session_by_title(target)
        if found:
            target = found["id"]
        else:
            return _err(rid, 4007, "session not found")
    with _host.sessions.lock:
        replace_sid = str(params.get("replace_session_id") or "").strip()
        replace_session = _host.sessions.get(replace_sid) if replace_sid else None
        try:
            live_sessions = list(_host.sessions.items())
        except RuntimeError:
            return _err(rid, 5000, "session registry changed during resume; retry")
        active_sid = next(
            (
                sid
                for sid, session in live_sessions
                if session.get("session_key") == target
            ),
            None,
        )
        if active_sid is not None:
            return _err(rid, 4010, "session is already active")
        recovery = _turn_recovery(db, target, recover=True)
        if recovery and recovery.get("owner_active"):
            return _err(rid, 4010, "session turn is still owned by a running gateway")
        sid = uuid.uuid4().hex[:8]
        if sid in _host.sessions:
            return _err(rid, 5000, "runtime session identifier collision; retry")
        if replace_session:
            replace_lock = replace_session.get("history_lock")
            if replace_lock is None:
                replace_lock = contextlib.nullcontext()
            with replace_lock:
                if in_use(replace_session) or replace_session.get("_closing") or replace_session.get("_cleanup_pending"):
                    return _err(
                        rid,
                        4009,
                        "current session is busy; wait for the response before resuming",
                    )
                # Reserve the old runtime so prompt/notification dispatch cannot
                # start work while its replacement is being constructed.
                replace_session["running"] = True
        _enable_gateway_prompts()
        try:
            history = db.get_messages_as_conversation(target)
            display_history = db.get_messages_as_conversation(
                target, include_ancestors=True
            )
            messages = _history_to_messages(display_history)
            tokens = _set_session_context(target)
            try:
                agent = _make_agent(sid, target, session_id=target)
            finally:
                _clear_session_context(tokens)
            _init_session(sid, target, agent, history, cols=int(params.get("cols", 80)), pending_handoff=True)
            db.reopen_session(target)
            if replace_sid and replace_sid != sid:
                _close_runtime_session(replace_sid, reserved=True)
        except Exception as e:
            try:
                _close_runtime_session(sid, mark_ended=False, reserved=True)
            except Exception:
                logger.exception("failed to roll back partial resumed session %s", sid)
            if replace_session and _host.sessions.get(replace_sid) is replace_session:
                replace_lock = replace_session.get("history_lock")
                if replace_lock is None:
                    replace_lock = contextlib.nullcontext()
                with replace_lock:
                    replace_session["running"] = False
            return _err(rid, 5000, f"resume failed: {e}")
        with _host.sessions[sid]["history_lock"]:
            _host.sessions[sid]["_replacing"] = False
            _host.sessions[sid]["running"] = False
        return _ok(
            rid,
            {
                "session_id": sid,
                "resumed": target,
                "message_count": len(messages),
                "messages": messages,
                "info": _session_info(agent),
                "recovery": recovery,
            },
        )


@rpc_validated("session.delete")
def _(rid, params: dict) -> dict:
    """Delete a stored session and its on-disk transcript files.

    Used by the TUI resume picker (``d`` key) so users can prune old
    sessions without dropping to the CLI.  Refuses to delete a session
    that is currently active in this gateway process — those rows are
    still being written to and removing them out from under the live
    agent corrupts message ordering and trips FK constraints when the
    next message append flushes.
    """
    target = params.get("session_id", "")
    if not target:
        return _err(rid, 4006, "session_id required")
    db = _get_db()
    if db is None:
        return _db_unavailable_error(rid, code=5036)
    # Block deletion of any session currently bound to a live TUI session
    # in this process.  The picker hides the active session anyway, but a
    # racing caller could still target it.  Snapshot via ``list(...)``
    # because ``_host.sessions`` is mutated by concurrent RPCs on the thread
    # pool — iterating the dict directly can raise ``RuntimeError:
    # dictionary changed size during iteration``.  If even the snapshot
    # raises, fail closed (refuse the delete) rather than fail open.
    try:
        snapshot = list(_host.sessions.values())
    except Exception as e:
        return _err(rid, 5036, f"could not enumerate active forecast sessions: {e}")
    active = {s.get("session_key") for s in snapshot if s.get("session_key")}
    if target in active:
        return _err(rid, 4023, "cannot delete an active forecast session")
    sessions_dir = get_agent_home() / "sessions"
    try:
        deleted = db.delete_session(target, sessions_dir=sessions_dir)
    except Exception as e:
        return _err(rid, 5036, f"delete failed: {e}")
    if not deleted:
        return _err(rid, 4007, "session not found")
    return _ok(rid, {"deleted": target})


@rpc_validated("session.title")
def _(rid, params: dict) -> dict:
    session, err = _sess_nowait(params, rid)
    if err:
        return err
    db = _get_db()
    if db is None:
        return _db_unavailable_error(rid, code=5007)
    key = session["session_key"]
    if "title" not in params:
        from superforecasting_agent.application.sessions import reconcile_session_title

        try:
            title, pending = reconcile_session_title(db, key, session.get("pending_title"))
            session["pending_title"] = title if pending else None
            return _ok(rid, {"title": title, "session_key": key})
        except ValueError as exc:
            return _err(rid, 4022, str(exc))
        except Exception as exc:
            return _err(rid, 5007, str(exc))
    title = (params.get("title", "") or "").strip()
    if not title:
        return _err(rid, 4021, "title required")
    try:
        from superforecasting_agent.application.sessions import set_session_title

        title, pending = set_session_title(db, key, title)
        session["pending_title"] = title if pending else None
        return _ok(rid, {"pending": pending, "title": title})
    except ValueError as e:
        return _err(rid, 4022, str(e))
    except Exception as e:
        return _err(rid, 5007, str(e))


@rpc_validated("session.usage")
def _(rid, params: dict) -> dict:
    session, err = _sess_nowait(params, rid)
    if err:
        return err
    agent = session.get("agent")
    return _ok(
        rid,
        (
            _get_usage(agent)
            if agent is not None
            else {"calls": 0, "input": 0, "output": 0, "total": 0}
        ),
    )


@rpc_validated("session.status")
def _(rid, params: dict) -> dict:
    session, err = _sess_nowait(params, rid)
    if err:
        return err

    from superforecasting_agent.constants import display_agent_home

    key = session.get("session_key") or params.get("session_id") or ""
    agent = session.get("agent")
    meta = {}
    db = _get_db()
    if db and key:
        try:
            meta = db.get_session(key) or {}
        except Exception:
            meta = {}

    def _dt(value, fallback: datetime | None = None) -> datetime:
        if value:
            try:
                return datetime.fromtimestamp(float(value))
            except Exception:
                pass
        return fallback or datetime.now()

    created = _dt(meta.get("started_at"))
    updated = created
    for field in ("updated_at", "last_updated_at", "last_activity_at"):
        if meta.get(field):
            updated = _dt(meta.get(field), created)
            break

    usage = _get_usage(agent) if agent is not None else {}
    provider = getattr(agent, "provider", None) or "unknown"
    model = getattr(agent, "model", None) or "(unknown)"
    lines = [
        "Superforecasting Agent TUI Status",
        "",
        f"Session ID: {key}",
        f"Path: {display_agent_home()}",
    ]
    title = (meta.get("title") or "").strip()
    if title:
        lines.append(f"Title: {title}")
    lines.extend(
        [
            f"Model: {model} ({provider})",
            f"Created: {created.strftime('%Y-%m-%d %H:%M')}",
            f"Last Activity: {updated.strftime('%Y-%m-%d %H:%M')}",
            f"Tokens: {int(usage.get('total') or 0):,}",
            f"Agent Running: {'Yes' if session.get('running') else 'No'}",
        ]
    )
    from superforecasting_agent.storage import turns as turn_journal
    recovery = _turn_recovery(db, key) if db is not None else None
    if isinstance(recovery, dict):
        lines.append(f"Durable turn: {recovery['status']}")
    return _ok(rid, {"output": "\n".join(lines), "recovery": recovery})


# The warning-automode background job + the generic jobs.* runtime RPCs live in
# the ONE detached-job runtime (Arc B). Register them here (thin, pm_rpc-style):
# jobs.start/status/active/cancel emit jobs.* events, and the warnings aliases
# (forecast.warnings.automode.run/.cancel) return the byte-compatible shapes and
# emit the legacy forecast.warnings.automode.* events ALONGSIDE — so the alerts
# view is unchanged.
from tui_gateway import jobs_rpc as _jobs_rpc  # noqa: E402

_jobs_rpc.register(sys.modules[__name__])

# events.replay {session_id, since_id?, types?, limit?} — the logged frames from
# a session's append-only event log (Task #230(c)). Thin, pm_rpc-style register.
from tui_gateway import event_log as _event_log  # noqa: E402

_event_log.register(sys.modules[__name__])


@rpc_validated("session.history")
def _(rid, params: dict) -> dict:
    session, err = _sess_nowait(params, rid)
    if err:
        return err
    history = list(session.get("history", []))
    db = _get_db()
    if db is not None and session.get("session_key"):
        try:
            history = db.get_messages_as_conversation(
                session["session_key"], include_ancestors=True
            )
        except Exception:
            pass
    return _ok(
        rid,
        {
            "count": len(history),
            "messages": _history_to_messages(history),
        },
    )


@rpc_validated("session.undo")
def _(rid, params: dict) -> dict:
    session, err = _sess_nowait(params, rid)
    if err:
        return err
    from superforecasting_agent.application.history import prepare_undo

    with session["history_lock"]:
        # Admission and mutation share the same lock as prompt submission.
        if session.get("running"):
            return _err(rid, 4009, "session busy — /interrupt the current turn before /undo")
        plan = prepare_undo(session.get("history", []))
        if plan is not None:
            session["history"] = plan.history
            session["history_version"] = int(session.get("history_version", 0)) + 1
    return _ok(rid, {"removed": plan.removed if plan is not None else 0})


@rpc_validated("session.compress")
def _(rid, params: dict) -> dict:
    session, err = _sess(params, rid)
    if err:
        return err
    if session.get("running"):
        return _err(
            rid, 4009, "session busy — /interrupt the current turn before /compress"
        )
    sid = params.get("session_id", "")
    focus_topic = str(params.get("focus_topic", "") or "").strip()
    try:
        from agent.manual_compression_feedback import summarize_manual_compression
        from agent.model_metadata import estimate_request_tokens_rough

        with session["history_lock"]:
            before_messages = list(session.get("history", []))
            history_version = int(session.get("history_version", 0))
        before_count = len(before_messages)
        _agent = session["agent"]
        _sys_prompt = getattr(_agent, "_cached_system_prompt", "") or ""
        _tools = getattr(_agent, "tools", None) or None
        before_tokens = (
            estimate_request_tokens_rough(
                before_messages, system_prompt=_sys_prompt, tools=_tools
            )
            if before_count
            else 0
        )

        if before_count >= 4:
            focus_suffix = f', focus: "{focus_topic}"' if focus_topic else ""
            _status_update(
                sid,
                "compressing",
                f"⠋ compressing {before_count} messages "
                f"(~{before_tokens:,} tok){focus_suffix}…",
            )

        try:
            removed, usage = _compress_session_history(
                session,
                focus_topic,
                approx_tokens=before_tokens,
                before_messages=before_messages,
                history_version=history_version,
            )
            with session["history_lock"]:
                messages = list(session.get("history", []))
            after_count = len(messages)
            # Re-read system prompt + tools after compression — _compress_context
            # may have rebuilt the system prompt (_cached_system_prompt=None).
            _sys_prompt_after = (
                getattr(_agent, "_cached_system_prompt", "") or _sys_prompt
            )
            _tools_after = getattr(_agent, "tools", None) or _tools
            after_tokens = (
                estimate_request_tokens_rough(
                    messages,
                    system_prompt=_sys_prompt_after,
                    tools=_tools_after,
                )
                if after_count
                else 0
            )
            agent = session["agent"]
            _sync_session_key_after_compress(sid, session)
            summary = summarize_manual_compression(
                before_messages, messages, before_tokens, after_tokens
            )
            info = _session_info(agent)
            _emit("session.info", sid, info)
            return _ok(
                rid,
                {
                    "status": "compressed",
                    "removed": removed,
                    "before_messages": before_count,
                    "after_messages": after_count,
                    "before_tokens": before_tokens,
                    "after_tokens": after_tokens,
                    "summary": summary,
                    "usage": usage,
                    "info": info,
                    "messages": messages,
                },
            )
        finally:
            # Always clear the pinned compressing status so the bar
            # reverts to neutral whether compaction succeeded, was a
            # no-op, or raised.
            _status_update(sid, "ready")
    except Exception as e:
        return _err(rid, 5005, str(e))


@rpc_validated("session.save")
def _(rid, params: dict) -> dict:
    session, err = _sess_nowait(params, rid)
    if err:
        return err
    from superforecasting_agent.storage.transcripts import save_transcript

    try:
        with session["history_lock"]:
            history = copy.deepcopy(session.get("history", []))
            model = getattr(session.get("agent"), "model", "")
        filename = save_transcript(
            _hermes_home, messages=history, model=model,
            session_id=params.get("session_id", ""),
            session_key=session.get("session_key", ""),
        )
        return _ok(rid, {"file": str(filename)})
    except Exception as e:
        return _err(rid, 5011, str(e))


def _close_runtime_session(sid: str, *, mark_ended: bool = True, reserved: bool = False, drained: bool = False) -> bool:
    def finish(session: dict) -> None:
        _finalize_session(session, mark_ended=mark_ended)

        def release_notifications() -> None:
            from tools.approval import unregister_gateway_notify

            unregister_gateway_notify(session["session_key"])

        dispose_session(session, release_notifications=release_notifications)

    session = _host.sessions.retire(sid, finish, reserved=reserved, drained=drained)
    if session is None:
        return False
    _session_toggles.pop(session.get("session_key", ""), None)
    return True


@rpc_validated("session.close")
def _(rid, params: dict) -> dict:
    try:
        return _ok(rid, {"closed": _close_runtime_session(params.get("session_id", ""))})
    except SessionBusy:
        raise
    except Exception as exc:
        logger.exception("session close failed; retained for retry")
        return _err(rid, 5000, f"session close failed; retry: {exc}")


@rpc_validated("session.branch")
def _(rid, params: dict) -> dict:
    return _branch_session(rid, params, replace_current=False)


@rpc_validated("session.branch_replace")
def _(rid, params: dict) -> dict:
    session, err = _sess_nowait(params, rid)
    if err:
        return err
    with replacement(session):
        return _branch_session(rid, params, replace_current=True)


def _branch_session(rid, params: dict, *, replace_current: bool) -> dict:
    session, err = _sess(params, rid)
    if err:
        return err
    db = _get_db()
    if db is None:
        return _db_unavailable_error(rid, code=5008)
    old_key = session["session_key"]
    with session["history_lock"]:
        history = [dict(msg) for msg in session.get("history", [])]
    if not history:
        return _err(rid, 4008, "nothing to branch — send a forecast note first")
    new_key = _new_session_key()
    new_sid = uuid.uuid4().hex[:8]
    created = False
    agent = None
    try:
        from superforecasting_agent.application.sessions import branch_session
        title = branch_session(
            db, session_id=new_key, parent_session_id=old_key, history=history,
            name=params.get("name", ""), source="tui", model=_resolve_model(),
        )
        created = True
        tokens = _set_session_context(new_key)
        try:
            agent = _make_agent(new_sid, new_key, session_id=new_key)
        finally:
            _clear_session_context(tokens)
        _init_session(new_sid, new_key, agent, list(history), cols=session.get("cols", 80), pending_handoff=replace_current)
        if replace_current:
            _close_runtime_session(params["session_id"], reserved=True)
    except Exception as exc:
        cleanup_error = ""
        try:
            if (_host.sessions.get(new_sid) or {}).get("session_key") == new_key:
                _close_runtime_session(new_sid, mark_ended=False, reserved=replace_current)
            elif agent is not None:
                agent.close()
            if created:
                db.delete_session(new_key)
        except Exception as cleanup_exc:
            logger.exception("failed to roll back branch %s", new_key)
            cleanup_error = f"; branch cleanup failed: {cleanup_exc}"
        return _err(rid, 5008, f"branch failed: {exc}{cleanup_error}")
    if replace_current:
        with _host.sessions[new_sid]["history_lock"]:
            _host.sessions[new_sid]["_replacing"] = False
            _host.sessions[new_sid]["running"] = False
    return _ok(rid, {"session_id": new_sid, "title": title, "parent": old_key})


@rpc_validated("session.interrupt")
def _(rid, params: dict) -> dict:
    session, err = _sess_nowait(params, rid)
    if err:
        return err
    session["cancel_requested"] = True
    commands_pending = _host.interrupt_commands(session)
    if session.get("turn_id"):
        from superforecasting_agent.storage import turns as turn_journal
        turn_journal.transition(_get_db(), session["turn_id"], "cancelling")
    if hasattr(session.get("agent"), "interrupt"):
        session["agent"].interrupt()
    # Scope the pending-prompt release to THIS session.  A global
    # _clear_pending() would collaterally cancel clarify/sudo/secret
    # prompts on unrelated sessions sharing the same tui_gateway
    # process, silently resolving them to empty strings.
    _clear_pending(params.get("session_id", ""))
    try:
        from tools.approval import resolve_gateway_approval

        resolve_gateway_approval(session["session_key"], "deny", resolve_all=True)
    except Exception:
        pass
    return _ok(rid, {"status": "cancelling" if session.get("running") or commands_pending else "interrupted"})


# ── Delegation: subagent tree observability + controls ───────────────
# Powers the TUI's /agents overlay (see ui-tui/src/components/agentsOverlay).
# The registry lives in tools/delegate_tool — these handlers are thin
# translators between JSON-RPC and the Python API.


# ── Spawn-tree snapshots: TUI-written, disk-persisted ────────────────
# The TUI is the source of truth for subagent state (it assembles payloads
# from the event stream).  On turn-complete it posts the final tree here;
# /replay and /replay-diff fetch past snapshots by session_id + filename.
#
# Layout:  $HERMES_HOME/spawn-trees/<session_id>/<timestamp>.json
# Each file contains { session_id, started_at, finished_at, subagents: [...] }.


def _spawn_trees_root():
    from pathlib import Path as _P
    from superforecasting_agent.constants import get_agent_home

    root = get_agent_home() / "spawn-trees"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _spawn_tree_session_dir(session_id: str):
    safe = (
        "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id) or "unknown"
    )
    d = _spawn_trees_root() / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


# Per-session append-only index of lightweight snapshot metadata.  Read by
# `spawn_tree.list` so scanning doesn't require reading every full snapshot
# file (Copilot review on #14045).  One JSON object per line.
_SPAWN_TREE_INDEX = "_index.jsonl"


def _append_spawn_tree_index(session_dir, entry: dict) -> None:
    try:
        with (session_dir / _SPAWN_TREE_INDEX).open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        # Index is a cache — losing a line just means list() falls back
        # to a directory scan for that entry.  Never block the save.
        logger.debug("spawn_tree index append failed: %s", exc)


def _read_spawn_tree_index(session_dir) -> list[dict]:
    index_path = session_dir / _SPAWN_TREE_INDEX
    if not index_path.exists():
        return []
    out: list[dict] = []
    try:
        with index_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


@rpc_validated("session.steer")
def _(rid, params: dict) -> dict:
    """Inject a user message into the next tool result without interrupting.

    Mirrors AIAgent.steer(). Safe to call while a turn is running — the text
    lands on the last tool result of the next tool batch and the model sees
    it on its next iteration. No interrupt, no new user turn, no role
    alternation violation.
    """
    text = (params.get("text") or "").strip()
    if not text:
        return _err(rid, 4002, "text is required")
    session, err = _sess_nowait(params, rid)
    if err:
        return err
    agent = session.get("agent")
    if agent is None or not hasattr(agent, "steer"):
        return _err(rid, 4010, "agent does not support steer")
    try:
        accepted = agent.steer(text)
    except Exception as exc:
        return _err(rid, 5000, f"steer failed: {exc}")
    return _ok(rid, {"status": "queued" if accepted else "rejected", "text": text})


@rpc_validated("terminal.resize")
def _(rid, params: dict) -> dict:
    session, err = _sess_nowait(params, rid)
    if err:
        return err
    session["cols"] = int(params.get("cols", 80))
    return _ok(rid, {"cols": session["cols"]})


# ── Methods: prompt ──────────────────────────────────────────────────


@rpc_validated("prompt.submit")
def _(rid, params: dict) -> dict:
    sid, text = params.get("session_id", ""), params.get("text", "")
    session, err = _sess_nowait(params, rid)
    if err:
        return err
    with session["history_lock"]:
        if session.get("running"):
            return _err(rid, 4009, "session busy")
        session["running"] = True

    try:
        from superforecasting_agent.storage import turns as turn_journal
        db = _get_db()
        session["turn_id"] = turn_journal.start(db, session["session_key"], text) if db is not None else None
    except Exception as exc:
        with session["history_lock"]:
            session["running"] = False
        return _err(rid, 5000, f"Cannot preserve turn for recovery: {exc}")
    session["cancel_requested"] = False
    _start_agent_build(sid, session)

    def run_after_agent_ready() -> None:
        err = _wait_agent(session, rid)
        if err:
            _emit(
                "error",
                sid,
                {
                    "message": err.get("error", {}).get(
                        "message", "agent initialization failed"
                    )
                },
            )
            with session["history_lock"]:
                session["running"] = False
            return
        if session.get("cancel_requested"):
            _emit("message.complete", sid, {"text": "", "status": "interrupted", "usage": {}})
            with session["history_lock"]:
                session["running"] = False
            return
        _run_prompt_submit(rid, sid, session, text)

    _host.workers.start(run_after_agent_ready, name="forecast-agent-ready")
    return _ok(rid, {"status": "streaming"})


def _route_async_completion(evt: dict, my_session_key: str | None) -> str:
    """Compatibility name for shared host notification ownership policy."""
    from superforecasting_agent.hosting.notifications import route_notification

    return route_notification(evt, my_session_key)


def _notification_poller_loop(
    stop_event: threading.Event, sid: str, session: dict
) -> None:
    """Adapt host notification admission to RPC events and turn submission."""
    from superforecasting_agent.hosting.notifications import poll_notifications
    from tools.process_registry import process_registry, format_process_notification

    def dispatch(text: str) -> None:
        rid = f"__notif__{int(time.time() * 1000)}"
        try:
            _emit("status.update", sid, {"kind": "process", "text": text})
        except Exception:
            logger.exception("Notification status display failed")
        _run_prompt_submit(rid, sid, session, text)

    poll_notifications(
        stop_event, session, process_registry.completion_queue,
        consumed=process_registry.is_completion_consumed,
        format_event=format_process_notification,
        host_stopping=lambda: _host.workers.stopping,
        dispatch=dispatch,
    )


def _start_notification_poller(sid: str, session: dict) -> threading.Event:
    """Start the background notification poller for a TUI session."""
    stop = threading.Event()
    _host.workers.start(lambda: _notification_poller_loop(stop, sid, session), name="forecast-notifications")
    return stop


def _run_prompt_submit(rid, sid: str, session: dict, text: Any) -> None:
    with session["history_lock"]:
        history = list(session["history"])
        history_version = int(session.get("history_version", 0))
        images = list(session.get("attached_images", []))
        session["attached_images"] = []
    agent = session["agent"]
    from superforecasting_agent.storage import turns as turn_journal
    db = _get_db()
    if db is not None:
        receipt = _turn_recovery(db, session["session_key"])
        if not session.get("turn_id") or not receipt or receipt["status"] in turn_journal.TERMINAL:
            session["turn_id"] = turn_journal.start(db, session["session_key"], text)
    session["turn_persistence_unavailable"] = db is None
    turn_id = session.get("turn_id")
    _emit("message.start", sid)

    def run():
        approval_token = None
        session_tokens = []
        goal_followup = None  # set by the post-turn goal hook below
        try:
            from tools.approval import (
                reset_current_session_key,
                set_current_session_key,
            )

            approval_token = set_current_session_key(session["session_key"])
            session_tokens = _set_session_context(session["session_key"])
            cols = session.get("cols", 80)
            streamer = make_stream_renderer(cols)
            prompt = text

            if isinstance(prompt, str) and "@" in prompt:
                from agent.context_references import preprocess_context_references
                from agent.model_metadata import get_model_context_length

                ctx_len = get_model_context_length(
                    getattr(agent, "model", "") or _resolve_model(),
                    base_url=getattr(agent, "base_url", "") or "",
                    api_key=getattr(agent, "api_key", "") or "",
                    provider=getattr(agent, "provider", "") or "",
                    config_context_length=getattr(
                        agent, "_config_context_length", None
                    ),
                )
                ctx = preprocess_context_references(
                    prompt,
                    cwd=os.environ.get("TERMINAL_CWD", os.getcwd()),
                    allowed_root=os.environ.get("TERMINAL_CWD", os.getcwd()),
                    context_length=ctx_len,
                )
                if ctx.blocked:
                    _emit(
                        "error",
                        sid,
                        {
                            "message": "\n".join(ctx.warnings)
                            or "Context injection refused."
                        },
                    )
                    return
                prompt = ctx.message

            # Decide image routing per-turn based on active provider/model.
            # "native" → pass pixels to the main model as OpenAI-style content
            # parts (adapters translate for Anthropic/Gemini/Bedrock/etc.).
            # "text"   → pre-analyze with vision_analyze and prepend the text.
            # See agent/image_routing.py for the full decision table.
            run_message: Any = prompt
            if images:
                try:
                    from agent.image_routing import (
                        decide_image_input_mode,
                        build_native_content_parts,
                    )
                    from agent.auxiliary_client import (
                        _read_main_model,
                        _read_main_provider,
                    )
                    from superforecasting_agent.runtime.config import load_config as _tui_load_config

                    _cfg = _tui_load_config()
                    _mode = decide_image_input_mode(
                        _read_main_provider(),
                        _read_main_model(),
                        _cfg,
                    )
                except Exception as _img_exc:
                    print(
                        f"[tui_gateway] image_routing decision failed, defaulting to text: {_img_exc}",
                        file=sys.stderr,
                    )
                    _mode = "text"

                if _mode == "native":
                    try:
                        _parts, _skipped = build_native_content_parts(
                            prompt,
                            images,
                        )
                        if _skipped:
                            print(
                                f"[tui_gateway] native image attachment skipped {len(_skipped)} unreadable path(s)",
                                file=sys.stderr,
                            )
                        if any(p.get("type") == "image_url" for p in _parts):
                            run_message = _parts
                        else:
                            run_message = _enrich_with_attached_images(prompt, images)
                    except Exception as _img_exc:
                        print(
                            f"[tui_gateway] native attach failed, falling back to text: {_img_exc}",
                            file=sys.stderr,
                        )
                        run_message = _enrich_with_attached_images(prompt, images)
                else:
                    run_message = _enrich_with_attached_images(prompt, images)

            def _stream(delta):
                payload = {"text": delta, "turn_id": turn_id}
                if streamer and (r := streamer.feed(delta)) is not None:
                    payload["rendered"] = r
                _emit("message.delta", sid, payload)

            result = agent.run_conversation(
                run_message,
                conversation_history=list(history),
                stream_callback=_stream,
            )

            last_reasoning = None
            status_note = None
            if isinstance(result, dict):
                if isinstance(result.get("messages"), list):
                    with session["history_lock"]:
                        current_version = int(session.get("history_version", 0))
                        if current_version == history_version:
                            session["history"] = result["messages"]
                            session["history_version"] = history_version + 1
                        else:
                            # History mutated externally during the turn
                            # (undo/compress/retry/rollback now guard on
                            # session.running, but this is the defensive
                            # backstop for any path that slips past).
                            # Surface the desync rather than silently
                            # dropping the agent's output — the UI can
                            # show the response and warn that it was
                            # not persisted.
                            print(
                                f"[tui_gateway] prompt.submit: history_version mismatch "
                                f"(expected={history_version} current={current_version}) — "
                                f"agent output NOT written to session history",
                                file=sys.stderr,
                            )
                            status_note = (
                                "History changed during this turn — the response above is visible "
                                "but was not saved to session history."
                            )

                # If auto-compression fired inside run_conversation(), agent.session_id
                # may have rotated. Sync session_key before downstream title/goal/finalize
                # handling uses it. Preserve pending_title (user intent) so it can be
                # applied to the continuation. Restart slash worker so subsequent
                # worker-backed commands (/title etc.) target the live session.
                # Fix for #20001.
                _sync_session_key_after_compress(
                    sid, session, clear_pending_title=False, restart_slash_worker=True,
                )

                raw = result.get("final_response", "")
                status = (
                    "interrupted"
                    if result.get("interrupted")
                    else "error" if result.get("error") else "complete"
                )
                # When the backend produced no visible response AND reported a
                # real error (e.g. invalid model slug → provider 4xx), surface
                # that error as the visible text instead of shipping an empty
                # turn to Ink. Mirrors classic CLI behavior at cli.py where
                # (failed|partial) + no final_response → "Error: <detail>".
                # Leaves the None-with-no-error path untouched: an empty
                # successful turn still renders as empty, and the existing
                # "(empty)" sentinel handling stays in its own lane.
                if (not raw) and result.get("error") and (
                    result.get("failed") or result.get("partial")
                ):
                    raw = f"Error: {result.get('error')}"
                lr = result.get("last_reasoning")
                if isinstance(lr, str) and lr.strip():
                    last_reasoning = lr.strip()
            else:
                raw = str(result)
                status = "complete"

            payload = {"text": raw, "usage": _get_usage(agent), "status": status, "turn_id": turn_id}
            if last_reasoning:
                payload["reasoning"] = last_reasoning
            if status_note:
                payload["warning"] = status_note
            rendered = render_message(raw, cols)
            if rendered:
                payload["rendered"] = rendered
            _emit("message.complete", sid, payload)

            # ── /goal continuation (Ralph-style loop) ─────────────────
            # After every TUI turn, if a /goal is active, ask the judge
            # whether the goal is done and — if not and we're still under
            # budget — queue a continuation prompt to run after this
            # thread releases session["running"]. The verdict message
            # ("✓ Goal achieved" / "⏸ budget exhausted") is surfaced as
            # a system line so the user sees progress regardless of
            # outcome. Mirrors gateway/run._post_turn_goal_continuation.
            if status == "complete" and isinstance(raw, str) and raw.strip():
                try:
                    from superforecasting_agent.runtime.goals import GoalManager

                    sid_key = session.get("session_key") or ""
                    if sid_key:
                        try:
                            goals_cfg = _load_cfg().get("goals") or {}
                            goal_max_turns = configured_goal_turn_budget(goals_cfg)
                        except Exception:
                            goal_max_turns = configured_goal_turn_budget(None)
                        goal_mgr = GoalManager(
                            session_id=sid_key,
                            default_max_turns=goal_max_turns,
                            database_provider=_get_db,
                        )
                        if goal_mgr.is_active():
                            decision = goal_mgr.evaluate_after_turn(
                                raw,
                                user_initiated=True,
                            )
                            verdict_msg = decision.get("message") or ""
                            if verdict_msg:
                                _emit(
                                    "status.update",
                                    sid,
                                    {"kind": "goal", "text": verdict_msg},
                                )
                            if decision.get("should_continue"):
                                cont_prompt = decision.get("continuation_prompt") or ""
                                if cont_prompt:
                                    goal_followup = cont_prompt
                except Exception as _goal_exc:
                    print(
                        f"[tui_gateway] goal continuation hook failed: "
                        f"{type(_goal_exc).__name__}: {_goal_exc}",
                        file=sys.stderr,
                    )

            # Apply pending_title now that the DB row exists.
            _pending = session.get("pending_title")
            if _pending and status == "complete":
                _pdb = _get_db()
                if _pdb:
                    _session_key = session.get("session_key") or sid
                    try:
                        if _pdb.set_session_title(_session_key, _pending):
                            session["pending_title"] = None
                    except ValueError as exc:
                        # Invalid/duplicate title — non-retryable, drop it.
                        # Auto-title will take over. Fix for #19029.
                        session["pending_title"] = None
                        logger.info(
                            "Dropping pending title for session %s: %s",
                            _session_key, exc,
                        )
                    except Exception:
                        # Transient DB failure — keep pending_title for retry.
                        pass

            if (
                status == "complete"
                and isinstance(raw, str)
                and raw.strip()
                and isinstance(text, str)
                and text.strip()
            ):
                try:
                    from agent.title_generator import maybe_auto_title

                    maybe_auto_title(
                        _get_db(),
                        session.get("session_key") or sid,
                        text,
                        raw,
                        session.get("history", []),
                    )
                except Exception:
                    pass

            # CLI parity: when voice-mode TTS is on, speak the agent reply
            # (cli.py:_voice_speak_response).  Only the final text — tool
            # calls / reasoning already stream separately and would be
            # noisy to read aloud.
            if (
                status == "complete"
                and isinstance(raw, str)
                and raw.strip()
                and _voice_tts_enabled()
            ):
                try:
                    from superforecasting_agent.runtime.voice import speak_text  # noqa: F401 — availability check

                    spoken = raw
                    _host.workers.start(lambda: _speak_with_status(spoken, sid), name="forecast-speech")
                except ImportError:
                    logger.warning("voice TTS skipped: superforecasting_agent.runtime.voice unavailable")
                except Exception as e:
                    logger.warning("voice TTS dispatch failed: %s", e)
        except BaseException as e:
            import traceback

            trace = traceback.format_exc()
            try:
                os.makedirs(os.path.dirname(_CRASH_LOG), exist_ok=True)
                with open(_CRASH_LOG, "a", encoding="utf-8") as f:
                    f.write(
                        f"\n=== turn-dispatcher exception · "
                        f"{time.strftime('%Y-%m-%d %H:%M:%S')} · sid={sid} ===\n"
                    )
                    f.write(trace)
            except Exception:
                pass
            print(
                f"[gateway-turn] {type(e).__name__}: {e}", file=sys.stderr, flush=True
            )
            _emit("error", sid, {"message": str(e), "turn_id": turn_id})
        finally:
            try:
                if approval_token is not None:
                    reset_current_session_key(approval_token)
            except Exception:
                pass
            _clear_session_context(session_tokens)
            with session["history_lock"]:
                session["running"] = False

        # Chain a goal-continuation turn if the judge said so. We do
        # this AFTER the finally releases session["running"], so the
        # nested _run_prompt_submit doesn't deadlock on the busy
        # guard. A real user prompt that races us wins because
        # prompt.submit sets running=True under the history_lock and
        # we check that guard before re-firing.
        if goal_followup:
            with session["history_lock"]:
                if session.get("running"):
                    # User already sent something — their turn wins,
                    # the judge will re-run on the next turn anyway.
                    return
                session["running"] = True
            try:
                _emit("message.start", sid)
                _run_prompt_submit(rid, sid, session, goal_followup)
            except Exception as _cont_exc:
                print(
                    f"[tui_gateway] goal continuation dispatch failed: "
                    f"{type(_cont_exc).__name__}: {_cont_exc}",
                    file=sys.stderr,
                )
                with session["history_lock"]:
                    session["running"] = False

        # Drain completion notifications that arrived during this turn.
        # The background poller handles between-turn delivery; this is
        # the safety net for events that arrived mid-turn.
        try:
            from tools.process_registry import process_registry

            for _evt, synth in process_registry.drain_notifications():
                with session["history_lock"]:
                    if session.get("running"):
                        process_registry.completion_queue.put(_evt)
                        break
                    session["running"] = True
                try:
                    _emit("message.start", sid)
                    _run_prompt_submit(rid, sid, session, synth)
                except Exception as _n_exc:
                    print(
                        f"[tui_gateway] completion notification dispatch failed: "
                        f"{type(_n_exc).__name__}: {_n_exc}",
                        file=sys.stderr,
                    )
                    with session["history_lock"]:
                        session["running"] = False
        except Exception as _drain_exc:
            print(
                f"[tui_gateway] completion queue drain failed: "
                f"{type(_drain_exc).__name__}: {_drain_exc}",
                file=sys.stderr,
            )

    _host.workers.start(run, name="forecast-turn")


@rpc_validated("clipboard.paste")
def _(rid, params: dict) -> dict:
    session, err = _sess(params, rid)
    if err:
        return err
    try:
        from superforecasting_agent.runtime.clipboard import has_clipboard_image, save_clipboard_image
    except Exception as e:
        return _err(rid, 5027, f"clipboard unavailable: {e}")

    session["image_counter"] = session.get("image_counter", 0) + 1
    img_dir = _hermes_home / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    img_path = (
        img_dir
        / f"clip_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{session['image_counter']}.png"
    )

    # Save-first: mirrors CLI keybinding path; more robust than has_image() precheck
    if not save_clipboard_image(img_path):
        session["image_counter"] = max(0, session["image_counter"] - 1)
        msg = (
            "Clipboard has image but extraction failed"
            if has_clipboard_image()
            else "No image found in clipboard"
        )
        return _ok(rid, {"attached": False, "message": msg})

    session.setdefault("attached_images", []).append(str(img_path))
    return _ok(
        rid,
        {
            "attached": True,
            "path": str(img_path),
            "count": len(session["attached_images"]),
            **_image_meta(img_path),
        },
    )


@rpc_validated("image.attach")
def _(rid, params: dict) -> dict:
    session, err = _sess(params, rid)
    if err:
        return err
    raw = str(params.get("path", "") or "").strip()
    if not raw:
        return _err(rid, 4015, "path required")
    try:
        from superforecasting_agent.runtime.file_drop import (
            _IMAGE_EXTENSIONS,
            _detect_file_drop,
            _resolve_attachment_path,
            _split_path_input,
        )

        dropped = _detect_file_drop(raw)
        if dropped:
            image_path = dropped["path"]
            remainder = dropped["remainder"]
        else:
            path_token, remainder = _split_path_input(raw)
            image_path = _resolve_attachment_path(path_token)
            if image_path is None:
                return _err(rid, 4016, f"image not found: {path_token}")
        if image_path.suffix.lower() not in _IMAGE_EXTENSIONS:
            return _err(rid, 4016, f"unsupported image: {image_path.name}")
        session.setdefault("attached_images", []).append(str(image_path))
        return _ok(
            rid,
            {
                "attached": True,
                "path": str(image_path),
                "count": len(session["attached_images"]),
                "remainder": remainder,
                "text": remainder or f"[User attached image: {image_path.name}]",
                **_image_meta(image_path),
            },
        )
    except Exception as e:
        return _err(rid, 5027, str(e))


@rpc_validated("input.detect_drop")
def _(rid, params: dict) -> dict:
    session, err = _sess_nowait(params, rid)
    if err:
        return err
    try:
        # Import from the lightweight stdlib-only module, NOT cli.py — this
        # handler runs on the serial main dispatch thread on EVERY message, and
        # pulling cli.py (prompt_toolkit/fire/rich) onto that fast path adds
        # ~0.18s (worse under import-lock contention with the startup build).
        from superforecasting_agent.runtime.file_drop import _detect_file_drop

        raw = str(params.get("text", "") or "")
        dropped = _detect_file_drop(raw)
        if not dropped:
            return _ok(rid, {"matched": False})

        drop_path = dropped["path"]
        remainder = dropped["remainder"]
        if dropped["is_image"]:
            session.setdefault("attached_images", []).append(str(drop_path))
            text = remainder or f"[User attached image: {drop_path.name}]"
            return _ok(
                rid,
                {
                    "matched": True,
                    "is_image": True,
                    "path": str(drop_path),
                    "count": len(session["attached_images"]),
                    "text": text,
                    **_image_meta(drop_path),
                },
            )

        text = f"[User attached file: {drop_path}]" + (
            f"\n{remainder}" if remainder else ""
        )
        return _ok(
            rid,
            {
                "matched": True,
                "is_image": False,
                "path": str(drop_path),
                "name": drop_path.name,
                "text": text,
            },
        )
    except Exception as e:
        return _err(rid, 5027, str(e))


@rpc_validated("prompt.background")
def _(rid, params: dict) -> dict:
    session, err = _sess(params, rid)
    if err:
        return err
    text, parent = params.get("text", ""), params.get("session_id", "")
    if not text:
        return _err(rid, 4012, "text required")
    task_id = f"bg_{uuid.uuid4().hex[:6]}"

    with session["history_lock"]:
        session["_background_jobs"] = session.get("_background_jobs", 0) + 1

    def run():
        session_tokens = _set_session_context(task_id)
        background_agent = None
        try:
            from agent.agent_factory import build_agent

            # The parent already supplies resolved provider settings. Do not
            # resolve a different account while constructing its background work.
            background_agent = build_agent(
                runtime={}, **_background_agent_kwargs(session["agent"], task_id)
            )
            with session["history_lock"]:
                session.setdefault("_background_agents", {})[task_id] = background_agent
            if _host.workers.stopping:
                return
            result = background_agent.run_conversation(
                user_message=text,
                task_id=task_id,
            )
            _emit(
                "background.complete",
                parent,
                {
                    "task_id": task_id,
                    "text": (
                        result.get("final_response", str(result))
                        if isinstance(result, dict)
                        else str(result)
                    ),
                },
            )
        except Exception as e:
            _emit(
                "background.complete",
                parent,
                {"task_id": task_id, "text": f"error: {e}"},
            )
        finally:
            try:
                if background_agent is not None:
                    background_agent.close()
            finally:
                with session["history_lock"]:
                    session.get("_background_agents", {}).pop(task_id, None)
                    session["_background_jobs"] -= 1
                _clear_session_context(session_tokens)

    try:
        _host.workers.start(run, name="forecast-background")
    except BaseException:
        with session["history_lock"]:
            session["_background_jobs"] -= 1
        raise
    return _ok(rid, {"task_id": task_id})


# ── Methods: respond ─────────────────────────────────────────────────


def _respond(rid, params, key):
    r = params.get("request_id", "")
    entry = _pending.get(r)
    if not entry:
        return _err(rid, 4009, f"no pending {key} request")
    _, ev = entry
    _answers[r] = params.get(key, "")
    ev.set()
    return _ok(rid, {"status": "ok"})


@rpc_validated("clarify.respond")
def _(rid, params: dict) -> dict:
    return _respond(rid, params, "answer")


@rpc_validated("sudo.respond")
def _(rid, params: dict) -> dict:
    return _respond(rid, params, "password")


@rpc_validated("secret.respond")
def _(rid, params: dict) -> dict:
    return _respond(rid, params, "value")


@rpc_validated("approval.respond")
def _(rid, params: dict) -> dict:
    session, err = _sess(params, rid)
    if err:
        return err
    try:
        from tools.approval import resolve_gateway_approval

        return _ok(
            rid,
            {
                "resolved": resolve_gateway_approval(
                    session["session_key"],
                    params.get("choice", "deny"),
                    resolve_all=params.get("all", False),
                )
            },
        )
    except Exception as e:
        return _err(rid, 5004, str(e))


def _main_runtime_from_agent(agent) -> dict | None:
    """Build an aux-client main_runtime override from a live agent.

    Lets a one-shot inherit the session's provider/model/credentials so its
    output matches the model the user is actually coding with, instead of
    falling back to the cheapest auto-detected backend.
    """
    if agent is None:
        return None
    runtime: dict = {}
    for field in ("provider", "model", "base_url", "api_key", "api_mode", "auth_mode"):
        value = getattr(agent, field, None)
        if isinstance(value, str) and value.strip():
            runtime[field] = value.strip()
        elif field == "api_key" and callable(value):
            runtime[field] = value
    return runtime or None


@method("llm.oneshot")
def _(rid, params: dict) -> dict:
    """Run a single stateless LLM request outside any conversation.

    Generic helper for small generative chores (e.g. a commit message from a
    diff). Accepts either a named ``template`` + ``variables`` or an explicit
    ``instructions`` / ``input`` pair. When ``session_id`` resolves to a live
    session the call inherits that agent's model; otherwise it uses the
    configured auxiliary ``task`` backend. Never mutates session history, so
    prompt caching is untouched.
    """
    template = (params.get("template") or "").strip() or None
    instructions = params.get("instructions") or ""
    user_input = params.get("input") or ""
    variables = params.get("variables") if isinstance(params.get("variables"), dict) else {}
    task = (params.get("task") or "title_generation").strip() or "title_generation"

    try:
        max_tokens = int(params.get("max_tokens") or 1024)
    except (TypeError, ValueError):
        max_tokens = 1024
    temperature = params.get("temperature")
    if temperature is not None:
        try:
            temperature = float(temperature)
        except (TypeError, ValueError):
            temperature = None

    if not template and not str(instructions).strip() and not str(user_input).strip():
        return _err(rid, 4030, "llm.oneshot requires a template or instructions/input")

    # Optional: inherit the live session's model (no error if absent).
    session = _host.sessions.get(params.get("session_id") or "")
    main_runtime = _main_runtime_from_agent(session.get("agent")) if session else None

    try:
        from agent.oneshot import run_oneshot

        text = run_oneshot(
            instructions=instructions,
            user_input=user_input,
            template=template,
            variables=variables,
            task=task,
            max_tokens=max_tokens,
            temperature=temperature if temperature is not None else 0.3,
            main_runtime=main_runtime,
        )
    except KeyError as e:
        return _err(rid, 4031, str(e))
    except ValueError as e:
        return _err(rid, 4032, str(e))
    except Exception as e:
        logger.warning("llm.oneshot failed: %s", e)
        return _err(rid, 5030, f"one-shot generation failed: {e}")

    return _ok(rid, {"text": text})


# ── Methods: config ──────────────────────────────────────────────────


@rpc_validated("config.set")
def _(rid, params: dict) -> dict:
    key, value = params.get("key", ""), params.get("value", "")
    session = _host.sessions.get(params.get("session_id", ""))

    if key == "model":
        try:
            if not value:
                return _err(rid, 4002, "model value required")
            if session:
                # Reject during an in-flight turn.  agent.switch_model()
                # mutates self.model / self.provider / self.base_url /
                # self.client in place; the worker thread running
                # agent.run_conversation is reading those on every
                # iteration.  A mid-turn swap can send an HTTP request
                # with the new base_url but old model (or vice versa),
                # producing 400/404s the user never asked for.  Parity
                # with the gateway's running-agent /model guard.
                if session.get("running"):
                    return _err(
                        rid,
                        4009,
                        "session busy — /interrupt the current turn before switching models",
                    )
                result = _apply_model_switch(
                    params.get("session_id", ""), session, value
                )
            else:
                result = _apply_model_switch("", {"agent": None}, value)
            return _ok(
                rid,
                {"key": key, "value": result["value"], "warning": result["warning"]},
            )
        except Exception as e:
            return _err(rid, 5001, str(e))

    if key == "fast":
        raw = str(value or "").strip().lower()
        agent = session.get("agent") if session else None
        if agent is not None:
            current_fast = getattr(agent, "service_tier", None) == "priority"
        else:
            current_fast = _load_service_tier() == "priority"

        from superforecasting_agent.constants import parse_fast_mode_command
        try:
            nv = parse_fast_mode_command(raw, current_fast=current_fast)
        except ValueError as exc:
            return _err(rid, 4002, str(exc))
        if nv == "status":
            return _ok(rid, {"key": key, "value": "fast" if current_fast else "normal"})

        overrides = None
        if nv == "fast":
            from superforecasting_agent.runtime.models import resolve_fast_mode_overrides

            target_model = (
                getattr(agent, "model", None) if agent is not None else _resolve_model()
            )
            if not target_model:
                return _err(
                    rid,
                    4002,
                    "fast mode is not available without a selected model",
                )
            overrides = resolve_fast_mode_overrides(target_model)
            if overrides is None:
                return _err(
                    rid,
                    4002,
                    "fast mode is not available for this model",
                )

        _write_config_key("agent.service_tier", nv)
        if agent is not None:
            agent.service_tier = "priority" if nv == "fast" else None
            current_overrides = dict(getattr(agent, "request_overrides", {}) or {})
            current_overrides.pop("service_tier", None)
            current_overrides.pop("speed", None)
            if nv == "fast":
                current_overrides.update(overrides)
            agent.request_overrides = current_overrides
            _emit(
                "session.info",
                params.get("session_id", ""),
                _session_info(agent),
            )
        return _ok(rid, {"key": key, "value": nv})

    if key == "busy":
        raw = str(value or "").strip().lower()
        if raw in {"", "status"}:
            return _ok(rid, {"key": key, "value": _load_busy_input_mode()})
        if raw not in {"queue", "steer", "interrupt"}:
            return _err(rid, 4002, f"unknown busy mode: {value}")
        _write_config_key("display.busy_input_mode", raw)
        return _ok(rid, {"key": key, "value": raw})

    if key == "verbose":
        cycle = ["off", "new", "all", "verbose"]
        cur = (
            session.get("tool_progress_mode", _load_tool_progress_mode())
            if session
            else _load_tool_progress_mode()
        )
        if value and value != "cycle":
            nv = str(value).strip().lower()
            if nv not in cycle:
                return _err(rid, 4002, f"unknown verbose mode: {value}")
        else:
            try:
                idx = cycle.index(cur)
            except ValueError:
                idx = 2
            nv = cycle[(idx + 1) % len(cycle)]
        _write_config_key("display.tool_progress", nv)
        if session:
            session["tool_progress_mode"] = nv
            agent = session.get("agent")
            if agent is not None:
                agent.verbose_logging = nv == "verbose"
        return _ok(rid, {"key": key, "value": nv})

    if key == "yolo":
        try:
            if session:
                from tools.approval import (
                    disable_session_yolo,
                    enable_session_yolo,
                    is_session_yolo_enabled,
                )

                current = is_session_yolo_enabled(session["session_key"])
                if current:
                    disable_session_yolo(session["session_key"])
                    nv = "0"
                else:
                    enable_session_yolo(session["session_key"])
                    nv = "1"
            else:
                from tools.approval import is_process_yolo_enabled, set_process_yolo_enabled

                current = is_process_yolo_enabled()
                if current:
                    set_process_yolo_enabled(False)
                    nv = "0"
                else:
                    set_process_yolo_enabled(True)
                    nv = "1"
            return _ok(rid, {"key": key, "value": nv})
        except Exception as e:
            return _err(rid, 5001, str(e))

    if key == "reasoning":
        try:
            from superforecasting_agent.constants import parse_reasoning_effort

            arg = str(value or "").strip().lower()
            if arg in {"show", "on"}:
                cfg = _load_cfg()
                display = (
                    cfg.get("display") if isinstance(cfg.get("display"), dict) else {}
                )
                sections = (
                    display.get("sections")
                    if isinstance(display.get("sections"), dict)
                    else {}
                )
                display["show_reasoning"] = True
                sections["thinking"] = "expanded"
                display["sections"] = sections
                cfg["display"] = display
                _save_cfg(cfg)
                if session:
                    session["show_reasoning"] = True
                return _ok(rid, {"key": key, "value": "show"})
            if arg in {"hide", "off"}:
                cfg = _load_cfg()
                display = (
                    cfg.get("display") if isinstance(cfg.get("display"), dict) else {}
                )
                sections = (
                    display.get("sections")
                    if isinstance(display.get("sections"), dict)
                    else {}
                )
                display["show_reasoning"] = False
                sections["thinking"] = "hidden"
                display["sections"] = sections
                cfg["display"] = display
                _save_cfg(cfg)
                if session:
                    session["show_reasoning"] = False
                return _ok(rid, {"key": key, "value": "hide"})

            parsed = parse_reasoning_effort(arg)
            if parsed is None:
                return _err(rid, 4002, f"unknown reasoning value: {value}")
            _write_config_key("agent.reasoning_effort", arg)
            if session and session.get("agent") is not None:
                session["agent"].reasoning_config = parsed
            return _ok(rid, {"key": key, "value": arg})
        except Exception as e:
            return _err(rid, 5001, str(e))

    if key == "details_mode":
        nv = str(value or "").strip().lower()
        if nv not in _DETAIL_MODES:
            return _err(rid, 4002, f"unknown details_mode: {value}")
        cfg = _load_cfg()
        display = cfg.get("display") if isinstance(cfg.get("display"), dict) else {}
        sections = (
            display.get("sections") if isinstance(display.get("sections"), dict) else {}
        )
        display["details_mode"] = nv
        for section in _DETAIL_SECTION_NAMES:
            sections[section] = nv
        display["sections"] = sections
        cfg["display"] = display
        _save_cfg(cfg)
        return _ok(rid, {"key": key, "value": nv})

    if key.startswith("details_mode."):
        # Per-section override: `details_mode.<section>` writes to
        # `display.sections.<section>`. Empty value clears the explicit
        # override and lets frontend resolution apply built-in section defaults
        # before the global details_mode.
        section = key.split(".", 1)[1]
        if section not in _DETAIL_SECTION_NAMES:
            return _err(rid, 4002, f"unknown section: {section}")

        cfg = _load_cfg()
        display = cfg.get("display") if isinstance(cfg.get("display"), dict) else {}
        sections_cfg = (
            display.get("sections") if isinstance(display.get("sections"), dict) else {}
        )

        nv = str(value or "").strip().lower()
        if not nv:
            sections_cfg.pop(section, None)
            display["sections"] = sections_cfg
            cfg["display"] = display
            _save_cfg(cfg)
            return _ok(rid, {"key": key, "value": ""})

        if nv not in _DETAIL_MODES:
            return _err(rid, 4002, f"unknown details_mode: {value}")

        sections_cfg[section] = nv
        display["sections"] = sections_cfg
        cfg["display"] = display
        _save_cfg(cfg)
        return _ok(rid, {"key": key, "value": nv})

    if key == "thinking_mode":
        nv = str(value or "").strip().lower()
        allowed_tm = frozenset({"collapsed", "truncated", "full"})
        if nv not in allowed_tm:
            return _err(rid, 4002, f"unknown thinking_mode: {value}")
        _write_config_key("display.thinking_mode", nv)
        # Backward compatibility bridge: keep details_mode aligned.
        _write_config_key(
            "display.details_mode", "expanded" if nv == "full" else "collapsed"
        )
        return _ok(rid, {"key": key, "value": nv})

    if key == "compact":
        raw = str(value or "").strip().lower()
        cfg0 = _load_cfg()
        d0 = cfg0.get("display") if isinstance(cfg0.get("display"), dict) else {}
        cur_b = bool(d0.get("tui_compact", False))
        if raw in {"", "toggle"}:
            nv_b = not cur_b
        elif raw == "on":
            nv_b = True
        elif raw == "off":
            nv_b = False
        else:
            return _err(rid, 4002, f"unknown compact value: {value}")
        _write_config_key("display.tui_compact", nv_b)
        return _ok(rid, {"key": key, "value": "on" if nv_b else "off"})

    if key == "statusbar":
        raw = str(value or "").strip().lower()
        display = _load_cfg().get("display")
        d0 = display if isinstance(display, dict) else {}
        current = _coerce_statusbar(d0.get("tui_statusbar", "top"))

        if raw in {"", "toggle"}:
            nv = "top" if current == "off" else "off"
        elif raw == "on":
            nv = "top"
        elif raw in _STATUSBAR_MODES:
            nv = raw
        else:
            return _err(rid, 4002, f"unknown statusbar value: {value}")

        _write_config_key("display.tui_statusbar", nv)
        return _ok(rid, {"key": key, "value": nv})

    if key == "mouse":
        raw = str(value or "").strip().lower()
        cfg = _load_cfg()
        display = cfg.get("display") if isinstance(cfg.get("display"), dict) else {}
        current = _display_mouse_tracking(display)

        if raw in {"", "toggle"}:
            nv = not current
        elif raw == "on":
            nv = True
        elif raw == "off":
            nv = False
        else:
            return _err(rid, 4002, f"unknown mouse value: {value}")

        _write_config_key("display.mouse_tracking", nv)
        return _ok(rid, {"key": key, "value": "on" if nv else "off"})

    if key == "indicator":
        # Use an explicit None check rather than `value or ""` so falsy
        # non-string inputs (0, False, []) still surface as themselves
        # in the error message instead of looking like a blank value.
        raw = "" if value is None else _normalize_indicator_style(value)
        if raw not in _INDICATOR_STYLES:
            return _err(
                rid,
                4002,
                f"unknown indicator: {raw!r}; pick one of {'|'.join(_INDICATOR_STYLES)}",
            )
        _write_config_key("display.tui_status_indicator", raw)
        return _ok(rid, {"key": key, "value": raw})

    if key == "appearance":
        raw = str(value or "auto").strip().lower()
        if raw not in {"light", "dark", "auto"}:
            return _err(rid, 4002, "appearance must be light, dark, or auto")
        try:
            _write_config_key("display.appearance", raw)
            # Re-emit the skin so the TUI re-resolves light/dark live; the
            # payload carries the appearance for fromSkin's mode override.
            _emit("skin.changed", "", resolve_skin())
            return _ok(rid, {"key": key, "value": raw})
        except Exception as e:
            return _err(rid, 5001, str(e))

    if key in {"prompt", "personality", "skin"}:
        try:
            cfg = _load_cfg()
            if key == "prompt":
                if value == "clear":
                    cfg.pop("custom_prompt", None)
                    nv = ""
                else:
                    cfg["custom_prompt"] = value
                    nv = value
                _save_cfg(cfg)
            elif key == "personality":
                sid_key = params.get("session_id", "")
                pname, new_prompt = _validate_personality(str(value or ""), cfg)
                _write_config_key("display.personality", pname)
                _write_config_key("agent.system_prompt", new_prompt)
                nv = str(value or "default")
                history_reset, info = _apply_personality_to_session(
                    sid_key, session, new_prompt
                )
            else:
                _write_config_key(f"display.{key}", value)
                nv = value
                if key == "skin":
                    _emit("skin.changed", "", resolve_skin())
            resp = {"key": key, "value": nv}
            if key == "personality":
                resp["history_reset"] = history_reset
                if info is not None:
                    resp["info"] = info
            return _ok(rid, resp)
        except Exception as e:
            return _err(rid, 5001, str(e))

    return _err(rid, 4002, f"unknown config key: {key}")


@method("config.get")
def _(rid, params: dict) -> dict:
    key = params.get("key", "")
    if key == "provider":
        try:
            from superforecasting_agent.runtime.models import list_available_providers
            from superforecasting_agent.configuration.providers import normalize_provider

            model = _resolve_model()
            parts = model.split("/", 1)
            return _ok(
                rid,
                {
                    "model": model,
                    "provider": (
                        normalize_provider(parts[0]) if len(parts) > 1 else "unknown"
                    ),
                    "providers": list_available_providers(),
                },
            )
        except Exception as e:
            return _err(rid, 5013, str(e))
    if key == "profile":
        from superforecasting_agent.constants import display_agent_home

        return _ok(rid, {"home": str(_hermes_home), "display": display_agent_home()})
    if key == "full":
        return _ok(rid, {"config": _load_cfg()})
    if key == "prompt":
        return _ok(rid, {"prompt": _load_cfg().get("custom_prompt", "")})
    if key == "skin":
        return _ok(
            rid, {"value": (_load_cfg().get("display") or {}).get("skin", "default")}
        )
    if key == "indicator":
        # Normalize so a hand-edited config.yaml with stray casing or
        # an unknown value reads back the SAME value the TUI actually
        # rendered (frontend's `normalizeIndicatorStyle` falls back to
        # `_INDICATOR_DEFAULT` for the same inputs).  Otherwise
        # `/indicator` would print one thing while the UI shows another.
        raw = (_load_cfg().get("display") or {}).get("tui_status_indicator", "")
        norm = _normalize_indicator_style(raw)
        return _ok(
            rid,
            {"value": norm if norm in _INDICATOR_STYLES else _INDICATOR_DEFAULT},
        )
    if key == "personality":
        return _ok(
            rid,
            {"value": (_load_cfg().get("display") or {}).get("personality", "default")},
        )
    if key == "reasoning":
        cfg = _load_cfg()
        effort = str(
            (cfg.get("agent") or {}).get("reasoning_effort", "medium") or "medium"
        )
        display = (
            "show"
            if bool((cfg.get("display") or {}).get("show_reasoning", False))
            else "hide"
        )
        return _ok(rid, {"value": effort, "display": display})
    if key == "fast":
        return _ok(
            rid,
            {
                "value": (
                    "fast"
                    if (session := _host.sessions.get(params.get("session_id", "")))
                    and getattr(session.get("agent"), "service_tier", None)
                    == "priority"
                    else ("fast" if _load_service_tier() == "priority" else "normal")
                ),
            },
        )
    if key == "busy":
        return _ok(rid, {"value": _load_busy_input_mode()})
    if key == "details_mode":
        allowed_dm = frozenset({"hidden", "collapsed", "expanded"})
        raw = (
            str(
                (_load_cfg().get("display") or {}).get("details_mode", "collapsed")
                or "collapsed"
            )
            .strip()
            .lower()
        )
        nv = raw if raw in allowed_dm else "collapsed"
        return _ok(rid, {"value": nv})
    if key == "thinking_mode":
        allowed_tm = frozenset({"collapsed", "truncated", "full"})
        cfg = _load_cfg()
        raw = (
            str((cfg.get("display") or {}).get("thinking_mode", "") or "")
            .strip()
            .lower()
        )
        if raw in allowed_tm:
            nv = raw
        else:
            dm = (
                str(
                    (cfg.get("display") or {}).get("details_mode", "collapsed")
                    or "collapsed"
                )
                .strip()
                .lower()
            )
            nv = "full" if dm == "expanded" else "collapsed"
        return _ok(rid, {"value": nv})
    if key == "compact":
        on = bool((_load_cfg().get("display") or {}).get("tui_compact", False))
        return _ok(rid, {"value": "on" if on else "off"})
    if key == "statusbar":
        display = _load_cfg().get("display")
        raw = (
            display.get("tui_statusbar", "top") if isinstance(display, dict) else "top"
        )
        return _ok(rid, {"value": _coerce_statusbar(raw)})
    if key == "mouse":
        display = _load_cfg().get("display")
        on = _display_mouse_tracking(display)
        return _ok(rid, {"value": "on" if on else "off"})
    if key == "mtime":
        cfg_path = _hermes_home / "config.yaml"
        try:
            return _ok(
                rid, {"mtime": cfg_path.stat().st_mtime if cfg_path.exists() else 0}
            )
        except Exception:
            return _ok(rid, {"mtime": 0})
    return _err(rid, 4002, f"unknown config key: {key}")


@rpc_validated("setup.status")
def _(rid, params: dict) -> dict:
    try:
        from superforecasting_agent.runtime.main import _has_any_provider_configured

        return _ok(rid, {"provider_configured": bool(_has_any_provider_configured())})
    except Exception as e:
        return _err(rid, 5016, str(e))


# ── Methods: tools & system ──────────────────────────────────────────


@rpc_validated("process.stop")
def _(rid, params: dict) -> dict:
    session, err = _sess_nowait(params, rid)
    if err:
        return err
    session_key = session.get("session_key")
    if not session_key:
        return _err(rid, 4004, "session has no background-work owner")
    try:
        from tools.process_registry import process_registry

        return _ok(rid, {"killed": process_registry.kill_all(session_key=session_key)})
    except Exception as e:
        return _err(rid, 5010, str(e))


@rpc_validated("reload.mcp")
def _(rid, params: dict) -> dict:
    session = _host.sessions.get(params.get("session_id", ""))
    try:
        # Gate: /reload-mcp invalidates the prompt cache for this session.
        # Respect the ``approvals.mcp_reload_confirm`` config toggle — if
        # set (default true) AND the caller did not pass ``confirm=true``
        # in params, surface a warning to the transcript instead of just
        # reloading silently.  Users pass confirm=true either by
        # re-invoking after reading the warning, or by setting the
        # config key to false permanently.
        user_confirm = bool(params.get("confirm", False))
        if not user_confirm:
            try:
                from superforecasting_agent.runtime.config import load_config as _load_config

                _cfg = _load_config()
                _approvals = _cfg.get("approvals") if isinstance(_cfg, dict) else None
                _confirm_required = True
                if isinstance(_approvals, dict):
                    _confirm_required = bool(_approvals.get("mcp_reload_confirm", True))
            except Exception:
                _confirm_required = True
            if _confirm_required:
                # Return a structured response the Ink client can surface
                # as a warning/confirmation without actually reloading yet.
                # Ink's ops.ts reads ``status`` and prints ``message`` to
                # the transcript; a follow-up invocation with confirm=true
                # (or an `always` choice that flips the config) proceeds.
                return _ok(
                    rid,
                    {
                        "status": "confirm_required",
                        "message": (
                            "⚠️  /reload-mcp invalidates the prompt cache (next "
                            "message re-sends full input tokens). Reply `/reload-mcp "
                            "now` to proceed, or `/reload-mcp always` to proceed and "
                            "silence this prompt permanently."
                        ),
                    },
                )

        from tools.mcp_tool import shutdown_mcp_servers, discover_mcp_tools

        shutdown_mcp_servers()
        discover_mcp_tools()
        if session:
            agent = session["agent"]
            if hasattr(agent, "refresh_tools"):
                agent.refresh_tools()
            _emit("session.info", params.get("session_id", ""), _session_info(agent))

        # Honor `always=true` by persisting the opt-out to config.
        if bool(params.get("always", False)):
            try:
                _write_config_key("approvals.mcp_reload_confirm", False)
            except Exception as _exc:
                logger.warning("Failed to persist mcp_reload_confirm=false: %s", _exc)

        return _ok(rid, {"status": "reloaded"})
    except Exception as e:
        return _err(rid, 5015, str(e))


@rpc_validated("reload.env")
def _(rid, params: dict) -> dict:
    """Re-read the active agent-home ``.env`` into the gateway process via
    ``superforecasting_agent.runtime.config.reload_env``, matching classic CLI's ``/reload``
    handler.  Newly added API keys take effect on the next agent call
    without restarting the TUI.

    The credential pool / provider routing for any *already-constructed*
    agent does not auto-rebuild — that's the same behaviour as classic
    CLI's ``/reload``.  Users who want a brand-new credential resolution
    should follow with ``/new``.
    """
    try:
        from superforecasting_agent.runtime.config import reload_env

        count = reload_env()
        return _ok(rid, {"updated": int(count)})
    except Exception as e:
        return _err(rid, 5015, str(e))


_TUI_HIDDEN: frozenset[str] = frozenset(
    {
        "sethome",
        "set-home",
        "commands",
        "approve",
        "deny",
    }
)

_TUI_EXTRA: list[tuple[str, str, str]] = [
    ("/compact", "Toggle compact display mode", "TUI"),
    ("/logs", "Show recent gateway log lines", "TUI"),
    ("/mouse", "Toggle mouse/wheel tracking [on|off|toggle]", "TUI"),
]

# Commands that queue messages onto _pending_input in the CLI.
# In the TUI the slash worker subprocess has no reader for that queue,
# so slash.exec rejects them → TUI falls through to command.dispatch.
_PENDING_INPUT_COMMANDS: frozenset[str] = frozenset(
    {
        "retry",
        "queue",
        "q",
        "steer",
        "plan",
        "goal",
        "subgoal",
        "learn",
    }
)

_WORKER_BLOCKED_COMMANDS: frozenset[str] = frozenset({"snapshot", "snap"})


# ── Methods: paste ────────────────────────────────────────────────────

_paste_counter = 0


# ── Methods: complete ─────────────────────────────────────────────────

_FUZZY_CACHE_TTL_S = 5.0
_FUZZY_CACHE_MAX_FILES = 20000
_FUZZY_FALLBACK_EXCLUDES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".next",
        ".cache",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        "target",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)
_fuzzy_cache_lock = threading.Lock()
_fuzzy_cache: dict[str, tuple[float, list[str]]] = {}


def _list_repo_files(root: str) -> list[str]:
    """Return file paths relative to ``root``.

    Uses ``git ls-files`` from the repo top (resolved via
    ``rev-parse --show-toplevel``) so the listing covers tracked + untracked
    files anywhere in the repo, then converts each path back to be relative
    to ``root``. Files outside ``root`` (parent directories of cwd, sibling
    subtrees) are excluded so the picker stays scoped to what's reachable
    from the gateway's cwd. Falls back to a bounded ``os.walk(root)`` when
    ``root`` isn't inside a git repo. Result cached per-root for
    ``_FUZZY_CACHE_TTL_S`` so rapid keystrokes don't respawn git processes.
    """
    now = time.monotonic()
    with _fuzzy_cache_lock:
        cached = _fuzzy_cache.get(root)
        if cached and now - cached[0] < _FUZZY_CACHE_TTL_S:
            return cached[1]

    files: list[str] = []
    try:
        top_result = subprocess.run(
            ["git", "-C", root, "rev-parse", "--show-toplevel"],
            capture_output=True,
            timeout=2.0,
            check=False,
        )
        if top_result.returncode == 0:
            top = top_result.stdout.decode("utf-8", "replace").strip()
            list_result = subprocess.run(
                [
                    "git",
                    "-C",
                    top,
                    "ls-files",
                    "-z",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                ],
                capture_output=True,
                timeout=2.0,
                check=False,
            )
            if list_result.returncode == 0:
                for p in list_result.stdout.decode("utf-8", "replace").split("\0"):
                    if not p:
                        continue
                    rel = os.path.relpath(os.path.join(top, p), root).replace(
                        os.sep, "/"
                    )
                    # Skip parents/siblings of cwd — keep the picker scoped
                    # to root-and-below, matching Cmd-P workspace semantics.
                    if rel.startswith("../"):
                        continue
                    files.append(rel)
                    if len(files) >= _FUZZY_CACHE_MAX_FILES:
                        break
    except (OSError, subprocess.TimeoutExpired):
        pass

    if not files:
        # Fallback walk: skip vendor/build dirs + dot-dirs so the walk stays
        # tractable. Dotfiles themselves survive — the ranker decides based
        # on whether the query starts with `.`.
        try:
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                dirnames[:] = [
                    d
                    for d in dirnames
                    if d not in _FUZZY_FALLBACK_EXCLUDES and not d.startswith(".")
                ]
                rel_dir = os.path.relpath(dirpath, root)
                for f in filenames:
                    rel = f if rel_dir == "." else f"{rel_dir}/{f}"
                    files.append(rel.replace(os.sep, "/"))
                    if len(files) >= _FUZZY_CACHE_MAX_FILES:
                        break
                if len(files) >= _FUZZY_CACHE_MAX_FILES:
                    break
        except OSError:
            pass

    with _fuzzy_cache_lock:
        _fuzzy_cache[root] = (now, files)

    return files


def _fuzzy_basename_rank(name: str, query: str) -> tuple[int, int] | None:
    """Rank ``name`` against ``query``; lower is better. Returns None to reject.

    Tiers (kind):
      0 — exact basename
      1 — basename prefix (e.g. `app` → `appChrome.tsx`)
      2 — word-boundary / camelCase hit (e.g. `chrome` → `appChrome.tsx`)
      3 — substring anywhere in basename
      4 — subsequence match (every query char appears in order)

    Secondary key is `len(name)` so shorter names win ties.
    """
    if not query:
        return (3, len(name))

    nl = name.lower()
    ql = query.lower()

    if nl == ql:
        return (0, len(name))

    if nl.startswith(ql):
        return (1, len(name))

    # Word-boundary split: `foo-bar_baz.qux` → ["foo","bar","baz","qux"].
    # camelCase split: `appChrome` → ["app","Chrome"]. Cheap approximation;
    # falls through to substring/subsequence if it misses.
    parts: list[str] = []
    buf = ""
    for ch in name:
        if ch in "-_." or (ch.isupper() and buf and not buf[-1].isupper()):
            if buf:
                parts.append(buf)
            buf = ch if ch not in "-_." else ""
        else:
            buf += ch
    if buf:
        parts.append(buf)
    for p in parts:
        if p.lower().startswith(ql):
            return (2, len(name))

    if ql in nl:
        return (3, len(name))

    i = 0
    for ch in nl:
        if ch == ql[i]:
            i += 1
            if i == len(ql):
                return (4, len(name))

    return None


def _details_completion_item(value: str, meta: str = "") -> dict:
    return {"text": value, "display": value, "meta": meta}


def _details_root_completion_item(
    value: str, meta: str, needs_leading_space: bool
) -> dict:
    return _details_completion_item(
        f" {value}" if needs_leading_space else value,
        meta,
    )


def _details_completions(text: str) -> list[dict] | None:
    if not text.lower().startswith("/details"):
        return None

    stripped = text.strip()
    if stripped and not "/details".startswith(stripped.lower().split()[0]):
        return None

    body = text[len("/details") :]
    if body.startswith(" "):
        body = body[1:]
    parts = body.split()
    has_trailing_space = text.endswith(" ")
    sections = ("thinking", "tools", "subagents", "activity")
    modes = ("hidden", "collapsed", "expanded")

    if not body or (len(parts) == 0 and has_trailing_space):
        return [
            *[
                _details_root_completion_item(
                    mode, "global mode", not has_trailing_space
                )
                for mode in modes
            ],
            _details_root_completion_item(
                "cycle", "cycle global mode", not has_trailing_space
            ),
            *[
                _details_root_completion_item(
                    section, "section override", not has_trailing_space
                )
                for section in sections
            ],
        ]

    if len(parts) == 1 and not has_trailing_space:
        prefix = parts[0].lower()
        candidates = [*modes, "cycle", *sections]
        return [
            _details_completion_item(
                candidate,
                (
                    "section override"
                    if candidate in sections
                    else "cycle global mode" if candidate == "cycle" else "global mode"
                ),
            )
            for candidate in candidates
            if candidate.startswith(prefix) and candidate != prefix
        ]

    if len(parts) == 1 and has_trailing_space and parts[0].lower() in sections:
        return [
            *[
                _details_completion_item(mode, f"set {parts[0].lower()}")
                for mode in modes
            ],
            _details_completion_item("reset", f"clear {parts[0].lower()} override"),
        ]

    if len(parts) == 2 and not has_trailing_space and parts[0].lower() in sections:
        prefix = parts[1].lower()
        return [
            _details_completion_item(
                candidate,
                (
                    f"clear {parts[0].lower()} override"
                    if candidate == "reset"
                    else f"set {parts[0].lower()}"
                ),
            )
            for candidate in (*modes, "reset")
            if candidate.startswith(prefix) and candidate != prefix
        ]

    return []


@rpc_validated("theme.list")
def _(rid, params: dict) -> dict:
    """List every available theme (built-in skins + user skins) with its
    resolved color map and branding, so the TUI's /theme picker can render a
    live preview of each without a round-trip per theme. Also reports the
    currently active theme name."""
    try:
        from superforecasting_agent.runtime.skin_engine import (
            get_active_skin_name,
            init_skin_from_config,
            list_skins,
            load_skin,
        )

        cfg = _load_cfg()
        init_skin_from_config(cfg)
        active = get_active_skin_name()
        appearance = str((cfg.get("display") or {}).get("appearance", "auto")).strip().lower()
        if appearance not in {"light", "dark", "auto"}:
            appearance = "auto"
        themes = []
        for entry in list_skins():
            name = entry.get("name", "")
            if not name:
                continue
            try:
                skin = load_skin(name)
            except Exception:
                continue
            themes.append(
                {
                    "name": name,
                    "description": entry.get("description", ""),
                    "source": entry.get("source", "builtin"),
                    "colors": skin.colors,
                    "branding": skin.branding,
                }
            )
        return _ok(rid, {"themes": themes, "active": active, "appearance": appearance})
    except Exception as e:
        return _err(rid, 5036, str(e))


@rpc_validated("model.options")
def _(rid, params: dict) -> dict:
    try:
        from superforecasting_agent.runtime.inventory import build_models_payload, load_picker_context

        session = _host.sessions.get(params.get("session_id", ""))
        agent = session.get("agent") if session else None
        # Layer agent-session state on top of disk config — once an agent
        # is spawned, IT owns the live provider/model/base_url. Empty
        # agent attributes must NOT clobber disk config (with_overrides
        # is truthy-only).
        ctx = load_picker_context().with_overrides(
            current_provider=getattr(agent, "provider", "") if agent else "",
            current_model=(
                (getattr(agent, "model", "") if agent else "") or _resolve_model()
            ),
            current_base_url=getattr(agent, "base_url", "") if agent else "",
        )
        # picker_hints + canonical_order produce the TUI's required shape:
        # `authenticated`/`auth_type`/`key_env`/`warning` per row, in
        # CANONICAL_PROVIDERS declaration order. include_unconfigured=True
        # so the picker can show the full provider universe (with the
        # setup-hint warning attached) instead of only authed rows.
        # Curated model lists are preserved — list_authenticated_providers
        # populates `models` from the curated catalog, not provider_model_ids
        # (which would pull non-agentic models like TTS/embeddings/etc.).
        payload = build_models_payload(
            ctx,
            include_unconfigured=True,
            picker_hints=True,
            canonical_order=True,
            max_models=50,
        )
        # Surface the live reasoning effort so the picker can pre-select it on
        # the effort step. Prefer the running agent's in-memory config (set by
        # the /reasoning path) and fall back to disk for a cold gateway.
        try:
            rc = getattr(agent, "reasoning_config", None) if agent else None
            if not isinstance(rc, dict):
                rc = _load_reasoning_config()
            if isinstance(rc, dict):
                if rc.get("enabled") is False:
                    payload["reasoning_effort"] = "none"
                elif rc.get("effort"):
                    payload["reasoning_effort"] = str(rc["effort"])
        except Exception:
            pass
        return _ok(rid, payload)
    except Exception as e:
        return _err(rid, 5033, str(e))


@method("model.save_key")
def _(rid, params: dict) -> dict:
    """Save an API key for a provider, then return its refreshed model list.

    Params:
        slug: provider slug (e.g. "deepseek", "xai")
        api_key: the key value to save

    Returns the provider dict with models populated (same shape as
    model.options entries) on success.
    """
    try:
        from superforecasting_agent.runtime.auth import PROVIDER_REGISTRY
        from superforecasting_agent.runtime.config import is_managed, save_env_value
        from superforecasting_agent.runtime.inventory import build_models_payload, load_picker_context

        slug = (params.get("slug") or "").strip()
        api_key = (params.get("api_key") or "").strip()
        if not slug or not api_key:
            return _err(rid, 4001, "slug and api_key are required")

        if is_managed():
            return _err(rid, 4006, "managed install — credentials are read-only")

        pconfig = PROVIDER_REGISTRY.get(slug)
        if not pconfig:
            return _err(rid, 4002, f"unknown provider: {slug}")
        if pconfig.auth_type != "api_key":
            return _err(
                rid,
                4003,
                f"{pconfig.name} uses {pconfig.auth_type} auth — "
                f"run `superforecasting-agent model` to configure",
            )
        if not pconfig.api_key_env_vars:
            return _err(rid, 4004, f"no env var defined for {pconfig.name}")

        # Save the key to the active agent-home .env
        env_var = pconfig.api_key_env_vars[0]
        save_env_value(env_var, api_key)
        # Also set in current process so the refreshed inventory sees it.
        import os

        os.environ[env_var] = api_key

        # Refresh provider data via the shared inventory builder so this
        # surface stays in lock-step with model.options + dashboard
        # /api/model/options. picker_hints=True ensures the returned row
        # carries `authenticated` for the TUI frontend.
        session = _host.sessions.get(params.get("session_id", ""))
        agent = session.get("agent") if session else None
        ctx = load_picker_context().with_overrides(
            current_provider=getattr(agent, "provider", "") if agent else "",
            current_model=(
                (getattr(agent, "model", "") if agent else "") or _resolve_model()
            ),
            current_base_url=getattr(agent, "base_url", "") if agent else "",
        )
        payload = build_models_payload(
            ctx, picker_hints=True, max_models=50,
        )
        provider_data = next(
            (p for p in payload["providers"] if p["slug"] == slug), None
        )
        if provider_data is None:
            # Key was saved but provider didn't appear — still return success.
            provider_data = {
                "slug": slug,
                "name": pconfig.name,
                "is_current": False,
                "models": [],
                "total_models": 0,
                "authenticated": True,
            }
        # picker_hints sets `authenticated` from the row state, but the
        # synthetic fallback above doesn't go through that path.
        provider_data["authenticated"] = True
        return _ok(rid, {"provider": provider_data})
    except Exception as e:
        return _err(rid, 5034, str(e))


# ── In-TUI OAuth (device-code) ──────────────────────────────────────────
# The CLI's `superforecasting-agent auth` is a blocking interactive flow, so
# an expired Codex sign-in used to force the user OUT of the TUI. The
# device-code handshake needs no loopback listener — show a code, poll —
# which makes it fully drivable from the TUI: auth.start returns the
# verification URL + user code immediately and polls in a background
# thread; auth.poll reports pending/success/failure.
def _run_codex_device_poll(owner, attempt, grant) -> None:
    from superforecasting_agent.runtime import codex_device_flow as flow
    from superforecasting_agent.runtime.auth import _save_codex_tokens

    owner.run(
        attempt,
        interval=grant.interval,
        max_wait=flow.DEVICE_FLOW_MAX_WAIT_SECONDS,
        poll=lambda: flow.poll_device_token_once(grant),
        exchange=lambda result: flow.exchange_device_code(
            result["authorization_code"], result["code_verifier"]
        ),
        persist=lambda credentials: _save_codex_tokens(
            credentials["tokens"], credentials.get("last_refresh")
        ),
        success_message="signed in to OpenAI Codex",
        timeout_message="sign-in timed out after 15 minutes — run /auth again",
    )


def _refresh_agent_credentials_after_auth(sid: str, provider: str) -> bool:
    session = _host.sessions.get(sid or "")
    if session is None:
        return False
    try:
        with use_session(session):
            return _refresh_session_credentials_after_auth(sid, provider)
    except SessionBusy:
        return False


def _refresh_session_credentials_after_auth(sid: str, provider: str) -> bool:
    """Re-resolve *provider* credentials from disk and apply them to the live
    agent, so a fresh in-TUI sign-in takes effect WITHOUT a TUI restart.

    Mirrors what `_apply_model_switch` does (same model/provider, freshly
    resolved key) — the long-lived agent caches its api_key/base_url at
    construction, so newly-written Codex tokens are otherwise invisible until
    the process restarts. If the pre-auth agent build failed, it is reset and
    retried. Returns True when credentials were applied or a rebuild started.
    """
    session = _host.sessions.get(sid or "")
    if not session:
        return False
    # Don't mutate the agent mid-turn; the user just signed in interactively,
    # so this is virtually never contended, but stay consistent with the
    # /model running-guard rather than risk a torn client swap.
    if session.get("running"):
        return False
    from superforecasting_agent.hosting.builds import retry_build

    def cleanup_failed_build():
        # Keep each completed cleanup step across retries. Only a failed build
        # uses these markers; normal session disposal has its own owner.
        stop = session.get("_notif_stop")
        if stop is not None:
            stop.set()
        if not session.get("_build_notifications_released"):
            from tools.approval import unregister_gateway_notify
            unregister_gateway_notify(session["session_key"])
            session["_build_notifications_released"] = True
        failed_agent = session.get("agent")
        if failed_agent is not None:
            failed_agent.close()
            session["agent"] = None

    try:
        status = retry_build(
            session, cleanup=cleanup_failed_build,
            start=lambda: _start_agent_build(sid, session),
        )
    except Exception as exc:
        logger.warning("post-auth agent rebuild could not start: %s", exc)
        return False
    if status != "ready":
        return status == "started"
    agent = session.get("agent")
    try:
        from superforecasting_agent.hosting.credentials import refresh_credentials
        from superforecasting_agent.runtime.runtime_provider import resolve_runtime_provider

        if not refresh_credentials(agent, provider, resolve=resolve_runtime_provider):
            return False
        _restart_slash_worker(session)
        _emit("session.info", sid, _session_info(agent))
        return True
    except Exception as e:  # never turn a successful sign-in into an error
        logger.warning("post-auth credential refresh failed: %s", e)
        return False


@method("auth.start")
def _(rid, params: dict) -> dict:
    """Start an in-TUI provider sign-in. Currently: openai-codex device code.

    Returns {url, user_code, interval} for the TUI to display; completion is
    observed via auth.poll. One flow at a time — starting a new flow
    supersedes a pending one.
    """
    provider = (params.get("provider") or "openai-codex").strip().lower()
    if provider in {"codex", "openai", "chatgpt"}:
        provider = "openai-codex"
    if provider != "openai-codex":
        return _err(
            rid,
            4003,
            f"in-TUI sign-in supports openai-codex today; for {provider} use "
            "/api-key (data + API-key providers) or `superforecasting-agent auth "
            f"add {provider}` in a terminal",
        )
    try:
        from superforecasting_agent.runtime.codex_device_flow import request_device_code

        grant = request_device_code()
    except Exception as e:
        return _err(rid, 5035, str(e))

    owner = _host.sign_in
    attempt = owner.begin(
        provider=provider,
        session_id=(params.get("session_id") or "").strip(),
        user_code=grant.user_code,
        url=grant.verification_url,
    )
    try:
        _host.workers.start(
            lambda: _run_codex_device_poll(owner, attempt, grant), name="codex-device-poll"
        )
    except Exception as exc:
        owner.fail(attempt, str(exc))
        return _err(rid, 5035, str(exc))
    return _ok(
        rid,
        {
            "provider": provider,
            "url": grant.verification_url,
            "user_code": grant.user_code,
            "interval": grant.interval,
        },
    )


@method("auth.poll")
def _(rid, params: dict) -> dict:
    """Report the in-flight sign-in state: none | pending | success | failed |
    cancelled. With params.cancel, abandon the pending flow.

    On the FIRST observation of success, this refreshes the live agent's
    credentials in place (so the new sign-in works without a restart) and
    marks the flow consumed — a terminal status is reported exactly once, so
    a lingering second poll loop can't double-report "signed in".
    """
    snapshot = _host.sign_in.poll(cancel=bool(params.get("cancel")))
    if not snapshot:
        return _ok(rid, {"status": "none"})

    status = snapshot.get("status", "none")

    # Terminal states are reported once, then the flow is cleared so repeat
    # polls (and any stale concurrent watcher) see "none".
    if status in {"success", "failed", "cancelled"}:
        applied = False
        if status == "success":
            session_id = snapshot.get("session_id") or params.get("session_id") or ""
            applied = _refresh_agent_credentials_after_auth(
                session_id, snapshot.get("provider") or "openai-codex"
            )
        return _ok(
            rid,
            {
                "status": status,
                "provider": snapshot.get("provider"),
                "user_code": snapshot.get("user_code"),
                "url": snapshot.get("url"),
                "message": snapshot.get("message", ""),
                "credentials_applied": applied,
            },
        )

    return _ok(
        rid,
        {
            "status": status,
            "provider": snapshot.get("provider"),
            "user_code": snapshot.get("user_code"),
            "url": snapshot.get("url"),
            "message": snapshot.get("message", ""),
        },
    )


@method("model.disconnect")
def _(rid, params: dict) -> dict:
    """Remove credentials for a provider.

    Params:
        slug: provider slug (e.g. "deepseek", "xai")

    Returns success status and the provider's slug.
    """
    try:
        from superforecasting_agent.runtime.auth import PROVIDER_REGISTRY, clear_provider_auth
        from superforecasting_agent.runtime.config import remove_env_value

        slug = (params.get("slug") or "").strip()
        if not slug:
            return _err(rid, 4001, "slug is required")

        pconfig = PROVIDER_REGISTRY.get(slug)
        cleared_env = False
        cleared_auth = False

        # Remove API key env vars from .env and process
        if pconfig and pconfig.api_key_env_vars:
            for ev in pconfig.api_key_env_vars:
                if remove_env_value(ev):
                    cleared_env = True

        # Clear OAuth / credential pool state
        cleared_auth = clear_provider_auth(slug)

        if not cleared_env and not cleared_auth:
            return _err(rid, 4005, f"no credentials found for {slug}")

        provider_name = pconfig.name if pconfig else slug
        return _ok(
            rid,
            {
                "slug": slug,
                "name": provider_name,
                "disconnected": True,
            },
        )
    except Exception as e:
        return _err(rid, 5035, str(e))


# ── Methods: slash.exec ──────────────────────────────────────────────


def _mirror_slash_side_effects(sid: str, session: dict, command: str) -> str:
    """Apply side effects that must also hit the gateway's live agent."""
    parts = command.lstrip("/").split(None, 1)
    if not parts:
        return ""
    name, arg, agent = (
        parts[0],
        (parts[1].strip() if len(parts) > 1 else ""),
        session.get("agent"),
    )

    # Reject agent-mutating commands during an in-flight turn.  These
    # all do read-then-mutate on live agent/session state that the
    # worker thread running agent.run_conversation is using.  Parity
    # with the session.compress / session.undo guards and the gateway
    # runner's running-agent /model guard.
    _MUTATES_WHILE_RUNNING = {"model", "style", "personality", "prompt", "compress"}
    if name in _MUTATES_WHILE_RUNNING and session.get("running"):
        return f"session busy — /interrupt the current turn before running /{name}"

    try:
        if name == "model" and arg and agent:
            result = _apply_model_switch(sid, session, arg)
            return result.get("warning", "")
        elif name in {"style", "personality"} and arg and agent:
            _, new_prompt = _validate_personality(arg, _load_cfg())
            _apply_personality_to_session(sid, session, new_prompt)
        elif name == "prompt" and agent:
            cfg = _load_cfg()
            new_prompt = (cfg.get("agent") or {}).get("system_prompt", "") or ""
            from forecasting.protocol import build_forecast_chat_system_prompt

            agent.ephemeral_system_prompt = build_forecast_chat_system_prompt(
                new_prompt
            )
            agent._cached_system_prompt = None
        elif name == "compress" and agent:
            _compress_session_history(session, arg)
            _sync_session_key_after_compress(sid, session)
            _emit("session.info", sid, _session_info(agent))
        elif name == "fast" and agent:
            mode = arg.lower()
            if mode in {"fast", "on"}:
                agent.service_tier = "priority"
            elif mode in {"normal", "off"}:
                agent.service_tier = None
            _emit("session.info", sid, _session_info(agent))
        elif name == "reload-mcp" and agent and hasattr(agent, "reload_mcp_tools"):
            agent.reload_mcp_tools()
    except Exception as e:
        # Expired/missing provider sign-in is fixable WITHOUT leaving the TUI
        # — point at /auth instead of echoing the CLI's "run
        # `superforecasting-agent auth`" guidance (rate-limit errors are not
        # auth problems and keep their own message).
        if getattr(e, "relogin_required", False) or "missing access_token" in str(e):
            return (
                f"{e}\n\nSign in without leaving the TUI: run /auth "
                "(shows a code to enter at auth.openai.com, then reconnects this session)."
            )
        return f"live session sync failed: {e}"
    return ""


def _background_command_output(session: dict, name: str) -> str:
    from superforecasting_agent.tooling.background import describe_background, stop_background

    session_key = session.get("session_key")
    if not session_key:
        raise ValueError("session has no background-work owner")
    if name == "stop":
        return stop_background(session_key=session_key)
    return describe_background(agent_running=bool(session.get("running")), session_key=session_key)


def _command_handoff(rid, message: str, dispatch: str = "command.dispatch") -> dict:
    response = _err(rid, 4018, message)
    response["error"]["data"] = {"dispatch": dispatch, "execution_started": False}
    return response


@rpc_validated("slash.exec")
def _(rid, params: dict) -> dict:
    session, err = _sess_nowait(params, rid)
    if err:
        return err

    cmd = params.get("command", "").strip()
    if not cmd:
        return _err(rid, 4004, "empty command")

    # Skill slash commands and _pending_input commands must NOT go through the
    # slash worker — see _PENDING_INPUT_COMMANDS definition above. Plugin
    # commands must also avoid the worker, but unlike skills/pending-input they
    # still return normal slash.exec output so the TUI keeps the pager path.
    _cmd_text = cmd.lstrip("/") if cmd.startswith("/") else cmd
    _cmd_parts = _cmd_text.split(maxsplit=1)
    _cmd_base = (_cmd_parts[0] if _cmd_parts else "").lower()
    _cmd_arg = _cmd_parts[1] if len(_cmd_parts) > 1 else ""

    from superforecasting_agent.application.command_catalog import configured_command, resolve_command
    try:
        quick = configured_command(_cmd_base, _load_cfg().get("quick_commands", {}))
    except ValueError as exc:
        return _err(rid, 4018, str(exc))
    if quick is not None:
        # Execute only in command.dispatch: executing here and then returning an
        # error would make the client's fallback repeat a failed shell command.
        return _command_handoff(rid, "configured command: use command.dispatch")

    # Match dispatch's canonical command identity before selecting an owner.
    # Otherwise registry aliases can initialize the classic worker even when
    # their canonical operation is already native (for example /gateway).
    definition = resolve_command(_cmd_base)
    if definition is not None:
        _cmd_base = definition.name

    tool_action = None
    if _cmd_base == "tools":
        import shlex

        try:
            tool_arguments = shlex.split(_cmd_arg)
        except ValueError:
            tool_arguments = _cmd_arg.split()
        tool_action = tool_arguments[0] if tool_arguments else ""

    if tool_action == "list":
        from superforecasting_agent.application.tools import describe_tool_configuration
        from superforecasting_agent.tooling.selection import _get_platform_tools

        try:
            config = _load_cfg()
            enabled = _get_platform_tools(config, "cli", include_default_mcp_servers=False)
            output = describe_tool_configuration(enabled, config.get("mcp_servers") or {}, platform="cli")
            return _ok(rid, {"output": output})
        except ValueError as exc:
            return _err(rid, 4004, str(exc))

    if tool_action is not None and tool_action not in {"list", "enable", "disable"}:
        from superforecasting_agent.application.tools import describe_tools
        from superforecasting_agent.tooling.inventory import session_toolset_selection
        from superforecasting_agent.tooling.runtime import get_tool_definitions, get_toolset_for_tool

        selection = session_toolset_selection(session, _load_enabled_toolsets)
        definitions = get_tool_definitions(enabled_toolsets=selection, quiet_mode=True)
        return _ok(rid, {"output": describe_tools(definitions, get_toolset_for_tool)})

    if _cmd_base in {"agents", "stop"}:
        try:
            return _ok(rid, {"output": _background_command_output(session, _cmd_base)})
        except ValueError as exc:
            return _err(rid, 4004, str(exc))
        except Exception as exc:
            return _err(rid, 5030, f"Background command failed: {exc}")

    if _cmd_base == "debug":
        from superforecasting_agent.runtime.debug import slash_output

        try:
            with _host.command(session) as stop:
                if stop.is_set():
                    return _err(rid, 5030, "Debug command cancelled before execution")
                code, output = slash_output()
            if code:
                return _err(rid, 5030, output or "Debug command failed")
            return _ok(rid, {"output": output})
        except Exception as exc:
            return _err(rid, 5030, f"Debug command failed: {exc}")

    if _cmd_base == "skills":
        from superforecasting_agent.runtime.skills_hub import skills_slash_output

        try:
            with _host.command(session) as stop:
                if stop.is_set():
                    return _err(rid, 5030, "Skills command cancelled before execution")
                output = skills_slash_output(_cmd_arg)
            return _ok(rid, {"output": output})
        except Exception as exc:
            return _err(rid, 5030, f"Skills command failed: {exc}")

    if _cmd_base == "kanban":
        from superforecasting_agent.runtime.kanban import run_slash

        try:
            with _host.command(session) as stop:
                command_id = uuid.uuid4().hex
                sid = params.get("session_id", "")
                status = "failed"
                delivery_failed = False
                def notify(event, payload):
                    nonlocal delivery_failed
                    if delivery_failed:
                        return
                    try:
                        _emit(event, sid, {"command_id": command_id, **payload})
                    except Exception:
                        delivery_failed = True
                        logger.exception("Native command event delivery failed")
                def output(stream, text):
                    for offset in range(0, len(text), 4096):
                        notify("command.output", {"stream": stream, "text": text[offset:offset + 4096]})
                notify("command.started", {"request_id": str(rid), "name": "kanban"})
                try:
                    result = run_slash(_cmd_arg, stop_event=stop, output_limit=65536, on_output=output)
                    status = "cancelled" if stop.is_set() else "finished"
                    return _ok(rid, {"output": result})
                finally:
                    notify("command.finished", {"status": status})
        except ValueError as exc:
            return _err(rid, 4004, str(exc))
        except OSError as exc:
            return _err(rid, 5017, str(exc))

    if _cmd_base in {"config", "plugins", "toolsets", "profile", "bundles", "insights", "codex-runtime", "gquota", "platforms", "cron", "curator"}:
        return _command_handoff(rid, "native command: use command.dispatch")

    if _cmd_base in _PENDING_INPUT_COMMANDS:
        return _command_handoff(
            rid, f"pending-input command: use command.dispatch for /{_cmd_base}"
        )

    if _cmd_base in _WORKER_BLOCKED_COMMANDS:
        subcommand = _cmd_arg.split(maxsplit=1)[0].lower() if _cmd_arg else ""
        if subcommand in {"restore", "rewind"}:
            return _command_handoff(
                rid,
                "snapshot restore mutates live config/state; use command.dispatch for /snapshot restore",
            )
        return _command_handoff(rid, "snapshot command: use command.dispatch")

    try:
        from agent.skill_bundles import get_skill_bundles
        from superforecasting_agent.application.command_catalog import resolve_command

        if resolve_command(_cmd_base) is None and f"/{_cmd_base}" in get_skill_bundles():
            return _command_handoff(rid, "bundle command: use command.dispatch")
    except Exception:
        pass

    try:
        from agent.skill_commands import get_skill_commands

        _cmd_key = f"/{_cmd_base}"
        if _cmd_key in get_skill_commands():
            return _command_handoff(
                rid, f"skill command: use command.dispatch for {_cmd_key}"
            )
    except Exception:
        pass

    plugin_handler = None
    resolve_plugin_command_result = None
    if _cmd_base and resolve_command(_cmd_base) is None:
        try:
            from superforecasting_agent.runtime.plugins import (
                get_plugin_command_handler,
                resolve_plugin_command_result,
            )

            plugin_handler = get_plugin_command_handler(_cmd_base)
        except Exception:
            plugin_handler = None
            resolve_plugin_command_result = None

    if plugin_handler and resolve_plugin_command_result:
        try:
            result = resolve_plugin_command_result(plugin_handler(_cmd_arg))
            return _ok(rid, {"output": str(result or "(no output)")})
        except Exception as e:
            return _ok(rid, {"output": f"Plugin command error: {e}"})

    from superforecasting_agent.application.command_catalog import resolve_command

    if resolve_command(_cmd_base) is None:
        return _err(rid, 4011, f"unknown command: {_cmd_base}")

    session, err = _sess(params, rid)
    if err:
        return err

    from superforecasting_agent.hosting.legacy_commands import use_worker

    try:
        with use_worker(session, lambda: _SlashWorker(
            session["session_key"],
            getattr(session.get("agent"), "model", _resolve_model()),
        )) as worker:
            output = worker.run(cmd)
            warning = _mirror_slash_side_effects(params.get("session_id", ""), session, cmd)
        payload = {"output": output or "(no output)"}
        if warning:
            payload["warning"] = warning
        return _ok(rid, payload)
    except Exception as e:
        return _err(rid, 5030, str(e))


# ── Methods: voice ───────────────────────────────────────────────────


_voice_sid_lock = threading.Lock()
_voice_event_sid: str = ""


def _voice_emit(event: str, payload: dict | None = None) -> None:
    """Emit a voice event toward the session that most recently turned the
    mode on. Voice is process-global (one microphone), so there's only ever
    one sid to target; the TUI handler treats an empty sid as "active
    session". Kept separate from _emit to make the lack of per-call sid
    argument explicit."""
    with _voice_sid_lock:
        sid = _voice_event_sid
    _emit(event, sid, payload)


def _speak_with_status(text: str, sid: str) -> None:
    """Run TTS on this (daemon) thread, bracketed with voice.status speaking/idle so the
    TUI can show a 'speaking' indicator + audiogram for the REAL playback duration (the
    start/stop are tied to speak_text actually opening/closing the speakers)."""
    try:
        from superforecasting_agent.runtime.voice import speak_text
    except Exception:
        return
    if sid:
        try:
            _emit("voice.status", sid, {"state": "speaking"})
        except Exception:
            pass
    try:
        speak_text(text)
    except Exception as e:
        logger.warning("voice TTS playback error: %s", e)
    finally:
        if sid:
            try:
                _emit("voice.status", sid, {"state": "idle"})
            except Exception:
                pass


def _voice_session_key(params: dict | None) -> str | None:
    """session_key for the session this voice RPC belongs to — params.session_id, else
    the active voice-event sid — or None when not resolvable (then VOICE/VOICE_TTS fall
    back to the process-global os.environ flag, i.e. today's behaviour)."""
    with _voice_sid_lock:
        sid = (params or {}).get("session_id") or _voice_event_sid
    return (_host.sessions.get(sid) or {}).get("session_key") if sid else None


def _voice_flag(session_key: str | None, name: str) -> bool:
    """Read a per-session voice flag (VOICE / VOICE_TTS): the session store wins, else
    the process-global os.environ alias. Reads _session_toggles directly so it is fresh
    even outside a seeded run-thread context (the voice RPC handler)."""
    if session_key:
        stored = _session_toggles.get(session_key, {}).get(name)
        if stored is not None:
            return stored.strip() == "1"
    return _runtime_env(name).strip() == "1"


def _voice_mode_enabled() -> bool:
    """Current voice-mode flag (runtime-only, CLI parity).

    cli.py initialises ``_voice_mode = False`` at startup and only flips
    it via ``/voice on``; it never reads a persisted enable bit from
    config.yaml.  We match that: no config lookup, env var only.  This
    avoids the TUI auto-starting in REC the next time the user opens it
    just because they happened to enable voice in a prior session.
    """
    return _runtime_env("VOICE").strip() == "1"


def _voice_tts_enabled() -> bool:
    """Whether agent replies should be spoken back via TTS (runtime only)."""
    return _runtime_env("VOICE_TTS").strip() == "1"


def _voice_cfg_dict() -> dict:
    """Shape-safe accessor for the ``voice:`` block in config.yaml.

    ``_load_cfg()`` returns raw ``yaml.safe_load()`` output, so both the
    root AND ``voice`` may be any YAML scalar / list / None. A hand-edit
    like ``voice: true`` or a malformed top-level config that parses to
    a scalar would otherwise break ``.get("…")`` and take every
    ``voice.*`` branch down with it (Copilot round-3..7 review on
    #19835). Coerce through ``isinstance`` at every level so malformed
    config falls back to an empty dict instead of crashing /voice.
    """
    cfg = _load_cfg()
    voice_cfg = cfg.get("voice") if isinstance(cfg, dict) else None

    return voice_cfg if isinstance(voice_cfg, dict) else {}


def _voice_record_key() -> str:
    """Current ``voice.record_key`` value, documented default on error."""
    record_key = _voice_cfg_dict().get("record_key")

    return str(record_key) if isinstance(record_key, str) and record_key else "ctrl+b"


# ── Methods: rollback ────────────────────────────────────────────────


# ── Methods: browser / plugins / cron / skills ───────────────────────


@method("plugins.list")
def _(rid, params: dict) -> dict:
    try:
        from superforecasting_agent.runtime.plugins import get_plugin_manager

        return _ok(
            rid,
            {
                "plugins": [
                    {
                        "name": n,
                        "version": getattr(i, "version", "?"),
                        "enabled": getattr(i, "enabled", True),
                    }
                    for n, i in get_plugin_manager()._plugins.items()
                ]
            },
        )
    except Exception as e:
        return _err(rid, 5032, str(e))


@method("config.show")
def _(rid, params: dict) -> dict:
    try:
        cfg = _load_cfg()
        model = _resolve_model(cfg)
        api_key = os.environ.get("HERMES_API_KEY", "") or cfg.get("api_key", "")
        from superforecasting_agent.configuration import model_section
        from superforecasting_agent.application.configuration_view import configuration_sections
        from superforecasting_agent.tooling.inventory import session_toolset_selection

        session = _host.sessions.get(params.get("session_id", "")) or {}
        agent = session.get("agent")
        base_url = os.environ.get("HERMES_BASE_URL", "") or model_section(cfg).get("base_url", "")
        sections = configuration_sections(
            model=getattr(agent, "model", model),
            base_url=getattr(agent, "base_url", base_url),
            api_key=getattr(agent, "api_key", api_key),
            max_turns=getattr(agent, "max_iterations", _cfg_max_turns(cfg, 90)),
            toolsets=session_toolset_selection(session, lambda: _load_enabled_toolsets(cfg)),
            verbose=getattr(agent, "verbose_logging", cfg.get("verbose", False)),
            cwd=os.getcwd(), config_path=str(_hermes_home / "config.yaml"),
        )
        return _ok(rid, {"sections": sections})
    except Exception as e:
        return _err(rid, 5030, str(e))


# ── Methods: shell ───────────────────────────────────────────────────


@rpc_validated("shell.exec")
def _(rid, params: dict) -> dict:
    cmd = params.get("command", "")
    if not cmd:
        return _err(rid, 4004, "empty command")
    try:
        from tools.approval import detect_dangerous_command, detect_hardline_command

        is_hardline, hardline_desc = detect_hardline_command(cmd)
        if is_hardline:
            return _err(
                rid, 4005, f"blocked (hardline): {hardline_desc}. Use the agent for dangerous commands."
            )
        is_dangerous, _, desc = detect_dangerous_command(cmd)
        if is_dangerous:
            return _err(
                rid, 4005, f"blocked: {desc}. Use the agent for dangerous commands."
            )
    except ImportError:
        return _err(rid, 5001, "shell.exec unavailable: approval safety module not importable")
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=os.getcwd()
        )
        return _ok(
            rid,
            {
                "stdout": r.stdout[-4000:],
                "stderr": r.stderr[-2000:],
                "code": r.returncode,
            },
        )
    except subprocess.TimeoutExpired:
        return _err(rid, 5002, "command timed out (30s)")
    except Exception as e:
        return _err(rid, 5003, str(e))


# ── Prediction-markets RPCs (Arc 4) — registered from a dedicated module so
# server.py only wires them; every pm.* handler lives in tui_gateway/pm_rpc.py.
from tui_gateway import pm_rpc as _pm_rpc  # noqa: E402

_pm_rpc.register(sys.modules[__name__])
atexit.register(_pm_rpc.shutdown)

# ── Market-data plane RPC (Arc C) — server-side quotes behind one service. ──
from tui_gateway import market_rpc as _market_rpc  # noqa: E402

_market_rpc.register(sys.modules[__name__])

# ── Carved RPC family modules (W2.a) — each replays its handlers into _methods
# via register(), re-entrant across importlib.reload(server) like pm_rpc/jobs_rpc.
from tui_gateway import obsidian_rpc as _obsidian_rpc  # noqa: E402
from tui_gateway import market_models_rpc as _market_models_rpc  # noqa: E402
from tui_gateway import forecast_rpc as _forecast_rpc  # noqa: E402
from tui_gateway import rollback_rpc as _rollback_rpc  # noqa: E402
from tui_gateway import agents_rpc as _agents_rpc  # noqa: E402
from tui_gateway import subagents_rpc as _subagents_rpc  # noqa: E402
from tui_gateway import completion_rpc as _completion_rpc  # noqa: E402
from tui_gateway import voice_rpc as _voice_rpc  # noqa: E402
from tui_gateway import browser_rpc as _browser_rpc  # noqa: E402
from tui_gateway import commands_rpc as _commands_rpc  # noqa: E402
from tui_gateway import tools_rpc as _tools_rpc  # noqa: E402
from tui_gateway import cron_skills_rpc as _cron_skills_rpc  # noqa: E402

_obsidian_rpc.register(sys.modules[__name__])
_market_models_rpc.register(sys.modules[__name__])
_forecast_rpc.register(sys.modules[__name__])
from tui_gateway import forecast_operations_rpc as _forecast_operations_rpc
_forecast_operations_rpc.register(sys.modules[__name__])
_rollback_rpc.register(sys.modules[__name__])
_agents_rpc.register(sys.modules[__name__])
_subagents_rpc.register(sys.modules[__name__])
_completion_rpc.register(sys.modules[__name__])
_voice_rpc.register(sys.modules[__name__])
_browser_rpc.register(sys.modules[__name__])
_commands_rpc.register(sys.modules[__name__])
_tools_rpc.register(sys.modules[__name__])
_cron_skills_rpc.register(sys.modules[__name__])

# Façade re-bind: tests call `server._cli_exec_blocked(argv)` directly (read-form),
# so keep the moved helper importable at its original path.
_cli_exec_blocked = _commands_rpc._cli_exec_blocked

from tui_gateway import host_rpc as _host_rpc
_host_rpc.register(sys.modules[__name__])
