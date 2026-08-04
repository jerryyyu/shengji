#!/bin/bash
# Pull all game logs from the Fly volume into local logs/.
# Usage: ./server/scripts/fetch_fly_logs.sh   (from the repo root)
set -euo pipefail
# Write to the REPO-ROOT logs dir regardless of cwd: run from server/ this
# script used to create server/logs/, so prod games never reached the corpus
# the shard builders read (found by the 2026-08-04 maintenance pass).
cd "$(dirname "$0")/../.." || exit 1
mkdir -p logs
cd logs
for f in $(fly ssh console -a shengji -C "ls /data/logs" 2>/dev/null | tr -d '\r'); do
  case "$f" in
    *.jsonl) echo "fetch $f"; fly ssh sftp get "/data/logs/$f" -a shengji >/dev/null || true ;;
  esac
done
ls -la .
