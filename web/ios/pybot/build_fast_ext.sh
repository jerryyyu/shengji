#!/bin/bash
# Cross-compile the four optional Cython extensions of the payload's shengji
# package for iOS (device and simulator), into fast/<sdk>/shengji/...
#   build_fast_ext.sh CYTHON   (a host `cython` 3.x binary)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
CYTHON="${1:?path to cython}"
XC="$HERE/Python.xcframework"
GEN="$HERE/fast/gen"
EXTS="shengji/engine/_fast shengji/ai/_cwv_math shengji/ai/_endgame_fast shengji/train/_pv_fast"
rm -rf "$HERE/fast"; mkdir -p "$GEN"
for e in $EXTS; do
  mkdir -p "$GEN/$(dirname "$e")"
  "$CYTHON" -3 -o "$GEN/$e.c" "$REPO/server/$e.pyx"
done
export IPHONEOS_DEPLOYMENT_TARGET=15.0
for sdk in iphoneos iphonesimulator; do
  if [ $sdk = iphoneos ]; then SLICE=ios-arm64; TGT=arm64-apple-ios15.0
  else SLICE=ios-arm64_x86_64-simulator; TGT=arm64-apple-ios15.0-simulator; fi
  INC="$XC/$SLICE/include/python3.14"
  FW="$XC/$SLICE"
  for e in $EXTS; do
    out="$HERE/fast/$sdk/$e.cpython-314-$sdk.so"
    mkdir -p "$(dirname "$out")"
    xcrun --sdk $sdk clang -target $TGT -O3 -fPIC -shared -Wno-unreachable-code \
      -I"$INC" -F"$FW" -framework Python -undefined error \
      -o "$out" "$GEN/$e.c"
  done
done
rm -rf "$GEN"
find "$HERE/fast" -name "*.so" -exec ls -la {} \;
