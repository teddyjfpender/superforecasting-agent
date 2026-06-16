#!/usr/bin/env bash
# ============================================================================
# Outrider / Superforecasting Agent — standalone one-command installer
# ============================================================================
# Installs the prebuilt RELEASE WHEEL with pipx. No git checkout, no Python
# venv to manage, no `npm run build` — the wheel bundles the prebuilt TUI and
# the launcher auto-provisions Node and runs the gateway from pipx's own venv.
#
# Quick start (always installs the newest release):
#
#     curl -fsSL https://github.com/teddyjfpender/superforecasting-agent/releases/latest/download/install.sh | bash
#
# Pin a specific release, or re-run to upgrade in place:
#
#     curl -fsSL https://github.com/teddyjfpender/superforecasting-agent/releases/download/v2026.6.16/install.sh | bash
#     TAG=v2026.6.16 bash install.sh
#
# Supported: macOS, Linux. Needs Python 3.10+ (the only prerequisite — pipx is
# installed automatically if missing).
# ============================================================================
set -euo pipefail

REPO="teddyjfpender/superforecasting-agent"
# Pin with TAG=v2026.6.16 (or SUPERFORECASTING_AGENT_RELEASE_TAG); default latest.
TAG="${SUPERFORECASTING_AGENT_RELEASE_TAG:-${TAG:-latest}}"
BIN="superforecasting-agent"

# A leaked PYTHONPATH/PYTHONHOME (e.g. when launched from another tool's venv)
# can make pip import the wrong packages and the install look broken.
unset PYTHONPATH PYTHONHOME 2>/dev/null || true

say()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m  %s\n' "$*"; }
warn() { printf '\033[33m⚠\033[0m  %s\n' "$*"; }
die()  { printf '\033[31m✗\033[0m  %s\n' "$*" >&2; exit 1; }

fetch() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$1"
  else
    die "Neither curl nor wget is available."
  fi
}

download() {
  # download <url> <dest>
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$2" "$1"
  else
    wget -qO "$2" "$1"
  fi
}

printf '\n\033[1m✦ Outrider — Superforecasting Agent\033[0m\n\n'

# 1. Locate a Python interpreter (the only hard prerequisite).
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -n "$PY" ] || die "Python 3.10+ is required but was not found. Install Python and re-run."

# 2. Resolve the wheel URL from the GitHub Releases API.
if [ "$TAG" = "latest" ]; then
  API="https://api.github.com/repos/$REPO/releases/latest"
else
  API="https://api.github.com/repos/$REPO/releases/tags/$TAG"
fi
say "Resolving release ($TAG)…"
WHEEL_URL="$(fetch "$API" | grep -o 'https://[^"]*\.whl' | head -n1 || true)"
[ -n "$WHEEL_URL" ] || die "Could not find a .whl asset on the '$TAG' release of $REPO."
WHEEL_NAME="${WHEEL_URL##*/}"
ok "Found $WHEEL_NAME"

# 3. Download the wheel to a temp file (more reliable than installing from a
#    URL: pipx reads the package name straight from the local wheel).
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
WHEEL="$TMP/$WHEEL_NAME"
say "Downloading…"
download "$WHEEL_URL" "$WHEEL"

# 4. Ensure pipx (isolated venv + clean, repeatable upgrades).
ensure_pipx() {
  command -v pipx >/dev/null 2>&1 && return 0
  say "Installing pipx…"
  if command -v brew >/dev/null 2>&1; then brew install pipx >/dev/null 2>&1 || true; fi
  command -v pipx >/dev/null 2>&1 && return 0
  "$PY" -m pip install --user -q --upgrade pipx >/dev/null 2>&1 || return 1
  "$PY" -m pipx ensurepath >/dev/null 2>&1 || true
  command -v pipx >/dev/null 2>&1 || hash -r 2>/dev/null || true
  command -v pipx >/dev/null 2>&1
}

# 5. Install (--force so re-running upgrades even at the same version number).
if ensure_pipx; then
  say "Installing with pipx…"
  pipx install --force "$WHEEL"
  BIN_DIR="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || echo "$HOME/.local/bin")"
else
  warn "pipx unavailable — falling back to 'pip install --user'."
  "$PY" -m pip install --user --force-reinstall "$WHEEL"
  BIN_DIR="$("$PY" -c 'import site, os; print(os.path.join(site.getuserbase(), "bin"))')"
fi

# 6. Report and tell them how to launch (never auto-launch — stdin is the
#    piped script here, not a terminal, so the interactive TUI can't attach).
echo
if command -v "$BIN" >/dev/null 2>&1; then
  ok "Installed $("$BIN" --version 2>/dev/null || echo "$BIN")"
  printf '\n   Start the desk:  \033[1m%s --tui\033[0m\n\n' "$BIN"
else
  ok "Installed."
  echo
  warn "'$BIN' isn't on your PATH yet in this shell. Add the bin dir:"
  printf '     export PATH="%s:$PATH"\n' "$BIN_DIR"
  printf '   then open a new terminal and run:  \033[1m%s --tui\033[0m\n\n' "$BIN"
fi
