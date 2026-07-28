#!/usr/bin/env bash
#
# Build an installable release of the Superforecasting Agent that bundles the
# prebuilt TUI, so it can be installed and launched WITHOUT a git checkout, a
# hand-rolled Python venv, or an npm install.
#
# The result is a wheel in dist/. Install it with pipx (which manages its own
# isolated venv) and launch the TUI:
#
#     pipx install dist/superforecasting_agent-*.whl
#     superforecasting-agent --tui
#
# The launcher finds the bundled TUI (hermes_cli/tui_dist/entry.js), runs it on
# Node — auto-provisioning Node via fnm/nvm/brew if it isn't already present —
# and spawns the gateway from the installed package's own Python. No source
# tree, no .venv, no `npm run build` on every pull.
#
# Mirrors the wheel build in .github/workflows/production-release.yml — the
# primary tag-triggered release pipeline — so a local build matches CI
# (upload_to_pypi.yml is the dormant opt-in CalVer path and no longer the
# reference). One deliberate difference: CI relies on the TRACKED
# hermes_cli/tui_dist/package.json ES-module marker surviving checkout (its
# bundle step only copies entry.js over it), while this script REWRITES the
# marker below so even a clean-room build holds the invariant.
#
# Env:
#   SKIP_NPM=1          reuse an existing ui-tui/dist/entry.js (skip npm ci+build)
#   RELEASE_WITH_WEB=1  also build + bundle the web dashboard (for --dashboard)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> [1/4] Building the TUI bundle (ui-tui → dist/entry.js)"
if [ "${SKIP_NPM:-0}" = "1" ] && [ -f ui-tui/dist/entry.js ]; then
  echo "    SKIP_NPM=1 — reusing existing ui-tui/dist/entry.js"
else
  ( cd ui-tui && npm ci --prefer-offline --no-audit && npm run build )
fi
test -f ui-tui/dist/entry.js || { echo "ERROR: ui-tui/dist/entry.js was not built"; exit 1; }

echo "==> [2/4] Bundling TUI into hermes_cli/tui_dist/"
mkdir -p hermes_cli/tui_dist
cp ui-tui/dist/entry.js hermes_cli/tui_dist/entry.js
# entry.js is an ES module. Without a "type" marker beside it Node walks UP
# looking for a package.json — finding the repo root's (which has none), warning
# MODULE_TYPELESS_PACKAGE_JSON to stderr before first paint and reparsing the
# bundle as ESM anyway. The file is tracked (see the .gitignore negation); this
# rewrite just keeps the invariant true for a clean-room build.
printf '{ "type": "module" }\n' > hermes_cli/tui_dist/package.json

if [ "${RELEASE_WITH_WEB:-0}" = "1" ]; then
  echo "    Building web dashboard (RELEASE_WITH_WEB=1)"
  ( cd web && npm ci --prefer-offline --no-audit && npm run build )
fi

echo "==> [3/4] Bundling install scripts"
mkdir -p hermes_cli/scripts
cp -f scripts/install.sh hermes_cli/scripts/install.sh 2>/dev/null || true
cp -f scripts/install.ps1 hermes_cli/scripts/install.ps1 2>/dev/null || true

echo "==> [4/4] Building wheel + sdist (dist/)"
rm -f dist/superforecasting_agent-*.whl dist/superforecasting_agent-*.tar.gz 2>/dev/null || true
if command -v uv >/dev/null 2>&1; then
  uv build --sdist --wheel
else
  python3 -m build
fi

echo
echo "==> Done. Built:"
ls -1 dist/*.whl dist/*.tar.gz 2>/dev/null | sed 's/^/    /'
echo
echo "    Install anywhere (pipx manages the venv for you):"
echo "        pipx install \"$ROOT\"/dist/superforecasting_agent-*.whl"
echo "        superforecasting-agent --tui"
echo
echo "    Upgrade later with:  pipx install --force <new.whl>"
