#!/bin/bash
# s69 staging (run on THIS Mac), in two phases, each refusing if ANY of its targets exists or is a symlink on the host (nothing is
# overwritten or removed); every copied file's sha256 is verified ON cloud against this Mac's and the copies are made read-only.  It does
# not build, arm, DRYRUN or release anything.  The tree /root/claude-main-56 is built separately (claude_build_main56_cloud.sh).
#
#   bash stage_s69.sh lane <expected sha256 of claude_s69_cloud.sh>
#       copies the launcher to $ROOT/claude_s69_cloud.sh and $ROOT/claude-s69/ = the harness + hypotheses (the launcher's DUEL / HYP, at
#       their pinned shas) and the host-rehearsal wrapper.  Enough for the host DRYRUN and the rehearsal.
#   bash stage_s69.sh rehearsal-r2 <expected sha256 of claude_s69_cloud.sh>
#       (after the lane phase staged r1's wrapper) copies the r2 host-rehearsal wrapper to $ROOT/claude-s69/rehearse_s69_cloud.r2.sh; refuses
#       if it or any r2 rehearsal output exists.  A fresh lane phase stages the r2 wrapper as rehearse_s69_cloud.sh directly.
#   bash stage_s69.sh reader <expected sha256 of claude_s69_cloud.sh>
#       copies the reader (its TRUSTED launcher sha = that sha), its pinned helpers (reader_lib, validity, row_schema, compare_runs) and the
#       S61 reference beside it in $ROOT/claude-s69/, and the reservation (naming that launcher sha) to $ROOT/claude_reservations/s69.json.
#
# The fresh-only check runs the remote loop with `bash -s -- <paths>` and the script on stdin, so the paths are the remote shell's positional
# arguments (s66dev r2's form: ssh concatenates its command words into ONE remote command line).
# Test hooks: S69_SSH / S69_SCP (default ssh / scp) and S69_ROOT (default /root) -- never set in production use.
set -u
H=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd) || { echo "REFUSING: cannot resolve the packet dir"; exit 3; }; HOST=shengji-cloud
SSH=${S69_SSH:-ssh}; SCP=${S69_SCP:-scp}; ROOT=${S69_ROOT:-/root}
PHASE=${1:-}; WANT=${2:-}
sha () { shasum -a 256 "$1" | cut -d' ' -f1; }
refuse_targets () {   # refuse_targets PATH...: ON the host, every path must be absent and not a symlink; the paths are bash -s positional arguments
  "$SSH" "$HOST" bash -s -- "$@" <<'REMOTE' || exit 3
set -u
[ "$#" -ge 1 ] || { echo "REFUSING: no target paths reached the host"; exit 3; }
for p in "$@"; do [ ! -e "$p" ] && [ ! -L "$p" ] || { echo "REFUSING: $p exists or is a symlink on the host"; exit 3; }; done
echo "targets clear ($# paths): $*"
REMOTE
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
    refuse_targets "$ROOT/claude_s69_cloud.sh" "$ROOT/claude-s69" "$ROOT/claude_s69_screen.status" "$ROOT/claude_s69.RELEASE" "$ROOT/claude_s69.HOLD" \
      "$ROOT/vol-dev-claude-s69-r48-20261026" "$ROOT/claude_s69_rehearsal.status" "$ROOT/vol-rehearsal-claude-s69-20261026" "$ROOT/claude_s69_rehearsal.peak_rss_kb"
    M=$(mktemp); trap 'rm -f "$M"' EXIT
    for f in exploit_duel_s61.py hypotheses.py rehearse_s69_cloud.sh; do echo "$(sha "$H/$f")  $ROOT/claude-s69/$f"; done >> "$M"
    echo "$WANT  $ROOT/claude_s69_cloud.sh" >> "$M"
    [ "$(wc -l < "$M" | tr -d ' ')" = 4 ] || { echo "REFUSING: expected 4 files"; cat "$M"; exit 3; }
    "$SSH" "$HOST" mkdir "$ROOT/claude-s69" || exit 3
    "$SCP" -q "$H/exploit_duel_s61.py" "$H/hypotheses.py" "$H/rehearse_s69_cloud.sh" "$HOST:$ROOT/claude-s69/" || exit 3
    "$SCP" -q "$H/claude_s69_cloud.sh" "$HOST:$ROOT/claude_s69_cloud.sh" || exit 3
    "$SCP" -q "$M" "$HOST:$ROOT/claude-s69/STAGED.lane.sha256" || exit 3
    "$SSH" "$HOST" "sha256sum -c $ROOT/claude-s69/STAGED.lane.sha256 && chmod a-w $ROOT/claude-s69/exploit_duel_s61.py $ROOT/claude-s69/hypotheses.py $ROOT/claude-s69/rehearse_s69_cloud.sh $ROOT/claude-s69/STAGED.lane.sha256 $ROOT/claude_s69_cloud.sh && echo \"STAGED ok (lane phase): \$(wc -l < $ROOT/claude-s69/STAGED.lane.sha256) files verified on the host, read-only\"" || exit 3
    echo "NEXT, ON cloud: DRYRUN=1 bash $ROOT/claude_s69_cloud.sh (rc 0 and the names: line); the rehearsal: nohup setsid bash $ROOT/claude-s69/rehearse_s69_cloud.sh $WANT"
    ;;
  rehearsal-r2)
    "$SSH" "$HOST" test -d "$ROOT/claude-s69" || { echo "REFUSING: $ROOT/claude-s69 is not staged (run the lane phase first)"; exit 3; }
    refuse_targets "$ROOT/claude-s69/rehearse_s69_cloud.r2.sh" "$ROOT/claude-s69/STAGED.rehearsal-r2.sha256" "$ROOT/claude_s69_rehearsal_r2.status" \
      "$ROOT/vol-rehearsal-claude-s69-r2-20261026" "$ROOT/claude_s69_rehearsal_r2.peak_rss_kb"
    M=$(mktemp); trap 'rm -f "$M"' EXIT
    echo "$(sha "$H/rehearse_s69_cloud.sh")  $ROOT/claude-s69/rehearse_s69_cloud.r2.sh" >> "$M"
    "$SCP" -q "$H/rehearse_s69_cloud.sh" "$HOST:$ROOT/claude-s69/rehearse_s69_cloud.r2.sh" || exit 3
    "$SCP" -q "$M" "$HOST:$ROOT/claude-s69/STAGED.rehearsal-r2.sha256" || exit 3
    "$SSH" "$HOST" "sha256sum -c $ROOT/claude-s69/STAGED.rehearsal-r2.sha256 && chmod a-w $ROOT/claude-s69/rehearse_s69_cloud.r2.sh $ROOT/claude-s69/STAGED.rehearsal-r2.sha256 && echo \"STAGED ok (rehearsal-r2 phase): 1 file verified on the host, read-only\"" || exit 3
    echo "NEXT, ON cloud: nohup setsid bash $ROOT/claude-s69/rehearse_s69_cloud.r2.sh $WANT"
    ;;
  reader)
    grep -q "^TRUSTED = dict(lane=LANE, launcher_sha256=\"$WANT\"" "$H/s69_read.py" || { echo "REFUSING: s69_read.py's TRUSTED launcher_sha256 is not $WANT"; exit 3; }
    python3 -c "import json,sys; r=json.load(open('$H/reservation_s69.json')); sys.exit(0 if r['launcher_sha256']=='$WANT' and r['lane']=='s69' and r['reader']=='Claude' else 3)" || { echo "REFUSING: reservation_s69.json does not name $WANT with reader Claude (run make_reservation.py --force and test_s69_packet.py)"; exit 3; }
    FILES="s69_read.py reader_lib.py validity.py row_schema.py compare_runs.py s61_reference.json"
    T=; for f in $FILES; do T="$T $ROOT/claude-s69/$f"; done
    "$SSH" "$HOST" test -d "$ROOT/claude-s69" || { echo "REFUSING: $ROOT/claude-s69 is not staged (run the lane phase first)"; exit 3; }
    # shellcheck disable=SC2086
    refuse_targets $T "$ROOT/claude-s69/STAGED.reader.sha256" "$ROOT/claude_reservations/s69.json"
    M=$(mktemp); trap 'rm -f "$M"' EXIT
    for f in $FILES; do echo "$(sha "$H/$f")  $ROOT/claude-s69/$f"; done >> "$M"
    echo "$(sha "$H/reservation_s69.json")  $ROOT/claude_reservations/s69.json" >> "$M"
    [ "$(wc -l < "$M" | tr -d ' ')" = 7 ] || { echo "REFUSING: expected 7 files"; cat "$M"; exit 3; }
    # shellcheck disable=SC2086
    "$SCP" -q $(for f in $FILES; do printf '%s ' "$H/$f"; done) "$HOST:$ROOT/claude-s69/" || exit 3
    "$SCP" -q "$H/reservation_s69.json" "$HOST:$ROOT/claude_reservations/s69.json" || exit 3
    "$SCP" -q "$M" "$HOST:$ROOT/claude-s69/STAGED.reader.sha256" || exit 3
    "$SSH" "$HOST" "sha256sum -c $ROOT/claude-s69/STAGED.reader.sha256 && chmod a-w$T $ROOT/claude_reservations/s69.json $ROOT/claude-s69/STAGED.reader.sha256 && echo \"STAGED ok (reader phase): \$(wc -l < $ROOT/claude-s69/STAGED.reader.sha256) files verified on the host, read-only\"" || exit 3
    echo "NEXT, ON cloud: $ROOT/gen-hybrid/server/.venv/bin/python -B $ROOT/claude-s69/s69_read.py --check-imports"
    ;;
  *) echo "usage: bash stage_s69.sh lane|rehearsal-r2|reader <sha256 of claude_s69_cloud.sh>"; exit 3;;
esac
