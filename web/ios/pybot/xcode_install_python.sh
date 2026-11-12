#!/bin/bash
# Xcode "Install Python (pybot)" build phase: copies the Python stdlib, the
# bot payload (shengji package, fly.toml, weights), offline_bot.py and the
# SDK's numpy into App.app/python, then turns every .so into a signed framework
# (Python-Apple-support's utils.sh), the layout the App Store accepts.
# build_payload.sh (and build_fast_ext.sh for the compiled engine) must have
# run first; the build stops here with the command to run if they have not.
set -euo pipefail
PYBOT="$PROJECT_DIR/../pybot"
if [ ! -d "$PYBOT/Python.xcframework" ] || [ ! -d "$PYBOT/payload" ]; then
  echo "error: the offline bot payload is not built; run web/ios/pybot/build_payload.sh <weights dir> (its header lists the steps)"
  exit 1
fi
case "$EFFECTIVE_PLATFORM_NAME" in
  -iphonesimulator) SITE=iphonesimulator ;;
  -iphoneos) SITE=iphoneos ;;
  *) echo "error: unsupported platform $EFFECTIVE_PLATFORM_NAME"; exit 1 ;;
esac
if [ ! -d "$PYBOT/fast/$SITE" ]; then
  echo "error: the compiled engine for $SITE is not built; run web/ios/pybot/build_fast_ext.sh <cython>"
  exit 1
fi
# A simulator build with signing off still needs ad-hoc signatures on arm64.
export EXPANDED_CODE_SIGN_IDENTITY="${EXPANDED_CODE_SIGN_IDENTITY:--}"
[ -n "$EXPANDED_CODE_SIGN_IDENTITY" ] || EXPANDED_CODE_SIGN_IDENTITY=-
set +u  # utils.sh reads unset Xcode variables
export EXPANDED_CODE_SIGN_IDENTITY_NAME="${EXPANDED_CODE_SIGN_IDENTITY_NAME:-ad-hoc}"
source "$PYBOT/Python.xcframework/build/utils.sh"
set -u
# utils.sh resolves the xcframework relative to PROJECT_DIR
REL="../pybot/Python.xcframework"
install_stdlib "$REL"
DEST="$CODESIGNING_FOLDER_PATH/python"
PYVER=$(ls -1 "$DEST/lib" | grep -E "^python3\.[0-9]+$")
# the stdlib's own tests and the GUI and installer packages are never imported
for d in test idlelib tkinter turtledemo ensurepip; do
  rm -rf "$DEST/lib/$PYVER/$d"
done
rsync -a --delete --exclude '__pycache__' "$PYBOT/payload/" "$DEST/app/"
cp "$PYBOT/offline_bot.py" "$DEST/app/offline_bot.py"
rsync -a --delete --exclude '__pycache__' --exclude 'tests/' "$PYBOT/site/$SITE/" "$DEST/app_packages/"
rsync -a "$PYBOT/fast/$SITE/" "$DEST/app/"
process_dylibs "$REL" "python/lib/$PYVER/lib-dynload"
process_dylibs "$REL" python/app_packages
process_dylibs "$REL" python/app
