#!/usr/bin/env bash
# ============================================================================
# Outrider / Superforecasting Agent — standalone one-command installer
# ============================================================================
# Installs the prebuilt RELEASE WHEEL with pipx. No git checkout, no Python
# venv to manage, no `npm run build`. Modern releases provide separate backend
# and prebuilt TUI wheels, installed together into the pipx environment.
#
# Every install is INTEGRITY-CHECKED before anything touches the system: the
# wheel is verified against the release's SHA256SUMS and, when the release
# ships one, cross-checked against the sha256 pinned in release-manifest.json.
# A checksum mismatch ABORTS with nothing installed — there is no
# install-anyway path. (Same verify story as scripts/upgrade.sh.)
#
# Quick start (always installs the newest release):
#
#     curl -fsSL https://github.com/teddyjfpender/superforecasting-agent/releases/latest/download/install.sh | bash
#
# Pin a specific release, or re-run to upgrade in place:
#
#     curl -fsSL https://github.com/teddyjfpender/superforecasting-agent/releases/download/v0.19.0/install.sh | bash
#     TAG=v0.19.0 bash install.sh
#
# Config:
#   TAG=vX.Y.Z | latest    release to install (alias: SUPERFORECASTING_AGENT_RELEASE_TAG)
#   RELEASE_DOWNLOAD_DIR=/new/directory
#                          verify and stage selected wheels without installing.
#   INSTALL_TUI=0         install only the backend/CLI (default: 1).
#   MANIFEST=/path/release-manifest.json
#                          pin the EXACT release a local manifest names: the
#                          tag, the wheel filename, and the wheel sha256 all
#                          come from the manifest (same pin scripts/upgrade.sh
#                          takes with MANIFEST=…)
#   ALLOW_UNVERIFIED=1     permit installing a release that predates the
#                          SHA256SUMS artifact (pre-P0 releases only).
#                          DANGEROUS: skips integrity verification entirely.
#                          Never needed for v0.18.0+ releases, and never a
#                          bypass for a FAILED check — a mismatch always aborts.
#
# Supported: macOS, Linux. Needs Python 3.11-3.13 (the only prerequisite — pipx is
# installed automatically if missing).
# ============================================================================
set -euo pipefail

REPO="${REPO:-teddyjfpender/superforecasting-agent}"
# Pin with TAG=v0.19.0 (or SUPERFORECASTING_AGENT_RELEASE_TAG); default latest.
# TAG_SET remembers whether the user pinned explicitly, so a conflicting
# MANIFEST= pin can be refused instead of silently winning.
TAG_SET="${SUPERFORECASTING_AGENT_RELEASE_TAG:-${TAG:-}}"
TAG="${TAG_SET:-latest}"
ALLOW_UNVERIFIED="${SUPERFORECASTING_AGENT_ALLOW_UNVERIFIED:-${ALLOW_UNVERIFIED:-0}}"
BIN="superforecasting-agent"
INSTALL_TUI="${INSTALL_TUI:-1}"
case "$INSTALL_TUI" in 0|1) ;; *) echo "INSTALL_TUI must be 0 or 1" >&2; exit 1;; esac

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

sha256_of() {  # <file> -> hex digest on stdout
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}

# verify_checksum <file> <SHA256SUMS> -> 0 iff the recorded sha256 matches.
# Kept in LOCKSTEP with scripts/upgrade.sh + scripts/hetzner-install.sh (the
# three installers stay self-contained — each is fetched and run alone, so the
# helper is duplicated deliberately, not factored into a shared file). A sums
# file with NO entry for the file is a FAILURE: never trust a sums file that
# does not mention the artifact it ships beside.
verify_checksum() {  # <file> <SHA256SUMS>  -> 0 iff the recorded sha256 matches
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

read_manifest() {  # <path> -> sets MAN_VERSION MAN_TAG MAN_WHEEL_NAME MAN_WHEEL_SHA
  local out
  out="$("$PY" -c '
import json, re, sys
m = json.load(open(sys.argv[1]))
print(m["version"]); print(m["tag"])
for role in ("wheel", "terminal_wheel"):
    w = m["artifacts"].get(role)
    if w is None and role == "terminal_wheel":
        print(""); print(""); continue
    if not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", w["name"]):
        raise ValueError("Invalid wheel filename")
    if not re.fullmatch(r"[0-9a-f]{64}", w["sha256"]):
        raise ValueError("Invalid wheel digest")
    print(w["name"]); print(w["sha256"])
' "$1" 2>/dev/null)" || return 1
  MAN_VERSION="$(printf '%s\n' "$out" | sed -n 1p)"
  MAN_TAG="$(printf '%s\n' "$out" | sed -n 2p)"
  MAN_WHEEL_NAME="$(printf '%s\n' "$out" | sed -n 3p)"
  MAN_WHEEL_SHA="$(printf '%s\n' "$out" | sed -n 4p)"
  MAN_TUI_NAME="$(printf '%s\n' "$out" | sed -n 5p)"
  MAN_TUI_SHA="$(printf '%s\n' "$out" | sed -n 6p)"
  [ -n "$MAN_VERSION" ] && [ -n "$MAN_TAG" ] && [ -n "$MAN_WHEEL_NAME" ] && [ -n "$MAN_WHEEL_SHA" ]
}

printf '\n\033[1m✦ Outrider — Superforecasting Agent\033[0m\n\n'

# 1. Locate a Python interpreter (the only hard prerequisite).
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 \
      && "$c" -c 'import sys; raise SystemExit(not ((3, 11) <= sys.version_info[:2] < (3, 14)))' 2>/dev/null; then
    PY="$c"
    break
  fi
done
[ -n "$PY" ] || die "Python 3.11-3.13 is required but was not found. Install a supported Python and re-run."

# 2. Resolve the target release. A local release-manifest.json (MANIFEST=…)
#    pins the exact tag; otherwise TAG (default: latest) resolves through the
#    GitHub Releases API.
MAN_VERSION="" MAN_TAG="" MAN_WHEEL_NAME="" MAN_WHEEL_SHA="" MAN_TUI_NAME="" MAN_TUI_SHA=""
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if [ -n "${MANIFEST:-}" ]; then
  [ -f "$MANIFEST" ] || die "MANIFEST=$MANIFEST does not exist."
  read_manifest "$MANIFEST" || die "MANIFEST=$MANIFEST is not a readable release manifest."
  if [ -n "$TAG_SET" ] && [ "$TAG_SET" != "latest" ] && [ "$TAG_SET" != "$MAN_TAG" ]; then
    die "TAG=$TAG_SET conflicts with the MANIFEST pin ($MAN_TAG) — drop one of the two."
  fi
  TAG="$MAN_TAG"
  say "Pinned by manifest: $TAG (wheel sha256 ${MAN_WHEEL_SHA:0:12}…)"
fi

if [ "$TAG" = "latest" ]; then
  API="https://api.github.com/repos/$REPO/releases/latest"
else
  API="https://api.github.com/repos/$REPO/releases/tags/$TAG"
fi
say "Resolving release ($TAG)…"
META="$(fetch "$API")" || die "Could not reach the GitHub Releases API for the '$TAG' release of $REPO (network error, or no such release)."
printf '%s' "$META" > "$TMP/release.json"
# Select exact asset names from structured metadata; API ordering is irrelevant.
asset_url() {
  "$PY" -c '
import json, sys
from urllib.parse import urlsplit
assets = json.load(open(sys.argv[1]))["assets"]
name = sys.argv[2]
urls = [a["browser_download_url"] for a in assets
        if urlsplit(a["browser_download_url"]).path.rsplit("/", 1)[-1] == name]
if len(urls) != 1 or urlsplit(urls[0]).scheme != "https":
    raise SystemExit(1)
print(urls[0])
' "$TMP/release.json" "$1"
}
SUMS_URL="$(asset_url SHA256SUMS || true)"
MANIFEST_URL="$(asset_url release-manifest.json || true)"

# 2b. Without a local pin, take the pin from the release's own manifest
#     (every formal release ships one; it names the wheel + its sha256).
if [ -z "$MAN_WHEEL_SHA" ] && [ -n "$MANIFEST_URL" ]; then
  download "$MANIFEST_URL" "$TMP/release-manifest.json" \
    || die "release-manifest.json download failed (network error?) — aborting, nothing installed."
  read_manifest "$TMP/release-manifest.json" \
    || die "release $TAG ships an unreadable release-manifest.json — aborting, nothing installed."
fi
if [ -n "$MAN_WHEEL_NAME" ]; then
  WHEEL_NAME="$MAN_WHEEL_NAME"
else
  # Historical releases had one bundled wheel. Ambiguous releases fail closed.
  WHEEL_NAME="$("$PY" -c '
import json, re, sys
from urllib.parse import urlsplit
names = [urlsplit(a["browser_download_url"]).path.rsplit("/", 1)[-1]
         for a in json.load(open(sys.argv[1]))["assets"]]
wheels = [n for n in names if n.endswith(".whl")]
if len(wheels) != 1 or not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", wheels[0]):
    raise SystemExit(1)
print(wheels[0])
' "$TMP/release.json")" || die "Release requires a manifest identifying its backend wheel."
fi
WHEEL_URL="$(asset_url "$WHEEL_NAME")" \
  || die "Release does not serve exactly one wheel matching the manifest pin '$WHEEL_NAME'."
ok "Found $WHEEL_NAME"
TUI_WHEEL=""
if [ "$INSTALL_TUI" = 1 ] && [ -n "$MAN_TUI_NAME" ]; then
  [ "$MAN_TUI_NAME" != "$WHEEL_NAME" ] || die "Backend and terminal wheel names must differ."
  TUI_URL="$(asset_url "$MAN_TUI_NAME")" || die "Missing or duplicate terminal wheel '$MAN_TUI_NAME'."
  TUI_WHEEL="$TMP/$MAN_TUI_NAME"
  download "$TUI_URL" "$TUI_WHEEL" || die "Terminal wheel download failed; nothing installed."
fi

# 3. Download the wheel to a temp file (more reliable than installing from a
#    URL: pipx reads the package name straight from the local wheel).
WHEEL="$TMP/$WHEEL_NAME"
say "Downloading…"
download "$WHEEL_URL" "$WHEEL" || die "wheel download failed (network error?) — aborting, nothing installed."

# 4. INTEGRITY GATE — verify before anything is installed.
#    TRUST RULE (lockstep with upgrade.sh + hetzner-install.sh): anything this
#    script DOWNLOADS must verify, fatally. ALLOW_UNVERIFIED=1 only covers a
#    release that genuinely ships no SHA256SUMS — never a FAILED check.
#    * SHA256SUMS missing from the release: fatal (pre-P0 releases predate the
#      checksum artifact; ALLOW_UNVERIFIED=1 is the explicit, loud opt-out).
#    * Checksum mismatch: ALWAYS fatal. Never degrades to a warning.
if [ -z "$SUMS_URL" ]; then
  if [ "$ALLOW_UNVERIFIED" = "1" ]; then
    warn "release $TAG ships no SHA256SUMS (pre-P0 release?) — ALLOW_UNVERIFIED=1 set, proceeding WITHOUT integrity verification. You own the risk."
  else
    die "release $TAG ships no SHA256SUMS (pre-P0 release?) — cannot verify the wheel. Pin a v0.18.0+ release, or re-run with ALLOW_UNVERIFIED=1 to accept an unverified install."
  fi
else
  say "Verifying wheel integrity…"
  download "$SUMS_URL" "$TMP/SHA256SUMS" \
    || die "SHA256SUMS download failed (network error?) — refusing to install an unverified wheel."
  verify_checksum "$WHEEL" "$TMP/SHA256SUMS" \
    || die "wheel sha256 MISMATCH against the release's SHA256SUMS — the download is corrupt or tampered with. Aborting: NOTHING was installed."
  ok "Wheel sha256 verified (SHA256SUMS)"
  if [ -n "$MAN_WHEEL_SHA" ]; then
    [ "$(sha256_of "$WHEEL")" = "$MAN_WHEEL_SHA" ] \
      || die "wheel sha256 MISMATCH against the release-manifest.json pin. Aborting: NOTHING was installed."
    ok "Wheel sha256 matches the release-manifest.json pin"
  fi
fi

# Every selected companion is verified before even the backend install starts.
if [ -n "$TUI_WHEEL" ]; then
  [ -f "$TMP/SHA256SUMS" ] || die "Split distributions require SHA256SUMS."
  verify_checksum "$TUI_WHEEL" "$TMP/SHA256SUMS" \
    || die "Terminal wheel sha256 MISMATCH; nothing installed."
  [ "$(sha256_of "$TUI_WHEEL")" = "$MAN_TUI_SHA" ] \
    || die "Terminal wheel manifest sha256 MISMATCH; nothing installed."
fi
# A manifest pin remains binding even for legacy releases without SHA256SUMS.
if [ -n "$MAN_WHEEL_SHA" ]; then
  [ "$(sha256_of "$WHEEL")" = "$MAN_WHEEL_SHA" ] \
    || die "Wheel manifest sha256 MISMATCH; nothing installed."
fi

# Provisioning/upgrades reuse this owner without running user installation steps.
# A new directory prevents an old receipt from admitting partially copied output.
if [ -n "${RELEASE_DOWNLOAD_DIR:-}" ]; then
  mkdir "$RELEASE_DOWNLOAD_DIR" || die "Download destination must be a new directory."
  cp "$WHEEL" "$RELEASE_DOWNLOAD_DIR/$WHEEL_NAME"
  if [ -n "$TUI_WHEEL" ]; then cp "$TUI_WHEEL" "$RELEASE_DOWNLOAD_DIR/$MAN_TUI_NAME"; fi
  printf '%s\n' "$WHEEL_NAME" > "$RELEASE_DOWNLOAD_DIR/wheels.txt"
  if [ -n "$TUI_WHEEL" ]; then printf '%s\n' "$MAN_TUI_NAME" >> "$RELEASE_DOWNLOAD_DIR/wheels.txt"; fi
  ok "Selected release wheels verified and staged."
  exit 0
fi

# 5. Ensure pipx (isolated venv + clean, repeatable upgrades).
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

# 6. Install (--force so re-running upgrades even at the same version number).
if ensure_pipx; then
  say "Installing with pipx…"
  pipx install --force "$WHEEL"
  if [ -n "$TUI_WHEEL" ]; then pipx inject --force "$BIN" "$TUI_WHEEL"; fi
  BIN_DIR="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || echo "$HOME/.local/bin")"
else
  warn "pipx unavailable — falling back to 'pip install --user'."
  INSTALL_WHEELS=("$WHEEL")
  if [ -n "$TUI_WHEEL" ]; then INSTALL_WHEELS+=("$TUI_WHEEL"); fi
  "$PY" -m pip install --user --force-reinstall "${INSTALL_WHEELS[@]}"
  BIN_DIR="$("$PY" -c 'import site, os; print(os.path.join(site.getuserbase(), "bin"))')"
fi

# Stamp the release lane so future update checks use GitHub Releases rather
# than looking for a package this fork does not publish to PyPI.
AGENT_HOME="${SUPERFORECASTING_AGENT_HOME:-${FORECAST_HOME:-${HERMES_HOME:-$HOME/.superforecasting-agent}}}"
if mkdir -p "$AGENT_HOME" && printf 'release\n' > "$AGENT_HOME/.install_method"; then
  :
else
  warn "Could not stamp $AGENT_HOME/.install_method; updates will still work via the release installer."
fi

# 7. Report and tell them how to launch (never auto-launch — stdin is the
#    piped script here, not a terminal, so the interactive TUI can't attach).
#    Report the binary we JUST installed, not whatever happens to shadow it
#    earlier on PATH.
INSTALLED_BIN="$BIN_DIR/$BIN"
[ -x "$INSTALLED_BIN" ] || INSTALLED_BIN="$BIN"
LAUNCH="$BIN --tui"
if [ "$INSTALL_TUI" = 0 ]; then LAUNCH="$BIN --help"; fi
echo
if command -v "$BIN" >/dev/null 2>&1; then
  ok "Installed $("$INSTALLED_BIN" --version 2>/dev/null || echo "$BIN")"
  printf '\n   Get started:  \033[1m%s\033[0m\n\n' "$LAUNCH"
else
  ok "Installed."
  echo
  warn "'$BIN' isn't on your PATH yet in this shell. Add the bin dir:"
  printf '     export PATH="%s:$PATH"\n' "$BIN_DIR"
  printf '   then open a new terminal and run:  \033[1m%s\033[0m\n\n' "$LAUNCH"
fi
