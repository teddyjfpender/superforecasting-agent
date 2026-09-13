#!/usr/bin/env bash
# Install the Superforecasting Agent repository git hooks.
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

# Moves-only refactor law, blame half: skip the verified moves-only carve commits
# in `git blame` so authorship flows through the carve (see .git-blame-ignore-revs
# and docs/plans/2026-07-10-modularization-program.md §W0.2).
git config blame.ignoreRevsFile .git-blame-ignore-revs

cat <<'EOF'
Superforecasting Agent git hooks installed  (core.hooksPath = .githooks)

  pre-commit  shared Python quality/contracts | wire-drift | ESLint + tsc (if ui-tui)
  commit-msg  type(scope): subject shape | WHY-body for feat/refactor | MOVES-ONLY gate
  pre-push    shared quality gates | targeted pytest | vitest --changed

  Escape hatch (logged to .githooks/skips.log, never silent):
    HERMES_HOOKS_SKIP="why this once" git <cmd>
    HERMES_HOOKS_SKIP_TSC=1 git commit ...   # skip only the WIP TypeScript check

  Uninstall:  git config --unset core.hooksPath

  Architecture contracts (import-linter): `lint-imports` enforces the import
  directions in pyproject.toml [tool.importlinter] (CI: lint.yml ->
  lint-architecture). Install with `uv pip install -e ".[dev]"`, then run
  `lint-imports` before a push that touches package boundaries.

  git blame now skips the moves-only carve commits (.git-blame-ignore-revs).

  The laws these gates enforce: CONTRIBUTING.md -> "The Laws" and "Local Gates".
EOF
