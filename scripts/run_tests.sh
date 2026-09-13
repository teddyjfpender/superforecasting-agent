#!/usr/bin/env bash
# Canonical test runner for Superforecasting Agent. Run this instead of calling
# `pytest` directly to guarantee your local run matches CI behavior.
#
# What this script enforces:
#   * -n 4 xdist workers (CI has 4 cores; -n auto diverges locally)
#   * TZ=UTC, LANG=C.UTF-8, PYTHONHASHSEED=0 (deterministic)
#   * Credential env vars blanked (conftest.py also does this, but this
#     is belt-and-suspenders for anyone running `pytest` outside of
#     our conftest path — e.g. calling pytest on a single file)
#   * Proper venv activation
#
# Usage:
#   scripts/run_tests.sh                     # full suite
#   scripts/run_tests.sh tests/agent/        # one directory
#   scripts/run_tests.sh tests/agent/test_foo.py::TestClass::test_method
#   scripts/run_tests.sh --tb=long -v        # pass-through pytest args

set -euo pipefail

# ── Locate repo root ────────────────────────────────────────────────────────
# Works whether this is the main checkout or a worktree.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Only explicit service selections may retain their own credentials. The normal
# suite always remains hermetic; selection also changes pytest collection below.
LIVE_DAYTONA=0
LIVE_MODAL=0
LIVE_PATHS=()
expect_service=0
for argument in "$@"; do
  service=""
  if [ "$expect_service" = 1 ]; then
    service="$argument"
    expect_service=0
  else
    case "$argument" in
      --live-service) expect_service=1; continue ;;
      --live-service=*) service="${argument#*=}" ;;
      *) continue ;;
    esac
  fi
  case "$service" in
    daytona)
      if [ "$LIVE_DAYTONA" = 0 ]; then LIVE_PATHS+=(tests/integration/test_daytona_terminal.py); fi
      LIVE_DAYTONA=1
      ;;
    modal)
      if [ "$LIVE_MODAL" = 0 ]; then LIVE_PATHS+=(tests/integration/test_modal_terminal.py); fi
      LIVE_MODAL=1
      ;;
    *) echo "error: unsupported live service '$service'" >&2; exit 2 ;;
  esac
done
if [ "$expect_service" = 1 ]; then
  echo "error: --live-service requires daytona or modal" >&2
  exit 2
fi
if [ "$LIVE_DAYTONA" = 1 ] && [ -z "${DAYTONA_API_KEY:-}" ]; then
  echo "error: live Daytona verification requires DAYTONA_API_KEY" >&2
  exit 2
fi
if [ "$LIVE_MODAL" = 1 ] && { [ -z "${MODAL_TOKEN_ID:-}" ] || [ -z "${MODAL_TOKEN_SECRET:-}" ]; }; then
  echo "error: live Modal verification requires MODAL_TOKEN_ID and MODAL_TOKEN_SECRET" >&2
  exit 2
fi

# ── Activate venv ───────────────────────────────────────────────────────────
# Prefer a .venv in the current tree, fall back to the main checkout's venv
# (useful for worktrees where we don't always duplicate the venv).
VENV=""
for candidate in \
  "$REPO_ROOT/.venv" \
  "$REPO_ROOT/venv" \
  "$HOME/.superforecasting-agent/superforecasting-agent/venv" \
  "$HOME/.hermes/hermes-agent/venv"; do
  if [ -f "$candidate/bin/activate" ] || [ -f "$candidate/Scripts/activate" ]; then
    VENV="$candidate"
    break
  fi
done

if [ -z "$VENV" ]; then
  echo "error: no virtualenv found in $REPO_ROOT/.venv, $REPO_ROOT/venv, or shared runtime homes" >&2
  exit 1
fi

PYTHON="$VENV/bin/python"
if [ -f "$VENV/Scripts/python.exe" ]; then
  PYTHON="$VENV/Scripts/python.exe"
fi

# ── Ensure pytest-split is installed (required for shard-equivalent runs) ──
if ! "$PYTHON" -c "import pytest_split" 2>/dev/null; then
  echo "→ installing pytest-split into $VENV"
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$PYTHON" --quiet "pytest-split>=0.9,<1"
  elif "$PYTHON" -m pip --version >/dev/null 2>&1; then
    "$PYTHON" -m pip install --quiet "pytest-split>=0.9,<1"
  else
    echo "error: neither uv nor pip is available in $VENV — pytest-split is missing" >&2
    echo "  fix: run  uv pip install -e \".[dev]\"  from $REPO_ROOT" >&2
    exit 1
  fi
fi

# ── Hermetic environment ────────────────────────────────────────────────────
# Mirror what CI does in .github/workflows/tests.yml + what conftest.py does.
# Unset every credential-shaped var currently in the environment.
while IFS='=' read -r name _; do
  case "$name" in
    DAYTONA_API_KEY) [ "$LIVE_DAYTONA" = 1 ] && continue ;;
    MODAL_TOKEN_ID|MODAL_TOKEN_SECRET) [ "$LIVE_MODAL" = 1 ] && continue ;;
  esac
  case "$name" in
    *_API_KEY|*_TOKEN|*_TOKEN_ID|*_SECRET|*_PASSWORD|*_CREDENTIALS|*_ACCESS_KEY| \
    *_SECRET_ACCESS_KEY|*_PRIVATE_KEY|*_OAUTH_TOKEN|*_WEBHOOK_SECRET| \
    *_ENCRYPT_KEY|*_APP_SECRET|*_CLIENT_SECRET|*_CORP_SECRET|*_AES_KEY| \
    AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|FAL_KEY| \
    GH_TOKEN|GITHUB_TOKEN)
      unset "$name"
      ;;
  esac
done < <(env)

# Unset HERMES_* behavioral vars too.
unset HERMES_YOLO_MODE HERMES_INTERACTIVE HERMES_QUIET HERMES_TOOL_PROGRESS \
      HERMES_TOOL_PROGRESS_MODE HERMES_MAX_ITERATIONS HERMES_SESSION_PLATFORM \
      HERMES_SESSION_CHAT_ID HERMES_SESSION_CHAT_NAME HERMES_SESSION_THREAD_ID \
      HERMES_SESSION_SOURCE HERMES_SESSION_KEY HERMES_GATEWAY_SESSION \
      HERMES_CRON_SESSION \
      HERMES_PLATFORM HERMES_INFERENCE_PROVIDER SUPERFORECASTING_AGENT_MANAGED \
      FORECAST_MANAGED HERMES_MANAGED HERMES_DEV \
      SUPERFORECASTING_AGENT_NOUS_PORTAL_BASE_URL FORECAST_NOUS_PORTAL_BASE_URL \
      SUPERFORECASTING_AGENT_PORTAL_BASE_URL FORECAST_PORTAL_BASE_URL \
      HERMES_PORTAL_BASE_URL NOUS_PORTAL_BASE_URL NOUS_BASE_URL \
      SUPERFORECASTING_AGENT_NOUS_INFERENCE_BASE_URL FORECAST_NOUS_INFERENCE_BASE_URL \
      NOUS_INFERENCE_BASE_URL SUPERFORECASTING_AGENT_NOUS_MIN_KEY_TTL_SECONDS \
      FORECAST_NOUS_MIN_KEY_TTL_SECONDS HERMES_NOUS_MIN_KEY_TTL_SECONDS \
      SUPERFORECASTING_AGENT_NOUS_TIMEOUT_SECONDS FORECAST_NOUS_TIMEOUT_SECONDS \
      HERMES_NOUS_TIMEOUT_SECONDS \
      HERMES_CONTAINER HERMES_EPHEMERAL_SYSTEM_PROMPT HERMES_PREFILL_MESSAGES_FILE \
      HERMES_TIMEZONE \
      HERMES_REDACT_SECRETS HERMES_BACKGROUND_NOTIFICATIONS HERMES_EXEC_ASK \
      HERMES_FILE_MUTATION_VERIFIER HERMES_IGNORE_USER_CONFIG HERMES_IGNORE_RULES \
      HERMES_ACCEPT_HOOKS HERMES_CRON_TIMEOUT HERMES_CRON_SCRIPT_TIMEOUT \
      HERMES_CRON_MAX_PARALLEL HERMES_AGENT_TIMEOUT \
      HERMES_AGENT_TIMEOUT_WARNING HERMES_AGENT_NOTIFY_INTERVAL \
      HERMES_RESTART_DRAIN_TIMEOUT HERMES_GATEWAY_BUSY_INPUT_MODE \
      HERMES_GATEWAY_BUSY_ACK_ENABLED HERMES_GATEWAY_PLATFORM_CONNECT_TIMEOUT \
      HERMES_AUTO_CONTINUE_FRESHNESS HERMES_GATEWAY_ADAPTER_DISCONNECT_TIMEOUT \
      HERMES_API_TIMEOUT HERMES_API_CALL_STALE_TIMEOUT \
      HERMES_STREAM_READ_TIMEOUT HERMES_STREAM_STALE_TIMEOUT HERMES_STREAM_RETRIES \
      HERMES_LIGHT HERMES_TUI_LIGHT HERMES_TUI_THEME HERMES_TUI_BACKGROUND \
      HERMES_SIGTERM_GRACE \
      HERMES_HOME_MODE 2>/dev/null || true
unset SUPERFORECASTING_AGENT_MODEL FORECAST_MODEL HERMES_MODEL \
      SUPERFORECASTING_AGENT_INFERENCE_MODEL FORECAST_INFERENCE_MODEL \
      HERMES_INFERENCE_MODEL SUPERFORECASTING_AGENT_INFERENCE_PROVIDER \
      FORECAST_INFERENCE_PROVIDER 2>/dev/null || true
unset SUPERFORECASTING_AGENT_INTERACTIVE FORECAST_INTERACTIVE 2>/dev/null || true
unset SUPERFORECASTING_AGENT_FILE_MUTATION_VERIFIER \
      FORECAST_FILE_MUTATION_VERIFIER 2>/dev/null || true
unset SUPERFORECASTING_AGENT_EPHEMERAL_SYSTEM_PROMPT \
      FORECAST_EPHEMERAL_SYSTEM_PROMPT \
      SUPERFORECASTING_AGENT_PREFILL_MESSAGES_FILE \
      FORECAST_PREFILL_MESSAGES_FILE 2>/dev/null || true
unset SUPERFORECASTING_AGENT_IGNORE_USER_CONFIG FORECAST_IGNORE_USER_CONFIG \
      SUPERFORECASTING_AGENT_IGNORE_RULES FORECAST_IGNORE_RULES 2>/dev/null || true
unset SUPERFORECASTING_AGENT_ACCEPT_HOOKS FORECAST_ACCEPT_HOOKS 2>/dev/null || true
unset SUPERFORECASTING_AGENT_EXEC_ASK FORECAST_EXEC_ASK 2>/dev/null || true
unset SUPERFORECASTING_AGENT_BACKGROUND_NOTIFICATIONS \
      FORECAST_BACKGROUND_NOTIFICATIONS 2>/dev/null || true
unset SUPERFORECASTING_AGENT_CRON_TIMEOUT FORECAST_CRON_TIMEOUT \
      SUPERFORECASTING_AGENT_CRON_SCRIPT_TIMEOUT FORECAST_CRON_SCRIPT_TIMEOUT \
      SUPERFORECASTING_AGENT_CRON_MAX_PARALLEL FORECAST_CRON_MAX_PARALLEL \
      2>/dev/null || true
unset SUPERFORECASTING_AGENT_AGENT_TIMEOUT FORECAST_AGENT_TIMEOUT \
      SUPERFORECASTING_AGENT_AGENT_TIMEOUT_WARNING FORECAST_AGENT_TIMEOUT_WARNING \
      SUPERFORECASTING_AGENT_AGENT_NOTIFY_INTERVAL FORECAST_AGENT_NOTIFY_INTERVAL \
      SUPERFORECASTING_AGENT_RESTART_DRAIN_TIMEOUT FORECAST_RESTART_DRAIN_TIMEOUT \
      SUPERFORECASTING_AGENT_GATEWAY_BUSY_INPUT_MODE FORECAST_GATEWAY_BUSY_INPUT_MODE \
      SUPERFORECASTING_AGENT_GATEWAY_BUSY_ACK_ENABLED FORECAST_GATEWAY_BUSY_ACK_ENABLED \
      SUPERFORECASTING_AGENT_GATEWAY_PLATFORM_CONNECT_TIMEOUT \
      FORECAST_GATEWAY_PLATFORM_CONNECT_TIMEOUT 2>/dev/null || true
unset SUPERFORECASTING_AGENT_AUTO_CONTINUE_FRESHNESS FORECAST_AUTO_CONTINUE_FRESHNESS \
      SUPERFORECASTING_AGENT_GATEWAY_ADAPTER_DISCONNECT_TIMEOUT \
      FORECAST_GATEWAY_ADAPTER_DISCONNECT_TIMEOUT 2>/dev/null || true
unset SUPERFORECASTING_AGENT_API_TIMEOUT FORECAST_API_TIMEOUT \
      SUPERFORECASTING_AGENT_API_CALL_STALE_TIMEOUT FORECAST_API_CALL_STALE_TIMEOUT \
      SUPERFORECASTING_AGENT_STREAM_READ_TIMEOUT FORECAST_STREAM_READ_TIMEOUT \
      SUPERFORECASTING_AGENT_STREAM_STALE_TIMEOUT FORECAST_STREAM_STALE_TIMEOUT \
      SUPERFORECASTING_AGENT_STREAM_RETRIES FORECAST_STREAM_RETRIES 2>/dev/null || true
unset SUPERFORECASTING_AGENT_LIGHT FORECAST_LIGHT \
      SUPERFORECASTING_AGENT_TUI_LIGHT FORECAST_TUI_LIGHT \
      SUPERFORECASTING_AGENT_TUI_THEME FORECAST_TUI_THEME \
      SUPERFORECASTING_AGENT_TUI_BACKGROUND FORECAST_TUI_BACKGROUND 2>/dev/null || true
unset SUPERFORECASTING_AGENT_SIGTERM_GRACE FORECAST_SIGTERM_GRACE 2>/dev/null || true

# Pin deterministic runtime.
export TZ=UTC
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export PYTHONHASHSEED=0

# ── Live-gateway test guard (developer machines) ────────────────────────────
# If a system-wide hermes pytest_live_guard plugin is installed at
# $HOME/.hermes/pytest_live_guard.py, force-load it here so every test run
# from this script gets the protection regardless of which worktree is
# checked out (in-tree tests/conftest.py guard may be missing on stale
# branches). Harmless on CI / fresh machines that don't have the file.
if [ -f "$HOME/.hermes/pytest_live_guard.py" ]; then
  case ":${PYTHONPATH:-}:" in
    *":$HOME/.hermes:"*) ;;
    *) export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$HOME/.hermes" ;;
  esac
  if [[ ",${PYTEST_PLUGINS:-}," != *,pytest_live_guard,* ]]; then
    export PYTEST_PLUGINS="${PYTEST_PLUGINS:+$PYTEST_PLUGINS,}pytest_live_guard"
  fi
fi

# ── Worker count ────────────────────────────────────────────────────────────
# CI uses `-n auto` on ubuntu-latest which gives 4 workers. A 20-core
# workstation with `-n auto` gets 20 workers and exposes test-ordering
# flakes that CI will never see. Pin to 4 so local matches CI.
WORKERS="${HERMES_TEST_WORKERS:-4}"

# ── Run pytest ──────────────────────────────────────────────────────────────
cd "$REPO_ROOT"

# PTY tests must exercise current source, not a stale release artifact left by
# packaging. Backend-only installations keep their no-Node test path.
if command -v npm >/dev/null 2>&1 && [ -x "$REPO_ROOT/ui-tui/node_modules/.bin/esbuild" ]; then
  npm run build --prefix "$REPO_ROOT/ui-tui"
fi

# Preserve partial progress and failures even when an outer command runner kills
# this script before pytest can print its final traceback. CI may override the
# directory while local runs default to an ignored repo-local artifact folder.
TEST_ARTIFACT_DIR="${HERMES_TEST_ARTIFACT_DIR:-$REPO_ROOT/.test-results}"
mkdir -p "$TEST_ARTIFACT_DIR"
JUNIT_XML="$TEST_ARTIFACT_DIR/pytest-$(date -u +%Y%m%dT%H%M%SZ)-$$.xml"
PYTEST_LOG="${JUNIT_XML%.xml}.log"

# If the first argument starts with `-` treat all args as pytest flags;
# otherwise treat them as test paths.
[ "$#" -gt 0 ] || set -- tests/
ARGS=("$@")

echo "▶ running pytest with $WORKERS workers, hermetic env, in $REPO_ROOT"
echo "  (TZ=UTC LANG=C.UTF-8 PYTHONHASHSEED=0; only explicitly selected service credentials retained)"
echo "  JUnit artifact: $JUNIT_XML"
echo "  Streaming log: $PYTEST_LOG"

# -o "addopts=" clears pyproject.toml's `-n auto` so our -n wins.
# We re-add --timeout/--timeout-method here because pyproject.toml's
# addopts is wiped above. The 60s cap is essential: see pyproject.toml
# for why (suite deadlocks at session teardown without it).
SELECTION=(--ignore=tests/integration -m "not integration")
if [ "${#LIVE_PATHS[@]}" -gt 0 ]; then
  SELECTION=(-m integration "${LIVE_PATHS[@]}")
fi
TIMEOUT_METHOD="$("$PYTHON" -c 'import signal; print("signal" if hasattr(signal, "SIGALRM") else "thread")')"
"$PYTHON" -m pytest \
  -o "addopts=" \
  -n "$WORKERS" \
  --timeout=30 \
  --timeout-method="$TIMEOUT_METHOD" \
  --junitxml="$JUNIT_XML" \
  --ignore=tests/e2e \
  "${SELECTION[@]}" \
  "${ARGS[@]}" 2>&1 | tee "$PYTEST_LOG"
