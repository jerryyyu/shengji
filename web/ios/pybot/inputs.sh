#!/bin/bash
# The inputs each built part of the app's offline bot was made from, so a part
# built from older sources is never packaged.
#
#   inputs.sh list   payload|fast        print "sha256  input" lines, sorted
#   inputs.sh record payload|fast DIR    write them to DIR/INPUTS.sha256
#   inputs.sh check  payload|fast DIR    exit 0 when DIR/INPUTS.sha256 lists exactly
#                                        the current inputs; else print what changed
#                                        and exit 1
#   inputs.sh identity DIR...            one digest over the recorded lists (and any
#                                        plain files given), for the build log
#
# payload: every file build_payload.sh copies from server/shengji, and fly.toml
#   (whose sha256 pins also pin the weights, which init() checks on the device).
# fast: the Cython sources build_fast_ext.sh compiles (and the .pxd files they
#   may cimport), that script itself, and the Python headers and xcframework
#   description of both slices (the ABI the extensions are compiled against).
#
# PYBOT_REPO and PYBOT_XCFRAMEWORK override the checkout and the xcframework.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="${PYBOT_REPO:-$(cd "$HERE/../../.." && pwd)}"
XC="${PYBOT_XCFRAMEWORK:-$HERE/Python.xcframework}"
FAST_EXTS="shengji/engine/_fast.pyx shengji/ai/_cwv_math.pyx shengji/ai/_endgame_fast.pyx shengji/train/_pv_fast.pyx"

sha() {  # sha FILE -> hex digest
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

line() {  # line PATH LABEL
  [ -f "$1" ] || { echo "missing input: $2" >&2; exit 2; }
  printf '%s  %s\n' "$(sha "$1")" "$2"
}

list_payload() {
  (cd "$REPO/server" && find shengji -type f ! -path '*/__pycache__/*' \
     ! -name '*.so' ! -name '*.c' ! -name '*.pyx' ! -name '.DS_Store' | LC_ALL=C sort) |
    while IFS= read -r f; do line "$REPO/server/$f" "server/$f"; done
  line "$REPO/fly.toml" fly.toml
}

list_fast() {
  local f slice
  for f in $FAST_EXTS; do line "$REPO/server/$f" "server/$f"; done
  (cd "$REPO/server" && find shengji -type f -name '*.pxd' | LC_ALL=C sort) |
    while IFS= read -r f; do line "$REPO/server/$f" "server/$f"; done
  line "$HERE/build_fast_ext.sh" web/ios/pybot/build_fast_ext.sh
  line "$XC/Info.plist" Python.xcframework/Info.plist
  for slice in ios-arm64 ios-arm64_x86_64-simulator; do
    for f in patchlevel.h pyconfig.h; do
      line "$XC/$slice/include/python3.14/$f" "Python.xcframework/$slice/include/python3.14/$f"
    done
  done
}

list() {
  case "$1" in
    payload) list_payload ;;
    fast) list_fast ;;
    *) echo "unknown part $1 (payload or fast)" >&2; exit 2 ;;
  esac | LC_ALL=C sort -k2
}

cmd="${1:?usage: inputs.sh list|record|check|identity ...}"
case "$cmd" in
  list) list "${2:?part}" ;;
  record)
    out="$(list "${2:?part}")"
    printf '%s\n' "$out" > "${3:?dir}/INPUTS.sha256" ;;
  check)
    part="${2:?part}"; dir="${3:?dir}"
    if [ ! -f "$dir/INPUTS.sha256" ]; then
      echo "error: $dir has no INPUTS.sha256: it predates input tracking; rebuild it" >&2; exit 1
    fi
    now="$(list "$part")"
    if [ "$now" != "$(cat "$dir/INPUTS.sha256")" ]; then
      echo "error: the built $part is stale; its inputs changed since it was built:" >&2
      diff <(cat "$dir/INPUTS.sha256") <(printf '%s\n' "$now") | grep '^[<>]' | sed 's/^</  built:  /; s/^>/  now:    /' >&2 || true
      exit 1
    fi ;;
  identity)
    shift
    for p in "$@"; do
      if [ -d "$p" ]; then sha "$p/INPUTS.sha256"; else sha "$p"; fi
    done | (if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi) | cut -d' ' -f1 ;;
  *) echo "unknown command $cmd" >&2; exit 2 ;;
esac
