#!/bin/bash
# Overnight RL progress at a glance. Run:  ./night_status.sh
# (or live:  watch -n 60 ./night_status.sh)
S="/private/tmp/claude-501/-Users-jerryyu-Projects/f51b8952-345f-4b62-a331-815143896dad/scratchpad"

hdr() { printf "\n\033[1m== %s ==\033[0m\n" "$1"; }
fresh() {  # warn if a log has gone quiet
  local f="$1" limit="$2"
  [ -f "$f" ] || { echo "(log not found)"; return 1; }
  local age=$(( $(date +%s) - $(stat -f %m "$f") ))
  [ "$age" -gt "$limit" ] && echo "!! log quiet for $((age/60)) min"
  return 0
}

hdr "N=30 low-noise teacher data (24k rounds, ~8-9h)  [$(date '+%H:%M')]"
if fresh "$S/distill_gen_n30.log" 2400; then
  tail -1 "$S/distill_gen_n30.log"
  N=$(ls /Users/jerryyu/Projects/shengji/server/rl_data/distill_n30/*.npz 2>/dev/null | wc -l | tr -d ' ')
  echo "shards flushed: $N"
fi

hdr "v6 Elo pool rating (4 pairings, ~40 min)"
if [ -f "$S/elo_v6.log" ]; then
  grep " vs " "$S/elo_v6.log"
  grep -A6 "Elo ratings" "$S/elo_v6.log"
  [ -z "$(grep 'Elo ratings' "$S/elo_v6.log")" ] && echo "(pairings in progress)"
else
  echo "(not started)"
fi

hdr "final results from earlier tonight"
echo "Elo: mc 1141 | rl-v5 1088 | mc-v5roll 1074 | smart 1055 | heuristic 1000"
echo "v6 gates: 51% vs Smart, 41% vs MC (strongest standalone net; unrated -> see above)"
echo "hybrid verdict: 55% preview reversed to 37% at n=60 — full-net rollouts dead end"
