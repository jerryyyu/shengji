#!/bin/bash
# s69 staging, revision r2 (run on THIS Mac), in two phases.  Every staged FILE must be absent on the host or already a regular file with
# exactly the bytes being staged (verified by sha256 ON the host; such a file is left as it is and reported "identical"); a target that
# exists with other bytes, or as a symlink or a non-file, refuses before anything is copied.  Every RUN path (status, RELEASE, HOLD, output
# roots) must be absent.  Copies are verified with sha256sum -c ON cloud and made read-only.  Nothing is ever overwritten or removed.  It
# does not build, arm, DRYRUN or release anything.  The tree /root/claude-main-56 is built separately (claude_build_main56_cloud.sh).
#
#   bash stage_s69.sh lane <expected sha256 of claude_s69_cloud.sh>
#       the launcher -> $ROOT/claude_s69_r2_cloud.sh; the harness + hypotheses (the launcher's DUEL / HYP, at their pinned shas) and the
#       --history re-rehearsal wrapper -> $ROOT/claude-s69/ (exploit_duel_s61.py, hypotheses.py, rehearse_s69_cloud.r3.sh).
#   bash stage_s69.sh reader <expected sha256 of claude_s69_cloud.sh>
#       the reader (its TRUSTED launcher sha = that sha) -> $ROOT/claude-s69/s69_read_r3.py; its pinned helpers (reader_lib, validity,
#       row_schema, compare_runs) and the S61 reference beside it; the reservation (naming that sha) -> $ROOT/claude_reservations/s69_r2.json.
#
# r2 (2026-10-26): r1 staged the r1 launcher (e3c25940, no --history) as $ROOT/claude_s69_cloud.sh and its reader / reservation as
# s69_read.py / s69.json; those stay on the host untouched (never armed).  r2 stages under new names and accepts the unchanged files r1
# already staged (the harness, hypotheses, the helpers, the S61 reference) as identical.  r1's script: superseded-r1/stage_s69.sh.
# r3 (2026-10-26, Codex HOLD 1075/6417632636, reader-only): the repaired reader is staged as $ROOT/claude-s69/s69_read_r3.py (r2's
# s69_read_r2.py stays on the host, read-only, unused); the launcher, harness, helpers and reservation are unchanged (identical).
# The host checks run with `bash -s -- <args>` and the script on stdin, so the arguments are the remote shell's positional arguments.
# Test hooks: S69_SSH / S69_SCP (default ssh / scp) and S69_ROOT (default /root) -- never set in production use.
set -u
H=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd) || { echo "REFUSING: cannot resolve the packet dir"; exit 3; }; HOST=shengji-cloud
SSH=${S69_SSH:-ssh}; SCP=${S69_SCP:-scp}; ROOT=${S69_ROOT:-/root}
PHASE=${1:-}; WANT=${2:-}
sha () { shasum -a 256 "$1" | cut -d' ' -f1; }
refuse_targets () {   # refuse_targets PATH...: ON the host, every path must be absent and not a symlink
  "$SSH" "$HOST" bash -s -- "$@" <<'REMOTE' || exit 3
set -u
[ "$#" -ge 1 ] || { echo "REFUSING: no target paths reached the host"; exit 3; }
for p in "$@"; do [ ! -e "$p" ] && [ ! -L "$p" ] || { echo "REFUSING: $p exists or is a symlink on the host"; exit 3; }; done
echo "run paths clear ($# paths): $*"
REMOTE
}
classify () {   # classify SHA PATH SHA PATH ...: ON the host, each PATH absent (prints 'copy PATH') or a regular file with SHA ('identical PATH'); else refuse
  "$SSH" "$HOST" bash -s -- "$@" <<'REMOTE' || exit 3
set -u
[ "$#" -ge 2 ] && [ $(( $# % 2 )) -eq 0 ] || { echo "REFUSING: no (sha, path) pairs reached the host"; exit 3; }
while [ "$#" -gt 0 ]; do
  want=$1; p=$2; shift 2
  if [ ! -e "$p" ] && [ ! -L "$p" ]; then echo "copy $p"
  elif [ -f "$p" ] && [ ! -L "$p" ] && [ "$(sha256sum "$p" | cut -d' ' -f1)" = "$want" ]; then echo "identical $p"
  else echo "REFUSING: $p exists on the host with other bytes, or is not a regular file"; exit 3
  fi
done
REMOTE
}
stage_files () {   # stage_files LABEL SRC DST [SRC DST ...]: classify, copy the absent ones, verify all on the host, make them read-only
  local label=$1; shift
  local pairs=() args=() s d out
  while [ "$#" -gt 0 ]; do pairs+=("$1" "$2"); args+=("$(sha "$1")" "$2"); shift 2; done
  out=$(classify "${args[@]}") || { echo "$out"; exit 3; }
  echo "$out"
  M=$(mktemp) || exit 3; trap 'rm -f "${M:-}"' EXIT   # M global: the EXIT trap runs after this function returns
  set -- "${pairs[@]}"
  while [ "$#" -gt 0 ]; do
    s=$1; d=$2; shift 2
    echo "$(sha "$s")  $d" >> "$M"
    if grep -qxF "copy $d" <<< "$out"; then "$SCP" -q "$s" "$HOST:$d" || exit 3; fi
  done
  "$SCP" -q "$M" "$HOST:$ROOT/claude-s69/STAGED.$label.sha256" || exit 3
  "$SSH" "$HOST" "sha256sum -c $ROOT/claude-s69/STAGED.$label.sha256 && chmod a-w $(cut -d' ' -f3 "$M" | tr '\n' ' ') $ROOT/claude-s69/STAGED.$label.sha256 && echo \"STAGED ok ($label): \$(wc -l < $ROOT/claude-s69/STAGED.$label.sha256) files verified on the host, read-only\"" || exit 3
}
[[ "$WANT" =~ ^[0-9a-f]{64}$ ]] || { echo "usage: bash stage_s69.sh lane|reader <sha256 of claude_s69_cloud.sh>"; exit 3; }
[ -f "$H/claude_s69_cloud.sh" ] && [ "$(sha "$H/claude_s69_cloud.sh")" = "$WANT" ] || { echo "REFUSING: claude_s69_cloud.sh missing or not $WANT"; exit 3; }
grep -q "TO_BE_PINNED;" "$H/claude_s69_cloud.sh" && { echo "REFUSING: the launcher still holds a TO_BE_PINNED pin"; exit 3; }
pin () { sed -n "s/^.*$1=\/root\/claude-s69\/\([^;]*\); $1_SHA=\([0-9a-f]\{64\}\).*/\1 \2/p" "$H/claude_s69_cloud.sh"; }
case "$PHASE" in
  lane)
    read -r dname dsha <<< "$(pin DUEL)"; read -r hname hsha <<< "$(pin HYP)"
    [ "$dname" = exploit_duel_s61.py ] && [ "$(sha "$H/$dname")" = "$dsha" ] || { echo "REFUSING: the launcher's DUEL pin ($dname $dsha) is not $H/exploit_duel_s61.py's sha"; exit 3; }
    [ "$hname" = hypotheses.py ] && [ "$(sha "$H/$hname")" = "$hsha" ] || { echo "REFUSING: the launcher's HYP pin ($hname $hsha) is not $H/hypotheses.py's sha"; exit 3; }
    refuse_targets "$ROOT/claude_s69_screen.status" "$ROOT/claude_s69.RELEASE" "$ROOT/claude_s69.HOLD" "$ROOT/vol-dev-claude-s69-r48-20261026" \
      "$ROOT/claude_s69_rehearsal_r3.status" "$ROOT/vol-rehearsal-claude-s69-r3-20261026" "$ROOT/claude_s69_rehearsal_r3.peak_rss_kb" "$ROOT/claude-s69/STAGED.lane-r2.sha256"
    "$SSH" "$HOST" mkdir -p "$ROOT/claude-s69" || exit 3
    stage_files lane-r2 "$H/claude_s69_cloud.sh" "$ROOT/claude_s69_r2_cloud.sh" "$H/exploit_duel_s61.py" "$ROOT/claude-s69/exploit_duel_s61.py" \
      "$H/hypotheses.py" "$ROOT/claude-s69/hypotheses.py" "$H/rehearse_s69_cloud.sh" "$ROOT/claude-s69/rehearse_s69_cloud.r3.sh"
    echo "NEXT, ON cloud: DRYRUN=1 bash $ROOT/claude_s69_r2_cloud.sh (rc 0 and the names: line); the --history re-rehearsal: nohup setsid bash $ROOT/claude-s69/rehearse_s69_cloud.r3.sh $WANT"
    ;;
  reader)
    grep -q "^TRUSTED = dict(lane=LANE, launcher_sha256=\"$WANT\"" "$H/s69_read.py" || { echo "REFUSING: s69_read.py's TRUSTED launcher_sha256 is not $WANT"; exit 3; }
    grep -q 'reservation="/root/claude_reservations/s69_r2.json")' "$H/s69_read.py" || { echo "REFUSING: s69_read.py's TRUSTED reservation is not s69_r2.json"; exit 3; }
    python3 -c "import json,sys; r=json.load(open('$H/reservation_s69.json')); sys.exit(0 if r['launcher_sha256']=='$WANT' and r['lane']=='s69' and r['reader']=='Claude' and r['reservation_path']=='/root/claude_reservations/s69_r2.json' else 3)" || { echo "REFUSING: reservation_s69.json does not name $WANT / s69_r2.json with reader Claude (run make_reservation.py --force and test_s69_packet.py)"; exit 3; }
    "$SSH" "$HOST" test -d "$ROOT/claude-s69" || { echo "REFUSING: $ROOT/claude-s69 is not staged (run the lane phase first)"; exit 3; }
    refuse_targets "$ROOT/claude-s69/STAGED.reader-r3.sha256"
    "$SSH" "$HOST" mkdir -p "$ROOT/claude_reservations" || exit 3
    stage_files reader-r3 "$H/s69_read.py" "$ROOT/claude-s69/s69_read_r3.py" "$H/reader_lib.py" "$ROOT/claude-s69/reader_lib.py" \
      "$H/validity.py" "$ROOT/claude-s69/validity.py" "$H/row_schema.py" "$ROOT/claude-s69/row_schema.py" "$H/compare_runs.py" "$ROOT/claude-s69/compare_runs.py" \
      "$H/s61_reference.json" "$ROOT/claude-s69/s61_reference.json" "$H/reservation_s69.json" "$ROOT/claude_reservations/s69_r2.json"
    echo "NEXT, ON cloud: $ROOT/gen-hybrid/server/.venv/bin/python -B $ROOT/claude-s69/s69_read_r3.py --check-imports"
    ;;
  *) echo "usage: bash stage_s69.sh lane|reader <sha256 of claude_s69_cloud.sh>"; exit 3;;
esac
