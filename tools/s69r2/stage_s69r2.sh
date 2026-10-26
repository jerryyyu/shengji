#!/bin/bash
# s69r2 staging (run on THIS Mac) = s69's r3 staging (identical-or-absent files, absent run paths, sha256sum -c on the host, read-only;
# nothing ever overwritten or removed) with the s69r2 names, in two phases:
#   bash stage_s69r2.sh lane <expected sha256 of claude_s69r2_cloud.sh>
#       the launcher -> $ROOT/claude_s69r2_cloud.sh; the harness + hypotheses (its DUEL / HYP pins) -> $ROOT/claude-s69/ (already staged
#       there for s69, read-only: accepted as identical).  No rehearsal wrapper: the child form is s69's, byte for byte.
#   bash stage_s69r2.sh reader <expected sha256 of claude_s69r2_cloud.sh>
#       the reader (TRUSTED launcher sha = that sha) -> $ROOT/claude-s69/s69r2_read.py beside the pinned helpers and the S61 reference
#       (already staged, identical); the reservation -> $ROOT/claude_reservations/s69r2.json.
# s69's files on the host (its launchers, readers, reservations, sealed output) are left untouched.
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
[[ "$WANT" =~ ^[0-9a-f]{64}$ ]] || { echo "usage: bash stage_s69r2.sh lane|reader <sha256 of claude_s69r2_cloud.sh>"; exit 3; }
[ -f "$H/claude_s69r2_cloud.sh" ] && [ "$(sha "$H/claude_s69r2_cloud.sh")" = "$WANT" ] || { echo "REFUSING: claude_s69r2_cloud.sh missing or not $WANT"; exit 3; }
grep -q "TO_BE_PINNED;" "$H/claude_s69r2_cloud.sh" && { echo "REFUSING: the launcher still holds a TO_BE_PINNED pin"; exit 3; }
pin () { sed -n "s/^.*$1=\/root\/claude-s69\/\([^;]*\); $1_SHA=\([0-9a-f]\{64\}\).*/\1 \2/p" "$H/claude_s69r2_cloud.sh"; }
case "$PHASE" in
  lane)
    read -r dname dsha <<< "$(pin DUEL)"; read -r hname hsha <<< "$(pin HYP)"
    [ "$dname" = exploit_duel_s61.py ] && [ "$(sha "$H/$dname")" = "$dsha" ] || { echo "REFUSING: the launcher's DUEL pin ($dname $dsha) is not $H/exploit_duel_s61.py's sha"; exit 3; }
    [ "$hname" = hypotheses.py ] && [ "$(sha "$H/$hname")" = "$hsha" ] || { echo "REFUSING: the launcher's HYP pin ($hname $hsha) is not $H/hypotheses.py's sha"; exit 3; }
    refuse_targets "$ROOT/claude_s69r2_screen.status" "$ROOT/claude_s69r2.RELEASE" "$ROOT/claude_s69r2.HOLD" "$ROOT/vol-dev-claude-s69r2-r48-20261026" "$ROOT/claude-s69/STAGED.s69r2-lane.sha256"
    "$SSH" "$HOST" mkdir -p "$ROOT/claude-s69" || exit 3
    stage_files s69r2-lane "$H/claude_s69r2_cloud.sh" "$ROOT/claude_s69r2_cloud.sh" "$H/exploit_duel_s61.py" "$ROOT/claude-s69/exploit_duel_s61.py" \
      "$H/hypotheses.py" "$ROOT/claude-s69/hypotheses.py"
    echo "NEXT, ON cloud: DRYRUN=1 bash $ROOT/claude_s69r2_cloud.sh (rc 0 and the names: line)"
    ;;
  reader)
    grep -q "^TRUSTED = dict(lane=LANE, launcher_sha256=\"$WANT\"" "$H/s69r2_read.py" || { echo "REFUSING: s69r2_read.py's TRUSTED launcher_sha256 is not $WANT"; exit 3; }
    grep -q 'reservation="/root/claude_reservations/s69r2.json")' "$H/s69r2_read.py" || { echo "REFUSING: s69r2_read.py's TRUSTED reservation is not s69r2.json"; exit 3; }
    python3 -c "import json,sys; r=json.load(open('$H/reservation_s69r2.json')); sys.exit(0 if r['launcher_sha256']=='$WANT' and r['lane']=='s69r2' and r['reader']=='Claude' and r['reservation_path']=='/root/claude_reservations/s69r2.json' else 3)" || { echo "REFUSING: reservation_s69r2.json does not name $WANT / s69r2.json with reader Claude (run make_reservation.py --force and test_s69r2_packet.py)"; exit 3; }
    "$SSH" "$HOST" test -d "$ROOT/claude-s69" || { echo "REFUSING: $ROOT/claude-s69 is not staged (run the lane phase first)"; exit 3; }
    refuse_targets "$ROOT/claude-s69/STAGED.s69r2-reader.sha256"
    "$SSH" "$HOST" mkdir -p "$ROOT/claude_reservations" || exit 3
    stage_files s69r2-reader "$H/s69r2_read.py" "$ROOT/claude-s69/s69r2_read.py" "$H/reader_lib.py" "$ROOT/claude-s69/reader_lib.py" \
      "$H/validity.py" "$ROOT/claude-s69/validity.py" "$H/row_schema.py" "$ROOT/claude-s69/row_schema.py" "$H/compare_runs.py" "$ROOT/claude-s69/compare_runs.py" \
      "$H/s61_reference.json" "$ROOT/claude-s69/s61_reference.json" "$H/reservation_s69r2.json" "$ROOT/claude_reservations/s69r2.json"
    echo "NEXT, ON cloud: $ROOT/gen-hybrid/server/.venv/bin/python -B $ROOT/claude-s69/s69r2_read.py --check-imports"
    ;;
  *) echo "usage: bash stage_s69r2.sh lane|reader <sha256 of claude_s69r2_cloud.sh>"; exit 3;;
esac
