#!/bin/bash
# Status of the distributed Elo pool (Air workers + any local chunks).
# Usage: ./scripts/pool_status.sh          (from server/, on the mini)
AIR_DIR='~/Projects/shengji-compute/server'
echo "== Air tournament workers =="
ssh -o BatchMode=yes -o ConnectTimeout=8 air "
  cd $AIR_DIR 2>/dev/null || { echo '(compute dir missing)'; exit 1; }
  n=\$(grep -h '^PAIR' pool_*.log 2>/dev/null | wc -l | tr -d ' ')
  echo \"pairings done: \$n / 24\"
  grep -h '^PAIR' pool_*.log 2>/dev/null | tail -6
  alive=\$(pgrep -f 'pool_20260802.py' | wc -l | tr -d ' ')
  echo \"worker processes alive: \$alive\"
" 2>/dev/null || echo "Air unreachable (asleep / off tailnet / SSH off)"
