#!/usr/bin/env bash
# ============================================================================
# scripts/release.sh — cut the formal artifact set for one release (vX.Y.Z).
# ============================================================================
# Produces, into the output dir (default dist/), the full formal set:
#   1. the Python wheel  (bundled tui_dist; pipx-installable, node auto-provision)
#   2. the sdist
#   3. install.sh        (the one-line installer, staged from install-release.sh)
#   4. install.ps1       (native Windows release-wheel installer)
#   5. SHA256SUMS        (checksums over 1-4)
#   6. release-manifest.json  (machine-readable: names, versions, image digest,
#                              min-migration version — the installer's contract)
#   7. RELEASE_NOTES.md  (changelog scaffold for this version)
#
# DRY-RUN ONLY. It never touches git, a registry, or GitHub. This is the
# offline dry-run-parity twin of .github/workflows/production-release.yml, so a
# release is fully testable before a tag is ever pushed.  The image is described
# in the manifest with digest=null. The formal workflow is the only publisher.
#
# Usage:
#   scripts/release.sh                       # dry-run, version from pyproject
#   scripts/release.sh --version 0.18.0      # assert the version explicitly
#   scripts/release.sh --min-migration 0.17.0
#   scripts/release.sh --out /tmp/rel        # write elsewhere
#   scripts/release.sh --build-npm           # rebuild the TUI bundle from source
#
# Env: SKIP_GATE=1 skips the readiness gate (tests/CI only).
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

IMAGE_REGISTRY="ghcr.io"
IMAGE_REPO="teddyjfpender/superforecasting-agent"
IMAGE_PLATFORMS="linux/amd64,linux/arm64"

BUILD_NPM=0
WANT_VERSION=""
MIN_MIGRATION="${RELEASE_MIN_MIGRATION:-0.17.0}"
OUT_DIR="dist"

while [ $# -gt 0 ]; do
  case "$1" in
    --build-npm) BUILD_NPM=1 ;;
    --version) WANT_VERSION="${2:-}"; shift ;;
    --version=*) WANT_VERSION="${1#*=}" ;;
    --min-migration) MIN_MIGRATION="${2:-}"; shift ;;
    --min-migration=*) MIN_MIGRATION="${1#*=}" ;;
    --out) OUT_DIR="${2:-}"; shift ;;
    --out=*) OUT_DIR="${1#*=}" ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m  %s\n' "$*"; }
die()  { printf '\033[31m✗\033[0m  %s\n' "$*" >&2; exit 1; }

PY="${PYTHON:-}"
[ -n "$PY" ] || { [ -x .venv/bin/python ] && PY=.venv/bin/python; }
[ -n "$PY" ] || PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || die "no python interpreter found"

VERSION="$(sed -n 's/^version = "\([^"]*\)".*/\1/p' pyproject.toml | head -n1)"
[ -n "$VERSION" ] || die "could not read version from pyproject.toml"
TAG="v${VERSION}"

printf '\n\033[1m✦ Release %s (DRY-RUN)\033[0m\n\n' "$TAG"

# 1. Readiness gate (shared with the workflow + pre-tag hook).
if [ "${SKIP_GATE:-0}" = "1" ]; then
  say "Readiness gate skipped (SKIP_GATE=1)"
else
  say "Running readiness gate"
  scripts/check-release-ready.sh --version "$VERSION" \
    || die "readiness gate failed — not releasing"
fi

if [ -n "$WANT_VERSION" ] && [ "$WANT_VERSION" != "$VERSION" ]; then
  die "requested --version $WANT_VERSION != pyproject $VERSION"
fi

# 2. Build the wheel + sdist (bundled TUI). Reuse the prebuilt bundle offline
#    unless --build-npm is passed.
say "Building wheel + sdist"
if [ "$BUILD_NPM" = "1" ]; then
  scripts/build-release.sh
else
  if [ -f ui-tui/dist/entry.js ]; then
    SKIP_NPM=1 scripts/build-release.sh
  else
    scripts/build-release.sh
  fi
fi

WHEEL="$(ls -1 dist/superforecasting_agent-*.whl 2>/dev/null | head -n1 || true)"
SDIST="$(ls -1 dist/superforecasting_agent-*.tar.gz 2>/dev/null | head -n1 || true)"
[ -n "$WHEEL" ] || die "no wheel produced in dist/"
[ -n "$SDIST" ] || die "no sdist produced in dist/"

# The wheel filename must carry the release version (catches a stale build).
case "$WHEEL" in
  *"superforecasting_agent-${VERSION}-"*) ok "wheel version matches ${VERSION}" ;;
  *) die "wheel '$WHEEL' does not match version ${VERSION}" ;;
esac

# 3. Assemble the release directory. The wheel/sdist are built into dist/, so
#    with the default --out=dist they are already in place — `cp` onto the
#    same file errors ("identical") on both BSD and GNU, killing the dry-run.
mkdir -p "$OUT_DIR"
if [ "$(cd "$(dirname "$WHEEL")" && pwd)" != "$(cd "$OUT_DIR" && pwd)" ]; then
  cp -f "$WHEEL" "$OUT_DIR/"
  cp -f "$SDIST" "$OUT_DIR/"
fi
cp -f scripts/install-release.sh "$OUT_DIR/install.sh"
cp -f scripts/install-release.ps1 "$OUT_DIR/install.ps1"
WHEEL_NAME="$(basename "$WHEEL")"
SDIST_NAME="$(basename "$SDIST")"

# 4. SHA256SUMS over the four shippable artifacts.
say "Computing SHA256SUMS"
(
  cd "$OUT_DIR"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$WHEEL_NAME" "$SDIST_NAME" install.sh install.ps1 > SHA256SUMS
  else
    shasum -a 256 "$WHEEL_NAME" "$SDIST_NAME" install.sh install.ps1 > SHA256SUMS
  fi
)
ok "wrote $OUT_DIR/SHA256SUMS"

# 5. Describe the image without publishing it.
IMAGE_DIGEST="null"
say "Image: dry-run — workflow will publish ${IMAGE_REGISTRY}/${IMAGE_REPO}:${TAG},latest ($IMAGE_PLATFORMS)"

# 6. Machine-readable release manifest.
say "Writing release-manifest.json"
plat_a="${IMAGE_PLATFORMS%%,*}"
plat_b="${IMAGE_PLATFORMS#*,}"
"$PY" -m scripts.release_manifest build \
  --version "$VERSION" \
  --tag "$TAG" \
  --min-migration "$MIN_MIGRATION" \
  --artifact "wheel=$OUT_DIR/$WHEEL_NAME" \
  --artifact "sdist=$OUT_DIR/$SDIST_NAME" \
  --artifact "installer=$OUT_DIR/install.sh" \
  --artifact "windows_installer=$OUT_DIR/install.ps1" \
  --artifact "checksums=$OUT_DIR/SHA256SUMS" \
  --image-registry "$IMAGE_REGISTRY" \
  --image-repo "$IMAGE_REPO" \
  --image-tag "$TAG" \
  --image-tag latest \
  --image-platform "$plat_a" \
  --image-platform "$plat_b" \
  --image-digest "$IMAGE_DIGEST" \
  --out "$OUT_DIR/release-manifest.json" \
  || die "manifest build/validation failed"
ok "wrote $OUT_DIR/release-manifest.json (validated)"

# 7. Release-notes scaffold from the changelog entry for this version.
say "Scaffolding RELEASE_NOTES.md"
NOTES="$OUT_DIR/RELEASE_NOTES.md"
{
  printf '# %s\n\n' "$TAG"
  awk -v ver="$VERSION" '
    $0 ~ "^## \\[" ver "\\]" { grab=1 }
    grab && seen && /^## \[/ { exit }
    grab { print; seen=1 }
  ' CHANGELOG.md 2>/dev/null || true
} > "$NOTES"
ok "wrote $NOTES"

# --- Summary ---------------------------------------------------------------
echo
printf '\033[1mArtifact set (%s):\033[0m\n' "$OUT_DIR"
for f in "$WHEEL_NAME" "$SDIST_NAME" install.sh install.ps1 SHA256SUMS release-manifest.json RELEASE_NOTES.md; do
  [ -f "$OUT_DIR/$f" ] && printf '    %s\n' "$f"
done
echo
printf '\033[32mDRY-RUN complete.\033[0m Publish only through .github/workflows/production-release.yml.\n'
