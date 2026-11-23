# Called under the joint lane's host lock. A timed slice may continue only
# after a new checkpoint boundary. An operator STOP always takes precedence.
joint_phase() {
  local phase=$1 train=$2 rc terminal cursor=0 next total digest expected
  local stop_re='^[^ ]+ STOPPED at epoch 1 buffer ([0-9]+)/([0-9]+) \(STOP file or --max-seconds\); checkpoint saved$'
  local pause_re='^[^ ]+ UTR PAUSED at epoch 1 buffer 400/[0-9]+ \(report boundary\); checkpoint saved$'
  [ "$phase" != medium-finish ] || cursor=400
  while true; do
    clean_tree && lane_admit "before-$phase" && lane_gate || lane_abort 6 "phase admission failed: $LANE_MSG"
    [ ! -e "$train/STOP" ] && [ ! -L "$train/STOP" ] || lane_pause "$phase operator STOP"
    lane_say PHASE "$phase after buffer $cursor"
    lane_supervise "$LANE_PY" -B "$worker" "$root" --phase "$phase" --provider-sha256 "$provider_sha"
    rc=$?
    case "$rc" in
      8) [ "$phase" = medium-finish ] || lane_abort 8 "unexpected gate refusal in $phase"
         lane_done 'FAIL-OFFLINE at buffer 400'; exit 0 ;;
      9) lane_abort 9 'provider restoration unverified' ;;
      0|3|7) ;;
      *) lane_abort "$rc" "$phase worker failed" ;;
    esac
    terminal=$(tail -1 "$train/status.log") || lane_abort 6 "missing $phase trainer terminal"
    [ ! -e "$train/STOP" ] && [ ! -L "$train/STOP" ] || lane_pause "$phase operator STOP"
    case "$rc" in
      3) [[ "$terminal" =~ $stop_re ]] || lane_abort 6 "invalid $phase checkpoint terminal"
         next=${BASH_REMATCH[1]}; total=${BASH_REMATCH[2]}
         [ "$next" -gt "$cursor" ] && [ "$next" -lt "$total" ] && [ -s "$train/checkpoint.pt" ] ||
           lane_abort 6 "$phase saved no forward checkpoint"
         cursor=$next ;;
      7) [ "$phase" = medium-prefix ] && [[ "$terminal" =~ $pause_re ]] &&
           [ -s "$train/checkpoint.pt" ] && [ -s "$train/epoch-1-buffer-400.json" ] ||
           lane_abort 6 "missing matched-prefix witness"
         return 0 ;;
      0) [ "$phase" != medium-prefix ] && [ -s "$train/best.pt" ] || lane_abort 6 "$phase missing best checkpoint"
         digest=$(lane_sha "$train/best.pt") || lane_abort 6 "$phase unreadable best checkpoint"
         expected="UTR DONE best=$train/best.pt sha256=$digest"
         [ "${terminal#* }" = "$expected" ] || lane_abort 6 "$phase best checkpoint differs from terminal"
         return 0 ;;
    esac
  done
}

joint_training() {
  joint_phase small "$root/S/train"
  joint_phase medium-prefix "$root/M/train"
  joint_phase medium-finish "$root/M/train"
  lane_done 'joint arms complete'
}
