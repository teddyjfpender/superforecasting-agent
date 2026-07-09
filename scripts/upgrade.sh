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
#   FORECAST_WHEEL=/path.whl     local wheel (pipx lane; skips download)
#   REPO=teddyjfpender/superforecasting-agent
#   FORCE=1                      bypass the migration guard (DANGEROUS; audited)
# ============================================================================
set -euo pipefail

FORECAST_USER="${FORECAST_USER:-forecast}"
FORECAST_HOME="${FORECAST_HOME:-/home/${FORECAST_USER}/.superforecasting-agent}"
TAG="${TAG:-latest}"
REPO="${REPO:-teddyjfpender/superforecasting-agent}"
SERVICE="superforecasting-agent-gateway"
COMPOSE_DIR="/opt/superforecasting"
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

verify_checksum() {  # <file> <SHA256SUMS>
  local file="$1" sums="$2" name want got
  name="$(basename "$file")"
  want="$(grep -E "  ${name}\$| ${name}\$" "$sums" 2>/dev/null | awk '{print $1}' | head -n1)"
  [ -n "$want" ] || { warn "no checksum for $name"; return 0; }
  if command -v sha256sum >/dev/null 2>&1; then got="$(sha256sum "$file" | awk '{print $1}')"
  else got="$(shasum -a 256 "$file" | awk '{print $1}')"; fi
  [ "$want" = "$got" ]
}

# ── 1. resolve manifest (local or from the GitHub release) ─────────────────
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
WHEEL=""
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
NEW_VERSION="$(python3 -c "import json;print(json.load(open('$MANIFEST_FILE'))['version'])")"
MIN_MIG="$(python3 -c "import json;print(json.load(open('$MANIFEST_FILE'))['min_migration_version'])")"
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
  if [ -n "${FORECAST_WHEEL:-}" ]; then
    WHEEL="$FORECAST_WHEEL"
  else
    if [ "$TAG" = "latest" ]; then api="https://api.github.com/repos/$REPO/releases/latest"
    else api="https://api.github.com/repos/$REPO/releases/tags/$TAG"; fi
    meta="$(curl -fsSL "$api" 2>/dev/null || true)"
    wheel_url="$(printf '%s' "$meta" | grep -o 'https://[^"]*\.whl' | head -n1 || true)"
    sums_url="$(printf '%s' "$meta" | grep -o 'https://[^"]*SHA256SUMS' | head -n1 || true)"
    [ -n "$wheel_url" ] || die "no wheel on release $TAG"
    curl -fsSL -o "$TMP/$(basename "$wheel_url")" "$wheel_url" || die "wheel download failed"
    WHEEL="$TMP/$(basename "$wheel_url")"
    if [ -n "$sums_url" ]; then
      curl -fsSL -o "$TMP/SHA256SUMS" "$sums_url" && verify_checksum "$WHEEL" "$TMP/SHA256SUMS" \
        && ok "wheel checksum verified" || die "wheel checksum mismatch"
    fi
  fi
  say "Installing wheel via pipx --force"
  sudo -u "$FORECAST_USER" env HOME="$USER_HOME" PIPX_HOME="$USER_HOME/.local/pipx" \
    PIPX_BIN_DIR="$USER_HOME/.local/bin" pipx install --force "$WHEEL" >/dev/null \
    || die "pipx install failed"
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
