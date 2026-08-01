#!/bin/bash
# Pull all game logs from the Fly volume into local logs/.
# Usage: ./server/scripts/fetch_fly_logs.sh   (from the repo root)
set -euo pipefail
mkdir -p logs
cd logs
for f in $(fly ssh console -a shengji -C "ls /data/logs" 2>/dev/null | tr -d '\r'); do
  case "$f" in
    *.jsonl) echo "fetch $f"; fly ssh sftp get "/data/logs/$f" -a shengji >/dev/null || true ;;
  esac
done
ls -la .
