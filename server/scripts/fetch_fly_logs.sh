#!/bin/bash
# Atomically refresh the local, ignored production-log cache from Fly.
# Usage: ./server/scripts/fetch_fly_logs.sh   (from any directory)
set -euo pipefail

default_repo_root=$(cd "$(dirname "$0")/../.." && pwd)
repo_root=${SHENGJI_FETCH_REPO_ROOT:-$default_repo_root}
test -d "$repo_root/server/shengji"
dest_dir="$repo_root/logs"
snapshot_id=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$dest_dir"
stage_dir=$(mktemp -d "$dest_dir/.fly-fetch.XXXXXX")
backup_dir="$dest_dir/archive/pre-refresh-$snapshot_id"
manifest_dir="$dest_dir/manifests"
cleanup() { rm -rf "$stage_dir"; }
trap cleanup EXIT

remote_files=$(fly ssh console -a shengji -C "ls -1 /data/logs" \
  2>/dev/null | tr -d '\r')
fetched=0
changed=0
unchanged=0

while IFS= read -r file_name; do
  case "$file_name" in
    *.jsonl) ;;
    *) continue ;;
  esac
  case "$file_name" in
    */*|.*) echo "refuse unsafe remote filename: $file_name" >&2; exit 1 ;;
  esac

  staged="$stage_dir/$file_name"
  echo "fetch $file_name"
  fly ssh sftp get "/data/logs/$file_name" "$staged" -a shengji >/dev/null
  test -s "$staged"
  jq -e -s 'length > 0' "$staged" >/dev/null
  fetched=$((fetched + 1))
done <<< "$remote_files"

if test "$fetched" -eq 0; then
  echo "refuse empty Fly log snapshot" >&2
  exit 1
fi

# Publish only after the complete remote set has downloaded and validated.
# Each file replacement is atomic on the local filesystem; replaced bytes are
# retained so even a later local I/O failure is recoverable.
while IFS= read -r file_name; do
  case "$file_name" in
    *.jsonl) ;;
    *) continue ;;
  esac
  staged="$stage_dir/$file_name"
  current="$dest_dir/$file_name"
  if test -f "$current" && cmp -s "$staged" "$current"; then
    rm "$staged"
    unchanged=$((unchanged + 1))
    continue
  fi
  if test -f "$current"; then
    mkdir -p "$backup_dir"
    cp -p "$current" "$backup_dir/$file_name"
  fi
  mv "$staged" "$current"
  changed=$((changed + 1))
done <<< "$remote_files"

mkdir -p "$manifest_dir"
manifest="$manifest_dir/fly-$snapshot_id.sha256"
(
  cd "$dest_dir"
  while IFS= read -r file_name; do
    case "$file_name" in
      *.jsonl) shasum -a 256 "$file_name" ;;
    esac
  done <<< "$remote_files"
) > "$manifest"

echo "snapshot=$snapshot_id fetched=$fetched changed=$changed unchanged=$unchanged"
echo "manifest=$manifest"
if test -d "$backup_dir"; then
  echo "replaced files preserved at $backup_dir"
fi
