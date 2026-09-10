"""Agent output sinks, lifecycle notifications, and buffered retry status."""

import logging
import sys

logger = logging.getLogger("run_agent")


def _safe_print(self, *args, **kwargs):
    """Print that silently handles broken pipes / closed stdout.

        In headless environments (systemd, Docker, nohup) stdout may become
        unavailable mid-session.  A raw ``print()`` raises ``OSError`` which
        can crash cron jobs and lose completed work.

        Internally routes through ``self._print_fn`` (default: builtin
        ``print``) so callers such as the CLI can inject a renderer that
        handles ANSI escape sequences properly (e.g. prompt_toolkit's
        ``print_formatted_text(ANSI(...))``) without touching this method.
        """
    try:
        fn = self._print_fn or print
        fn(*args, **kwargs)
    except (OSError, ValueError):
        pass


def _vprint(self, *args, force: bool = False, **kwargs):
    """Verbose print — suppressed when actively streaming tokens.

        Pass ``force=True`` for error/warning messages that should always be
        shown even during streaming playback (TTS or display).

        During tool execution (``_executing_tools`` is True), printing is
        allowed even with stream consumers registered because no tokens
        are being streamed at that point.

        After the main response has been delivered and the remaining tool
        calls are post-response housekeeping (``_mute_post_response``),
        all non-forced output is suppressed.

        ``suppress_status_output`` is a stricter CLI automation mode used by
        parseable single-query flows such as
        ``superforecasting-agent chat -q``. In that mode, all
        status/diagnostic prints routed through ``_vprint`` are suppressed so
        stdout stays machine-readable.
        """
    if getattr(self, "suppress_status_output", False):
        return
    if not force and getattr(self, "_mute_post_response", False):
        return
    if not force and self._has_stream_consumers() and not self._executing_tools:
        return
    self._safe_print(*args, **kwargs)


def _should_start_quiet_spinner(self) -> bool:
    """Return True when quiet-mode spinner output has a safe sink.

        In headless/stdio-protocol environments, a raw spinner with no custom
        ``_print_fn`` falls back to ``sys.stdout`` and can corrupt protocol
        streams such as ACP JSON-RPC. Allow quiet spinners only when either:
        - output is explicitly rerouted via ``_print_fn``; or
        - stdout is a real TTY.
        """
    if self._print_fn is not None:
        return True
    stream = getattr(sys, "stdout", None)
    if stream is None:
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _should_emit_quiet_tool_messages(self) -> bool:
    """Return True when quiet-mode tool summaries should print directly.

        Quiet mode is used by both the interactive CLI and embedded/library
        callers. The CLI may still want compact progress hints when no callback
        owns rendering. Embedded/library callers, on the other hand, expect
        quiet mode to be truly silent.
        """
    return (
        self.quiet_mode
        and not self.tool_progress_callback
        and getattr(self, "platform", "") == "cli"
    )


def _emit_status(self, message: str) -> None:
    """Emit a lifecycle status message to both CLI and gateway channels.

        CLI users see the message via ``_vprint(force=True)`` so it is always
        visible regardless of verbose/quiet mode.  Gateway consumers receive
        it through ``status_callback("lifecycle", ...)``.

        This helper never raises — exceptions are swallowed so it cannot
        interrupt the retry/fallback logic.
        """
    try:
        self._vprint(f"{self.log_prefix}{message}", force=True)
    except Exception:
        pass
    if self.status_callback:
        try:
            self.status_callback("lifecycle", message)
        except Exception:
            logger.debug("status_callback error in _emit_status", exc_info=True)


def _emit_warning(self, message: str) -> None:
    """Emit a user-visible warning through the same status plumbing.

        Unlike debug logs, these warnings are meant for degraded side paths
        such as auxiliary compression or memory flushes where the main turn can
        continue but the user needs to know something important failed.
        """
    try:
        self._vprint(f"{self.log_prefix}{message}", force=True)
    except Exception:
        pass
    if self.status_callback:
        try:
            self.status_callback("warn", message)
        except Exception:
            logger.debug("status_callback error in _emit_warning", exc_info=True)


def _buffer_status(self, message: str) -> None:
    """Buffer a retry/fallback status message.

        Stored as a (kind, text) tuple where ``kind`` is one of:
        - ``"status"``  -> replays via ``_emit_status``
        - ``"vprint"``  -> replays via ``_vprint(force=True)``
        - ``"warn"``    -> replays via ``_emit_warning``
        Used to defer noisy retry chatter until we know whether the
        turn ultimately recovered or failed.
        """
    try:
        buf = getattr(self, "_retry_status_buffer", None)
        if buf is None:
            buf = []
            self._retry_status_buffer = buf
        buf.append(("status", message))
    except Exception:
        # Never break the retry loop on a buffer hiccup.
        pass


def _buffer_vprint(self, message: str) -> None:
    """Buffer a vprint(force=True) retry/fallback line."""
    try:
        buf = getattr(self, "_retry_status_buffer", None)
        if buf is None:
            buf = []
            self._retry_status_buffer = buf
        buf.append(("vprint", message))
    except Exception:
        pass


def _clear_status_buffer(self) -> None:
    """Drop buffered retry messages — call on successful recovery."""
    try:
        buf = getattr(self, "_retry_status_buffer", None)
        if buf:
            buf.clear()
    except Exception:
        pass


def _flush_status_buffer(self) -> None:
    """Emit buffered retry messages — call on terminal failure.

        Surfaces the full retry/fallback trace so the user can see what
        was tried before the turn gave up.
        """
    try:
        buf = getattr(self, "_retry_status_buffer", None)
        if not buf:
            return
        # Drain first so a callback exception doesn't double-emit.
        messages = list(buf)
        buf.clear()
        for kind, msg in messages:
            try:
                if kind == "status":
                    self._emit_status(msg)
                elif kind == "warn":
                    self._emit_warning(msg)
                else:
                    self._vprint(f"{self.log_prefix}{msg}", force=True)
            except Exception:
                pass
    except Exception:
        pass
