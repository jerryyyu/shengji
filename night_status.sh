#!/bin/bash
# Overnight RL progress at a glance. Run:  ./night_status.sh
# (or live:  watch -n 60 ./night_status.sh)
S="/private/tmp/claude-501/-Users-jerryyu-Projects/f51b8952-345f-4b62-a331-815143896dad/scratchpad"

hdr() { printf "\n\033[1m== %s ==\033[0m\n" "$1"; }

hdr "v6 distillation (12 epochs -> gates)  [$(date '+%H:%M')]"
if [ -f "$S/distill_v6.log" ]; then
  DONE=$(grep -c "^epoch" "$S/distill_v6.log")
  echo "epochs done: $DONE/12 (each ~10-15 min)"
  grep "^epoch" "$S/distill_v6.log" | tail -3
  grep "GATE" "$S/distill_v6.log"
  # freshness: has the log moved in the last 20 min?
  AGE=$(( $(date +%s) - $(stat -f %m "$S/distill_v6.log") ))
  [ $AGE -gt 1200 ] && echo "!! log quiet for $((AGE/60)) min (epoch in progress or stalled)"
else
  echo "(log not found)"
fi

hdr "Elo tournament (rl-v5 + mc-v5roll + anchors, 10 pairings)"
if [ -f "$S/elo_v5.log" ]; then
  PAIR=$(grep -c " vs " "$S/elo_v5.log")
  echo "pairings done: $PAIR/10 (mc-v5roll ones are slow, ~25 min each)"
  grep " vs " "$S/elo_v5.log" | tail -4
  grep -A8 "Elo ratings" "$S/elo_v5.log"
else
  echo "(log not found)"
fi

hdr "reference numbers"
echo "gates for v6: >=60% vs Smart, >=45% vs MC | v5 was 42%/38%"
echo "current Elo champ: mc 1137 | v5-hybrid preview: 55% vs mc (n=40)"
