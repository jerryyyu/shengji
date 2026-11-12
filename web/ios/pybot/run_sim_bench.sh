#!/bin/bash
# Run one benchmark launch in a booted simulator and copy its results out.
#   run_sim_bench.sh SIM_UDID WORLDS ROUNDS pure|fast OUT_DIR
set -euo pipefail
U=$1; W=$2; R=$3; MODE=$4; OUT=$5
TAG="w$W-$MODE"
C=$(xcrun simctl get_app_container "$U" com.jerryyu.shengji data)
rm -f "$C/Documents/pybot/summary-$TAG.json" "$C/Documents/pybot/bench-$TAG.json"
ARGS=(-pybot-bench "$W" "$R"); [ "$MODE" = fast ] && ARGS+=(fast)
xcrun simctl launch --terminate-running-process "$U" com.jerryyu.shengji "${ARGS[@]}"
for _ in $(seq 1 1800); do
  [ -f "$C/Documents/pybot/summary-$TAG.json" ] && break
  sleep 2
done
mkdir -p "$OUT"
cp "$C/Documents/pybot/summary-$TAG.json" "$OUT/"
cp "$C/Documents/pybot/bench-$TAG.json" "$OUT/" 2>/dev/null || true
cp "$C/Documents/pybot/pybot_log.txt" "$OUT/pybot_log-$TAG.txt"
xcrun simctl terminate "$U" com.jerryyu.shengji || true
echo "done $TAG"
