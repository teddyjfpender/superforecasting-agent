#!/usr/bin/env bash
# ============================================================================
# Release-readiness gate — shared by scripts/release.sh, the production-release
# workflow, and a pre-tag hook.  RED means "do not cut a release".
# ============================================================================
# Cheap, deterministic checks (always run):
#   1. version source-of-truth consistency  (pyproject == hermes_cli/__init__)
#   2. semver format                         (X.Y.Z)
#   3. version is not an existing git tag    (vX.Y.Z unused)
#   4. changelog has a non-empty entry       (## [X.Y.Z] ... with body)
#
# Strict checks (--strict; need the full venv/toolchain — CI and pre-tag):
#   5. protocol codegen is not stale         (scripts/check-protocol.sh)
#   6. generated docs are not stale          (python -m scripts.docgen --check)
#   7. worktree is clean                      (tracked + untracked files)
#
# Suites-green is enforced by the *workflow* (the test job gates the release
# job via needs:), and locally by `--with-tests` here.  Keeping the heavy run
# out of the default path is deliberate: this gate must stay fast enough to run
# on every `release.sh` dry-run and every pre-tag hook.
#
# Usage:
#   scripts/check-release-ready.sh                 # cheap checks, current ver
#   scripts/check-release-ready.sh --version 0.18.0
#   scripts/check-release-ready.sh --strict        # + codegen checks
#   scripts/check-release-ready.sh --with-tests    # + full pytest suite
#
# Exit: 0 all green, 1 one or more red.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

STRICT=0
WITH_TESTS=0
WANT_VERSION=""
while [ $# -gt 0 ]; do
  case "$1" in
    --strict) STRICT=1 ;;
    --with-tests) WITH_TESTS=1 ;;
    --version) WANT_VERSION="${2:-}"; shift ;;
    --version=*) WANT_VERSION="${1#*=}" ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

RED=0
c_ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
c_bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; RED=1; }
c_skip() { printf '  \033[33m∅\033[0m %s\n' "$*"; }

# --- helpers ---------------------------------------------------------------
pyproject_version() {
  sed -n 's/^version = "\([^"]*\)".*/\1/p' pyproject.toml | head -n1
}
init_version() {
  sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' hermes_cli/__init__.py | head -n1
}

PYPROJECT_VER="$(pyproject_version)"
INIT_VER="$(init_version)"
VERSION="${WANT_VERSION:-$PYPROJECT_VER}"

echo "Release-readiness gate — version ${VERSION}"

# 1. Single source of truth: the two version strings must agree.
if [ -n "$PYPROJECT_VER" ] && [ "$PYPROJECT_VER" = "$INIT_VER" ]; then
  c_ok "version consistent (pyproject == __init__ == ${PYPROJECT_VER})"
else
  c_bad "version drift: pyproject='${PYPROJECT_VER}' __init__='${INIT_VER}'"
fi

# If an explicit --version was requested, it must equal the source of truth.
if [ -n "$WANT_VERSION" ] && [ "$WANT_VERSION" != "$PYPROJECT_VER" ]; then
  c_bad "requested version '${WANT_VERSION}' != pyproject '${PYPROJECT_VER}'"
fi

# 2. Strict semver.
if printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  c_ok "semver format ok (${VERSION})"
else
  c_bad "version '${VERSION}' is not strict semver X.Y.Z"
fi

# 3. Tag discipline. Two legitimate modes:
#    - pre-tag (local, default): the tag must NOT exist yet — bump first.
#    - tag-run (CI, GITHUB_REF points at this tag): the tag exists BY
#      DEFINITION; the real invariant is that it points at HEAD.
TAG="v${VERSION}"
if [ "${GITHUB_REF:-}" = "refs/tags/${TAG}" ]; then
  if [ "$(git rev-parse "refs/tags/${TAG}^{commit}")" = "$(git rev-parse HEAD)" ]; then
    c_ok "tag-run: ${TAG} points at HEAD"
  else
    c_bad "tag-run: ${TAG} does not point at HEAD"
  fi
elif git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null 2>&1; then
  c_bad "tag ${TAG} already exists — bump before releasing"
else
  c_ok "tag ${TAG} is unused"
fi

# 4. Changelog entry present and non-empty for this version.
CHANGELOG="CHANGELOG.md"
if [ ! -f "$CHANGELOG" ]; then
  c_bad "CHANGELOG.md is missing"
else
  # Grab the body between "## [VERSION]" and the next "## [" header.
  body="$(
    awk -v ver="$VERSION" '
      $0 ~ "^## \\[" ver "\\]" { grab=1; next }
      grab && /^## \[/ { exit }
      grab { print }
    ' "$CHANGELOG" | grep -v '^[[:space:]]*$' || true
  )"
  if [ -n "$body" ]; then
    lines="$(printf '%s\n' "$body" | wc -l | tr -d ' ')"
    c_ok "changelog entry for ${VERSION} present (${lines} non-blank lines)"
  else
    c_bad "changelog has no non-empty '## [${VERSION}]' entry"
  fi
fi

# --- strict (codegen) checks ----------------------------------------------
if [ "$STRICT" = "1" ]; then
  if [ -x scripts/check-protocol.sh ]; then
    if scripts/check-protocol.sh >/dev/null 2>&1; then
      c_ok "protocol codegen up to date"
    else
      c_bad "protocol codegen stale (run: python -m protocol.codegen)"
    fi
  else
    c_skip "protocol check skipped (scripts/check-protocol.sh absent)"
  fi

  PY="${PYTHON:-}"
  [ -n "$PY" ] || { [ -x .venv/bin/python ] && PY=.venv/bin/python; }
  [ -n "$PY" ] || PY="$(command -v python3 || true)"
  if [ -n "$PY" ] && "$PY" -c "import scripts.docgen" >/dev/null 2>&1; then
    if docgen_output="$("$PY" -m scripts.docgen --check 2>&1)"; then
      c_ok "generated docs up to date"
    else
      printf '%s\n' "$docgen_output" >&2
      c_bad "generated docs stale (run: python -m scripts.docgen)"
    fi
  else
    c_skip "docgen check skipped (docgen toolchain unavailable)"
  fi

  dirty="$(git status --porcelain=v1 --untracked-files=all)"
  if [ -z "$dirty" ]; then
    c_ok "worktree clean"
  else
    printf '%s\n' "$dirty" >&2
    c_bad "worktree dirty — commit the exact release candidate first"
  fi
else
  c_skip "strict codegen checks skipped (pass --strict to enforce)"
fi

# --- optional full suite ---------------------------------------------------
if [ "$WITH_TESTS" = "1" ]; then
  if [ -x scripts/run_tests.sh ]; then
    if scripts/run_tests.sh -q >/dev/null 2>&1; then
      c_ok "test suite green"
    else
      c_bad "test suite red (run: scripts/run_tests.sh)"
    fi
  else
    c_skip "test suite skipped (scripts/run_tests.sh absent)"
  fi
else
  c_skip "full suite skipped (workflow gates it; pass --with-tests locally)"
fi

echo
if [ "$RED" = "0" ]; then
  if [ "$WITH_TESTS" = "1" ]; then
    printf '\033[32mREADY\033[0m — %s can be released\n' "$TAG"
  else
    printf '\033[32mCHECKS PASSED\033[0m — run with --with-tests before tagging %s\n' "$TAG"
  fi
  exit 0
else
  printf '\033[31mNOT READY\033[0m — resolve the ✗ items above\n'
  exit 1
fi
