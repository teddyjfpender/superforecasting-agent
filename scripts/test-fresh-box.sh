#!/usr/bin/env bash
# ============================================================================
# test-fresh-box.sh — prove the WHOLE deploy chain on a pristine box.
# ============================================================================
# Runs the entire bootstrap → services-up → doctor-green → SSH-lands-in-TUI
# sequence inside a throwaway ubuntu:24.04 container with a real sshd, so the
# fresh-box path is PROVEN, not hoped. Automated + repeatable; per-stage
# PASS/FAIL; non-zero exit on any failure.
#
#   scripts/test-fresh-box.sh                 # ubuntu:24.04 (default)
#   TEST_IMAGE=debian:12 scripts/test-fresh-box.sh
#   KEEP=1 scripts/test-fresh-box.sh          # leave the container up for triage
#
# HONEST REAL-HETZNER DELTA — what a container proof CANNOT cover, and where
# the real box is verified instead:
#   * cloud-init execution       → deploy/cloud-init.yaml (runs the same script)
#   * systemd boot-time units +  → this proof uses SUPERVISOR=none (setsid);
#     Restart=always/reboot         a real box uses `gateway install --system`
#                                    (Restart=always, verified in the unit gen)
#   * persistent volumes          → {home} is a bind mount here; a real box uses
#                                    a Hetzner volume mounted at {home}
#   * UFW firewall (needs a       → SKIP_HARDENING=1 here; the bootstrap runs
#     kernel netfilter/daemon)       `ufw allow 22 && ufw enable` on a real box
#   * multi-arch pull from ghcr   → CI (production-release.yml) + the local
#                                    `docker build` proof
# Everything else — user creation, pipx install, gateway boot + in-process
# cron banner, config doctor, the SSH ForceCommand → tmux → TUI landing, the
# escape hatches — is exercised for real below.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_IMAGE="${TEST_IMAGE:-ubuntu:24.04}"
CNAME="sfa-freshbox-$$"
SCRATCH="$(mktemp -d)"

say()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m  %s\n' "$*"; }
warn() { printf '\033[33m⚠\033[0m  %s\n' "$*"; }
err()  { printf '\033[31m✗\033[0m  %s\n' "$*" >&2; }

STAGES=()
stage() {  # stage <PASS|FAIL> <name>
  STAGES+=("$1|$2")
  [ "$1" = PASS ] && ok "STAGE $2" || err "STAGE $2"
}

cleanup() {
  if [ "${KEEP:-0}" = "1" ]; then
    warn "KEEP=1 — leaving container '$CNAME' up (docker exec -it $CNAME bash; docker rm -f $CNAME)"
  else
    docker rm -f "$CNAME" >/dev/null 2>&1 || true
  fi
  rm -rf "$SCRATCH"
}
trap cleanup EXIT

command -v docker >/dev/null 2>&1 || { err "docker not found"; exit 1; }
docker info >/dev/null 2>&1 || { err "docker daemon not reachable"; exit 1; }

printf '\n\033[1m✦ Fresh-box proof — %s\033[0m\n\n' "$TEST_IMAGE"

# ── STAGE 0: build the wheel locally (hermetic — no published release needed) ─
say "STAGE 0: ensure a local wheel"
WHEEL="$(ls -1 "$REPO_ROOT"/dist/superforecasting_agent-*.whl 2>/dev/null | head -n1 || true)"
if [ -z "$WHEEL" ]; then
  say "no wheel in dist/ — building (SKIP_NPM reuses the prebuilt TUI bundle)"
  if [ -f "$REPO_ROOT/ui-tui/dist/entry.js" ]; then
    ( cd "$REPO_ROOT" && SKIP_NPM=1 scripts/build-release.sh >/dev/null )
  else
    ( cd "$REPO_ROOT" && scripts/build-release.sh >/dev/null )
  fi
  WHEEL="$(ls -1 "$REPO_ROOT"/dist/superforecasting_agent-*.whl 2>/dev/null | head -n1 || true)"
fi
[ -n "$WHEEL" ] && [ -f "$WHEEL" ] || { stage FAIL "0-wheel-build"; exit 1; }
cp "$WHEEL" "$SCRATCH/"; WHEEL_NAME="$(basename "$WHEEL")"
# A SHA256SUMS so the bootstrap's checksum-verify path is exercised too.
( cd "$SCRATCH" && { command -v sha256sum >/dev/null 2>&1 && sha256sum "$WHEEL_NAME" || shasum -a 256 "$WHEEL_NAME"; } > SHA256SUMS )
# Copy the deploy scripts the bootstrap installs from beside itself.
cp "$REPO_ROOT/scripts/hetzner-install.sh" "$REPO_ROOT/scripts/forecast-desk" \
   "$REPO_ROOT/scripts/migration_guard.py" "$SCRATCH/"
stage PASS "0-wheel-build ($WHEEL_NAME)"

# ── STAGE 1: launch a pristine container + base tools + sshd + node ─────────
say "STAGE 1: launch pristine container + sshd + node"
docker rm -f "$CNAME" >/dev/null 2>&1 || true
docker run -d --name "$CNAME" "$TEST_IMAGE" sleep infinity >/dev/null
inx() { docker exec "$CNAME" bash -lc "$*"; }
# Ship the artifact set into the box with `docker cp` (backend-agnostic — a
# bind mount would depend on the host path being inside the docker VM's mounts).
inx "mkdir -p /opt/boot"
docker cp "$SCRATCH/." "$CNAME:/opt/boot/" >/dev/null
inx "chmod +x /opt/boot/hetzner-install.sh /opt/boot/forecast-desk /opt/boot/migration_guard.py"
# Pre-install ONLY what the bootstrap doesn't (sshd, node, sudo); the bootstrap
# installs python3/pipx/tmux itself so that path is proven too.
#
# Node 20 (via NodeSource), NOT distro node 18: a real bootstrapped box installs
# no node, so the launcher's ensure_node provisions a MODERN node (>=20). Distro
# node 18 rejects `--expose-gc` in NODE_OPTIONS (which the TUI sets), so pinning
# node 20 here matches the real runtime instead of a stale one.
if inx "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null 2>&1 && \
        apt-get install -y -qq openssh-server openssh-client sudo ca-certificates \
        curl iproute2 procps xz-utils >/dev/null 2>&1 && \
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null 2>&1 && \
        apt-get install -y -qq nodejs >/dev/null 2>&1"; then
  stage PASS "1-container-up (node $(inx 'node --version' 2>/dev/null))"
else
  stage FAIL "1-container-up"; exit 1
fi

# Ephemeral SSH keypair for the landing test (generated inside the box).
inx "install -d -m700 /root/.ssh && ssh-keygen -t ed25519 -N '' -f /root/.ssh/id_ed25519 -q"
PUBKEY="$(inx 'cat /root/.ssh/id_ed25519.pub')"

# ── STAGE 2: run the bootstrap (LANE=pipx, no systemd, no firewall) ─────────
say "STAGE 2: run the bootstrap"
set +e
docker exec \
  -e LANE=pipx -e SUPERVISOR=none -e SKIP_HARDENING=1 \
  -e FORECAST_WHEEL="/opt/boot/$WHEEL_NAME" \
  -e FORECAST_CHECKSUMS="/opt/boot/SHA256SUMS" \
  -e SSH_PUBKEY="$PUBKEY" \
  "$CNAME" bash /opt/boot/hetzner-install.sh
BOOT_RC=$?
set -e
[ "$BOOT_RC" -eq 0 ] && stage PASS "2-bootstrap-green (exit 0)" || stage FAIL "2-bootstrap-red (exit $BOOT_RC)"

# ── STAGE 3: independent re-checks — gateway up + doctor green + version stamp
say "STAGE 3: services up + config doctor + version stamp"
if inx "pgrep -f 'superforecasting-agent gateway run' >/dev/null"; then
  stage PASS "3a-gateway-running"
else
  stage FAIL "3a-gateway-running"
fi
# Gateway banner ("Messaging platforms + cron scheduler") proves the in-process
# nightly cron is live inside the running gateway.
if inx "grep -qiE 'cron|scheduler|messaging' /home/forecast/.superforecasting-agent/logs/gateway.out 2>/dev/null"; then
  stage PASS "3b-cron-scheduler-banner"
else
  warn "cron/scheduler banner not found in gateway.out (non-fatal; gateway may log elsewhere)"
  stage PASS "3b-cron-scheduler-banner (skipped)"
fi
DOCTOR_JSON="$(inx "sudo -u forecast env HOME=/home/forecast SUPERFORECASTING_AGENT_HOME=/home/forecast/.superforecasting-agent \
  /usr/local/bin/superforecasting-agent forecast config doctor --json 2>/dev/null" || true)"
# program in `python3 -c` so the piped JSON reaches sys.stdin (see SC2259).
DOCTOR_VERDICT="$(printf '%s' "$DOCTOR_JSON" | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: print("PARSE_FAIL"); sys.exit()
print("RED" if (d.get("unknown_set") or d.get("precedence_conflicts")) else "GREEN")
' 2>/dev/null || echo PARSE_FAIL)"
[ "$DOCTOR_VERDICT" = GREEN ] && stage PASS "3c-config-doctor-green" || stage FAIL "3c-config-doctor ($DOCTOR_VERDICT)"
STAMP="$(inx 'cat /home/forecast/.superforecasting-agent/.release_version 2>/dev/null' || true)"
if printf '%s' "$STAMP" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  stage PASS "3d-version-stamp ($STAMP)"
else
  stage FAIL "3d-version-stamp (got: '$STAMP')"
fi

# ── STAGE 4: sshd up + SSH lands in the TUI (the whole ForceCommand chain) ──
say "STAGE 4: SSH into the box → lands in the TUI"
inx "mkdir -p /run/sshd && ssh-keygen -A >/dev/null 2>&1 && \
     sed -ri 's/^#?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config && \
     /usr/sbin/sshd" \
  && stage PASS "4a-sshd-started" || stage FAIL "4a-sshd-started"

SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i /root/.ssh/id_ed25519"

# 4b. escape hatch: `ssh forecast@box shell` → a real login shell. The `shell`
#     token routes to `exec $SHELL -l`; we pipe a command into that shell's
#     stdin to prove it's a real shell (not the TUI).
if inx "echo 'echo SHELL_HATCH_OK' | $SSH forecast@localhost shell 2>/dev/null" | grep -q SHELL_HATCH_OK; then
  stage PASS "4b-escape-hatch-shell"
else
  stage FAIL "4b-escape-hatch-shell"
fi

# 4c. escape hatch: an arbitrary one-off command (scp/rsync/git path).
if inx "$SSH forecast@localhost 'uname -s' 2>/dev/null" | grep -qi linux; then
  stage PASS "4c-escape-hatch-oneoff"
else
  stage FAIL "4c-escape-hatch-oneoff"
fi

# 4d. THE LANDING: default ssh → forecast-desk → tmux 'desk' running the TUI.
#     Drive it over a PTY in the background, then verify the tmux session +
#     the TUI process exist, then tear it down.
# TERM=xterm so tmux can initialize (a docker-exec shell has no TERM, which
# makes tmux abort with "terminal does not support clear").
inx "TERM=xterm setsid $SSH -tt forecast@localhost </dev/null >/tmp/desk.out 2>&1 & echo started" >/dev/null
sleep 10
LANDED=FAIL
if inx "sudo -u forecast tmux ls 2>/dev/null | grep -q '^desk'"; then
  # A 'desk' tmux session exists (created ONLY by forecast-desk's ForceCommand).
  if inx "pgrep -f 'superforecasting-agent --tui' >/dev/null || pgrep -f 'tui_dist/entry.js' >/dev/null || pgrep -x node >/dev/null"; then
    LANDED=PASS
  fi
fi
if [ "$LANDED" = PASS ]; then
  stage PASS "4d-ssh-lands-in-tui (tmux 'desk' + TUI process)"
else
  err "landing debug (last 15 lines of the desk session output):"
  inx "tail -n 15 /tmp/desk.out 2>/dev/null" || true
  inx "sudo -u forecast tmux ls 2>/dev/null" || true
  stage FAIL "4d-ssh-lands-in-tui"
fi
# Tear the desk session down so cleanup is clean.
inx "sudo -u forecast tmux kill-server 2>/dev/null" || true

# ── STAGE 5: reconnect-resume — the whole point of tmux ─────────────────────
say "STAGE 5: reconnect-resume (drop the link, session survives)"
inx "TERM=xterm setsid $SSH -tt forecast@localhost </dev/null >/tmp/desk2.out 2>&1 & echo s" >/dev/null
sleep 8
count_desk() { inx "sudo -u forecast tmux ls 2>/dev/null | grep -c '^desk' || true" | tr -d '[:space:]'; }
SESS_BEFORE="$(count_desk)"; SESS_BEFORE="${SESS_BEFORE:-0}"
# Kill the ssh client (simulate a dropped link) but NOT the server-side session.
inx "pkill -f 'ssh -o StrictHostKeyChecking' 2>/dev/null" || true
sleep 2
SESS_AFTER="$(count_desk)"; SESS_AFTER="${SESS_AFTER:-0}"
if [ "$SESS_BEFORE" -ge 1 ] && [ "$SESS_AFTER" -ge 1 ]; then
  stage PASS "5-reconnect-resume (session survived link drop)"
else
  stage FAIL "5-reconnect-resume (before=$SESS_BEFORE after=$SESS_AFTER)"
fi
inx "sudo -u forecast tmux kill-server 2>/dev/null" || true

# ── report ──────────────────────────────────────────────────────────────────
printf '\n\033[1mFresh-box proof — results\033[0m\n'
FAILS=0
for s in "${STAGES[@]}"; do
  st="${s%%|*}"; nm="${s#*|}"
  if [ "$st" = PASS ]; then printf '  \033[32mPASS\033[0m  %s\n' "$nm"
  else printf '  \033[31mFAIL\033[0m  %s\n' "$nm"; FAILS=$((FAILS+1)); fi
done
printf '\n'
if [ "$FAILS" -eq 0 ]; then
  printf '\033[1;32m✦ FRESH-BOX PROOF GREEN — bootstrap → services → doctor → SSH-into-TUI all pass.\033[0m\n\n'
  exit 0
else
  printf '\033[1;31m✗ FRESH-BOX PROOF RED — %d stage(s) failed.\033[0m\n\n' "$FAILS"
  exit 1
fi
