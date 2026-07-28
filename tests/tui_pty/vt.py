"""A deliberately small VT100/xterm screen emulator.

Why this exists
---------------
The TUI is an Ink app that paints with cursor addressing: it emits
``\\x1b[12C`` to skip 12 columns rather than writing 12 spaces, and repaints
a frame by moving the cursor around and overwriting only the cells that
changed.  That means *stripping* the escape sequences out of a pty capture
does NOT reconstruct what a human sees — characters silently vanish
(``Home`` renders as ``Hom``, ``Setup Required`` as ``Stup Requid``).  Every
assertion built on stripped text is therefore a coin flip.

So we replay the byte stream into a real cell grid and assert on *that*.
This is a test-only emulator: it implements the subset of sequences Ink and
the terminal libraries in this repo actually emit, and deliberately ignores
colour (SGR), OSC, and every mode-set it does not need.  It is not trying to
be ``pyte`` — it is trying to be 200 lines of dependency-free, deterministic
truth about what landed on the screen.

Unsupported-but-harmless sequences are dropped, never rendered as text, so a
new escape code introduced upstream degrades into a missing cell rather than
garbage in the assertion.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["VTScreen"]

# CSI: ESC [ <private?> <params> <intermediates> <final>
_CSI_RE = re.compile(r"\x1b\[([\x30-\x3f]*)([\x20-\x2f]*)([\x40-\x7e])")
# OSC: ESC ] ... BEL   or   ESC ] ... ESC \
_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
# Two-byte escapes we ignore wholesale (charset selection, DECSC/DECRC, …)
_ESC2_RE = re.compile(r"\x1b[()*+][\x20-\x7e]|\x1b[=>78MDEHcZ]")


def _char_width(ch: str) -> int:
    """Terminal cell width of *ch* (0, 1, or 2)."""
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


class VTScreen:
    """Replay a pty byte stream into a ``rows x cols`` character grid."""

    def __init__(self, rows: int = 24, cols: int = 80) -> None:
        self.rows = rows
        self.cols = cols
        self._grid = [[" "] * cols for _ in range(rows)]
        self._row = 0
        self._col = 0
        # Alternate-screen support: ``\x1b[?1049h`` swaps in a fresh buffer and
        # ``\x1b[?1049l`` swaps the primary one back.  The TUI lives in the alt
        # screen, so without this the primary buffer's boot noise (node warnings)
        # would bleed into every assertion.
        self._saved: tuple[list[list[str]], int, int] | None = None
        self._pending = ""
        # Deferred wrap (DECAWM "pending wrap" flag).  Writing into the LAST
        # column does NOT move the cursor to the next line -- it parks it on
        # the last column and arms this flag, and only the *next* printable
        # character wraps.  Any cursor motion disarms it.  Without this a
        # full-width line (every box border the TUI draws at the terminal's
        # exact width) spuriously scrolls the screen by one row.
        self._wrap_pending = False

    # ── geometry ──────────────────────────────────────────────────────────

    def resize(self, rows: int, cols: int) -> None:
        """Resize the grid, preserving the top-left overlap (like a terminal)."""
        grid = [[" "] * cols for _ in range(rows)]
        for r in range(min(rows, self.rows)):
            for c in range(min(cols, self.cols)):
                grid[r][c] = self._grid[r][c]
        self._grid = grid
        self.rows, self.cols = rows, cols
        self._row = min(self._row, rows - 1)
        self._col = min(self._col, cols - 1)
        self._wrap_pending = False

    # ── output ────────────────────────────────────────────────────────────

    def rows_text(self) -> list[str]:
        """The grid as a list of right-stripped lines."""
        return ["".join(row).rstrip() for row in self._grid]

    def text(self) -> str:
        """The whole visible screen as newline-joined text."""
        return "\n".join(self.rows_text())

    def region_text(self, *, col_start: int = 0, col_end: int | None = None) -> str:
        """Text of a vertical column slice — used to assert on side panels."""
        end = self.cols if col_end is None else col_end
        return "\n".join("".join(row[col_start:end]).rstrip() for row in self._grid)

    # ── input ─────────────────────────────────────────────────────────────

    def feed(self, data: bytes | str) -> None:
        """Consume a chunk of pty output.  Safe to call with partial sequences."""
        if isinstance(data, bytes):
            data = data.decode("utf-8", "replace")
        buf = self._pending + data
        self._pending = ""
        i, n = 0, len(buf)

        while i < n:
            ch = buf[i]

            if ch == "\x1b":
                # A trailing partial escape: stash it for the next feed().
                consumed = self._try_escape(buf, i)
                if consumed is None:
                    self._pending = buf[i:]
                    return
                i += consumed
                continue

            i += 1

            # NOTE: "\n" is a LINE FEED only — it does not return to column 0.
            # Programs emit "\r\n"; and while the tty is still in cooked mode
            # the kernel's ONLCR does that translation for them. Treating "\n"
            # as CR+LF here would silently repair output that a real terminal
            # would render differently.
            if ch == "\r":
                self._col = 0
                self._wrap_pending = False
            elif ch == "\n":
                self._newline()
                self._wrap_pending = False
            elif ch == "\b":
                self._col = max(0, self._col - 1)
                self._wrap_pending = False
            elif ch == "\t":
                self._col = min(self.cols - 1, (self._col // 8 + 1) * 8)
                self._wrap_pending = False
            elif ch == "\x07":
                pass  # bell
            elif ch < " ":
                pass  # other C0 — never printable
            else:
                self._put(ch)

    # ── internals ─────────────────────────────────────────────────────────

    def _try_escape(self, buf: str, i: int) -> int | None:
        """Handle the escape at ``buf[i]``.  Returns chars consumed, or None
        when the sequence is truncated and we need more bytes."""
        rest = buf[i:]

        m = _CSI_RE.match(rest)
        if m:
            self._csi(m.group(1), m.group(3))
            return m.end()

        m = _OSC_RE.match(rest)
        if m:
            return m.end()

        m = _ESC2_RE.match(rest)
        if m:
            return m.end()

        # Could be an incomplete CSI/OSC awaiting more bytes. Only treat it as
        # garbage once we have enough lookahead that it cannot complete.
        if rest.startswith("\x1b[") or rest.startswith("\x1b]") or rest == "\x1b":
            return None
        return 1  # unknown lone ESC — drop it

    def _csi(self, params: str, final: str) -> None:
        # Every CSI that moves or erases disarms the pending wrap; the private
        # modes we ignore leave it alone (they emit nothing).
        if final not in "mhl":
            self._wrap_pending = False
        private = params.startswith("?") or params.startswith(">") or params.startswith("<")
        body = params.lstrip("?><")
        nums = [int(p) if p.isdigit() else 0 for p in body.split(";")] if body else []

        def arg(idx: int, default: int = 1) -> int:
            return nums[idx] if idx < len(nums) and nums[idx] else default

        if private:
            if final in "hl" and 1049 in nums:
                self._alt_screen(final == "h")
            return  # every other private mode (mouse, paste, cursor) is invisible

        if final == "m":
            return  # colour / attributes: invisible in a character grid
        if final in "ABCD":  # cursor up / down / forward / back
            n = arg(0)
            if final == "A":
                self._row = max(0, self._row - n)
            elif final == "B":
                self._row = min(self.rows - 1, self._row + n)
            elif final == "C":
                self._col = min(self.cols - 1, self._col + n)
            else:
                self._col = max(0, self._col - n)
        elif final in "Hf":  # CUP
            self._row = min(self.rows - 1, max(0, arg(0) - 1))
            self._col = min(self.cols - 1, max(0, arg(1) - 1))
        elif final == "G":  # CHA
            self._col = min(self.cols - 1, max(0, arg(0) - 1))
        elif final == "d":  # VPA
            self._row = min(self.rows - 1, max(0, arg(0) - 1))
        elif final in "EF":  # next / prev line
            self._row = min(self.rows - 1, max(0, self._row + (arg(0) if final == "E" else -arg(0))))
            self._col = 0
        elif final == "J":  # erase in display
            self._erase_display(nums[0] if nums else 0)
        elif final == "K":  # erase in line
            self._erase_line(nums[0] if nums else 0)
        elif final == "X":  # erase n chars
            for c in range(self._col, min(self.cols, self._col + arg(0))):
                self._grid[self._row][c] = " "
        elif final in "LM":  # insert / delete lines
            self._scroll_region(final, arg(0))
        elif final in "ST":  # scroll up / down
            self._scroll_screen(arg(0) if final == "S" else -arg(0))
        # everything else (DSR, DECSTBM, SGR-mouse reports, …) is a no-op

    def _alt_screen(self, enter: bool) -> None:
        if enter:
            if self._saved is None:
                self._saved = ([row[:] for row in self._grid], self._row, self._col)
            self._grid = [[" "] * self.cols for _ in range(self.rows)]
            self._row = self._col = 0
        elif self._saved is not None:
            grid, row, col = self._saved
            self._saved = None
            self._grid = [
                (r[:self.cols] + [" "] * max(0, self.cols - len(r)))
                for r in grid[: self.rows]
            ]
            while len(self._grid) < self.rows:
                self._grid.append([" "] * self.cols)
            self._row, self._col = min(row, self.rows - 1), min(col, self.cols - 1)

    def _erase_display(self, mode: int) -> None:
        if mode == 0:  # cursor → end
            self._erase_line(0)
            for r in range(self._row + 1, self.rows):
                self._grid[r] = [" "] * self.cols
        elif mode == 1:  # start → cursor
            for r in range(self._row):
                self._grid[r] = [" "] * self.cols
            self._erase_line(1)
        else:  # 2 = whole screen, 3 = + scrollback
            self._grid = [[" "] * self.cols for _ in range(self.rows)]

    def _erase_line(self, mode: int) -> None:
        row = self._grid[self._row]
        if mode == 0:
            for c in range(self._col, self.cols):
                row[c] = " "
        elif mode == 1:
            for c in range(0, min(self._col + 1, self.cols)):
                row[c] = " "
        else:
            self._grid[self._row] = [" "] * self.cols

    def _scroll_region(self, final: str, n: int) -> None:
        if final == "L":  # insert blank lines at cursor
            for _ in range(n):
                self._grid.insert(self._row, [" "] * self.cols)
                self._grid.pop()
        else:  # delete lines at cursor
            for _ in range(n):
                del self._grid[self._row]
                self._grid.append([" "] * self.cols)

    def _scroll_screen(self, n: int) -> None:
        for _ in range(abs(n)):
            if n > 0:
                self._grid.pop(0)
                self._grid.append([" "] * self.cols)
            else:
                self._grid.insert(0, [" "] * self.cols)
                self._grid.pop()

    def _newline(self) -> None:
        if self._row >= self.rows - 1:
            self._scroll_screen(1)
        else:
            self._row += 1

    def _put(self, ch: str) -> None:
        width = _char_width(ch)
        if width == 0:
            return  # combining mark: folded into the preceding cell
        if self._wrap_pending:
            self._col = 0
            self._newline()
            self._wrap_pending = False
        # A double-width glyph will not straddle the right margin: it wraps.
        if width == 2 and self._col + 1 >= self.cols:
            self._col = 0
            self._newline()
        self._grid[self._row][self._col] = ch
        # A wide glyph owns two cells; the second holds a zero-length filler so
        # column indexing stays honest while joined text keeps its real length.
        for pad in range(1, width):
            if self._col + pad < self.cols:
                self._grid[self._row][self._col + pad] = ""
        if self._col + width >= self.cols:
            self._col = self.cols - 1
            self._wrap_pending = True
        else:
            self._col += width
