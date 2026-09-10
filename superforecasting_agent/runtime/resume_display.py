"""Render saved forecast conversations and replay their recap on resize."""

import shutil

from rich.console import Console

from .assistant_text import _strip_reasoning_tags
from .console_output import _record_output_history_entry, _suspend_output_history

def _display_resumed_history(self):
    """Render a compact recap of previous forecast-session messages.

        Uses Rich markup with dim/muted styling so the recap is visually
        distinct from the active conversation.  Caps the display at the
        last ``MAX_DISPLAY_EXCHANGES`` user/forecaster exchanges and shows
        an indicator for earlier hidden messages.
        """
    if not self.conversation_history:
        return

    # Check config: resume_display setting
    if self.resume_display == "minimal":
        return

    MAX_DISPLAY_EXCHANGES = 10   # max user+assistant pairs to show
    MAX_USER_LEN = 300           # truncate user messages
    MAX_ASST_LEN = 200           # truncate assistant text
    MAX_ASST_LINES = 3           # max lines of assistant text

    # Collect displayable entries (skip system, tool-result messages)
    entries = []  # list of (role, display_text)
    _last_asst_idx = None       # index of last assistant entry
    _last_asst_full = None      # un-truncated display text for last assistant
    for msg in self.conversation_history:
        role = msg.get("role", "")
        content = msg.get("content")
        tool_calls = msg.get("tool_calls") or []

        if role == "system":
            continue
        if role == "tool":
            continue

        if role == "user":
            text = "" if content is None else str(content)
            # Handle multimodal content (list of dicts)
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif isinstance(part, dict) and part.get("type") == "image_url":
                        parts.append("[image]")
                text = " ".join(parts)
            if len(text) > MAX_USER_LEN:
                text = text[:MAX_USER_LEN] + "..."
            entries.append(("user", text))

        elif role == "assistant":
            text = "" if content is None else str(content)
            text = _strip_reasoning_tags(text)
            parts = []
            full_parts = []  # un-truncated version
            if text:
                full_parts.append(text)
                lines = text.splitlines()
                if len(lines) > MAX_ASST_LINES:
                    text = "\n".join(lines[:MAX_ASST_LINES]) + " ..."
                if len(text) > MAX_ASST_LEN:
                    text = text[:MAX_ASST_LEN] + "..."
                parts.append(text)
            if tool_calls:
                tc_count = len(tool_calls)
                # Extract tool names
                names = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "unknown") if isinstance(fn, dict) else "unknown"
                    if name not in names:
                        names.append(name)
                names_str = ", ".join(names[:4])
                if len(names) > 4:
                    names_str += ", ..."
                noun = "call" if tc_count == 1 else "calls"
                tc_summary = f"[{tc_count} tool {noun}: {names_str}]"
                parts.append(tc_summary)
                full_parts.append(tc_summary)
            if not parts:
                # Skip pure-reasoning messages that have no visible output
                continue
            entries.append(("assistant", " ".join(parts)))
            _last_asst_idx = len(entries) - 1
            _last_asst_full = " ".join(full_parts)

    if not entries:
        return

    # Determine if we need to truncate
    skipped = 0
    if len(entries) > MAX_DISPLAY_EXCHANGES * 2:
        skipped = len(entries) - MAX_DISPLAY_EXCHANGES * 2
        entries = entries[skipped:]

    # Replace last assistant entry with full (un-truncated) text
    # so the user can see where they left off without wasting tokens.
    if _last_asst_idx is not None and _last_asst_full:
        adj_idx = _last_asst_idx - skipped
        if 0 <= adj_idx < len(entries):
            entries[adj_idx] = ("assistant_last", _last_asst_full)

    # Build the display using Rich
    from rich.panel import Panel
    from rich.text import Text

    try:
        from superforecasting_agent.runtime.skin_engine import get_active_skin
        _skin = get_active_skin()
        _history_text_c = _skin.get_color("banner_text", "#FFF8DC")
        _session_label_c = _skin.get_color("session_label", "#DAA520")
        _session_border_c = _skin.get_color("session_border", "#8B8682")
        _assistant_label_c = _skin.get_color("ui_ok", "#8FBC8F")
    except Exception:
        _history_text_c = "#FFF8DC"
        _session_label_c = "#DAA520"
        _session_border_c = "#8B8682"
        _assistant_label_c = "#8FBC8F"

    lines = Text()
    if skipped:
        lines.append(
            f"  ... {skipped} earlier messages ...\n\n",
            style="dim italic",
        )

    for i, (role, text) in enumerate(entries):
        if role == "user":
            lines.append("  ● You: ", style=f"dim bold {_session_label_c}")
            # Show first line inline, indent rest
            msg_lines = text.splitlines() or [""]
            lines.append(msg_lines[0] + "\n", style="dim")
            for ml in msg_lines[1:]:
                lines.append(f"         {ml}\n", style="dim")
        elif role == "assistant_last":
            # Last forecaster response shown in full, non-dim
            lines.append("  ◆ Forecaster: ", style=f"bold {_assistant_label_c}")
            msg_lines = text.splitlines()
            lines.append(msg_lines[0] + "\n", style="")
            for ml in msg_lines[1:]:
                lines.append(f"            {ml}\n", style="")
        else:
            lines.append("  ◆ Forecaster: ", style=f"dim bold {_assistant_label_c}")
            msg_lines = text.splitlines()
            lines.append(msg_lines[0] + "\n", style="dim")
            for ml in msg_lines[1:]:
                lines.append(f"            {ml}\n", style="dim")
        if i < len(entries) - 1:
            lines.append("")  # small gap

    panel = Panel(
        lines,
        title=f"[dim {_session_label_c}]Previous Forecast Session[/]",
        border_style=f"dim {_session_border_c}",
        padding=(0, 1),
        style=_history_text_c,
    )
    _record_output_history_entry(lambda: self._render_resume_history_panel_lines(panel))
    with _suspend_output_history():
        self._console_print(panel)


def _render_resume_history_panel_lines(self, panel) -> list[str]:
    """Render the resume panel at the current terminal width for resize replay."""
    from io import StringIO

    buf = StringIO()
    width = shutil.get_terminal_size((80, 24)).columns
    console = Console(
        file=buf,
        force_terminal=True,
        color_system="truecolor",
        highlight=False,
        width=width,
    )
    with _suspend_output_history():
        console.print(panel)
    return buf.getvalue().rstrip("\n").splitlines()
