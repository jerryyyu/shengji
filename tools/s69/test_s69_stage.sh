#!/bin/bash
# s69 staged-layout regression: test_lane_stage.template.sh with ONLY the LANE HEADER block filled (stage both phases of stage_s69.sh).
# Model: s67c's test_s67c_stage.sh (r2), which answered Codex 1075/6405786268 (r1 staged the adapter in claude-s67c/ and its
# harness only in a sibling dir; every local test passed because they ran from the source tree, and the host run would have died).
# STAGED_LAYOUT_REGRESSION: runs the packet's real stage command into a temp copy of the host layout (ssh / scp shims, so the bytes
#   checked are the bytes copied), checks each launcher-pinned file is a regular file at its pinned sha in HOST_DIR, runs the COPIED
#   adapter --help from outside the tree, and runs the launcher's preflight import through the COPIED adapter in the staged dir.
# STAGED_LAYOUT_NEGATIVE_CONTROL: the same staged dir with NEG_REMOVE deleted must make the copied adapter --help exit non-zero, so a
#   pass above cannot come from files found outside the staged layout.
# Run and save (lane_lint --packet reads the .out; re-run after any edit to the test):
#   bash test_<lane>_stage.sh > test_<lane>_stage.out 2>&1; echo rc=$? >> test_<lane>_stage.out
# Writes nothing outside a temp dir.  Exit = number of failed checks (3 = unfilled header / bad setup).
set -u
# ---- LANE HEADER (fill every placeholder; quote values that contain spaces or $)
PKT=/Users/jerryyu/Projects/shengji-wt/claude-s69-redteam/tools/s69   # local packet dir (absolute)
LAUNCHER=$PKT/claude_s69_cloud.sh   # the exact launcher file the lane runs; sourced with LANE_FUNCTIONS_ONLY=1
HOST_ROOT=/root   # host prefix the launcher's paths start with, e.g. /root
HOST_DIR=/root/claude-s69   # the one host dir the launcher reads its helpers from, e.g. /root/claude-s67c
PINNED='DUEL HYP'   # launcher variables naming staged files, each with a <VAR>_SHA, e.g. 'DUEL HYP ADAPTER'
ADAPTER_VAR=DUEL   # the entry point among PINNED (run with --help), e.g. ADAPTER
STAGE_CMD='mkdir -p $STAGE_ROOT/claude_reservations && L=$(shasum -a 256 $PKT/claude_s69_cloud.sh | cut -c1-64) && S69_ROOT=$STAGE_ROOT S69_SSH=ssh S69_SCP=scp bash $PKT/stage_s69.sh lane $L && S69_ROOT=$STAGE_ROOT S69_SSH=ssh S69_SCP=scp bash $PKT/stage_s69.sh reader $L'   # stages into $STAGE_ROOT, e.g. 'S67_ROOT=$STAGE_ROOT S67_SSH=ssh S67_SCP=scp bash $PKT/stage_s67c.sh tree'
PREFLIGHT_CMD='bash $PKT/stage_preflight.sh "$SA" "$SD" "$STAGE_ROOT"'   # the launcher's preflight import via the COPIED adapter ($SA adapter, $SD dir, $PY; envrun = clean env)
NEG_REMOVE=hypotheses.py   # a file in HOST_DIR whose absence must break the copied adapter, e.g. exploit_duel_s61.py
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python   # the python the host run uses (locally: the venv of the pinned tree)
RUN_ENV='FIND_GAPS_PATH_MAP=/data/models/s58-e6-42444515.npz=/Users/jerryyu/.claude/jobs/d0498cda/tmp/s69pkg/s58-e6-42444515.npz PYTHONPATH=/Users/jerryyu/Projects/shengji-wt/claude-s69-redteam/server FIND_GAPS_SERVER=/Users/jerryyu/Projects/shengji-wt/claude-s69-redteam/server FIND_GAPS_PKG=/Users/jerryyu/Projects/shengji-wt/pkg/smv3out-491ee4bf.npz SHENGJI_FAST=1'   # env words for the copied adapter, e.g. 'PYTHONPATH=/x/server SHENGJI_FAST=1', or - for none
# ---- end LANE HEADER
for v in "$PKT" "$LAUNCHER" "$HOST_ROOT" "$HOST_DIR" "$PINNED" "$ADAPTER_VAR" "$STAGE_CMD" "$PREFLIGHT_CMD" "$NEG_REMOVE" "$PY" "$RUN_ENV"; do
  case "$v" in *@\@*|'') echo "REFUSING: unfilled LANE HEADER value '$v'"; exit 3 ;; esac
done
[ -f "$LAUNCHER" ] && [ -d "$PKT" ] && [ -x "$PY" ] || { echo "REFUSING: launcher, packet dir or python missing"; exit 3; }
case "$HOST_DIR" in "$HOST_ROOT"/*) ;; *) echo "REFUSING: HOST_DIR $HOST_DIR is not under HOST_ROOT $HOST_ROOT"; exit 3 ;; esac
ENVW=()
if [ "$RUN_ENV" != - ]; then set -f; ENVW=($RUN_ENV); set +f; fi
envrun () { env -i HOME="$HOME" PATH=/usr/bin:/bin ${ENVW[@]+"${ENVW[@]}"} "$@"; }
sha () { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
T=$(mktemp -d "${TMPDIR:-/tmp}/lanestage.XXXXXX") || { echo "REFUSING: mktemp failed"; exit 3; }
trap 'chmod -R u+w "$T" 2>/dev/null; rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/host" "$T/run" || { echo "REFUSING: cannot make the temp layout"; exit 3; }
cat > "$T/bin/ssh" <<'EOF'
#!/bin/bash
# ssh shim: drop the host, join the remaining words into one command line as ssh does, run it with the caller's stdin
shift
exec bash -c "$*"
EOF
cat > "$T/bin/scp" <<'EOF'
#!/bin/bash
# scp shim: copy the sources to the HOST:dest path with the host prefix dropped, as scp would
args=(); for a in "$@"; do [ "$a" = -q ] || [ "$a" = -p ] || args+=("$a"); done
n=${#args[@]}; dest=${args[$((n - 1))]}; dest=${dest#*:}
exec cp "${args[@]:0:$((n - 1))}" "$dest"
EOF
chmod +x "$T/bin/ssh" "$T/bin/scp" || { echo "REFUSING: cannot make the shims executable"; exit 3; }
export PATH="$T/bin:$PATH" STAGE_ROOT="$T/host" PKT PY
fails=0; passes=0
pass () { echo "PASS $1"; passes=$((passes + 1)); }
fail () { echo "FAIL $1"; fails=$((fails + 1)); }
# 1. the real stage command into the temp host
out=$(cd "$T/run" && eval "$STAGE_CMD" 2>&1); rc=$?
if [ "$rc" -eq 0 ]; then pass "stage command rc 0 into the temp host layout"; else fail "stage command rc=$rc: $(printf '%s\n' "$out" | tail -3)"; fi
# 2. every pinned file is the staged copy at its pinned sha, all in HOST_DIR
pins=$(LANE_FUNCTIONS_ONLY=1 bash -c 'source "$1" >/dev/null; shift; for v in "$@"; do s=${v}_SHA; printf "%s %s %s\n" "$v" "${!v-}" "${!s-}"; done' x "$LAUNCHER" $PINNED); rc=$?
[ "$rc" -eq 0 ] && [ -n "$pins" ] || { fail "could not source the launcher's pins (rc=$rc)"; pins=; }
SA=
while read -r var path want; do
  [ -n "$var" ] || continue
  f=$T/host${path#"$HOST_ROOT"}
  got=none
  if [ -f "$f" ] && [ ! -L "$f" ]; then got=$(sha "$f") || got=none; fi
  if [ "${path#"$HOST_ROOT"/}" != "$path" ] && [ "$(dirname "$path")" = "$HOST_DIR" ] && [ "${#got}" -eq 64 ] && [ "$got" = "$want" ]; then
    pass "$var = $path is the staged copy at its pinned sha ${want:0:12}, in $HOST_DIR"
  else fail "$var = '$path' (pinned '${want:-}'): missing, a symlink, outside $HOST_DIR or sha '$got'"; fi
  [ "$var" = "$ADAPTER_VAR" ] && SA=$f
done <<< "$pins"
SD=$T/host${HOST_DIR#"$HOST_ROOT"}
export SA SD
# 3. the COPIED adapter --help, from outside both trees
if [ -n "$SA" ] && [ -f "$SA" ]; then
  out=$(cd "$T/run" && envrun "$PY" -B "$SA" --help 2>&1); rc=$?
  if [ "$rc" -eq 0 ]; then pass "the COPIED adapter --help runs rc 0 from the staged dir"; else fail "copied adapter --help rc=$rc: $(printf '%s\n' "$out" | tail -3)"; fi
else fail "ADAPTER_VAR $ADAPTER_VAR is not among the staged pins"; fi
# 4. the launcher preflight import through the COPIED adapter, in the staged dir
out=$(cd "$SD" 2>/dev/null && eval "$PREFLIGHT_CMD" 2>&1); rc=$?
if [ "$rc" -eq 0 ]; then pass "launcher preflight through the COPIED adapter rc 0: $(printf '%s\n' "$out" | tail -1 | cut -c1-120)"; else fail "preflight rc=$rc: $(printf '%s\n' "$out" | tail -3)"; fi
# 5. negative control: the staged dir without NEG_REMOVE must break the copied adapter
if [ -n "$SA" ] && [ -f "$SD/$NEG_REMOVE" ] && cp -R "$SD" "$T/neg" && chmod -R u+w "$T/neg" && rm -f "$T/neg/$NEG_REMOVE"; then
  out=$(cd "$T/run" && envrun "$PY" -B "$T/neg/$(basename "$SA")" --help 2>&1); rc=$?
  if [ "$rc" -ne 0 ]; then pass "negative control: without $NEG_REMOVE the copied adapter --help exits $rc"; else fail "negative control: the adapter still ran without $NEG_REMOVE (it reads files outside the staged layout)"; fi
else fail "negative control: $SD/$NEG_REMOVE is not staged, or the copy failed"; fi
[ "$passes" -ge 4 ] || fail "only $passes checks passed"
if [ "$fails" -eq 0 ]; then echo "ALL PASS"; else echo "$fails FAILED"; fi
exit "$fails"
