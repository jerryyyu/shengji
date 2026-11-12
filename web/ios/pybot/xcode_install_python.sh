#!/bin/bash
# Xcode "Install Python (pybot)" build phase: copies the stdlib, the bundled
# payload and the SDK's numpy into App.app/python, then turns every .so into a
# signed framework (Python-Apple-support's utils.sh).  Skips quietly when the
# payload has not been built (build_payload.sh), so the app still builds
# without the spike.
set -euo pipefail
PYBOT="$PROJECT_DIR/../pybot"
if [ ! -d "$PYBOT/Python.xcframework" ] || [ ! -d "$PYBOT/payload" ]; then
  echo "warning: pybot payload not built; run web/ios/pybot/build_payload.sh"
  exit 0
fi
case "$EFFECTIVE_PLATFORM_NAME" in
  -iphonesimulator) SITE=iphonesimulator ;;
  -iphoneos) SITE=iphoneos ;;
  *) echo "unsupported platform $EFFECTIVE_PLATFORM_NAME"; exit 1 ;;
esac
# A simulator build with signing off still needs ad-hoc signatures on arm64.
export EXPANDED_CODE_SIGN_IDENTITY="${EXPANDED_CODE_SIGN_IDENTITY:--}"
[ -n "$EXPANDED_CODE_SIGN_IDENTITY" ] || EXPANDED_CODE_SIGN_IDENTITY=-
set +u  # utils.sh reads unset Xcode variables
export EXPANDED_CODE_SIGN_IDENTITY_NAME="${EXPANDED_CODE_SIGN_IDENTITY_NAME:-ad-hoc}"
source "$PYBOT/Python.xcframework/build/utils.sh"
# utils.sh resolves the xcframework relative to PROJECT_DIR
REL="../pybot/Python.xcframework"
install_stdlib "$REL"
DEST="$CODESIGNING_FOLDER_PATH/python"
rsync -a --delete "$PYBOT/payload/" "$DEST/app/"
cp "$PYBOT/offline_bot.py" "$DEST/app/offline_bot.py"  # the entry module is source, not payload
rsync -a --delete "$PYBOT/site/$SITE/" "$DEST/app_packages/"
if [ -d "$PYBOT/fast/$SITE" ]; then
  rsync -a "$PYBOT/fast/$SITE/" "$DEST/app/"
fi
PYVER=$(ls -1 "$DEST/lib" | grep -E "^python3\.[0-9]+$")
process_dylibs "$REL" "python/lib/$PYVER/lib-dynload"
process_dylibs "$REL" python/app_packages
process_dylibs "$REL" python/app
