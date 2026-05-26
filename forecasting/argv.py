"""Argument splitting helpers for forecast CLI command strings."""

from __future__ import annotations

import shlex


def split_forecast_cli_args(raw_arg: str) -> list[str]:
    """Split a forecast command string with a tolerant update-rationale fallback.

    Slash-command surfaces receive text, not an already-tokenized argv. Normal
    shell-style splitting is still the right default, but forecast rationale
    text often contains apostrophes or other prose punctuation. If only the
    rationale tail is malformed for shell quoting, preserve it as raw text so a
    forecast update does not fail before argparse sees it.
    """

    try:
        return shlex.split(raw_arg)
    except ValueError:
        fallback = _split_raw_rationale_tail(raw_arg)
        if fallback is not None:
            return fallback
        raise


def _split_raw_rationale_tail(raw_arg: str) -> list[str] | None:
    marker = " --rationale "
    marker_index = raw_arg.find(marker)
    marker_length = len(marker)
    if marker_index < 0:
        marker = " --rationale="
        marker_index = raw_arg.find(marker)
        marker_length = len(marker)
    if marker_index < 0:
        return None

    prefix = raw_arg[:marker_index].strip()
    rationale = raw_arg[marker_index + marker_length :].strip()
    if not prefix or not rationale:
        return None

    try:
        argv = shlex.split(f"{prefix} --rationale")
    except ValueError:
        return None

    return [*argv, _strip_unbalanced_edge_quote(rationale)]


def _strip_unbalanced_edge_quote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    if value[:1] in {"'", '"'} and value.count(value[0]) == 1:
        return value[1:]
    return value
