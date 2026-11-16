#!/bin/bash
# Assemble the offline bot that the iOS app bundles (all outputs gitignored;
# every download and weight file is checked against MANIFEST.sha256).
#
#   web/ios/pybot/build_payload.sh [WEIGHTS_DIR [DL_DIR]]
#
# WEIGHTS_DIR holds the four release weight files fly.toml names
# (g3a-e04-f4f4127e.npz, p0-ft1-1fa201b2.npz, b1a-028131a0.npz,
# js-m1-0d17fd03.npz); without it (or with "-") the weights of the payload
# already built are reused, checked again. DL_DIR (default web/ios/pybot/dl)
# caches the downloads; the xcframework and numpy are unpacked only once.
# The payload records its inputs (inputs.sh), and the Xcode phase refuses a
# payload whose server/shengji sources or fly.toml have changed since.
# Outputs:
#   Python.xcframework            BeeWare Python-Apple-support 3.14-b14
#   payload/                      shengji package + fly.toml + offline_bot.py + models/
#   site/iphoneos|iphonesimulator numpy, unpacked from BeeWare's iOS wheels
#
# A clean checkout builds the app in four steps:
#   web/ios/pybot/build_payload.sh <weights dir>
#   web/ios/pybot/build_fast_ext.sh <a host cython 3.x binary, e.g. server/.venv/bin/cython>
#   (cd web && npm ci && npm run ios:sync)
#   open web/ios/App/App.xcodeproj, then Run or Product > Archive
# The "Install Python (pybot)" build phase (xcode_install_python.sh) copies all
# of it into the app and stops the build if a step above has not run.
# Rerun build_payload.sh after a change to server/shengji or fly.toml.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
WEIGHTS="${1:-}"
[ "$WEIGHTS" != "-" ] || WEIGHTS=""
DL="${2:-$HERE/dl}"
MAN="$HERE/MANIFEST.sha256"
PAS_URL="https://github.com/beeware/Python-Apple-support/releases/download/3.14-b14/Python-3.14-iOS-support.b14.tar.gz"
WHEEL_BASE="https://pypi.anaconda.org/beeware/simple/numpy/2.5.2.post1"

want() { awk -v f="$1" '$2==f {print $1}' "$MAN"; }
check() {  # check FILE NAME
  local got; got=$(shasum -a 256 "$1" | cut -d' ' -f1)
  local exp; exp=$(want "$2")
  [ -n "$exp" ] || { echo "no manifest entry for $2" >&2; exit 2; }
  [ "$got" = "$exp" ] || { echo "sha256 mismatch $2: $got != $exp" >&2; exit 2; }
}
fetch() {  # fetch URL NAME
  mkdir -p "$DL"
  [ -f "$DL/$2" ] || curl -fsSL -o "$DL/$2" "$1"
  check "$DL/$2" "$2"
}

fetch "$PAS_URL" Python-3.14-iOS-support.b14.tar.gz
for p in iphoneos iphonesimulator; do
  fetch "$WHEEL_BASE/numpy-2.5.2.post1-cp314-cp314-ios_13_0_arm64_$p.whl" \
        "numpy-2.5.2.post1-cp314-cp314-ios_13_0_arm64_$p.whl"
done

# The compiled engine (fast/) is built against this xcframework, so it is
# unpacked once and kept.
if [ ! -d "$HERE/Python.xcframework" ]; then
  X=$(mktemp -d); tar -xzf "$DL/Python-3.14-iOS-support.b14.tar.gz" -C "$X"
  mv "$X/Python.xcframework" "$HERE/Python.xcframework"; rm -rf "$X"
fi
for p in iphoneos iphonesimulator; do
  if [ ! -d "$HERE/site/$p" ]; then
    mkdir -p "$HERE/site/$p"
    (cd "$HERE/site/$p" && unzip -q "$DL/numpy-2.5.2.post1-cp314-cp314-ios_13_0_arm64_$p.whl")
  fi
done

P="$HERE/payload"
NEW="$HERE/payload.new"
rm -rf "$NEW"
mkdir -p "$NEW/models"
for f in g3a-e04-f4f4127e.npz p0-ft1-1fa201b2.npz b1a-028131a0.npz js-m1-0d17fd03.npz; do
  src="${WEIGHTS:-$P/models}/$f"
  [ -f "$src" ] || { echo "no $f: pass the weights dir (no built payload to reuse)" >&2; exit 2; }
  check "$src" "$f"
  cp "$src" "$NEW/models/$f"
done
rsync -a --exclude '__pycache__' --exclude '*.so' --exclude '*.c' --exclude '*.pyx' \
  --exclude '.DS_Store' "$REPO/server/shengji" "$NEW/"
cp "$REPO/fly.toml" "$NEW/fly.toml"
cp "$HERE/offline_bot.py" "$NEW/offline_bot.py"
"$HERE/inputs.sh" record payload "$NEW"
rm -rf "$P"
mv "$NEW" "$P"
du -sh "$HERE/Python.xcframework" "$HERE/site/"* "$P" "$P/models"
echo "payload ready: inputs $("$HERE/inputs.sh" identity "$P")"
