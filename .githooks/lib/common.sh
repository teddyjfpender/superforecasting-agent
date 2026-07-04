# shellcheck shell=bash
# Shared plumbing for the Hermes git hooks (.githooks/*) AND the CI mirror
# (.github/workflows/contributing-gates.yml). This file is SOURCED, never run.
#
# The whole point: the hooks and CI call the SAME functions (here + in
# checks.sh), so a local pass and a CI pass can never mean different things.
#
# Written for bash 3.2 (the macOS system bash) — no mapfile, no associative
# arrays, no ${var^^}.

set -o pipefail

HOOKS_REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
export HOOKS_REPO_ROOT
HOOKS_SKIPS_LOG="$HOOKS_REPO_ROOT/.githooks/skips.log"

# ── colours (only when stderr is a real terminal) ───────────────────────────
if [ -t 2 ]; then
  _C_RED=$'\033[31m'; _C_YEL=$'\033[33m'; _C_GRN=$'\033[32m'
  _C_BLD=$'\033[1m'; _C_DIM=$'\033[2m'; _C_RST=$'\033[0m'
else
  _C_RED=""; _C_YEL=""; _C_GRN=""; _C_BLD=""; _C_DIM=""; _C_RST=""
fi

hook_note() { printf '%s\n' "${_C_DIM}$*${_C_RST}" >&2; }
hook_ok()   { printf '%s\n' "${_C_GRN}$*${_C_RST}" >&2; }
hook_warn() { printf '%s\n' "${_C_YEL}${_C_BLD}$*${_C_RST}" >&2; }

# hook_fail <law-name> <CONTRIBUTING section> <detail...>
# The teaching error: names the law, quotes the section it enforces, and always
# shows the (logged) escape hatch. This is the shape every gate speaks in.
hook_fail() {
  law="$1"; section="$2"; shift 2
  {
    printf '\n%s\n' "${_C_RED}${_C_BLD}BLOCKED: ${law}${_C_RST}"
    printf '%s\n' "$*"
    printf '%s\n' "${_C_DIM}  Enforces: CONTRIBUTING.md -> \"${section}\"${_C_RST}"
    printf '%s\n' "${_C_DIM}  Escape hatch (logged to .githooks/skips.log, never silent):${_C_RST}"
    printf '%s\n' "${_C_DIM}    HERMES_HOOKS_SKIP=\"why this once\" git <cmd>${_C_RST}"
  } >&2
}

# ── tool discovery ──────────────────────────────────────────────────────────
hook_python() {
  for c in \
    "$HOOKS_REPO_ROOT/.venv/bin/python" \
    "$HOOKS_REPO_ROOT/venv/bin/python" \
    "$(command -v python3 2>/dev/null)" \
    "$(command -v python 2>/dev/null)"; do
    if [ -n "$c" ] && [ -x "$c" ]; then printf '%s' "$c"; return 0; fi
  done
  return 1
}

hook_ruff() {
  for c in \
    "$HOOKS_REPO_ROOT/.venv/bin/ruff" \
    "$(command -v ruff 2>/dev/null)"; do
    if [ -n "$c" ] && [ -x "$c" ]; then printf '%s' "$c"; return 0; fi
  done
  return 1
}

# ── escape hatch (visible, never silent) ────────────────────────────────────
# hook_log_skip <hook> <scope> <reason>
hook_log_skip() {
  _hook="$1"; _scope="$2"; _reason="$3"
  _head="$(git rev-parse --short HEAD 2>/dev/null || echo '-')"
  _who="$(git config user.email 2>/dev/null || echo "${USER:-unknown}")"
  _ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '%s\t%s\t%s\t%s\t%s\n' \
    "$_ts" "$_hook" "$_scope" "$_who@$_head" "$_reason" >> "$HOOKS_SKIPS_LOG"
}

# hook_honor_global_skip <hook>
#   returns 0  -> caller should `exit 0` (skip requested + logged)
#   returns 1  -> no skip; run the gates
#   exits 1    -> HERMES_HOOKS_SKIP set but EMPTY (a reason is mandatory)
hook_honor_global_skip() {
  _hook="$1"
  if [ -z "${HERMES_HOOKS_SKIP+set}" ]; then
    return 1
  fi
  if [ -z "${HERMES_HOOKS_SKIP}" ]; then
    hook_warn "HERMES_HOOKS_SKIP is set but empty -- refusing to skip silently."
    hook_note "  A bypass must state why:  HERMES_HOOKS_SKIP=\"rebasing WIP\" git <cmd>"
    exit 1
  fi
  hook_log_skip "$_hook" "ALL" "$HERMES_HOOKS_SKIP"
  hook_warn "!! $_hook SKIPPED via HERMES_HOOKS_SKIP=\"$HERMES_HOOKS_SKIP\""
  hook_warn "   Logged to .githooks/skips.log -- this bypass is visible to reviewers."
  return 0
}
