#!/bin/bash
# Assemble the bundled Python payload for the iOS pybot spike.
#
#   web/ios/pybot/build_payload.sh WEIGHTS_DIR [DL_DIR]
#
# WEIGHTS_DIR holds the four release-52 .npz files named in fly.toml; each is
# checked against fly.toml's sha256 (or MANIFEST.sha256) before it is copied.
# DL_DIR (default web/ios/pybot/dl) receives the downloads, verified against
# MANIFEST.sha256.  Output (all gitignored):
#   web/ios/pybot/Python.xcframework           BeeWare Python-Apple-support 3.14-b14
#   web/ios/pybot/payload/                     shengji package + fly.toml + offline_bot.py + models/
#   web/ios/pybot/site/iphoneos|iphonesimulator numpy unpacked from the iOS wheels
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
WEIGHTS="${1:?weights dir}"
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

rm -rf "$HERE/Python.xcframework" "$HERE/payload" "$HERE/site"
X=$(mktemp -d); tar -xzf "$DL/Python-3.14-iOS-support.b14.tar.gz" -C "$X"
mv "$X/Python.xcframework" "$HERE/Python.xcframework"; rm -rf "$X"

for p in iphoneos iphonesimulator; do
  mkdir -p "$HERE/site/$p"
  (cd "$HERE/site/$p" && unzip -q "$DL/numpy-2.5.2.post1-cp314-cp314-ios_13_0_arm64_$p.whl")
done

P="$HERE/payload"
mkdir -p "$P/models"
rsync -a --exclude '__pycache__' --exclude '*.so' --exclude '*.c' --exclude '*.pyx' \
  "$REPO/server/shengji" "$P/"
cp "$REPO/fly.toml" "$P/fly.toml"
cp "$HERE/offline_bot.py" "$P/offline_bot.py"
for f in g3a-e04-f4f4127e.npz p0-ft1-1fa201b2.npz b1a-028131a0.npz js-m1-0d17fd03.npz; do
  check "$WEIGHTS/$f" "$f"
  cp "$WEIGHTS/$f" "$P/models/$f"
done
# compiled engine extensions (optional): build_fast_ext.sh drops them in fast/<sdk>/
du -sh "$HERE/Python.xcframework" "$HERE/site/"* "$P" "$P/models"
echo "payload ready"
