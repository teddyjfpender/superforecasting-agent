"""Redaction remains authoritative with Uvicorn's real colored formatter."""

import logging

import pytest
from uvicorn.logging import DefaultFormatter

from superforecasting_agent.hosting.__main__ import _PrivateQueryFilter


@pytest.mark.parametrize("colors", [False, True])
@pytest.mark.parametrize(
    "message,args,colored,expected",
    [
        (
            "Uvicorn running on %s://%s:%d",
            ("http", "127.0.0.1", 54321),
            "Uvicorn running on \x1b[1m%s://%s:%d\x1b[0m",
            "Uvicorn running on http://127.0.0.1:54321",
        ),
        (
            'WebSocket "%s" accepted',
            ("/api/ws?token=do-not-log-this",),
            'WebSocket "\x1b[1m%s\x1b[0m" accepted',
            'WebSocket "/api/ws?[redacted]" accepted',
        ),
        (
            'WebSocket "%s" rejected',
            ("/api/ws?token=do-not-log-this",),
            'WebSocket "/api/ws?token=do-not-log-this" rejected',
            'WebSocket "/api/ws?[redacted]" rejected',
        ),
    ],
)
def test_formatter_cannot_restore_secret_or_unexpanded_template(
    colors, message, args, colored, expected
):
    record = logging.LogRecord(
        "uvicorn.error", logging.INFO, "", 0, message, args, None
    )
    record.color_message = colored
    redactor = _PrivateQueryFilter()
    assert redactor.filter(record)
    assert redactor.filter(record)  # Multiple handlers may share a record.
    rendered = DefaultFormatter(
        "%(levelprefix)s %(message)s", use_colors=colors
    ).format(record)
    assert expected in rendered
    assert "do-not-log-this" not in rendered
    assert "%s" not in rendered
    assert "%d" not in rendered
