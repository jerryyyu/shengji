#!/usr/bin/env bash
# Builds the default link-preview clip (web/public/og/preview.mp4 and
# preview.jpg) from scene.html: render.mjs seeks the scene's GSAP timeline
# frame by frame at 2x, and ffmpeg encodes the frames at 60 fps.
#
#   NODE_PATH=<node_modules with playwright> web/scripts/og-preview/encode_scene.sh
#
# Needs ffmpeg, node and Playwright (CHROMIUM_PATH optional). scene.html loads
# GSAP from cdnjs, so rendering needs network access.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
WORK="${WORK:-/tmp/og-scene}"
OUT="${OUT:-$ROOT/web/public/og}"

rm -rf "$WORK"
node "$HERE/render.mjs" --out "$WORK" --fps 60
mkdir -p "$OUT"
ffmpeg -v error -y -framerate 60 -i "$WORK/f%05d.png" \
  -vf "scale=1200:630:flags=lanczos:out_color_matrix=bt709:out_range=tv,format=yuv420p" \
  -an -c:v libx264 -preset veryslow -crf "${CRF:-20}" -profile:v high -pix_fmt yuv420p \
  -color_range tv -colorspace bt709 -color_primaries bt709 -color_trc bt709 \
  -tag:v avc1 -movflags +faststart "$OUT/preview.mp4"
ffmpeg -v error -y -i "$WORK/poster.png" -vf "scale=1200:630:flags=lanczos" -q:v 2 "$OUT/preview.jpg"
# Contact sheet for reviewing the motion: one frame per second.
ffmpeg -v error -y -i "$OUT/preview.mp4" -vf "fps=1,scale=600:-1,tile=3x4" -frames:v 1 -q:v 3 "$WORK/preview-sheet.jpg"
ls -la "$OUT/preview.mp4" "$OUT/preview.jpg" "$WORK/preview-sheet.jpg"
