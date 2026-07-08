#!/bin/bash
# Capture the raw escape-stream the TUI writes in a real session.
# Usage: bash scripts/tui-frame-capture.sh   (from the repo root, in YOUR terminal)
# Then: open the chat, type ~5 plain characters, Ctrl+C / quit.
OUT=/tmp/tui-capture-$(date +%s).raw
{ echo "TERM_PROGRAM=$TERM_PROGRAM $TERM_PROGRAM_VERSION TERM=$TERM COLS=$(tput cols) LINES=$(tput lines)"; } > "$OUT.env"
echo "capturing to $OUT — type a few characters in the chat, then quit the TUI"
script -q "$OUT" "$(command -v superforecasting-agent || echo .venv/bin/superforecasting-agent)" --tui
echo "done: $OUT ($(wc -c < "$OUT") bytes) + $OUT.env — tell the agent the path"
