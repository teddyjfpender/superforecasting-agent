#!/usr/bin/env bash
# Protocol staleness gate (Arc A / F(c)).
#
# Fails if `ui-tui/src/protocol/generated.ts` is out of date with the `protocol/`
# pydantic models — i.e. someone changed a wire model without regenerating the
# TypeScript. "generated types are stale" becomes an unmissable build error
# instead of a runtime mystery.
#
# Fix on failure:  python -m protocol.codegen   (then commit generated.ts)
#
# Usage:  scripts/check-protocol.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in \
    "$REPO_ROOT/.venv/bin/python" \
    "$REPO_ROOT/venv/bin/python" \
    "$(command -v python3 || true)" \
    "$(command -v python || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      PYTHON="$candidate"
      break
    fi
  done
fi

if [ -z "$PYTHON" ]; then
  echo "error: no python interpreter found for the protocol staleness gate" >&2
  exit 1
fi

cd "$REPO_ROOT"
exec "$PYTHON" -m protocol.codegen --check
