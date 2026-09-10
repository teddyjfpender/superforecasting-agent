#!/usr/bin/env bash
# ============================================================================
# hetzner-install.sh — one-command Hetzner bootstrap for the Superforecasting
# Agent. Create a box, curl this, done. Idempotent: re-running upgrades/repairs.
# ============================================================================
# The three-command quickstart (a lazy prompter never reads a runbook):
#
#   1.  hcloud server create --name desk --type cax21 --image ubuntu-24.04 ...
#   2.  ssh root@<ip> 'curl -fsSL <this-url> | SSH_PUBKEY="$(cat ~/.ssh/id_ed25519.pub)" bash'
#   3.  ssh forecast@<ip>            # lands straight in the TUI
#
# What it does, in order:
#   - creates the unprivileged `forecast` user + persistent {home}
#   - base hardening: UFW allow 22 only, unattended-upgrades
#   - picks an install lane (Docker Compose preferred; pipx native fallback)
#   - installs the artifact set (checksum-verified when a manifest is present)
#   - seeds secrets (AUTH_JSON_BOOTSTRAP + data keys into {home}/.env, 0600)
#   - supervises the gateway (systemd `gateway install --system`) so the
#     in-process nightly cron stays up across crashes + reboots
#   - arms a daily ledger-backup systemd timer
#   - wires the SSH->TUI landing (forecast-desk ForceCommand on your key)
#   - ACCEPTANCE: runs `forecast config doctor`, checks gateway health + the
#     SSH landing, and prints a red/green summary + the exact `ssh` line
#
# THE BLESSED LANE — Docker Compose (with pipx native as the auto-fallback):
#   SECURITY.md's boundary is "the only security boundary against an
#   adversarial LLM is the OS". An unattended, internet-connected agent that
#   spends money and holds OAuth tokens wants whole-process isolation; Docker
#   Compose gives that (restart: unless-stopped survives reboot). When Docker
#   is absent or the image can't be resolved, the bootstrap falls back to the
#   pipx native lane, which works end-to-end today and lands the SSH->TUI story
#   with zero registry dependency. The bootstrap says which lane it chose.
#
# Config (all optional; env or exported before the curl|bash):
#   FORECAST_USER=forecast              unix user to create/run as
#   FORECAST_HOME=/home/<user>/.superforecasting-agent   persistent volume
#   LANE=auto|docker|pipx               force a lane (default: auto)
#   TAG=latest|vX.Y.Z                   release to install (pipx lane)
#   FORECAST_WHEEL=/path/to.whl         install a LOCAL wheel (skips download)
#   FORECAST_CHECKSUMS=/path/SHA256SUMS verify FORECAST_WHEEL against this
#   ALLOW_UNVERIFIED=1                  permit installing from a release that
#                                       ships no SHA256SUMS (pre-P0 releases
#                                       only). NEVER bypasses a FAILED check.
#   FORECAST_IMAGE=ghcr.io/...:tag      image ref (docker lane); local ok
#   FORECAST_BUILD_IMAGE=1              build the image locally if pull fails
#   AUTH_JSON_BOOTSTRAP='{...}'         seed {home}/auth.json non-interactively
#   SSH_PUBKEY='ssh-ed25519 AAAA...'    key that lands in the TUI (ForceCommand)
#   SSH_ADMIN_PUBKEY='ssh-... '         key that gets a PLAIN shell (no landing)
#   SUPERVISOR=auto|systemd|none        override supervision (none = test-only)
#   SKIP_HARDENING=1                    skip UFW/unattended-upgrades (test-only)
#   REPO=teddyjfpender/superforecasting-agent
# ============================================================================
set -euo pipefail

# ── config ────────────────────────────────────────────────────────────────
FORECAST_USER="${FORECAST_USER:-forecast}"
FORECAST_HOME="${FORECAST_HOME:-/home/${FORECAST_USER}/.superforecasting-agent}"
LANE="${LANE:-auto}"
TAG="${TAG:-latest}"
ALLOW_UNVERIFIED="${SUPERFORECASTING_AGENT_ALLOW_UNVERIFIED:-${ALLOW_UNVERIFIED:-0}}"
REPO="${REPO:-teddyjfpender/superforecasting-agent}"
SUPERVISOR="${SUPERVISOR:-auto}"
FORECAST_IMAGE="${FORECAST_IMAGE:-ghcr.io/${REPO}:${TAG}}"
COMPOSE_DIR="/opt/superforecasting"
DESK_ENV="/etc/superforecasting/desk.env"
DESK_BIN="/usr/local/bin/forecast-desk"
SERVICE="superforecasting-agent-gateway"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo /tmp)"
INSTALLED_VERSION=""   # set by the lane installer; feeds the upgrade-guard stamp

say()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m  %s\n' "$*"; }
warn() { printf '\033[33m⚠\033[0m  %s\n' "$*"; }
die()  { printf '\033[31m✗\033[0m  %s\n' "$*" >&2; exit 1; }

# Accumulate acceptance results for the final red/green summary.
CHECK_FAILURES=()
record() {  # record <PASS|FAIL|WARN> <name>
  local status="$1"; shift
  case "$status" in
    PASS) ok   "$*" ;;
    WARN) warn "$*" ;;
    FAIL) printf '\033[31m✗\033[0m  %s\n' "$*"; CHECK_FAILURES+=("$*") ;;
  esac
}

[ "$(id -u)" = "0" ] || die "run as root (creates users, writes systemd units). Try: sudo bash $0"

printf '\n\033[1m✦ Superforecasting Agent — Hetzner bootstrap\033[0m\n\n'

# ── OS detection ──────────────────────────────────────────────────────────
APT=0; command -v apt-get >/dev/null 2>&1 && APT=1
IN_SYSTEMD=0; [ -d /run/systemd/system ] && IN_SYSTEMD=1
if [ "$SUPERVISOR" = "auto" ]; then
  [ "$IN_SYSTEMD" = "1" ] && SUPERVISOR="systemd" || SUPERVISOR="none"
fi

# ── 1. forecast user + persistent {home} ──────────────────────────────────
say "Ensuring unix user '$FORECAST_USER' + persistent home"
if ! id "$FORECAST_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$FORECAST_USER"
  ok "created user $FORECAST_USER"
else
  ok "user $FORECAST_USER already exists (idempotent)"
fi
USER_HOME="$(getent passwd "$FORECAST_USER" | cut -d: -f6)"
install -d -m 0700 -o "$FORECAST_USER" -g "$FORECAST_USER" "$FORECAST_HOME"
# Volume layout: the ledger + secrets + runtime state all live under {home}.
for sub in forecasting logs cron sessions workspace home backups; do
  install -d -m 0700 -o "$FORECAST_USER" -g "$FORECAST_USER" "$FORECAST_HOME/$sub"
done
ok "volume layout under $FORECAST_HOME"

# ── 2. base hardening ─────────────────────────────────────────────────────
if [ "${SKIP_HARDENING:-0}" = "1" ]; then
  warn "SKIP_HARDENING=1 — not touching firewall/unattended-upgrades (test box)"
else
  say "Base hardening (SSH-only firewall, unattended security upgrades)"
  if command -v ufw >/dev/null 2>&1; then
    ufw allow 22/tcp >/dev/null 2>&1 || true
    ufw --force enable >/dev/null 2>&1 || true
    ok "UFW: allow 22/tcp only (zero other inbound ports)"
  else
    warn "ufw not installed — install it + 'ufw allow 22' for the zero-inbound posture"
  fi
  if [ "$APT" = "1" ]; then
    DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1 || true
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq unattended-upgrades >/dev/null 2>&1 \
      && ok "unattended-upgrades installed" \
      || warn "could not install unattended-upgrades"
  fi
fi

# ── 3. lane pick ──────────────────────────────────────────────────────────
docker_usable() { command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }
if [ "$LANE" = "auto" ]; then
  if docker_usable; then LANE="docker"; else LANE="pipx"; fi
fi
say "Install lane: $LANE"

# ── shared: secret seeding into {home} ────────────────────────────────────
seed_secrets() {
  if [ ! -f "$FORECAST_HOME/.env" ]; then
    install -m 0600 -o "$FORECAST_USER" -g "$FORECAST_USER" /dev/null "$FORECAST_HOME/.env"
    ok "created {home}/.env (0600)"
  fi
  if [ -n "${AUTH_JSON_BOOTSTRAP:-}" ] && [ ! -f "$FORECAST_HOME/auth.json" ]; then
    printf '%s' "$AUTH_JSON_BOOTSTRAP" > "$FORECAST_HOME/auth.json"
    chown "$FORECAST_USER:$FORECAST_USER" "$FORECAST_HOME/auth.json"
    chmod 600 "$FORECAST_HOME/auth.json"
    ok "seeded {home}/auth.json from AUTH_JSON_BOOTSTRAP (0600)"
  fi
}

# ── gateway HTTP bearer token — minted 0600; local clients auto-read it ─────
# The B4 HTTP+SSE serve mode gates EVERY route (incl /status, /health) on this
# token. We pre-mint it so the /status observability runbook works immediately
# and the server reuses it (idempotent). The SSH->TUI landing is unaffected: it
# spawns the gateway over stdio, never HTTP — this token gates the HTTP surface.
mint_gateway_token() {
  local tok="$FORECAST_HOME/gateway.token"
  if [ -s "$tok" ]; then
    ok "gateway.token already present (idempotent)"
    return
  fi
  local val
  if command -v openssl >/dev/null 2>&1; then
    val="$(openssl rand -base64 33 | tr '+/' '-_' | tr -d '=\n')"
  else
    val="$(head -c 33 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n')"
  fi
  printf '%s\n' "$val" > "$tok"
  chown "$FORECAST_USER:$FORECAST_USER" "$tok"
  chmod 600 "$tok"
  ok "minted {home}/gateway.token (0600) for the HTTP serve mode"
}

# ── spend-guard guidance (commented; the operator arms it) ─────────────────
# P3.2: an unattended box can spend across cycles even when every policy cell is
# `auto`. We seed COMMENTED box-level ceilings so a lazy operator only has to
# uncomment + set a number — zero behaviour change until they do.
seed_spend_guidance() {
  local envf="$FORECAST_HOME/.env"
  # Propagate any budget/policy ceilings set in the bootstrap env into {home}/.env
  # (uncommented — the operator meant these). Idempotent: never duplicate a key.
  local v val
  for v in FORECAST_BUDGET_DAILY_TOKENS FORECAST_BUDGET_DAILY_USD \
           FORECAST_BUDGET_MONTHLY_TOKENS FORECAST_BUDGET_MONTHLY_USD \
           FORECAST_POLICY_CRON_LLM_SPEND; do
    val="${!v:-}"
    [ -n "$val" ] || continue
    grep -q "^${v}=" "$envf" 2>/dev/null && continue
    printf '%s=%s\n' "$v" "$val" >> "$envf"
    ok "armed ${v} from bootstrap env"
  done
  chown "$FORECAST_USER:$FORECAST_USER" "$envf" 2>/dev/null || true
  # Seed the commented guidance block once (skip if any budget line now exists).
  grep -q "FORECAST_BUDGET_" "$envf" 2>/dev/null && return
  cat >> "$envf" <<'ENVG'

# ── Unattended spend guards (P3.2) — uncomment + set to cap an unwatched box ──
# Box-level LLM ceilings. 0 / unset = UNLIMITED. A breach REFUSES paid jobs,
# raises a severity=high ledger alert, and notifies your connected surfaces.
# Reset is implicit on the UTC day / month rollover (no cron).
# FORECAST_BUDGET_DAILY_TOKENS=2000000
# FORECAST_BUDGET_DAILY_USD=10
# FORECAST_BUDGET_MONTHLY_TOKENS=40000000
# FORECAST_BUDGET_MONTHLY_USD=150
# Require explicit sign-off before any UNATTENDED (cron) LLM spend:
# FORECAST_POLICY_CRON_LLM_SPEND=ask
ENVG
  chown "$FORECAST_USER:$FORECAST_USER" "$envf"
  ok "seeded spend-guard guidance into {home}/.env (commented; edit to arm)"
}

# ── 4a. pipx native lane ──────────────────────────────────────────────────
install_pipx_lane() {
  if [ "$APT" = "1" ]; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      python3 python3-venv python3-pip pipx tmux curl ca-certificates git ripgrep \
      >/dev/null 2>&1 || warn "some apt packages failed to install"
  fi
  command -v pipx >/dev/null 2>&1 || die "pipx unavailable and could not be installed"

  local wheel="" tmp=""
  # TRUST RULE (do not "helpfully" tighten this — scripts/test-fresh-box.sh
  # depends on it): an artifact this script DOWNLOADS must be checksum-verified,
  # fatally (see resolve_and_verify_wheel). A LOCAL wheel the operator passed in
  # (FORECAST_WHEEL=) is the operator's own trust decision — it installs
  # unverified unless FORECAST_CHECKSUMS= is also given, in which case
  # verification is mandatory and a failure is fatal. test-fresh-box.sh builds
  # its wheel locally in STAGE 0 and feeds it here in STAGE 2.
  if [ -n "${FORECAST_WHEEL:-}" ]; then
    wheel="$FORECAST_WHEEL"
    [ -f "$wheel" ] || die "FORECAST_WHEEL not found: $wheel"
    if [ -n "${FORECAST_CHECKSUMS:-}" ]; then
      [ -f "$FORECAST_CHECKSUMS" ] || die "FORECAST_CHECKSUMS not found: $FORECAST_CHECKSUMS"
      verify_checksum "$wheel" "$FORECAST_CHECKSUMS" \
        || die "local wheel failed verification against $(basename "$FORECAST_CHECKSUMS") — aborting, nothing installed."
      ok "wheel checksum verified against $(basename "$FORECAST_CHECKSUMS")"
    fi
  else
    tmp="$(mktemp -d)"
    resolve_and_verify_wheel "$tmp" || die "could not resolve/verify a release wheel"
    wheel="$(ls -1 "$tmp"/*.whl | head -n1)"
  fi
  # The wheel filename carries the version (superforecasting_agent-X.Y.Z-...whl):
  # the most reliable source for the upgrade-guard stamp.
  INSTALLED_VERSION="$(basename "$wheel" | sed -n 's/^superforecasting_agent-\([0-9]\+\.[0-9]\+\.[0-9]\+\)-.*/\1/p')"
  say "Installing wheel as $FORECAST_USER via pipx"
  # pipx into the forecast user's home so the launcher/venv are user-owned.
  sudo -u "$FORECAST_USER" env HOME="$USER_HOME" PIPX_HOME="$USER_HOME/.local/pipx" \
    PIPX_BIN_DIR="$USER_HOME/.local/bin" pipx install --force "$wheel" >/dev/null
  [ -n "$tmp" ] && rm -rf "$tmp"
  # Symlink the launcher onto a system PATH dir so ForceCommand/systemd find it.
  local launcher="$USER_HOME/.local/bin/superforecasting-agent"
  [ -x "$launcher" ] || die "launcher not found at $launcher after pipx install"
  ln -sf "$launcher" /usr/local/bin/superforecasting-agent
  ln -sf "$USER_HOME/.local/bin/forecast" /usr/local/bin/forecast 2>/dev/null || true
  ok "installed: $(sudo -u "$FORECAST_USER" "$launcher" --version 2>/dev/null | head -n1 || echo superforecasting-agent)"

  echo "pipx" > "$FORECAST_HOME/.install_method"
  chown "$FORECAST_USER:$FORECAST_USER" "$FORECAST_HOME/.install_method"
}

# Resolve wheel + SHA256SUMS from the GitHub release, verify, into $1.
# TRUST RULE: everything this function DOWNLOADS must verify. A release with no
# SHA256SUMS, a failed SHA256SUMS download, a sums file with no entry for the
# wheel, or a mismatch are all FATAL — nothing is installed. The only opt-out
# is an explicit ALLOW_UNVERIFIED=1, and it only covers a release that
# genuinely ships no SHA256SUMS (pre-P0), never a FAILED check.
resolve_and_verify_wheel() {
  local dest="$1" api
  if [ "$TAG" = "latest" ]; then
    api="https://api.github.com/repos/$REPO/releases/latest"
  else
    api="https://api.github.com/repos/$REPO/releases/tags/$TAG"
  fi
  say "Resolving release ($TAG) from $REPO"
  local meta; meta="$(curl -fsSL "$api" 2>/dev/null || true)"
  local wheel_url sums_url
  wheel_url="$(printf '%s' "$meta" | grep -o 'https://[^"]*\.whl' | head -n1 || true)"
  sums_url="$(printf '%s' "$meta" | grep -o 'https://[^"]*SHA256SUMS' | head -n1 || true)"
  [ -n "$wheel_url" ] || return 1
  curl -fsSL -o "$dest/$(basename "$wheel_url")" "$wheel_url" \
    || die "wheel download failed (network error?) — aborting, nothing installed."
  if [ -z "$sums_url" ]; then
    if [ "$ALLOW_UNVERIFIED" = "1" ]; then
      warn "release $TAG ships no SHA256SUMS (pre-P0 release?) — ALLOW_UNVERIFIED=1 set, proceeding WITHOUT integrity verification. You own the risk."
    else
      die "release $TAG ships no SHA256SUMS (pre-P0 release?) — cannot verify the downloaded wheel. Pin a v0.18.0+ release, or re-run with ALLOW_UNVERIFIED=1 to accept an unverified install."
    fi
  else
    curl -fsSL -o "$dest/SHA256SUMS" "$sums_url" \
      || die "SHA256SUMS download failed (network error?) — refusing to install an unverified wheel."
    verify_checksum "$dest/$(basename "$wheel_url")" "$dest/SHA256SUMS" \
      || die "wheel sha256 MISMATCH against the release's SHA256SUMS — the download is corrupt or tampered with. Aborting: NOTHING was installed."
    ok "wheel sha256 verified (SHA256SUMS)"
  fi
  return 0
}

sha256_of() {  # <file> -> hex digest on stdout
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}

# verify_checksum <file> <SHA256SUMS> -> 0 iff the recorded sha256 matches.
# Kept in LOCKSTEP with scripts/install-release.sh + scripts/upgrade.sh (the
# three installers stay self-contained — each can be fetched and run alone —
# so the helper is duplicated deliberately, not factored into a shared file).
# A sums file with NO entry for the file is a FAILURE: never trust a sums file
# that does not mention the artifact it ships beside.
verify_checksum() {
  local file="$1" sums="$2" name want got
  name="$(basename "$file")"
  want="$(grep -E "  ${name}\$| ${name}\$" "$sums" 2>/dev/null | awk '{print $1}' | head -n1)"
  [ -n "$want" ] || { warn "SHA256SUMS has no entry for $name"; return 1; }
  got="$(sha256_of "$file")"
  if [ "$want" != "$got" ]; then
    warn "expected sha256: $want"
    warn "computed sha256: $got"
    return 1
  fi
}

# ── 4b. docker compose lane ───────────────────────────────────────────────
install_docker_lane() {
  docker_usable || die "docker lane chosen but docker is not usable"
  command -v tmux >/dev/null 2>&1 || { [ "$APT" = "1" ] && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq tmux >/dev/null 2>&1 || true; }

  # Resolve the image: pull, or build locally if asked / if the pull fails.
  if docker image inspect "$FORECAST_IMAGE" >/dev/null 2>&1; then
    ok "image present locally: $FORECAST_IMAGE"
  elif docker pull "$FORECAST_IMAGE" >/dev/null 2>&1; then
    ok "pulled image: $FORECAST_IMAGE"
  elif [ "${FORECAST_BUILD_IMAGE:-0}" = "1" ] && [ -f "$SCRIPT_DIR/../Dockerfile" ]; then
    say "Pull failed — building image locally (FORECAST_BUILD_IMAGE=1)"
    docker build -t "$FORECAST_IMAGE" "$SCRIPT_DIR/.." || die "local image build failed"
  else
    die "could not pull $FORECAST_IMAGE (not yet published?). Set FORECAST_BUILD_IMAGE=1 to build locally, or LANE=pipx."
  fi

  install -d -m 0755 "$COMPOSE_DIR"
  local uid gid; uid="$(id -u "$FORECAST_USER")"; gid="$(id -g "$FORECAST_USER")"
  cat > "$COMPOSE_DIR/compose.yml" <<YAML
# Generated by hetzner-install.sh — Superforecasting Agent (Docker lane).
services:
  gateway:
    image: ${FORECAST_IMAGE}
    container_name: ${SERVICE}
    restart: unless-stopped
    network_mode: host
    volumes:
      - ${FORECAST_HOME}:/opt/data
    environment:
      - SUPERFORECASTING_AGENT_HOME=/opt/data
      - SUPERFORECASTING_AGENT_UID=${uid}
      - SUPERFORECASTING_AGENT_GID=${gid}
    command: ["gateway", "run"]
YAML
  ok "wrote $COMPOSE_DIR/compose.yml"
  # Prefer a vX.Y.Z tag for the version stamp; else query the image metadata.
  INSTALLED_VERSION="$(printf '%s' "$FORECAST_IMAGE" | sed -n 's/.*:v\{0,1\}\([0-9]\+\.[0-9]\+\.[0-9]\+\)$/\1/p')"
  echo "docker" > "$FORECAST_HOME/.install_method"
  chown "$FORECAST_USER:$FORECAST_USER" "$FORECAST_HOME/.install_method"
}

# ── 5. supervision ────────────────────────────────────────────────────────
supervise_pipx() {
  case "$SUPERVISOR" in
    systemd)
      say "Installing systemd unit (gateway install --system --run-as-user $FORECAST_USER)"
      /usr/local/bin/superforecasting-agent gateway install --system \
        --run-as-user "$FORECAST_USER" >/dev/null 2>&1 \
        || warn "gateway install --system returned non-zero (see 'systemctl status $SERVICE')"
      systemctl enable --now "$SERVICE" >/dev/null 2>&1 || true
      ;;
    none)
      warn "no systemd (container/test) — supervising the gateway with setsid/nohup (TEST-ONLY)"
      start_gateway_fallback
      ;;
  esac
}
supervise_docker() {
  case "$SUPERVISOR" in
    systemd|none)
      say "Starting gateway container (restart: unless-stopped)"
      ( cd "$COMPOSE_DIR" && docker compose up -d ) \
        || die "docker compose up failed"
      ;;
  esac
}
start_gateway_fallback() {
  # Test-only supervision when there's no systemd (e.g. inside a bare container).
  # The redirect runs INSIDE the sudo'd shell so the log is forecast-owned.
  local log="$FORECAST_HOME/logs/gateway.out"
  sudo -u "$FORECAST_USER" env HOME="$USER_HOME" SUPERFORECASTING_AGENT_HOME="$FORECAST_HOME" \
    bash -c "setsid /usr/local/bin/superforecasting-agent gateway run >'$log' 2>&1 </dev/null &"
  ok "gateway started (fallback); log: $log"
}

# ── 6. backup timer (systemd) ─────────────────────────────────────────────
install_backup_timer() {
  [ "$SUPERVISOR" = "systemd" ] || { warn "no systemd — skipping backup timer (in-process cron still runs the 07:30 backup)"; return; }
  local svc="/etc/systemd/system/superforecasting-agent-backup.service"
  local tmr="/etc/systemd/system/superforecasting-agent-backup.timer"
  local runner
  if [ "$LANE" = "docker" ]; then
    runner="/usr/bin/docker exec ${SERVICE} superforecasting-agent forecast backup run"
  else
    runner="/usr/local/bin/superforecasting-agent forecast backup run"
  fi
  cat > "$svc" <<UNIT
[Unit]
Description=Superforecasting Agent — daily ledger backup (SQLite online-backup + retention)
After=${SERVICE}.service

[Service]
Type=oneshot
User=${FORECAST_USER}
Environment=SUPERFORECASTING_AGENT_HOME=${FORECAST_HOME}
ExecStart=${runner}
UNIT
  cat > "$tmr" <<UNIT
[Unit]
Description=Run the Superforecasting Agent ledger backup daily

[Timer]
OnCalendar=*-*-* 07:30:00
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl enable --now superforecasting-agent-backup.timer >/dev/null 2>&1 || true
  ok "armed daily ledger-backup timer (07:30, Persistent=true)"
}

# ── 7. SSH -> TUI landing ─────────────────────────────────────────────────
install_ssh_landing() {
  say "Installing the SSH->TUI landing (forecast-desk)"
  if [ -f "$SCRIPT_DIR/forecast-desk" ]; then
    install -m 0755 "$SCRIPT_DIR/forecast-desk" "$DESK_BIN"
  else
    # curl|bash path: the script isn't on disk beside us — fetch it.
    curl -fsSL "https://raw.githubusercontent.com/$REPO/main/scripts/forecast-desk" -o "$DESK_BIN" \
      && chmod 0755 "$DESK_BIN" || die "could not install $DESK_BIN"
  fi
  install -d -m 0755 "$(dirname "$DESK_ENV")"
  if [ "$LANE" = "docker" ]; then
    cat > "$DESK_ENV" <<ENV
# forecast-desk launch command (Docker lane): attach the TUI inside the container.
DESK_CMD="docker exec -it ${SERVICE} superforecasting-agent --tui"
ENV
  else
    cat > "$DESK_ENV" <<ENV
# forecast-desk launch command (native lane): run the bundled TUI directly.
DESK_CMD="/usr/local/bin/superforecasting-agent --tui"
ENV
  fi
  ok "wrote $DESK_ENV"

  # Wire authorized_keys: the desk key gets ForceCommand; an admin key stays raw.
  local ssh_dir="$USER_HOME/.ssh" ak
  ak="$ssh_dir/authorized_keys"
  install -d -m 0700 -o "$FORECAST_USER" -g "$FORECAST_USER" "$ssh_dir"
  touch "$ak"; chown "$FORECAST_USER:$FORECAST_USER" "$ak"; chmod 0600 "$ak"
  if [ -n "${SSH_PUBKEY:-}" ]; then
    local opts='command="/usr/local/bin/forecast-desk",no-agent-forwarding,no-X11-forwarding,no-port-forwarding'
    # Idempotent: replace any prior forecast-desk line for this key.
    grep -vF "$SSH_PUBKEY" "$ak" 2>/dev/null > "$ak.tmp" || true
    printf '%s %s\n' "$opts" "$SSH_PUBKEY" >> "$ak.tmp"
    mv "$ak.tmp" "$ak"; chown "$FORECAST_USER:$FORECAST_USER" "$ak"; chmod 0600 "$ak"
    ok "wired SSH_PUBKEY -> forecast-desk ForceCommand"
  else
    warn "no SSH_PUBKEY given — set it so 'ssh $FORECAST_USER@<ip>' lands in the TUI"
  fi
  if [ -n "${SSH_ADMIN_PUBKEY:-}" ]; then
    grep -qF "$SSH_ADMIN_PUBKEY" "$ak" 2>/dev/null || printf '%s\n' "$SSH_ADMIN_PUBKEY" >> "$ak"
    ok "added SSH_ADMIN_PUBKEY (plain shell — escape hatch)"
  fi
}

# ── 8. acceptance checks ──────────────────────────────────────────────────
acceptance() {
  printf '\n\033[1mAcceptance checks\033[0m\n'

  # (a) binary reachable
  if [ "$LANE" = "docker" ]; then
    docker exec "$SERVICE" superforecasting-agent --version >/dev/null 2>&1 \
      && record PASS "agent binary reachable in container" \
      || record FAIL "agent binary NOT reachable in container"
  else
    /usr/local/bin/superforecasting-agent --version >/dev/null 2>&1 \
      && record PASS "agent binary reachable ($(/usr/local/bin/superforecasting-agent --version 2>/dev/null | head -n1))" \
      || record FAIL "agent binary NOT reachable"
  fi

  # (b) config doctor — always exits 0, so we PARSE it: typo'd/unknown product
  #     vars and precedence conflicts are hard fails; absent secrets are warns.
  local doctor_json; doctor_json="$(run_agent forecast config doctor --json 2>/dev/null || true)"
  if [ -n "$doctor_json" ]; then
    # NB: the program goes in `python3 -c` so the piped JSON reaches sys.stdin
    # (a `python3 - <<HEREDOC` would let the heredoc override the pipe).
    local verdict
    verdict="$(printf '%s' "$doctor_json" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("PARSE_FAIL"); sys.exit()
bad = []
if d.get("unknown_set"):
    bad.append("unknown/typo vars: " + ", ".join(r["name"] for r in d["unknown_set"]))
if d.get("precedence_conflicts"):
    bad.append("file-vs-env conflicts: " + ", ".join(r["name"] for r in d["precedence_conflicts"]))
absent = [s["name"] for s in d.get("secrets", []) if not s.get("present")]
if bad:
    print("FAIL: " + "; ".join(bad))
else:
    print("PASS: config coherent" + (f" (secrets absent: {len(absent)})" if absent else ""))
' 2>/dev/null || echo "PARSE_FAIL")"
    case "$verdict" in
      PASS*) record PASS "config doctor — ${verdict#PASS: }" ;;
      FAIL*) record FAIL "config doctor — ${verdict#FAIL: }" ;;
      *)     record WARN "config doctor — could not parse report JSON" ;;
    esac
  else
    record WARN "config doctor — produced no JSON (agent env issue?)"
  fi

  # (c) gateway health
  if [ "$LANE" = "docker" ]; then
    docker ps --filter "name=$SERVICE" --filter status=running -q | grep -q . \
      && record PASS "gateway container running" \
      || record FAIL "gateway container NOT running"
  elif [ "$SUPERVISOR" = "systemd" ]; then
    systemctl is-active --quiet "$SERVICE" \
      && record PASS "gateway systemd unit active (Restart=always)" \
      || record FAIL "gateway systemd unit NOT active"
  else
    pgrep -f "superforecasting-agent gateway run" >/dev/null 2>&1 \
      && record PASS "gateway process running (fallback supervision)" \
      || record FAIL "gateway process NOT running"
  fi

  # (c2) gateway HTTP bearer token minted 0600 (the HTTP-surface auth).
  if [ -s "$FORECAST_HOME/gateway.token" ]; then
    local mode; mode="$(stat -c '%a' "$FORECAST_HOME/gateway.token" 2>/dev/null || stat -f '%Lp' "$FORECAST_HOME/gateway.token" 2>/dev/null || echo '?')"
    if [ "$mode" = "600" ]; then
      record PASS "gateway.token minted (0600) — HTTP serve mode is auth-gated"
    else
      record WARN "gateway.token present but mode=$mode (want 600)"
    fi
  else
    record WARN "gateway.token not minted — HTTP serve mode will mint on first start"
  fi

  # (d) SSH landing self-test — forecast-desk resolves + tmux available.
  if [ -x "$DESK_BIN" ] && [ -r "$DESK_ENV" ]; then
    if command -v tmux >/dev/null 2>&1; then
      # Non-interactively verify tmux can create+kill a session as the user.
      if sudo -u "$FORECAST_USER" tmux -L acctest new-session -d -s selftest 'true' 2>/dev/null; then
        sudo -u "$FORECAST_USER" tmux -L acctest kill-server 2>/dev/null || true
        record PASS "SSH landing wired (forecast-desk + tmux session create/kill)"
      else
        record WARN "forecast-desk installed but tmux session self-test failed"
      fi
    else
      record FAIL "tmux not installed — SSH->TUI landing needs it"
    fi
  else
    record FAIL "forecast-desk landing not installed"
  fi
}

# run_agent <args...> — invoke the CLI on whichever lane is active.
run_agent() {
  if [ "$LANE" = "docker" ]; then
    docker exec -e SUPERFORECASTING_AGENT_HOME=/opt/data "$SERVICE" superforecasting-agent "$@"
  else
    sudo -u "$FORECAST_USER" env HOME="$USER_HOME" SUPERFORECASTING_AGENT_HOME="$FORECAST_HOME" \
      /usr/local/bin/superforecasting-agent "$@"
  fi
}

# ── 9. version stamp (for the upgrade guard) ──────────────────────────────
stamp_version() {
  local ver="${INSTALLED_VERSION:-}"
  # Fall back to the `--version` banner ("Superforecasting Agent v0.18.0 (...)").
  [ -n "$ver" ] || ver="$(run_agent --version 2>/dev/null | sed -n 's/.* v\([0-9]\+\.[0-9]\+\.[0-9]\+\).*/\1/p' | head -n1)"
  if [ -n "$ver" ]; then
    printf '%s\n' "$ver" > "$FORECAST_HOME/.release_version"
    chown "$FORECAST_USER:$FORECAST_USER" "$FORECAST_HOME/.release_version"
    ok "stamped installed version: $ver (for the upgrade guard)"
  else
    warn "could not determine installed version to stamp — upgrade guard will treat this box as 'unknown current'"
  fi
}

# ── run ───────────────────────────────────────────────────────────────────
seed_secrets
mint_gateway_token
seed_spend_guidance
case "$LANE" in
  pipx)   install_pipx_lane; supervise_pipx ;;
  docker) install_docker_lane; supervise_docker ;;
  *)      die "unknown LANE: $LANE (want docker|pipx|auto)" ;;
esac
install_backup_timer
install_ssh_landing
# Give a freshly-started gateway a moment before we probe it.
sleep 2
stamp_version
acceptance

# ── summary ────────────────────────────────────────────────────────────────
printf '\n'
IP="$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<ip>')"
if [ "${#CHECK_FAILURES[@]}" -eq 0 ]; then
  printf '\033[1;32m✦ GREEN — the desk is up.\033[0m\n\n'
  printf '   Land in the TUI:   \033[1mssh %s@%s\033[0m\n' "$FORECAST_USER" "$IP"
  printf '   Plain shell:       \033[1mssh %s@%s shell\033[0m\n' "$FORECAST_USER" "$IP"
  printf '   Second desk:       \033[1mssh -t %s@%s desk2\033[0m\n\n' "$FORECAST_USER" "$IP"
  exit 0
else
  printf '\033[1;31m✗ RED — %d check(s) failed:\033[0m\n' "${#CHECK_FAILURES[@]}"
  for f in "${CHECK_FAILURES[@]}"; do printf '   - %s\n' "$f"; done
  printf '\n   Fix the above and re-run this installer (idempotent).\n\n'
  exit 1
fi
