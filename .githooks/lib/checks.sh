# shellcheck shell=bash
# The gate implementations shared by the git hooks and CI. Sourced, not run.
# Every function is exit-code gated (0 = pass, non-zero = fail) and prints its
# own teaching error via hook_fail. Requires common.sh already sourced.

# ── ruff on a set of files (repo pyproject config: select = PLW1514) ─────────
# check_ruff <file>...   (no files => no-op pass)
check_ruff() {
  if [ "$#" -eq 0 ]; then return 0; fi
  _ruff="$(hook_ruff)" || {
    hook_fail "ruff not found" "Local Gates: Git Hooks" \
      "No ruff in .venv/bin or PATH. Install:  uv pip install -e \".[all,dev]\""
    return 1
  }
  ( cd "$HOOKS_REPO_ROOT" && "$_ruff" check "$@" )
}

# ── protocol codegen staleness (generated.ts vs the pydantic models) ─────────
check_protocol_stale() {
  _py="$(hook_python)" || {
    hook_fail "python not found" "The Laws -> Protocol-first" "No python interpreter available."
    return 1
  }
  ( cd "$HOOKS_REPO_ROOT" && "$_py" -m protocol.codegen --check )
}

# ── tsc --noEmit for the TUI ─────────────────────────────────────────────────
check_tsc() {
  _tsc="$HOOKS_REPO_ROOT/ui-tui/node_modules/.bin/tsc"
  if [ ! -x "$_tsc" ]; then
    hook_fail "TypeScript toolchain missing" "Local Gates: Git Hooks" \
      "ui-tui files are staged but ui-tui/node_modules is absent. Run:  ( cd ui-tui && npm install )"
    return 1
  fi
  ( cd "$HOOKS_REPO_ROOT/ui-tui" && "$_tsc" --noEmit -p tsconfig.json )
}

# ── vitest --changed since <base> ────────────────────────────────────────────
check_vitest_changed() {
  _base="$1"
  _vitest="$HOOKS_REPO_ROOT/ui-tui/node_modules/.bin/vitest"
  if [ ! -x "$_vitest" ]; then
    hook_fail "vitest missing" "Local Gates: Git Hooks" \
      "ui-tui changed but ui-tui/node_modules is absent. Run:  ( cd ui-tui && npm install )"
    return 1
  fi
  ( cd "$HOOKS_REPO_ROOT/ui-tui" && "$_vitest" run --changed "$_base" --passWithNoTests )
}

# ── commit message shape + WHY-body for feat/refactor ────────────────────────
# check_commit_msg <msgfile>
check_commit_msg() {
  _msgfile="$1"
  _header="$(grep -v -e '^[[:space:]]*#' "$_msgfile" | sed -e '/^[[:space:]]*$/d' | head -n1)"

  case "$_header" in
    Merge\ *|Revert\ *|fixup!\ *|squash!\ *) return 0 ;;
  esac

  _re='^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([a-z0-9,._/ -]+\))?(!)?: .+'
  if ! printf '%s' "$_header" | grep -Eq "$_re"; then
    hook_fail "Commit message shape" "Commit provenance" \
"Header must read:  type(scope): subject
  Got: ${_header:-<empty>}
  Types: feat fix docs style refactor perf test build ci chore revert
  e.g.  feat(jobs): one runtime for every detached job"
    return 1
  fi

  if [ "${#_header}" -gt 72 ]; then
    hook_warn "  note: subject is ${#_header} chars (>72) -- consider tightening."
  fi

  _type="$(printf '%s' "$_header" | sed -E 's/^([a-z]+).*/\1/')"
  case "$_type" in
    feat|refactor)
      # body = comment-stripped content after the first blank line past the header,
      # minus trailer lines (Key: value) and blanks. A trailers-only body does not
      # explain the WHY, so it does not count.
      _body="$(grep -v -e '^[[:space:]]*#' "$_msgfile" | awk '
        { if(!h){ if($0 ~ /[^[:space:]]/){h=1} ; next }
          if(!b){ if($0 ~ /^[[:space:]]*$/){b=1} ; next }
          print }')"
      _prose="$(printf '%s\n' "$_body" | grep -Ev '^[A-Za-z][A-Za-z-]+: ' | sed -e '/^[[:space:]]*$/d')"
      if [ -z "$_prose" ]; then
        hook_fail "Empty commit body" "Commit provenance" \
"A '$_type' commit must explain the WHY, not just the subject.
  Add a blank line after the subject, then a sentence or two of motivation."
        return 1
      fi
      ;;
  esac
  return 0
}

# ── oversize gate: no single file adds > 1200 lines without a MOVES-ONLY marker
# check_oversize cached <msgfile>
# check_oversize range  <base> [head]
check_oversize() {
  _mode="$1"; shift
  _limit=1200
  if [ "$_mode" = "cached" ]; then
    _numstat="$(git diff --cached --numstat)"
    _msg="$(cat "$1" 2>/dev/null)"
  else
    _base="$1"; _head="${2:-HEAD}"
    _numstat="$(git diff --numstat "$_base" "$_head")"
    _msg="$(git log --format=%B "$_base..$_head")"
  fi

  _offenders=""
  while IFS='	' read -r _add _del _path; do
    [ -z "$_path" ] && continue
    [ "$_add" = "-" ] && continue           # binary
    # Generated artifacts are exempt: they are legitimately large and carry a
    # STRONGER control than line counts — their own deterministic --check
    # staleness gates (protocol.codegen, scripts.docgen) fail CI when they
    # drift from their sources. Hand-written code stays under the limit.
    case "$_path" in
      docs/reference/*|ui-tui/src/protocol/generated.ts) continue ;;
    esac
    if [ "$_add" -gt "$_limit" ] 2>/dev/null; then
      _offenders="${_offenders}    $_path (+$_add lines)
"
    fi
  done <<EOF
$_numstat
EOF

  if [ -n "$_offenders" ]; then
    if printf '%s' "$_msg" | grep -q 'MOVES-ONLY'; then
      hook_note "  large diff acknowledged by MOVES-ONLY marker -- reviewer must confirm the diff is bodies moved + one-line delegates only."
      return 0
    fi
    hook_fail "Oversize change (> $_limit added lines in one file)" "The Laws -> Moves-only refactor slices" \
"These files add more than $_limit lines:
$_offenders  A change this large is almost always a refactor that belongs in a moves-only
  slice: method bodies moved out + one-line delegates, verified by a mechanical
  (difflib) diff showing zero unexpected added lines. If this genuinely IS such a
  carve, put the word MOVES-ONLY in the commit body."
    return 1
  fi
  return 0
}

# ── wire-drift gate: generated.ts / ui-tui/dist may not change without a
#    protocol/ change in the same set (cross-layer halves land together)
# check_drift cached
# check_drift range <base> [head]
check_drift() {
  _mode="$1"; shift
  if [ "$_mode" = "cached" ]; then
    _changed="$(git diff --cached --name-only)"
  else
    _changed="$(git diff --name-only "$1" "${2:-HEAD}")"
  fi
  _gen="$(printf '%s\n' "$_changed" | grep -E '^ui-tui/src/protocol/generated\.ts$|^ui-tui/dist/' || true)"
  _prot="$(printf '%s\n' "$_changed" | grep -E '^protocol/' || true)"
  if [ -n "$_gen" ] && [ -z "$_prot" ]; then
    hook_fail "Wire drift -- generated/built artifact changed without its source" \
      "The Laws -> Protocol-first & Cross-layer halves" \
"Changed generated/built artifacts (do not hand-edit these):
$(printf '    %s\n' $_gen)
  generated.ts is emitted from the protocol/ pydantic models; ui-tui/dist is built.
  Change the model under protocol/ and regenerate, then commit both halves together:
    python -m protocol.codegen"
    return 1
  fi
  return 0
}

# ── map changed .py files -> the test dirs that cover them (pre-push) ─────────
# py_test_targets <base> [head]  -> prints unique, existing test paths
py_test_targets() {
  _base="$1"; _head="${2:-HEAD}"
  _changed="$(git diff --name-only "$_base" "$_head" -- '*.py')"
  [ -z "$_changed" ] && return 0
  _raw=""
  while IFS= read -r _f; do
    [ -z "$_f" ] && continue
    case "$_f" in
      tests/*)                                  _raw="$_raw
$_f" ;;
      forecasting/*|tools/forecast_actions/*)   _raw="$_raw
tests/forecasting" ;;
      protocol/*)                               _raw="$_raw
tests/test_protocol_codegen.py" ;;
      gateway/*|tui_gateway/*)                  _raw="$_raw
tests/gateway" ;;
      agent/*)                                  _raw="$_raw
tests/agent" ;;
      superforecasting_agent/runtime/*)                             _raw="$_raw
tests/runtime_cli" ;;
      providers/*)                              _raw="$_raw
tests/providers" ;;
      cron/*)                                   _raw="$_raw
tests/cron" ;;
      acp_adapter/*|acp_registry/*)             _raw="$_raw
tests/acp" ;;
    esac
  done <<EOF
$_changed
EOF
  printf '%s\n' "$_raw" | sed -e '/^[[:space:]]*$/d' | sort -u | while IFS= read -r _t; do
    [ -e "$HOOKS_REPO_ROOT/$_t" ] && printf '%s\n' "$_t"
  done
}
