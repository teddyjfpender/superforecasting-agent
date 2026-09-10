"""Prompt-toolkit output, background-thread dispatch, and bounded redraw history."""

import shutil

from rich.console import Console

from collections import deque
from contextlib import contextmanager

from prompt_toolkit import print_formatted_text as _pt_print
from prompt_toolkit.formatted_text import ANSI as _PT_ANSI


_OUTPUT_HISTORY_ENABLED = True
_OUTPUT_HISTORY_REPLAYING = False
_OUTPUT_HISTORY_SUPPRESSED = False
_OUTPUT_HISTORY_MAX_LINES = 200
_OUTPUT_HISTORY = deque(maxlen=_OUTPUT_HISTORY_MAX_LINES)


def _coerce_output_history_limit(value) -> int:
    try:
        return max(10, int(value))
    except (TypeError, ValueError):
        return 200


def _configure_output_history(enabled: bool, max_lines=200) -> None:
    """Configure recent CLI output replayed after terminal redraws."""
    global _OUTPUT_HISTORY_ENABLED, _OUTPUT_HISTORY_MAX_LINES, _OUTPUT_HISTORY
    _OUTPUT_HISTORY_ENABLED = bool(enabled)
    _OUTPUT_HISTORY_MAX_LINES = _coerce_output_history_limit(max_lines)
    _OUTPUT_HISTORY = deque(maxlen=_OUTPUT_HISTORY_MAX_LINES)


def _clear_output_history() -> None:
    _OUTPUT_HISTORY.clear()


@contextmanager
def _suspend_output_history():
    global _OUTPUT_HISTORY_SUPPRESSED
    old_value = _OUTPUT_HISTORY_SUPPRESSED
    _OUTPUT_HISTORY_SUPPRESSED = True
    try:
        yield
    finally:
        _OUTPUT_HISTORY_SUPPRESSED = old_value


def _record_output_history_entry(entry) -> None:
    if not _OUTPUT_HISTORY_ENABLED or _OUTPUT_HISTORY_REPLAYING or _OUTPUT_HISTORY_SUPPRESSED:
        return
    _OUTPUT_HISTORY.append(entry)


def _record_output_history(text: str) -> None:
    if not _OUTPUT_HISTORY_ENABLED or _OUTPUT_HISTORY_REPLAYING or _OUTPUT_HISTORY_SUPPRESSED:
        return
    normalized = str(text).replace("\r", "").rstrip("\n")
    if not normalized:
        return
    for line in normalized.splitlines():
        _record_output_history_entry(line)


def _replay_output_history() -> None:
    """Repaint recent output above the prompt after a full screen clear."""
    global _OUTPUT_HISTORY_REPLAYING
    if not _OUTPUT_HISTORY_ENABLED or not _OUTPUT_HISTORY:
        return
    _OUTPUT_HISTORY_REPLAYING = True
    try:
        rendered_lines = []
        for entry in tuple(_OUTPUT_HISTORY):
            if callable(entry):
                try:
                    lines = entry()
                except Exception:
                    continue
                if isinstance(lines, str):
                    lines = lines.splitlines()
            else:
                lines = [entry]
            rendered_lines.extend(str(line) for line in lines)
        if rendered_lines:
            # Replay after resize can contain hundreds of history lines. A
            # per-line prompt_toolkit print forces one synchronous terminal I/O
            # and redraw cycle per line, which users perceive as a waterfall of
            # old output. Keep the existing history contents unchanged, but
            # emit the replay as one ANSI payload so resize recovery does a
            # single prompt_toolkit print/redraw.
            _pt_print(_PT_ANSI("\n".join(rendered_lines)))
    except Exception:
        pass
    finally:
        _OUTPUT_HISTORY_REPLAYING = False


def _cprint(text: str):
    """Print ANSI-colored text through prompt_toolkit's native renderer.

    Raw ANSI escapes written via print() are swallowed by patch_stdout's
    StdoutProxy.  Routing through print_formatted_text(ANSI(...)) lets
    prompt_toolkit parse the escapes and render real colors.

    When called from a background thread while a prompt_toolkit
    ``Application`` is running (the common case for the self-improvement
    background review's ``💾 …`` summary, curator summaries, and other
    bg-thread emissions), a direct ``_pt_print`` races with the input
    area's redraw and the line can end up visually buried behind the
    prompt.  Route those cases through ``run_in_terminal`` via
    ``loop.call_soon_threadsafe``, which pauses the input area, prints
    the line above it, and redraws the prompt cleanly.
    """
    _record_output_history(text)

    try:
        from prompt_toolkit.application import get_app_or_none, run_in_terminal
    except Exception:
        _pt_print(_PT_ANSI(text))
        return

    app = None
    try:
        app = get_app_or_none()
    except Exception:
        app = None

    # No active app, or we're already on the app's main thread: the
    # direct prompt_toolkit print is safe and matches existing behavior
    # (spinner frames, streamed tokens, tool activity prefixes, …).
    if app is None or not getattr(app, "_is_running", False):
        try:
            _pt_print(_PT_ANSI(text))
        except Exception:
            # Fallback when stdout is not a real console (e.g. subprocess
            # worker logging to a file). prompt_toolkit raises
            # NoConsoleScreenBufferError (Windows) or OSError (other).
            try:
                print(text)
            except Exception:
                pass
        return

    try:
        loop = app.loop  # type: ignore[attr-defined]
    except Exception:
        loop = None
    if loop is None:
        _pt_print(_PT_ANSI(text))
        return

    import asyncio as _asyncio
    try:
        # Use get_running_loop() instead of get_event_loop() to avoid the
        # DeprecationWarning / RuntimeWarning emitted by Python 3.10+ when
        # get_event_loop() is called from a thread that has no current event
        # loop set (e.g. the process_loop background thread).  Fixes #19285.
        current_loop = _asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None
    except Exception:
        current_loop = None
    # Same thread as the app's loop → safe to print directly.
    if current_loop is loop and loop.is_running():
        _pt_print(_PT_ANSI(text))
        return

    # Cross-thread emission: ask the app's event loop to schedule a
    # ``run_in_terminal`` that wraps ``_pt_print``.  This hides the
    # prompt, prints, and redraws.  Fire-and-forget — if scheduling
    # fails we fall back to a direct print so the line isn't lost.
    def _schedule():
        # run_in_terminal() may return either:
        #   • a coroutine / Future (prompt_toolkit ≥ 3.0) — must be scheduled
        #     via ensure_future so the coroutine is actually awaited; calling
        #     it bare would leave it unawaited and silently drop the output
        #     (fixes #23185 Bug A).
        #   • None (some mocks / older PT builds) — just call the inner
        #     function directly since PT already executed it synchronously.
        # Do NOT fall back to a bare _pt_print when ensure_future raises,
        # because run_in_terminal already invoked the lambda in that case
        # (the mock path), which would double-print the line.
        try:
            import asyncio as _aio
            import inspect as _inspect
            coro = run_in_terminal(lambda: _pt_print(_PT_ANSI(text)))
            if coro is not None and (_inspect.isawaitable(coro) or _inspect.iscoroutine(coro)):
                _aio.ensure_future(coro)
            # else: run_in_terminal ran the lambda synchronously; nothing more
            # to do (double-scheduling would print twice).
        except Exception:
            pass  # best-effort; the line may already have been printed

    try:
        loop.call_soon_threadsafe(_schedule)
    except Exception:
        try:
            _pt_print(_PT_ANSI(text))
        except Exception:
            pass


class ChatConsole:
    """Rich Console adapter for prompt_toolkit's patch_stdout context.

    Captures Rich's rendered ANSI output and routes it through _cprint
    so colors and markup render correctly inside the interactive chat loop.
    Drop-in replacement for Rich Console — just pass this to any function
    that expects a console.print() interface.
    """

    def __init__(self):
        from io import StringIO
        self._buffer = StringIO()
        self._inner = Console(
            file=self._buffer,
            force_terminal=True,
            color_system="truecolor",
            highlight=False,
        )

    def print(self, *args, **kwargs):
        self._buffer.seek(0)
        self._buffer.truncate()
        # Read terminal width at render time so panels adapt to current size
        self._inner.width = shutil.get_terminal_size((80, 24)).columns
        self._inner.print(*args, **kwargs)
        output = self._buffer.getvalue()
        for line in output.rstrip("\n").split("\n"):
            _cprint(line)

    @contextmanager
    def status(self, *_args, **_kwargs):
        """Provide a no-op Rich-compatible status context.

        Some slash command helpers use ``console.status(...)`` when running in
        the standalone CLI. Interactive chat routes those helpers through
        ``ChatConsole()``, which historically only implemented ``print()``.
        Returning a silent context manager keeps slash commands compatible
        without duplicating the higher-level busy indicator already shown by
        ``ForecastCLI._busy_command()``.
        """
        yield self


_RST = "\033[0m"
# Use ANSI dim+italic attributes (\x1b[2;3m) instead of a hardcoded
# hex color so dim/thinking text inherits the terminal's default
# foreground color and stays readable in both light and dark
# Terminal.app modes.  Hardcoded skin colors like #B8860B
# (dark goldenrod) become invisible against light cream backgrounds.
_DIM = "\x1b[2;3m"
