#!/bin/bash
# Generate Chinese voice announcement clips via ElevenLabs (sag CLI).
# Usage: source ../.env (or export ELEVENLABS_API_KEY) then run from server/.
# Idempotent: existing non-empty mp3s are skipped. ~60 clips, ~400 chars total.
set -euo pipefail

OUT="$(dirname "$0")/../../web/public/sounds"
mkdir -p "$OUT"
VOICE="${SHENGJI_VOICE:-0H4ruoQ81Ei2FCwjW5j1}"   # Susan - Warm Narrator (Beijing Mandarin)
ARGS=(--model-id eleven_multilingual_v2 --seed 42 --lang zh -v "$VOICE")

say_clip() {  # $1 = filename (no ext), $2 = text
  local f="$OUT/$1.mp3"
  if [ -s "$f" ]; then echo "skip $1"; return; fi
  echo "gen  $1  <- $2"
  sag speak "${ARGS[@]}" -o "$f" "$2"
}

declare -a SUITS=("S:黑桃" "H:红桃" "D:方片" "C:梅花")
declare -a RANKS=("2:二" "3:三" "4:四" "5:五" "6:六" "7:七" "8:八" "9:九" "10:十" "J:钩" "Q:圈" "K:K" "A:尖儿")

for s in "${SUITS[@]}"; do
  sc="${s%%:*}"; sn="${s#*:}"
  for r in "${RANKS[@]}"; do
    rc="${r%%:*}"; rn="${r#*:}"
    say_clip "$sc$rc" "$sn$rn"
  done
done
say_clip "BJ" "大王"
say_clip "LJ" "小王"
say_clip "pair" "一对"
say_clip "nt" "无主"
say_clip "throw" "甩牌"
# bi uses the expressive v3 model for a sharp falling-tone exclamation
if [ ! -s "$OUT/bi.mp3" ]; then
  echo "gen  bi  <- 毙！ (eleven_v3)"
  sag speak --model-id eleven_v3 --lang zh -v "$VOICE" -o "$OUT/bi.mp3" "毙！"
fi

echo "done: $(ls "$OUT" | wc -l | tr -d ' ') clips in $OUT"
