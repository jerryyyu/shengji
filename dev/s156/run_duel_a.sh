#!/bin/bash
# Run one frozen SZ2-A decision capture under the shared Ultra lock.
set -u
for setting in ${!LANE_@}; do echo "inherited lane setting: $setting" >&2; exit 6; done

fleet=/Users/jeryyu/fleet
worktrees=/Users/jeryyu/Projects/shengji-wt
name=sz2-duel-a-v1
packet=$fleet/codex-$name
recipe=$packet/recipe.json
clearance=$packet/d1.json
config=$packet/packet.pins
supervisor=$packet/supervisor
status=$packet/SZ2-A.status
root=$packet/out/SZ2-A
LANE_HOSTNAME=Jerrys-Mac-Studio.local
[ "$(hostname)" = "$LANE_HOSTNAME" ] && [ "$0" = "$packet/run_duel_a.sh" ] || exit 6
[ -d "$packet" ] && [ ! -L "$packet" ] || exit 6
for path in "$config" "$recipe" "$clearance" "$0" "$packet/dispatch_duel_a.sh"; do
  [ -s "$path" ] && [ -f "$path" ] && [ ! -L "$path" ] || exit 6
done
read -r head recipe_sha clearance_sha workers disk_floor wall_ceiling extra < "$config" || exit 6
[[ "$head" =~ ^[0-9a-f]{40}$ && "$recipe_sha" =~ ^[0-9a-f]{64}$ && "$clearance_sha" =~ ^[0-9a-f]{64}$ && -z "$extra" ]] || exit 6
for value in "$workers" "$disk_floor" "$wall_ceiling"; do
  [[ "$value" =~ ^[1-9][0-9]{0,8}$ ]] || exit 6
done
[ "$(wc -l < "$config" | tr -d ' ')" = 1 ] || exit 6

tree=$worktrees/codex-sz2-duel-a-${head:0:8}
base=$tree/server/scripts
lib=$base/lanes/lane_lib.sh
clean_tree() {
  local dirty
  [ "$(git -C "$tree" rev-parse HEAD)" = "$head" ] &&
    dirty=$(git -C "$tree" status --porcelain) && [ -z "$dirty" ] &&
    cmp -s "$0" "$tree/dev/s156/run_duel_a.sh" &&
    cmp -s "$packet/dispatch_duel_a.sh" "$tree/dev/s156/dispatch_duel_a.sh"
}
clean_tree || exit 6
. "$base/lanes/lane_lib.sh" || exit 6

LANE_NAME=$name
LANE_RELEASE=$packet/launcher.RELEASE
LANE_LOCK=$fleet/.claude-host.lock
LANE_HOLDS="$packet/launcher.HOLD $fleet/codex-sz2-joint-v1/launcher.HOLD $fleet/codex-sz2-post-S-v1/launcher.HOLD $fleet/codex-sz2-post-M-v1/launcher.HOLD $fleet/claude_ut_gen2.HOLD"
LANE_PY=/Users/jeryyu/Projects/shengji/server/.venv/bin/python
LANE_SEED_TREE=/Users/jeryyu/Projects/shengji
LANE_SEED_PURPOSE=screen
LANE_FILES=("$0" "$packet/dispatch_duel_a.sh" "$config" "$lib" "$tree/dev/s156/SZ2_A_DECISION.md")
while IFS= read -r path; do
  LANE_FILES+=("$tree/$path")
done < <(git -C "$tree" ls-files -- 'server/scripts/sz2_*.py')
LANE_PINS="$recipe_sha  $recipe
$clearance_sha  $clearance"
LANE_GATES="$fleet/codex-sz2-post-S-v1/capture/launcher.status ^LANE DONE sz2-post-S-v1 [^ ]+ selected package parity verified rc=0$
$fleet/codex-sz2-post-M-v1/capture/launcher.status ^LANE DONE sz2-post-M-v1 [^ ]+ selected package parity verified rc=0$"
LANE_DISK_DIR=$fleet
LANE_MIN_FREE_GIB=$disk_floor
LANE_MAX_SECONDS=$wall_ceiling
LANE_WAIT_CEILING=2
LANE_POLL=1
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1

clearance_ok() {
  # The freeze review independently verifies exposure evidence before pinning this attestation.
  "$LANE_PY" -I -B - "$recipe" "$recipe_sha" "$clearance" "$clearance_sha" <<'PY'
import hashlib
import json
import re
import sys


def pinned_json(path, digest):
    with open(path, "rb") as stream:
        raw = stream.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024 or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(f"{path}: missing or changed frozen input")
    return json.loads(raw)


try:
    recipe, receipt = (pinned_json(*sys.argv[i : i + 2]) for i in (1, 3))
    arms = recipe["arms"]
    arm = arms["SZ2-A"]
    if set(arms) != {"SZ2-A"} or (arm["seed0"], arm["deals"]) != (2665000000, 1000):
        raise ValueError("wrong decision window")
    expected = dict(schema="sz2-a-exposure-r1", verdict="CLEAR", recipe_sha256=sys.argv[2],
                    arm="SZ2-A", seed0=2665000000, deals=1000, unresolved=0, overlaps=0)
    for kind in ("package", "belief"):
        identities = {role: arm[f"{role}_{kind}_sha256"] for role in ("ex", "def")}
        if len(set(identities.values())) != 2 or any(
            not re.fullmatch("[0-9a-f]{64}", value) for value in identities.values()
        ):
            raise ValueError(f"invalid {kind} identities")
        expected[f"{kind}_sha256"] = identities
    if any(type(receipt.get(key)) is not type(value) or receipt[key] != value for key, value in expected.items()):
        raise ValueError("D1 attestation does not clear the frozen recipe, sides and window")
except (KeyError, OSError, TypeError, ValueError, AttributeError) as exc:
    raise SystemExit(str(exc))
PY
}

fresh() {
  [ ! -L "$packet/out" ] && { [ ! -e "$packet/out" ] || [ -d "$packet/out" ]; } &&
    [ ! -e "$root" ] && [ ! -L "$root" ] &&
    [ ! -e "$status" ] && [ ! -L "$status" ] &&
    [ ! -e "$supervisor" ] && [ ! -L "$supervisor" ]
}

preflight() {
  clean_tree && fresh && ! lane_hold_present && lane_gate && lane_disk_check &&
    clearance_ok &&
    PYTHONPATH="$LANE_SEED_TREE/server" lane_require_registered_seeds 2665000000 1000 &&
    [ "$LANE_MSG" = 'seeds: [2665000000, 2665001000) reserved by sz2-dev-2665000000 screen [2665000000, 2665002200)' ]
}

refuse() { echo "SZ2-A refused: ${LANE_MSG:-$*}" >&2; exit 6; }

utd_owns_status() {
  local first
  local expected="^UTD START [^ ]+ mode=SZ2-A arm=SZ2-A pid=$$ seed0=2665000000 deals=1000 workers=$workers recipe=$recipe_sha$"
  [ -f "$status" ] && [ ! -L "$status" ] &&
    IFS= read -r first < "$status" && [[ "$first" =~ $expected ]]
}

utd_unlock() {
  local last
  last=$(tail -1 "$LANE_STATUS") || return 1
  [[ "$last" = "LANE UNLOCKED $name "* ]] && [[ "$last" = *" $LANE_LOCK" ]] && utd_owns_status &&
    printf 'UTD UNLOCKED %s %s\n' "$(lane_now)" "$LANE_LOCK" >> "$status"
}

finish_duel() {
  local rc=$?
  trap - EXIT
  # Supervision stops the owned process group before reconciling its status.
  lane_group_alive && lane_stop_group
  if [ "$rc" != 0 ] && [ -n "${LANE_STATUS:-}" ] && utd_owns_status; then
    if ! grep -q '^UTD ABORT ' "$status"; then
      printf 'UTD ABORT %s rc=%s reason=supervisor\n' "$(lane_now)" "$rc" >> "$status"
    fi
    # FAILED/PAUSED paths may already have released the host lock.
    lane_on_exit
    utd_unlock || :
  else
    lane_on_exit
  fi
  exit "$rc"
}

case "${1:-}" in
  --identity)
    [ "$#" = 1 ] || exit 2
    lane_check_pins && lane_identity "${LANE_FILES[@]}"
    exit $? ;;
  --preflight)
    [ "$#" = 1 ] || exit 2
    [ ! -e "$LANE_LOCK" ] && [ ! -L "$LANE_LOCK" ] && preflight || refuse 'preflight'
    if [ -e "$LANE_RELEASE" ] || [ -L "$LANE_RELEASE" ]; then
      lane_arm || refuse 'release'
      echo "$LANE_ARMED_ID"
    else
      lane_identity "${LANE_FILES[@]}"
    fi
    exit $? ;;
  --run)
    [ "$#" = 2 ] && [[ "$2" =~ ^[0-9a-f]{64}$ ]] || exit 2 ;;
  *) exit 2 ;;
esac

lane_arm && [ "$LANE_ARMED_ID" = "$2" ] && preflight || refuse 'admission'
lane_init
trap finish_duel EXIT
lane_lock_acquire || refuse 'host lock'
lane_admit after-lock && preflight || refuse 'after-lock admission'
mkdir "$supervisor" || refuse 'supervisor output already claimed'
LANE_STATUS=$supervisor/launcher.status
LANE_LOG=$supervisor/launcher.log
lane_say START "pid=$$ identity=$LANE_ARMED_ID recipe=$recipe_sha workers=$workers"
lane_supervise "$LANE_PY" -B "$base/sz2_a_dispatch.py" --recipe "$recipe" --recipe-sha256 "$recipe_sha" --workers "$workers"
rc=$?
[ "$rc" = 0 ] || lane_abort "$rc" 'duel worker failed'
utd_owns_status || lane_abort 6 'worker returned without an owned capture'
seal_sum=$(lane_sha "$root/SHA256SUMS") || lane_abort 6 'seal manifest missing'
done_pattern="^UTD DONE [^ ]+ recipe=$recipe_sha rows=2000 sums=$seal_sum rc=0$"
[[ "$(tail -1 "$status")" =~ $done_pattern ]] ||
  lane_abort 6 'worker returned without a successful sealed terminal'
lane_lock_release
utd_unlock || lane_abort 6 'could not record actual host unlock'
lane_done 'SZ2-A sealed for the reserved reader'
