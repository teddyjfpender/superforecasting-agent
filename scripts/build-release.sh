#!/usr/bin/env bash
# Build independent backend/CLI and TUI wheels plus the backend source archive.
# SKIP_NPM=1 reuses an existing compiled Ink bundle. RELEASE_WITH_WEB=1 also
# creates a separate dashboard-assets.tar.gz; UI assets never enter the backend.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"

if [ "${SKIP_NPM:-0}" != "1" ] || [ ! -f ui-tui/dist/entry.js ]; then
  (cd ui-tui && npm ci --prefer-offline --no-audit && npm run build)
fi
mkdir -p dist
rm -f dist/superforecasting_agent-*.whl dist/superforecasting_agent-*.tar.gz \
  dist/superforecasting_agent_tui-*.whl dist/dashboard-assets.tar.gz
"$PY" scripts/build_profiles.py --out dist --skip-tui-build

if [ "${RELEASE_WITH_WEB:-0}" = "1" ]; then
  (cd web && npm ci --prefer-offline --no-audit && npm run build)
  test -f superforecasting_agent/runtime/web_dist/index.html
  tar -czf dist/dashboard-assets.tar.gz -C superforecasting_agent/runtime/web_dist .
fi
printf '\nBuilt independent products in %s/dist\n' "$ROOT"
printf 'Install the backend wheel, then the terminal wheel into the same environment for the desktop desk.\n'
printf 'The terminal wheel can also run separately against an authenticated remote host.\n'
