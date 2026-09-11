#!/usr/bin/env bash
# ============================================================================
# upgrade.sh — safe in-place upgrade of a provisioned Superforecasting box.
# ============================================================================
# The order is the safety story:
#   1. resolve the target release manifest (names + checksums + min-migration)
#   2. MIGRATION GUARD *before* switching anything — refuse a downgrade or a
#      build that can't forward-migrate this box's ledger (scripts/migration_guard.py)
#   3. pre-upgrade ledger backup (SQLite online-backup)
#   4. install the new artifact (checksum-verified wheel / pulled image)
#   5. restart the supervised gateway
#   6. re-stamp the version + run config doctor as the post-upgrade gate
#
# Idempotent and lane-aware (reads {home}/.install_method). Refuses loudly and
# changes NOTHING when the guard says stop.
#
# Config:
#   FORECAST_USER=forecast
#   FORECAST_HOME=/home/<user>/.superforecasting-agent
#   TAG=latest|vX.Y.Z            target release
#   MANIFEST=/path/release-manifest.json   local manifest (skips download)
#   INSTALL_TUI=0             upgrade backend only (default: 1)
#   FORECAST_TUI_WHEEL=/path.whl  optional local terminal companion
#   FORECAST_WHEEL=/path.whl     local wheel (pipx lane; skips download)
#   FORECAST_CHECKSUMS=/path/SHA256SUMS  verify a local FORECAST_WHEEL against this
#   ALLOW_UNVERIFIED=1           permit a release that ships no SHA256SUMS
#                                (pre-P0 only). NEVER bypasses a FAILED check.
#   REPO=teddyjfpender/superforecasting-agent
#   FORCE=1                      bypass the migration guard (DANGEROUS; audited)
# ============================================================================
set -euo pipefail

FORECAST_USER="${FORECAST_USER:-forecast}"
FORECAST_HOME="${FORECAST_HOME:-/home/${FORECAST_USER}/.superforecasting-agent}"
TAG="${TAG:-latest}"
ALLOW_UNVERIFIED="${SUPERFORECASTING_AGENT_ALLOW_UNVERIFIED:-${ALLOW_UNVERIFIED:-0}}"
REPO="${REPO:-teddyjfpender/superforecasting-agent}"
SERVICE="superforecasting-agent-gateway"
COMPOSE_DIR="/opt/superforecasting"
INSTALL_TUI="${INSTALL_TUI:-1}"
case "$INSTALL_TUI" in 0|1) ;; *) echo "INSTALL_TUI must be 0 or 1" >&2; exit 1;; esac
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m  %s\n' "$*"; }
warn() { printf '\033[33m⚠\033[0m  %s\n' "$*"; }
die()  { printf '\033[31m✗\033[0m  %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "run as root. Try: sudo bash $0"
USER_HOME="$(getent passwd "$FORECAST_USER" | cut -d: -f6)"
LANE="$(cat "$FORECAST_HOME/.install_method" 2>/dev/null || echo pipx)"
[ "$LANE" = "git" ] && LANE="pipx"   # git checkout ~ native for our purposes
CURRENT="$(cat "$FORECAST_HOME/.release_version" 2>/dev/null || echo unknown)"

printf '\n\033[1m✦ Superforecasting Agent — upgrade (lane: %s, current: %s)\033[0m\n\n' "$LANE" "$CURRENT"

sha256_of() {  # <file> -> hex digest on stdout
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}

# verify_checksum <file> <SHA256SUMS> -> 0 iff the recorded sha256 matches.
# Kept in LOCKSTEP with scripts/install-release.sh + scripts/hetzner-install.sh
# (the three installers stay self-contained — each can be fetched and run
# alone — so the helper is duplicated deliberately, not factored into a shared
# file). A sums file with NO entry for the file is a FAILURE: never trust a
# sums file that does not mention the artifact it ships beside.
verify_checksum() {
  local file="$1" sums="$2" name want got
  name="$(basename "$file")"
  want="$(awk -v name="$name" '$2 == name {digest=$1; count++} END {if (count == 1) print digest}' "$sums")"
  [ -n "$want" ] || { warn "SHA256SUMS has no entry for $name"; return 1; }
  got="$(sha256_of "$file")"
  if [ "$want" != "$got" ]; then
    warn "expected sha256: $want"
    warn "computed sha256: $got"
    return 1
  fi
}

# ── 1. resolve manifest (local or from the GitHub release) ─────────────────
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
WHEEL=""
TUI_WHEEL=""
if [ -n "${MANIFEST:-}" ]; then
  cp "$MANIFEST" "$TMP/release-manifest.json"
  say "Using local manifest: $MANIFEST"
else
  if [ "$TAG" = "latest" ]; then api="https://api.github.com/repos/$REPO/releases/latest"
  else api="https://api.github.com/repos/$REPO/releases/tags/$TAG"; fi
  say "Resolving release ($TAG) from $REPO"
  meta="$(curl -fsSL "$api" 2>/dev/null || true)"
  man_url="$(printf '%s' "$meta" | grep -o 'https://[^"]*release-manifest\.json' | head -n1 || true)"
  [ -n "$man_url" ] || die "release $TAG has no release-manifest.json (pre-P0 release?)"
  curl -fsSL -o "$TMP/release-manifest.json" "$man_url" || die "manifest download failed"
fi
MANIFEST_FILE="$TMP/release-manifest.json"
NEW_VERSION="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$MANIFEST_FILE")"
MIN_MIG="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["min_migration_version"])' "$MANIFEST_FILE")"
ok "target v$NEW_VERSION (min_migration v$MIN_MIG)"

# ── 2. MIGRATION GUARD — before we touch anything ──────────────────────────
say "Migration guard: current v$CURRENT -> v$NEW_VERSION (min v$MIN_MIG)"
set +e
python3 "$SCRIPT_DIR/migration_guard.py" --current "$CURRENT" --manifest "$MANIFEST_FILE"
GUARD_RC=$?
set -e
if [ "$GUARD_RC" -eq 3 ]; then
  if [ "${FORCE:-0}" = "1" ]; then
    warn "migration guard REFUSED but FORCE=1 — proceeding (audited; you own the risk)"
  else
    die "migration guard refused this upgrade — nothing changed. (FORCE=1 to override.)"
  fi
elif [ "$GUARD_RC" -ne 0 ]; then
  die "migration guard error (rc=$GUARD_RC) — nothing changed."
fi

# ── 3. pre-upgrade backup ──────────────────────────────────────────────────
say "Pre-upgrade ledger backup"
if [ "$LANE" = "docker" ]; then
  docker exec "$SERVICE" superforecasting-agent forecast backup run >/dev/null 2>&1 \
    && ok "backup taken" || warn "backup run returned non-zero (continuing)"
else
  sudo -u "$FORECAST_USER" env HOME="$USER_HOME" SUPERFORECASTING_AGENT_HOME="$FORECAST_HOME" \
    /usr/local/bin/superforecasting-agent forecast backup run >/dev/null 2>&1 \
    && ok "backup taken" || warn "backup run returned non-zero (continuing)"
fi

# ── 4. install the new artifact ────────────────────────────────────────────
if [ "$LANE" = "docker" ]; then
  IMAGE="$(python3 -c "import json;m=json.load(open('$MANIFEST_FILE'))['image'];print(m['registry']+'/'+m['repository']+':'+m['tags'][0])")"
  say "Pulling $IMAGE"
  docker pull "$IMAGE" || die "image pull failed"
  # Repoint compose at the new tag.
  if [ -f "$COMPOSE_DIR/compose.yml" ]; then
    sed -i.bak -E "s|^( *image: ).*|\\1${IMAGE}|" "$COMPOSE_DIR/compose.yml"
  fi
else
  # TRUST RULE (lockstep with install-release.sh + hetzner-install.sh; do not
  # "helpfully" tighten the local path): an artifact this script DOWNLOADS must
  # be checksum-verified, fatally — missing SHA256SUMS, a failed SHA256SUMS
  # download, a sums file with no entry for the wheel, and a mismatch all
  # refuse the upgrade with nothing changed. A LOCAL wheel the operator passed
  # in (FORECAST_WHEEL=) is the operator's own trust decision — it installs
  # unverified unless FORECAST_CHECKSUMS= is also given, in which case
  # verification is mandatory and a failure is fatal.
  if [ -n "${FORECAST_WHEEL:-}" ]; then
    WHEEL="$FORECAST_WHEEL"
    [ -f "$WHEEL" ] || die "FORECAST_WHEEL not found: $WHEEL"
    if [ -n "${FORECAST_CHECKSUMS:-}" ]; then
      [ -f "$FORECAST_CHECKSUMS" ] || die "FORECAST_CHECKSUMS not found: $FORECAST_CHECKSUMS"
      verify_checksum "$WHEEL" "$FORECAST_CHECKSUMS" \
        || die "local wheel failed verification against $(basename "$FORECAST_CHECKSUMS") — nothing changed."
      ok "wheel checksum verified against $(basename "$FORECAST_CHECKSUMS")"
    fi
  else
    # Reuse the standalone installer's artifact selection and integrity owner.
    # The already admitted manifest freezes the release even if latest changes.
    [ -f "$SCRIPT_DIR/install-release.sh" ] || die "install-release.sh is required beside upgrade.sh."
    MANIFEST="$MANIFEST_FILE" RELEASE_DOWNLOAD_DIR="$TMP/verified" REPO="$REPO" \
      TAG="$TAG" INSTALL_TUI="${INSTALL_TUI:-1}" ALLOW_UNVERIFIED="$ALLOW_UNVERIFIED" \
      bash "$SCRIPT_DIR/install-release.sh" || die "Release artifact verification failed; nothing installed."
    WHEEL="$TMP/verified/$(sed -n 1p "$TMP/verified/wheels.txt")"
    terminal_name="$(sed -n 2p "$TMP/verified/wheels.txt")"
    if [ -n "$terminal_name" ]; then TUI_WHEEL="$TMP/verified/$terminal_name"; fi
  fi
  if [ -n "${FORECAST_TUI_WHEEL:-}" ]; then
    [ -n "${FORECAST_WHEEL:-}" ] || die "FORECAST_TUI_WHEEL requires a local FORECAST_WHEEL."
    [ "${INSTALL_TUI:-1}" = 1 ] || die "FORECAST_TUI_WHEEL conflicts with INSTALL_TUI=0."
    TUI_WHEEL="$FORECAST_TUI_WHEEL"
    [ -f "$TUI_WHEEL" ] || die "FORECAST_TUI_WHEEL not found: $TUI_WHEEL"
    if [ -n "${FORECAST_CHECKSUMS:-}" ]; then
      verify_checksum "$TUI_WHEEL" "$FORECAST_CHECKSUMS" || die "Local terminal wheel failed verification."
    fi
  fi
  # mktemp creates a root-only directory; pipx runs as the forecast user.
  # Only this invocation's private staging tree changes ownership.
  chown -R "$FORECAST_USER:$FORECAST_USER" "$TMP" || die "Could not hand off verified artifacts to $FORECAST_USER."
  say "Installing wheel via pipx --force"
  sudo -u "$FORECAST_USER" env HOME="$USER_HOME" PIPX_HOME="$USER_HOME/.local/pipx" \
    PIPX_BIN_DIR="$USER_HOME/.local/bin" pipx install --force "$WHEEL" >/dev/null \
    || die "pipx install failed"
  if [ -n "$TUI_WHEEL" ]; then
    sudo -u "$FORECAST_USER" env HOME="$USER_HOME" PIPX_HOME="$USER_HOME/.local/pipx" \
      PIPX_BIN_DIR="$USER_HOME/.local/bin" pipx inject --force superforecasting-agent "$TUI_WHEEL" >/dev/null \
      || die "pipx terminal companion installation failed"
  fi
fi

# ── 5. restart the supervised gateway ──────────────────────────────────────
say "Restarting the gateway"
if [ "$LANE" = "docker" ]; then
  ( cd "$COMPOSE_DIR" && docker compose up -d ) || die "compose up failed"
elif [ -d /run/systemd/system ]; then
  systemctl restart "$SERVICE" || warn "systemctl restart returned non-zero"
else
  warn "no systemd — restart the gateway process manually (test box)"
fi

# ── 6. re-stamp + post-upgrade doctor ──────────────────────────────────────
printf '%s\n' "$NEW_VERSION" > "$FORECAST_HOME/.release_version"
chown "$FORECAST_USER:$FORECAST_USER" "$FORECAST_HOME/.release_version"
ok "stamped v$NEW_VERSION"
sleep 2
say "Post-upgrade config doctor"
if [ "$LANE" = "docker" ]; then
  docker exec "$SERVICE" superforecasting-agent forecast config doctor 2>/dev/null | head -6 || true
else
  sudo -u "$FORECAST_USER" env HOME="$USER_HOME" SUPERFORECASTING_AGENT_HOME="$FORECAST_HOME" \
    /usr/local/bin/superforecasting-agent forecast config doctor 2>/dev/null | head -6 || true
fi

printf '\n\033[1;32m✦ Upgraded %s -> %s.\033[0m\n\n' "$CURRENT" "$NEW_VERSION"
