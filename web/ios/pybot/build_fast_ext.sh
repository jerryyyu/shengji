#!/bin/bash
# Cross-compile the four Cython extensions of the shengji package for iOS
# (device and simulator), into fast/<sdk>/shengji/...
#   build_fast_ext.sh CYTHON [--force]   (CYTHON: a host `cython` 3.x binary)
# The output records its inputs (inputs.sh); while they are unchanged the
# build is skipped, and the Xcode phase refuses an output whose .pyx sources,
# this script or the Python headers have changed since.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
CYTHON="${1:?path to cython}"
XC="$HERE/Python.xcframework"
[ -d "$XC" ] || { echo "no Python.xcframework: run build_payload.sh first" >&2; exit 2; }
if [ "${2:-}" != "--force" ] && [ -d "$HERE/fast" ] && "$HERE/inputs.sh" check fast "$HERE/fast" 2>/dev/null; then
  echo "compiled engine up to date: inputs $("$HERE/inputs.sh" identity "$HERE/fast")"
  exit 0
fi
NEW="$HERE/fast.new"
GEN="$NEW/gen"
EXTS="shengji/engine/_fast shengji/ai/_cwv_math shengji/ai/_endgame_fast shengji/train/_pv_fast"
rm -rf "$NEW"; mkdir -p "$GEN"
for e in $EXTS; do
  mkdir -p "$GEN/$(dirname "$e")"
  "$CYTHON" -3 -o "$GEN/$e.c" "$REPO/server/$e.pyx"
done
# Python.xcframework wraps every extension in a framework whose Info.plist
# declares MinimumOSVersion 13.0; App Store validation rejects a binary built
# for a later minimum than its framework declares.
export IPHONEOS_DEPLOYMENT_TARGET=13.0
for sdk in iphoneos iphonesimulator; do
  if [ $sdk = iphoneos ]; then SLICE=ios-arm64; TGT=arm64-apple-ios13.0
  else SLICE=ios-arm64_x86_64-simulator; TGT=arm64-apple-ios13.0-simulator; fi
  INC="$XC/$SLICE/include/python3.14"
  FW="$XC/$SLICE"
  for e in $EXTS; do
    out="$NEW/$sdk/$e.cpython-314-$sdk.so"
    mkdir -p "$(dirname "$out")"
    xcrun --sdk $sdk clang -target $TGT -O3 -fPIC -shared -Wno-unreachable-code \
      -I"$INC" -F"$FW" -framework Python -undefined error \
      -o "$out" "$GEN/$e.c"
  done
done
rm -rf "$GEN"
"$HERE/inputs.sh" record fast "$NEW"
"$CYTHON" --version > "$NEW/CYTHON_VERSION" 2>&1
rm -rf "$HERE/fast"
mv "$NEW" "$HERE/fast"
find "$HERE/fast" -name "*.so" -exec ls -la {} \;
echo "compiled engine ready: inputs $("$HERE/inputs.sh" identity "$HERE/fast")"
