"""Unit tests for the VT screen emulator.

Every assertion in ``test_tui_boot_smoke.py`` is only as trustworthy as this
emulator, so it gets its own tests -- and they run everywhere, with no node,
no bundle and no pty, because a silently-wrong emulator would turn the whole
directory into a green rubber stamp.

The first test is the one that motivated writing an emulator instead of a
regex: it reproduces exactly how Ink paints, and shows that ANSI-stripping
gets the wrong answer.
"""

from __future__ import annotations

import re

from .vt import VTScreen


def strip_ansi(data: str) -> str:
    """The naive approach this module exists to replace."""
    data = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", data)
    return re.sub(r"\x1b[@-Z\\-_]|\x1b\[[0-?]*[ -/]*[@-~]", "", data)


def test_cursor_forward_padding_defeats_ansi_stripping():
    """Ink pads with ESC[nC instead of spaces; stripping eats the gap."""
    # This is the real shape of a nav-bar paint, lifted from a pty capture:
    # "Home", two spaces of style change, then a 1-column skip, then "Desk".
    paint = "\x1b[H\x1b[38;5;225mHome\x1b[38;5;60m  \x1b[1C\x1b[38;5;146mDesk"

    screen = VTScreen(rows=3, cols=20)
    screen.feed(paint)

    assert screen.rows_text()[0] == "Home   Desk"
    # ...whereas the regex loses the skipped column entirely.
    assert strip_ansi(paint) == "Home  Desk"


def test_absolute_and_relative_cursor_motion():
    screen = VTScreen(rows=4, cols=12)
    screen.feed("\x1b[2;3Hmid")        # CUP: row 2, col 3
    screen.feed("\x1b[4;1Hbot")        # CUP: row 4, col 1
    screen.feed("\x1b[3;1H")           # CUP: row 3
    screen.feed("\x1b[4Cright")        # CUF: forward 4
    screen.feed("\x1b[1;1Ha\x1b[2Cb")  # home, write, skip 2, write

    assert screen.rows_text() == ["a  b", "  mid", "    right", "bot"]


def test_carriage_return_backspace_and_wrap():
    screen = VTScreen(rows=3, cols=5)
    screen.feed("abcdefgh")            # wraps at col 5
    assert screen.rows_text()[:2] == ["abcde", "fgh"]

    screen.feed("\rXY")                # CR then overwrite
    assert screen.rows_text()[1] == "XYh"

    screen.feed("\b\bZ")               # back from col 2 to col 0, overwrite
    assert screen.rows_text()[1] == "ZYh"


def test_line_feed_does_not_return_to_column_zero():
    """LF is LF.  Only CR (or the kernel's ONLCR) returns to column 0."""
    screen = VTScreen(rows=3, cols=10)
    screen.feed("abc\ndef")
    assert screen.rows_text()[:2] == ["abc", "   def"]

    screen = VTScreen(rows=3, cols=10)
    screen.feed("abc\r\ndef")
    assert screen.rows_text()[:2] == ["abc", "def"]


def test_writing_the_last_column_defers_the_wrap():
    """A full-width line must not scroll until something more is printed."""
    screen = VTScreen(rows=2, cols=4)
    screen.feed("abcd")                # exactly fills row 0
    assert screen.rows_text() == ["abcd", ""], "filling a row must not wrap yet"

    screen.feed("\r\nxy")              # explicit CR+LF: no phantom blank row
    assert screen.rows_text() == ["abcd", "xy"]

    # ...and the deferred wrap does fire when the next character arrives.
    screen = VTScreen(rows=2, cols=4)
    screen.feed("abcde")
    assert screen.rows_text() == ["abcd", "e"]

    # Cursor motion disarms the pending wrap instead of wrapping.
    screen = VTScreen(rows=2, cols=4)
    screen.feed("abcd\x1b[1;1HZ")
    assert screen.rows_text() == ["Zbcd", ""]


def test_erase_in_line_and_display():
    screen = VTScreen(rows=3, cols=8)
    screen.feed("aaaaaaaa\r\nbbbbbbbb\r\ncccccccc")

    screen.feed("\x1b[2;4H\x1b[K")     # EL 0: cursor to end of line 2
    assert screen.rows_text()[1] == "bbb"

    screen.feed("\x1b[1;1H\x1b[J")     # ED 0: cursor to end of screen
    assert screen.rows_text() == ["", "", ""]

    screen.feed("zzz\x1b[2J")          # ED 2: whole screen
    assert screen.rows_text() == ["", "", ""]


def test_alternate_screen_isolates_and_restores():
    screen = VTScreen(rows=2, cols=12)
    screen.feed("primary out\r\n")
    screen.feed("\x1b[?1049h")         # enter alt screen
    assert screen.text().strip() == "", "alt screen must start blank"

    screen.feed("\x1b[1;1Halt ui")
    assert screen.rows_text()[0] == "alt ui"

    screen.feed("\x1b[?1049l")         # leave: primary buffer comes back
    assert screen.rows_text()[0] == "primary out"
    assert "alt ui" not in screen.text()


def test_osc_and_unknown_sequences_never_leak_as_text():
    screen = VTScreen(rows=2, cols=30)
    screen.feed("\x1b]0;Forecast Desk\x07")      # OSC title (BEL-terminated)
    screen.feed("\x1b]9;4;0;\x1b\\")             # OSC (ST-terminated)
    screen.feed("\x1b[?2026h\x1b[?25l\x1b[>4m")  # private modes we ignore
    screen.feed("\x1b[38;5;146m\x1b[1mvisible\x1b[22m")

    assert screen.rows_text()[0] == "visible"
    for noise in ("Forecast Desk", "2026", "38;5;146"):
        assert noise not in screen.text()


def test_partial_escape_across_chunk_boundary_is_buffered():
    """A pty read can split a sequence; the halves must still combine."""
    screen = VTScreen(rows=2, cols=10)
    screen.feed(b"\x1b[2;")            # truncated CSI
    screen.feed(b"3Hok")               # completion + payload

    assert screen.rows_text()[1] == "  ok"


def test_region_text_slices_columns_for_side_panels():
    screen = VTScreen(rows=2, cols=20)
    screen.feed("\x1b[1;1HrailA\x1b[1;12Hbody1")
    screen.feed("\x1b[2;1HrailB\x1b[2;12Hbody2")

    assert screen.region_text(col_end=10) == "railA\nrailB"
    # Column offsets are preserved (only trailing blanks are trimmed), so a
    # slice reports where content sits, not just that it exists.
    assert screen.region_text(col_start=10) == " body1\n body2"
    assert "body1" in screen.region_text(col_start=10)


def test_resize_preserves_the_overlapping_corner():
    screen = VTScreen(rows=2, cols=6)
    screen.feed("abcdef\r\nghijkl")

    screen.resize(3, 4)
    assert screen.rows_text() == ["abcd", "ghij", ""]


def test_scrolling_off_the_bottom():
    screen = VTScreen(rows=3, cols=8)
    screen.feed("one\r\ntwo\r\nthree\r\nfour")

    assert screen.rows_text() == ["two", "three", "four"]


def test_wrapping_past_the_last_row_also_scrolls():
    screen = VTScreen(rows=2, cols=4)
    screen.feed("aaaa\r\nbbbb")   # both rows full, wrap armed on row 1
    assert screen.rows_text() == ["aaaa", "bbbb"]

    screen.feed("c")              # the wrap fires and pushes row 0 off
    assert screen.rows_text() == ["bbbb", "c"]


def test_fragmented_utf8_preserves_unicode_and_cursor_columns():
    text = "café 東京 — forecast"
    whole = VTScreen(rows=3, cols=40)
    whole.feed(text.encode("utf-8"))
    fragmented = VTScreen(rows=3, cols=40)
    for byte in text.encode("utf-8"):
        fragmented.feed(bytes([byte]))
    assert fragmented.text() == whole.text()
    assert "�" not in fragmented.text()
