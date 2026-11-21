#!/bin/bash
# Xcode "Check flavor (nearby)" build phase: an App Store binary never carries
# Play nearby. The Release configuration (what Product > Archive builds for the
# App Store) stops here when the Swift flags define SHENGJI_NEARBY* or the app's
# Info.plist asks for the local network (NSLocalNetworkUsageDescription,
# NSBonjourServices): App Review has not covered either. The Beta configuration
# (TestFlight internal testing only) must carry all of them, so a Beta archive
# without nearby is refused too. Debug passes: a device test may define the
# flags on the xcodebuild command line.
# Reads Xcode's CONFIGURATION, SWIFT_ACTIVE_COMPILATION_CONDITIONS,
# OTHER_SWIFT_FLAGS, GCC_PREPROCESSOR_DEFINITIONS, PROJECT_DIR and
# INFOPLIST_FILE, and the processed TARGET_BUILD_DIR/INFOPLIST_PATH when it is
# already there (declaring it as an input would make a dependency cycle).
set -euo pipefail
NEARBY_KEYS="NSLocalNetworkUsageDescription NSBonjourServices"
FLAGS=" ${SWIFT_ACTIVE_COMPILATION_CONDITIONS:-} ${OTHER_SWIFT_FLAGS:-} ${GCC_PREPROCESSOR_DEFINITIONS:-} "

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
    if [ "$nearby_flag" = yes ]; then
      named=$(set -f; printf '%s\n' $FLAGS | grep SHENGJI_NEARBY | tr '\n' ' ')
      echo "error: $CONFIGURATION defines SHENGJI_NEARBY (${named% }): an App Store build has no nearby play"
      exit 1
    fi
    for f in "${PLISTS[@]}"; do
      for k in $NEARBY_KEYS; do
        if plist_has "$k" "$f"; then
          echo "error: $CONFIGURATION Info.plist $f has $k: an App Store build never asks for the local network"
          exit 1
        fi
      done
    done
    echo "flavor: $CONFIGURATION (App Store), nearby off" ;;
esac
