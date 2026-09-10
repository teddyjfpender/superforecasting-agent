"""Interactive forecast desk commands and question-reference resolution."""

import re
import shlex
import sys

from .console_output import _cprint


def _handle_forecast_command(self, cmd_original: str) -> None:
    """Handle /forecast by delegating to the forecast desk CLI."""
    parts = cmd_original.split(None, 1)
    raw_arg = parts[1].strip() if len(parts) > 1 else ""
    try:
        from forecasting.argv import split_forecast_cli_args

        argv = split_forecast_cli_args(raw_arg)
    except ValueError as exc:
        _cprint(f"  forecast: {exc}")
        return

    try:
        from forecasting.cli import main as forecast_main

        forecast_main(argv)
    except SystemExit as exc:
        if exc.code not in (None, 0) and not isinstance(exc.code, int):
            print(str(exc.code), file=sys.stderr)
    except Exception as exc:
        _cprint(f"  forecast: {exc}")


def _resolve_forecast_ref(cls, ref: str, *, limit: int = 75) -> str | None:
    from forecasting.dashboard import build_dashboard_summary

    trimmed = ref.strip()
    if not trimmed:
        return None

    try:
        summary = build_dashboard_summary(limit=limit)
    except Exception as exc:
        _cprint(f"  forecast lookup: {exc}")
        return None

    questions = list(summary.get("questions") or [])
    review_queue = list(summary.get("review_queue") or [])
    if trimmed.isdigit():
        index = int(trimmed)
        if index <= 0:
            _cprint("  Forecast row numbers start at 1.")
            return None
        try:
            return str(questions[index - 1]["id"])
        except (IndexError, KeyError, TypeError):
            _cprint(f"  No forecast row {index}. Run /questions to inspect current forecast questions.")
            return None

    lowered = trimmed.lower()
    for row in [*questions, *review_queue]:
        row_id = str(row.get("id") or "")
        if row_id.lower() == lowered or re.sub(r"^fq_", "", row_id).lower().startswith(lowered):
            return row_id

    matches = cls._forecast_search_matches(summary, trimmed, limit=8)
    top = matches[0] if matches else None
    next_match = matches[1] if len(matches) > 1 else None
    if top and top["row"].get("id") and (not next_match or int(top["score"]) >= int(next_match["score"]) + 10):
        return str(top["row"]["id"])

    if matches:
        cls._print_forecast_search(summary, trimmed)
    else:
        _cprint(f'  No forecast matched "{trimmed}". Try /find {trimmed}')
    return None


def _handle_forecast_book_command(self, cmd_original: str) -> None:
    """Handle /questions as a forecast-question summary and numbered drill-down."""
    parts = cmd_original.split(None, 1)
    raw_arg = parts[1].strip() if len(parts) > 1 else ""
    try:
        from forecasting.cli import main as forecast_main
        from forecasting.dashboard import build_dashboard_summary, render_forecast_book_text
    except Exception as exc:
        _cprint(f"  book: {exc}")
        return

    forecast_id_arg = re.match(r"^fq_[a-z0-9][a-z0-9_:-]*$", raw_arg, flags=re.IGNORECASE)
    if raw_arg and raw_arg.isdigit():
        question_id = self._resolve_forecast_ref(raw_arg, limit=max(int(raw_arg), 20))
        if question_id:
            forecast_main(["show", question_id])
        return

    if raw_arg and forecast_id_arg:
        forecast_main(["show", raw_arg])
        return

    if raw_arg and not raw_arg.lower().startswith("list"):
        try:
            self._print_forecast_search(build_dashboard_summary(limit=75), raw_arg)
        except Exception as exc:
            _cprint(f"  book: {exc}")
        return

    limit = 20
    if raw_arg:
        try:
            argv = shlex.split(raw_arg)
            if len(argv) > 1:
                limit = max(int(argv[1]), 1)
        except (ValueError, IndexError) as exc:
            _cprint(f"  book: {exc}")
            return

    try:
        print(render_forecast_book_text(build_dashboard_summary(limit=limit)))
    except Exception as exc:
        _cprint(f"  book: {exc}")


def _handle_forecast_ledger_command(self, cmd_original: str) -> None:
    """Handle /ledger as a compact forecast-store navigation shortcut."""
    parts = cmd_original.split(None, 1)
    raw_arg = parts[1].strip() if len(parts) > 1 else "book"
    view = raw_arg.lower().split(maxsplit=1)[0] if raw_arg else "book"
    try:
        from forecasting.dashboard import (
            build_dashboard_summary,
            render_dashboard_text,
            render_forecast_book_text,
        )

        summary = build_dashboard_summary(limit=75 if view == "search" else 20)
        if view in {"", "book", "questions", "desk", "state", "store"}:
            print(render_forecast_book_text(summary))
            return
        if view in {"all", "overview", "dashboard"}:
            print(render_dashboard_text(summary))
            return
        if view == "search":
            query = raw_arg.split(maxsplit=1)[1] if len(raw_arg.split(maxsplit=1)) > 1 else ""
            if not query:
                _cprint("  Usage: /ledger search <forecast words>")
                return
            self._print_forecast_search(summary, query)
            return

        self._print_forecast_search(build_dashboard_summary(limit=75), raw_arg)
    except Exception as exc:
        _cprint(f"  ledger: {exc}")


def _handle_forecast_find_command(self, cmd_original: str) -> None:
    parts = cmd_original.split(None, 1)
    query = parts[1].strip() if len(parts) > 1 else ""
    if not query:
        _cprint("  Usage: /find <forecast words>")
        return
    try:
        from forecasting.dashboard import build_dashboard_summary

        self._print_forecast_search(build_dashboard_summary(limit=75), query)
    except Exception as exc:
        _cprint(f"  find: {exc}")


def _handle_forecast_open_command(self, cmd_original: str) -> None:
    parts = cmd_original.split(None, 1)
    ref = parts[1].strip() if len(parts) > 1 else ""
    if not ref:
        _cprint("  Usage: /open <row|id|forecast words>")
        return
    question_id = self._resolve_forecast_ref(ref)
    if question_id:
        from forecasting.cli import main as forecast_main

        forecast_main(["show", question_id])


def _handle_forecast_evidence_for_command(self, cmd_original: str) -> None:
    parts = cmd_original.split(None, 1)
    raw_arg = parts[1].strip() if len(parts) > 1 else ""
    ref, note = self._split_forecast_ref_and_rest(raw_arg)
    if not ref or not note:
        _cprint("  Usage: /note <row|id|forecast words> -- <evidence note>")
        return
    question_id = self._resolve_forecast_ref(ref)
    if question_id:
        from forecasting.cli import main as forecast_main

        forecast_main(["research", question_id, note])


def _handle_forecast_update_for_command(self, cmd_original: str) -> None:
    parts = cmd_original.split(None, 1)
    raw_arg = parts[1].strip() if len(parts) > 1 else ""
    ref, rest = self._split_forecast_ref_and_rest(raw_arg)
    if not ref or not rest:
        _cprint("  Usage: /revise <row|id|forecast words> -- --probability <0-1> --rationale <why>")
        return
    question_id = self._resolve_forecast_ref(ref)
    if not question_id:
        return
    try:
        from forecasting.argv import split_forecast_cli_args

        argv = split_forecast_cli_args(rest)
    except ValueError as exc:
        _cprint(f"  revise: {exc}")
        return
    from forecasting.cli import main as forecast_main

    forecast_main(["update", question_id, *argv])
