#!/usr/bin/env bash
# Install the Hermes repository git hooks.
#
# Git hooks cannot install themselves (a fresh clone has no way to know the repo
# ships hooks), so every contributor runs this ONCE after cloning. It points
# git at the tracked .githooks/ directory — no copying, so the hooks stay in
# sync with the repo automatically.
#
#   scripts/install-hooks.sh
#
# Uninstall:  git config --unset core.hooksPath
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -d "$REPO_ROOT/.git" ] && [ ! -f "$REPO_ROOT/.git" ]; then
  echo "error: $REPO_ROOT is not a git repository" >&2
  exit 1
fi

git config core.hooksPath .githooks
chmod +x .githooks/pre-commit .githooks/commit-msg .githooks/pre-push 2>/dev/null || true

cat <<'EOF'
Hermes git hooks installed  (core.hooksPath = .githooks)

  pre-commit  ruff (changed .py) | codegen staleness | wire-drift | tsc (if ui-tui)
  commit-msg  type(scope): subject shape | WHY-body for feat/refactor | MOVES-ONLY gate
  pre-push    targeted pytest for changed domains | vitest --changed | codegen staleness

  Escape hatch (logged to .githooks/skips.log, never silent):
    HERMES_HOOKS_SKIP="why this once" git <cmd>
    HERMES_HOOKS_SKIP_TSC=1 git commit ...   # skip only the WIP TypeScript check

  Uninstall:  git config --unset core.hooksPath

  The laws these gates enforce: CONTRIBUTING.md -> "The Laws" and "Local Gates".
EOF
