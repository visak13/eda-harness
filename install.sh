#!/usr/bin/env sh
# Heronry installer for Linux and macOS (also Git Bash on Windows) - S3 s-870e401942,
# design-e963c656f5 4.4 / 4.10.
#
#   curl -LsSf https://github.com/visak13/eda-harness/releases/latest/download/install.sh | sh
#   sh install.sh [--version v0.9.0] [--release-url <dir or https base>] [--force] [--no-modify-path] [--yes]
#                 [--no-embed]
#
# 1. uv: uses the uv on PATH when it is at least $UV_VERSION, else installs exactly $UV_VERSION into
#    ~/.local/bin after checking the archive against uv's published SHA-256.
# 2. the release: SHA256SUMS plus the four wheels (edp8, edp_contracts, edp_pool, edp_broker), each
#    verified against SHA256SUMS before anything is installed.
# 3. `uv tool install --force "edp8[embed] @ <edp8 wheel>" --with <the other three>` (never `uv tool upgrade`,
#    a no-op for wheel installs; --no-embed drops the embed extra); skipped when that version is already
#    installed, unless --force. Safe to re-run.
# 4. puts uv's tool bin dir on PATH (uv tool update-shell; --no-modify-path skips it) and prints
#    `heronry version`. No root needed; your data lives outside the install and survives a reinstall.
# 5. `heronry prereqs install`: checks git, node, a harness (claude/codex), the embedder and its model against
#    the one prerequisites manifest, asks once (on the terminal, also under `curl | sh`), and installs the
#    missing required ones with brew or apt (--yes: no question; apt asks sudo for its password).
set -eu

UV_VERSION="0.9.11"
PYTHON="3.12"
REPO="visak13/eda-harness"
VERSION=""; RELEASE_URL=""; FORCE=0; MODIFY_PATH=1; YES=0; EMBED=1
while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --release-url) RELEASE_URL="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --no-modify-path) MODIFY_PATH=0; shift ;;
    --yes|-y) YES=1; shift ;;
    --no-embed) EMBED=0; shift ;;
    *) echo "heronry-install: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

say() { echo "heronry-install: $*"; }
die() { echo "heronry-install: $*" >&2; exit 1; }
sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}
fetch() {  # fetch <url-or-path> <dest>
  case "$1" in
    http://*|https://*) curl -fsSL --retry 3 -o "$2" "$1" ;;
    file://*) cp "${1#file://}" "$2" ;;
    *) cp "$1" "$2" ;;
  esac
}
ver_ge() {  # ver_ge A B: A >= B for X.Y.Z
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -t. -k1,1n -k2,2n -k3,3n | head -n1)" = "$2" ]
}
ver_of() { echo "$1" | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n1; }

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t heronry)"
trap 'rm -rf "$WORK"' EXIT INT TERM
export NO_COLOR=1

# -- 1. uv ------------------------------------------------------------------------------------------------
UV="$(command -v uv 2>/dev/null || true)"
[ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv" &&
  { PATH="$HOME/.local/bin:$PATH"; export PATH; }  # `heronry prereqs` / `heronry update` look uv up on PATH
HAVE=""; [ -n "$UV" ] && HAVE="$(ver_of "$("$UV" --version)")"
if [ -z "$UV" ] || [ -z "$HAVE" ] || ! ver_ge "$HAVE" "$UV_VERSION"; then
  case "$(uname -m)" in
    x86_64|amd64) ARCH=x86_64 ;;
    arm64|aarch64) ARCH=aarch64 ;;
    *) die "unsupported CPU $(uname -m); install uv $UV_VERSION yourself, then re-run" ;;
  esac
  case "$(uname -s)" in
    Linux) ASSET="uv-$ARCH-unknown-linux-gnu.tar.gz" ;;
    Darwin) ASSET="uv-$ARCH-apple-darwin.tar.gz" ;;
    MINGW*|MSYS*|CYGWIN*) ASSET="uv-$ARCH-pc-windows-msvc.zip" ;;
    *) die "unsupported OS $(uname -s)" ;;
  esac
  BASE="https://github.com/astral-sh/uv/releases/download/$UV_VERSION"
  say "installing uv $UV_VERSION ($ASSET)"
  fetch "$BASE/$ASSET" "$WORK/$ASSET"
  fetch "$BASE/$ASSET.sha256" "$WORK/$ASSET.sha256"
  WANT="$(cut -d' ' -f1 < "$WORK/$ASSET.sha256" | tr 'A-F' 'a-f')"
  [ "$(sha256 "$WORK/$ASSET")" = "$WANT" ] || die "uv archive SHA-256 mismatch; nothing installed"
  mkdir -p "$WORK/uv" "$HOME/.local/bin"
  case "$ASSET" in
    *.zip) unzip -q -o "$WORK/$ASSET" -d "$WORK/uv" ;;
    *) tar -xzf "$WORK/$ASSET" -C "$WORK/uv" ;;
  esac
  find "$WORK/uv" -type f \( -name uv -o -name uvx -o -name uv.exe -o -name uvx.exe \) -exec cp {} "$HOME/.local/bin/" \;
  chmod +x "$HOME/.local/bin/"uv* 2>/dev/null || true
  UV="$HOME/.local/bin/uv"; [ -x "$UV" ] || UV="$HOME/.local/bin/uv.exe"
  PATH="$HOME/.local/bin:$PATH"; export PATH
fi
say "uv: $("$UV" --version)"

# -- 2. the release, verified -------------------------------------------------------------------------------
: > "$WORK/files"   # lines: <name> <url-or-path>
if [ -n "$RELEASE_URL" ]; then
  BASE="${RELEASE_URL%/}"
  fetch "$BASE/SHA256SUMS" "$WORK/SHA256SUMS"
  awk -v b="$BASE" 'NF==2 { n=$2; sub(/^\*/, "", n); print n, b "/" n }' "$WORK/SHA256SUMS" > "$WORK/files"
else
  if [ -n "$VERSION" ]; then API="https://api.github.com/repos/$REPO/releases/tags/$VERSION"
  else API="https://api.github.com/repos/$REPO/releases/latest"; fi
  curl -fsSL -H "Accept: application/vnd.github+json" "$API" -o "$WORK/release.json"
  grep -o '"browser_download_url": *"[^"]*"' "$WORK/release.json" | sed 's/.*"\(http[^"]*\)"/\1/' |
    while read -r u; do echo "${u##*/} $u"; done > "$WORK/files"
  SUMS_URL="$(awk '$1=="SHA256SUMS" {print $2}' "$WORK/files")"
  [ -n "$SUMS_URL" ] || die "the release has no SHA256SUMS; refusing an unverifiable install"
  fetch "$SUMS_URL" "$WORK/SHA256SUMS"
fi
WITH=""; EDP8=""
for W in edp8 edp_contracts edp_pool edp_broker; do
  NAME="$(awk -v w="$W" 'index($1, w "-")==1 && $1 ~ /\.whl$/ {print $1}' "$WORK/files" | sort | tail -n1)"
  [ -n "$NAME" ] || die "the release has no $W wheel"
  WANT="$(awk -v n="$NAME" '{ f=$2; sub(/^\*/, "", f) } f==n && length($1)==64 {print tolower($1)}' "$WORK/SHA256SUMS")"
  [ -n "$WANT" ] || die "$NAME is not listed in SHA256SUMS; refusing it"
  fetch "$(awk -v n="$NAME" '$1==n {print $2}' "$WORK/files")" "$WORK/$NAME"
  [ "$(sha256 "$WORK/$NAME")" = "$WANT" ] || die "SHA-256 mismatch for $NAME; nothing installed"
  if [ "$W" = edp8 ]; then EDP8="$WORK/$NAME"; else WITH="$WITH --with $WORK/$NAME"; fi
done
TARGET="$(basename "$EDP8" | cut -d- -f2)"
say "verified 4 wheels of heronry $TARGET against SHA256SUMS"

# -- 3. install (idempotent) ----------------------------------------------------------------------------------
BIN="$("$UV" tool dir --bin --color never)"
PATH="$BIN:$PATH"; export PATH
EXE="$BIN/heronry"; [ -x "$EXE" ] || [ ! -x "$BIN/heronry.exe" ] || EXE="$BIN/heronry.exe"
INSTALLED=""; [ -x "$EXE" ] && INSTALLED="$(ver_of "$("$EXE" version 2>/dev/null || true)")"
if [ -n "$INSTALLED" ] && [ "$INSTALLED" = "$(ver_of "$TARGET")" ] && [ "$FORCE" = 0 ]; then
  say "heronry $TARGET is already installed; nothing to do (--force reinstalls)"
else
  SPEC="$EDP8"
  if [ "$EMBED" = 1 ]; then  # the embed extra needs a PEP 508 URL: "edp8[embed] @ file:///abs/path.whl"
    ABS="$(cd "$(dirname "$EDP8")" && { pwd -W 2>/dev/null || pwd; })/$(basename "$EDP8")"
    case "$ABS" in /*) SPEC="edp8[embed] @ file://$ABS" ;; *) SPEC="edp8[embed] @ file:///$ABS" ;; esac
  fi
  say "uv tool install --force --python $PYTHON $SPEC$WITH"
  # shellcheck disable=SC2086  # WITH is a list of --with <path> pairs (temp paths without spaces)
  "$UV" tool install --force --python "$PYTHON" "$SPEC" $WITH ||
    die "uv tool install failed. If heronry is running, stop it first: heronry stop"
  EXE="$BIN/heronry"; [ -x "$EXE" ] || EXE="$BIN/heronry.exe"
fi

# -- 4. PATH and the proof ------------------------------------------------------------------------------------
[ "$MODIFY_PATH" = 1 ] && { "$UV" tool update-shell >/dev/null 2>&1 || true; }
"$EXE" version || die "heronry version failed after the install"

# -- 5. prerequisites (the one manifest: edp_contracts.prereqs) ----------------------------------------------
PA="prereqs install"; [ "$YES" = 1 ] && PA="$PA --yes"; [ "$EMBED" = 0 ] && PA="$PA --no-embed"
say "heronry $PA"
# under `curl | sh` stdin is the script: the one question goes to the terminal instead
# shellcheck disable=SC2086
if [ "$YES" = 0 ] && [ -r /dev/tty ] && [ ! -t 0 ]; then "$EXE" $PA </dev/tty; else "$EXE" $PA; fi ||
  say "some prerequisites are still missing (above); Heronry is installed: run 'heronry prereqs install' again after fixing them"
say "next: heronry init   (then heronry start; open a new shell if 'heronry' is not found)"
