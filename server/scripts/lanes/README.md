# Fleet lane library

`lane_lib.sh` holds the guards every new fleet lane (data generation, training, duel and screen runners) sources
instead of re-implementing them. `server/tests/test_lane_lib.py` drives each guard with stub producers, and
`server/scripts/check_lane_scripts.py` (CI) requires a launcher under this directory to source the library.

## Calling order

```bash
#!/bin/bash
set -u
. /path/to/server/scripts/lanes/lane_lib.sh
. "$CFG"                                   # sets the LANE_* variables below
LANE_FILES=("$0" /path/to/lane_lib.sh "$CFG" "$PLAN" "$PRODUCER")
lane_init
lane_arm;                 g=$?; [ $g = 3 ] && lane_pause "$LANE_MSG"; [ $g = 0 ] || lane_abort 6 "$LANE_MSG"
lane_require_registered_seeds "$SEED0" "$CLUSTERS" || lane_abort 6 "$LANE_MSG"
lane_lock_acquire;        g=$?; case $g in 0) ;; 3) lane_pause "$LANE_MSG" ;; 5) lane_abort 5 "$LANE_MSG" ;; *) lane_abort 6 "$LANE_MSG" ;; esac
lane_admit after-wait;    g=$?; [ $g = 3 ] && lane_pause "$LANE_MSG"; [ $g = 0 ] || lane_abort 6 "$LANE_MSG"
lane_supervise "$PY" "$PRODUCER" --out "$OUT" ...; rc=$?
[ $rc = 0 ] || lane_abort "$rc" "producer rc=$rc"
n=$(lane_count_files "$OUT" 'cluster-*.json'); [ "$n" = "$WANT" ] || lane_abort 4 "shards=$n"
lane_done "shards=$n"
# later, before removing a verified local copy:
lane_hold_check_before_delete "$OUT" && python3 safe_rm.py "$OUT"
```

`tests/test_lane_lib.py` contains the same launcher as `LAUNCHER`.

## Functions

| function | does | returns |
|---|---|---|
| `lane_identity FILE...` | sha256 of the manifest `<sha256>  <basename>` of each file, in order; refuses a missing file or a repeated basename | prints the identity |
| `lane_init [note]` | installs the TERM/INT/HUP and EXIT traps, writes `START` | |
| `lane_arm` | sets `LANE_ARMED_ID` (unless inherited from a parent chain) and runs `lane_admit arming` | as `lane_admit` |
| `lane_admit MOMENT` | hostname is `LANE_HOSTNAME`; no file of `LANE_HOLDS`; identity of `LANE_FILES` equals `LANE_ARMED_ID`; `LANE_RELEASE` is a regular file (not a symlink) whose first field is that identity; every `LANE_PINS` line and `LANE_PIN_HOOK` | 0, 3 HOLD, 6 refusal |
| `lane_gate` | each `LANE_GATES` line `<status file> <ERE>` matches the file's last line (anchor the ERE); `LANE_GATE_PROCEED` opens them; then any other `*.RELEASE` in `LANE_YIELD_DIR` matching `LANE_YIELD_GLOB` whose `.status` is not terminal makes this lane yield | 0 open, 1 wait, 2 a predecessor failed |
| `lane_lock_acquire` | polls every `LANE_POLL` s up to `LANE_WAIT_CEILING` s: HOLD stops, gates must be open, then `mkdir LANE_LOCK` with an owner line `<pid> <lane> <utc>`, gates re-checked with the lock held | 0, 3 HOLD, 5 ceiling, 6 failed predecessor |
| `lane_lock_release` | removes the lock only when its owner line names this shell | |
| `lane_supervise CMD...` | runs CMD in its own process group (setsid via `LANE_PY`), output to `LANE_LOG`; HOLD, `LANE_MAX_SECONDS` or the disk floor (`LANE_DISK_DIR` under `LANE_MIN_FREE_GIB`) stop the group and write `PAUSED`; TERM/INT/HUP do the same through the trap | the producer's rc, or exits 1 after `PAUSED` |
| `lane_done` / `lane_abort RC WHY` / `lane_pause WHY` | write the one terminal line, then release the lock | `lane_abort` exits RC, `lane_pause` exits 1 |
| `lane_hold_check_before_delete PATH` | any HOLD present: writes `DELETE_HELD`, keeps PATH | 0 may delete, 3 held |
| `lane_count_files DIR PATTERN` | `find DIR -type f -name PATTERN \| wc -l`, never a shell glob; 0 for a missing DIR | prints the count |
| `lane_require_registered_seeds SEED0 CLUSTERS` | the block lies inside exactly one window of the registry committed in `LANE_SEED_TREE` (HEAD on `LANE_SEED_MAIN_REF`, default `origin/main`; registry files tracked and unmodified), as reported by that tree's `seed_windows.py check --purpose other`; `LANE_SEED_PURPOSE` optionally fixes the window's purpose | 0 reserved, 6 refusal |

`seed_windows.py check` answers whether a span is *free*: exit 0 means disjoint from every window, which for a
reserved block is a refusal. On exit 1 the library parses the overlap lines and accepts only one window sharing all
`CLUSTERS` seeds; a partial overlap, a block straddling two windows or a parse mismatch refuses.

Every status line is `<LANE_PREFIX> <WORD> <LANE_NAME> <utc> ...` in `LANE_STATUS`. Each attempt ends in exactly one
of `DONE`, `PAUSED` (resumable) or `ABORT`, and `UNLOCKED` follows it. The library runs nothing when sourced; a running
launcher is never edited, because `lane_admit after-wait` refuses any change to `LANE_FILES` since arming.
