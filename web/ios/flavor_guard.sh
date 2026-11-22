#!/bin/bash
# Xcode "Check flavor (nearby)" build phase: which test tools each flavor may
# carry. The Release configuration (what Product > Archive builds for the App
# Store) has Play nearby and none of the test tools: its Swift active
# compilation conditions must name SHENGJI_NEARBY; it defines no other
# nearby flag (SHENGJI_NEARBY_BETA, _DEV and _SPIKE compile the soak's chaos,
# its log file, the device test's extras and the offline autoplay) and no
# DEBUG; its Info.plist must ask for the local network
# (NSLocalNetworkUsageDescription, NSBonjourServices); and its bundled page
# (App/public, built by `npm run ios:sync:appstore`) must carry none of the
# soak's, log upload's, hidden switch's, autoplay's or spike's markers, nor
# the spike's test page or bundle. The Beta configuration (TestFlight
# internal testing only) must carry nearby and its plist keys. Debug passes:
# a device test may define the flags on the xcodebuild command line.
# Reads Xcode's CONFIGURATION, SWIFT_ACTIVE_COMPILATION_CONDITIONS,
# OTHER_SWIFT_FLAGS, GCC_PREPROCESSOR_DEFINITIONS, PROJECT_DIR and
# INFOPLIST_FILE, and the processed TARGET_BUILD_DIR/INFOPLIST_PATH when it is
# already there (declaring it as an input would make a dependency cycle).
set -euo pipefail
NEARBY_KEYS="NSLocalNetworkUsageDescription NSBonjourServices"
# Strings only the page's test tools carry (the soak and its chaos and
# coverage, the log file and its upload, the hidden switch, the offline
# autoplay); test_ios_flavor_guard.py checks each one is still in their source.
SOAK_MARKERS=("shengji.nearbySoak" "debugChaos" "debugLogFile" "/api/nearby-log" "coverage health"
              "Copy soak summary" "__shengjiOfflineAutoplay" "spikeBench")
# The spike's test page and bundle (vite.config.ts NEARBY_SPIKE), by name, so
# a stale one left in App/public by an earlier build is caught too.
SPIKE_NAMES=(-name 'nearby-spike*' -o -name 'spike-*' -o -name 'spike.*')
SOAK_ARGS=()
for m in "${SOAK_MARKERS[@]}"; do SOAK_ARGS+=(-e "$m"); done
FLAGS=" ${SWIFT_ACTIVE_COMPILATION_CONDITIONS:-} ${OTHER_SWIFT_FLAGS:-} ${GCC_PREPROCESSOR_DEFINITIONS:-} "
SWIFT_CONDITIONS=" $(set -f; printf '%s\n' ${SWIFT_ACTIVE_COMPILATION_CONDITIONS:-} | tr -d '"' | tr '\n' ' ')"

plist_ok() {  # plist_ok FILE: FILE is a readable, parseable (XML or binary) plist
  if [ -x /usr/bin/plutil ]; then
    /usr/bin/plutil -lint -s "$1" >/dev/null 2>&1
  else
    python3 -c 'import plistlib, sys; plistlib.load(open(sys.argv[1], "rb"))' "$1" >/dev/null 2>&1
  fi
}

plist_has() {  # plist_has KEY FILE: the top-level KEY is in the plist (FILE already passed plist_ok)
  if [ -x /usr/libexec/PlistBuddy ]; then
    /usr/libexec/PlistBuddy -c "Print :$1" "$2" >/dev/null 2>&1
  else
    python3 -c 'import plistlib, sys; sys.exit(0 if sys.argv[1] in plistlib.load(open(sys.argv[2], "rb")) else 1)' "$1" "$2"
  fi
}

PLISTS=("$PROJECT_DIR/$INFOPLIST_FILE")
BUILT="${TARGET_BUILD_DIR:-}/${INFOPLIST_PATH:-}"
[ -z "${INFOPLIST_PATH:-}" ] || [ ! -f "$BUILT" ] || PLISTS+=("$BUILT")
[ -f "${PLISTS[0]}" ] || { echo "error: no Info.plist at ${PLISTS[0]}"; exit 1; }
for f in "${PLISTS[@]}"; do
  plist_ok "$f" || { echo "error: $f is not a readable plist"; exit 1; }
done

nearby_flag=no
case "$FLAGS" in *SHENGJI_NEARBY*) nearby_flag=yes ;; esac

case "${CONFIGURATION:?}" in
  Debug) exit 0 ;;
  Beta)
    [ "$nearby_flag" = yes ] || { echo "error: the Beta configuration must define SHENGJI_NEARBY"; exit 1; }
    for f in "${PLISTS[@]}"; do
      for k in $NEARBY_KEYS; do
        plist_has "$k" "$f" || { echo "error: Beta Info.plist $f has no $k"; exit 1; }
      done
    done
    echo "flavor: Beta (TestFlight internal testing only), nearby on" ;;
  *)
    # every defined name, from "-D" "X", -DX, X=1 or a bare condition
    names=" $(set -f; printf '%s\n' $FLAGS | tr -d '"' | sed -e 's/^-D//' -e 's/=.*//' | grep -v '^-' | tr '\n' ' ')"
    # the Swift condition itself: a C define (GCC_PREPROCESSOR_DEFINITIONS)
    # or another flag leaves the Swift nearby code out
    case "$SWIFT_CONDITIONS" in *" SHENGJI_NEARBY "*) ;; *)
      echo "error: $CONFIGURATION has no SHENGJI_NEARBY in SWIFT_ACTIVE_COMPILATION_CONDITIONS: the App Store build has Play nearby"
      exit 1 ;;
    esac
    extra=$(set -f; printf '%s\n' $names | grep -E '^(SHENGJI_NEARBY_.*|DEBUG)$' | tr '\n' ' ' || true)
    if [ -n "$extra" ]; then
      echo "error: $CONFIGURATION defines ${extra% }: an App Store build has none of the test tools"
      exit 1
    fi
    for f in "${PLISTS[@]}"; do
      for k in $NEARBY_KEYS; do
        plist_has "$k" "$f" || { echo "error: $CONFIGURATION Info.plist $f has no $k: nearby play needs it"; exit 1; }
      done
    done
    page="$PROJECT_DIR/App/public"
    [ -f "$page/index.html" ] || { echo "error: no bundled page at $page (npm run ios:sync:appstore)"; exit 1; }
    spike=$(find "$page" \( "${SPIKE_NAMES[@]}" \) -print) || { echo "error: could not read the bundled page at $page"; exit 1; }
    if [ -n "$spike" ]; then
      echo "error: the bundled page carries the nearby spike (rebuild with npm run ios:sync:appstore):"
      printf '%s\n' "$spike" | sed 's/^/  /'
      exit 1
    fi
    rc=0
    found=$(grep -r -l -F "${SOAK_ARGS[@]}" "$page") || rc=$?
    [ "$rc" -le 1 ] || { echo "error: could not read the bundled page at $page"; exit 1; }
    if [ "$rc" -eq 0 ]; then
      echo "error: the bundled page carries test tools (rebuild with npm run ios:sync:appstore):"
      printf '%s\n' "$found" | sed 's/^/  /'
      exit 1
    fi
    echo "flavor: $CONFIGURATION (App Store), nearby on, no test tools" ;;
esac
