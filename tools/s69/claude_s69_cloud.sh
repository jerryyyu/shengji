#!/bin/bash
# s69: the DEV head-to-head of board row S69 (#1075: where does R48 lose now?  S61 ran against release 46, whose top loss cells R48 has
# since absorbed): the S61 design re-run against R48.  PAIRED, SEAT-SWAPPED: the EXPLOITER seats = R48 at the M27 expert budget (play worlds
# 64 -> 256, admission K 8 -> 32, exact caps 7/7 -> 8/8, exact-lead deadline 2.25 -> 9 s, exact node caps 5e7 -> 2e8, play budget 3 -> 60 s,
# no lgfd: SHENGJI_PV_LEAF_GREEDY_DEADLINE removed) vs the DEFENDER seats = R48 as served (fly.toml SHENGJI_BOT at d33bfd70 = origin/main).
# Everything else is R48's on BOTH sides: S58 at its stored temperature, dtrx, lgf, lgfx, the declare and bury knobs (bury budget 2 s), and
# the three fly.toml latency switches (the harness's served_env exports fly.toml's SHENGJI_* keys; the bot factory binds the switches for
# every bot).  The r2 rank-mixed plan per deal, 600 fresh deals 311060910..311061509, both sides from the cloud tree /root/claude-main-56.
# Revision r2 (2026-10-26, before any lane deal): the child also runs with --history (every row keeps buried / history / failed_detail),
# so S69's top cells can feed same-root replay fixtures (S61's extraction was refused because its producer ran without it); staged as
# /root/claude_s69_r2_cloud.sh (r1 e3c25940, staged as /root/claude_s69_cloud.sh, is superseded and never armed).
# WHAT RUNS.  One child: /root/claude-s69/exploit_duel_s61.py (the reviewed resumable S61 producer, verbatim, b15d292f; sha-pinned below
# with hypotheses.py), --arm identity, 12 workers, a KILL_AFTER-second hard stop and a BACKSTOP-second watchdog.  Every deal is played
# twice with the teams swapped; per-(deal, seat) seeds do not depend on the arm or the mirror.  Child output is sealed for the separate
# reader (s69_read.py, whose read is written in predeclare_s69.md BEFORE launch); this wrapper makes no strength claim.
# Source: s61dev's cloud launcher (claude_s61dev_cloud.final.sh fd6f3005, Codex-PASSed, LANE DONE on cloud) with s65dev's R48 check_names
# form (claude_s65dev_perf.sh, Codex-PASSed, LANE DONE on perf); the guard, wait, lock, legacy-peer, cleanup and signal blocks verbatim; the
# child launch is factored into run_child so the host rehearsal (rehearse_s69_cloud.sh) runs the same bytes.  FRESH runs only: an existing
# output root refuses; reopening an interrupted run through the producer's resume binding is a separate, separately authorized step.
# Dispatch requires the exact launcher SHA in a Claude-owned RELEASE, no HOLD, and exclusive host ownership.  This file grants no authority.
#   Usage ON shengji-cloud:  DRYRUN=1 bash /root/claude_s69_r2_cloud.sh
#     nohup setsid bash /root/claude_s69_r2_cloud.sh > /root/claude_s69_r2_cloud.nohup 2>&1 < /dev/null &      (arms; waits for the RELEASE)
#     then the RELEASE (Claude, after Codex's PASS): printf '%s\n' <this file's sha256> > /root/claude_s69.RELEASE

set -u


LANE=s69
LANE_ROOT=${LANE_ROOT:-/root}
SELF=$(readlink -f "${BASH_SOURCE[0]}"); SELF_SHA=$(sha256sum "$SELF" | cut -d" " -f1)   # lint-ok: both checked on the next line (non-empty path, 64-hex sha) before any use
[ -n "$SELF" ] && [ "${#SELF_SHA}" -eq 64 ] || { echo "REFUSING: cannot resolve or hash this launcher ('$SELF' '$SELF_SHA')"; exit 3; }
PY=${PY:-/root/gen-hybrid/server/.venv/bin/python}
TIME_BIN=${TIME_BIN:-/usr/bin/time}
TREE_HEAD_FULL=d33bfd70bb2f434368b7e83cdb5732cc791bd0ab; R=${R:-/root/claude-main-56}
EXT_ENGINE_SHA=e3b22690f0f19c4445bdadafb2ef8dee2ddfc5ce22844784366e0baaaa6b6820; EXT_CWV_SHA=325d607f313d097e0bdbeccb23f8e639cec62e9cf643735c1af83b22a28178e8; EXT_ENDGAME_SHA=776988da54e7bab940cfbafe64ea432232422dca995fd6a2d4f18d6c01fc8b55   # the three compiled extensions of the cloud build of d33bfd70 in $R (claude_build_main56_cloud.sh, BUILD_RC=0, 2026-10-26)
OUT=${OUT:-/root/vol-dev-claude-s69-r48-20261026}
S=$LANE_ROOT/claude_${LANE}_screen.status
RELEASE=$LANE_ROOT/claude_${LANE}.RELEASE; HOLD=$LANE_ROOT/claude_${LANE}.HOLD
HOSTLOCK=$LANE_ROOT/.claude-host.lock; LEGACY=$LANE_ROOT/.claude-screen.lock; DATAGEN=$LANE_ROOT/.claude-datagen.lock
WAIT_CEILING=${WAIT_CEILING:-108000}
LANE_SLEEP=${LANE_SLEEP:-120}
LEGACY_PS_RE=${LEGACY_PS_RE:-"cwv_screen[_]queue|shengji.harvest.trajector[y]|policy_world[_]duel|policy_abc[_]launche[r]"}
DEALS=600; SEED0=311060910; WORKERS=12; PLAN=r2; KILL_AFTER=28800; BACKSTOP=28810; MEM_MIN_KB=12582912   # 600 deals x 2 mirrors on the r2 rank-mixed plan per deal; the stop covers >= 2x the rehearsal projection (predeclare_s69.md); no predecessor gate (host-lock order)
COMBO_NAME=pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-rc252e656-bury-hybrid-bwv-cd6dd3d2b02a   # R48 as served = fly.toml SHENGJI_BOT on the tree: the DEFENDER seats
CAND_NAME=pv-search-491ee4bf-w256-k32-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-ed8-els9000-edn200000000-xf8-xfcompactlevel-r9779eb5a-bury-hybrid-bwv-80b4500430de   # the S69 exploiter: the EXPLOITER seats; derived from fly.toml + EX_ENV (name_probe.py -> name_probe.out) and re-derived by check_names
EX_ENV="SHENGJI_PV_WORLDS=256 SHENGJI_PV_CANDIDATES=32 SHENGJI_PV_EXACT_DEEP_CARDS=8 SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS=8 SHENGJI_PV_EXACT_LEAD_MAX_SECONDS=9.0 SHENGJI_PV_EXACT_DEEP_MAX_NODES=200000000 SHENGJI_PV_EXACT_FOLLOW_MAX_NODES=200000000 SHENGJI_PV_SERVING_BUDGET_SECONDS=60 SHENGJI_PV_LEAF_GREEDY_DEADLINE="   # the nine exploiter overrides (nine --exploiter-env arguments; an empty value removes the key: no lgfd)
FLY_SHA=ff64b52fb7ac81ae13158f6d3e03db2308338c1c961cd9e771b7679d62bf0a6e     # fly.toml at d33bfd70 (R48 as served; its SHENGJI_PV_* / SHENGJI_BOT lines byte-identical to 0c1e9965's)
DUEL=/root/claude-s69/exploit_duel_s61.py; DUEL_SHA=b15d292f564f2643e35d50e07584cecab839b1e61f9890bc31dc8363f495ceec    # the reviewed resumable S61 producer, verbatim (f746e976:tools/s61dev/exploit_duel_s61.py)
HYP=/root/claude-s69/hypotheses.py; HYP_SHA=4365a15d6c868263eaa64fca0038168342f2ebd96689da36f46be4e2082e49ce     # its hypotheses module (--arm identity), verbatim from the S34 duel
# volume path = cloud path = sha256
PKGS="/data/models/smv3out-491ee4bf.npz=/root/models/smv3out-491ee4bf.npz=491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670
/data/models/js-m1-0d17fd03.npz=/root/models/js-m1-0d17fd03.npz=0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747
/data/models/s58-e6-42444515.npz=/root/codex-r48-assets/s58-e6-42444515.npz=424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e"   # S58: fly.toml's belief package (both sides'), at its cloud copy (v105lat's and h1a's pin)
E2PATH=/root/codex-r48-assets/s58-e6-42444515.npz; PATH_MAP="/data/models/s58-e6-42444515.npz=$E2PATH"   # fly.toml names /data/models; the harness maps the value on BOTH sides (a path is in no digest)
STATUS_OWNED=0; HOST_OWNED=0; LEGACY_OWNED=0; WAIT_START=0; FIRST_DISPATCH_DONE=0

# --- guards -------------------------------------------------------------------------------------------------------
placeholder_guard () {   # the cloud build's pins must be filled before any DRYRUN, arming or dispatch
  local v; for v in "$EXT_ENGINE_SHA" "$EXT_CWV_SHA" "$EXT_ENDGAME_SHA"; do
    case "$v" in *TO_BE_PINNED*|"") echo "REFUSING: placeholder pins remain (EXT_* = TO_BE_PINNED): build $R at $TREE_HEAD_FULL and pin its three extensions first"; exit 3;; esac
  done
}
say () { if [ "$STATUS_OWNED" -eq 1 ]; then echo "$(date -u +%FT%TZ) $*" >> "$S"; else echo "$(date -u +%FT%TZ) $*"; fi; }
die () { say "REFUSING: $*"; exit 3; }
hold_guard () { [ ! -e "$HOLD" ] && [ ! -L "$HOLD" ] || die "HOLD file $HOLD exists"; }
deadline_guard () { [ $(( SECONDS - WAIT_START )) -lt "$WAIT_CEILING" ] || die "wait ceiling ($WAIT_CEILING s) reached $1; nothing started"; }
wait_guarded () { hold_guard; deadline_guard "$1"; sleep "$LANE_SLEEP"; }     # one guarded turn of any pre-dispatch wait
release_present () { [ -e "$RELEASE" ] || [ -L "$RELEASE" ]; }
release_ok () {   # the RELEASE token must be THIS launcher's sha256, and the launcher file unchanged since arming
  [ -f "$RELEASE" ] && [ ! -L "$RELEASE" ] || die "RELEASE $RELEASE absent or symlinked"
  [ "$(tr -d " \n" < "$RELEASE")" = "$SELF_SHA" ] || die "RELEASE does not hold this launcher's sha256 ($SELF_SHA)"
  [ "$(sha256sum "$SELF" | cut -d" " -f1)" = "$SELF_SHA" ] || die "launcher file changed since arming"
}
verify_tree () {
  [ -d "$R/.git" ] || die "tree $R missing"
  grep -q "BUILD_RC=0" "$R-build.log" 2>/dev/null || die "$R not built (no BUILD_RC=0 in $R-build.log)"
  [ "$(git -C "$R" rev-parse HEAD)" = "$TREE_HEAD_FULL" ] || die "tree $R is $(git -C "$R" rev-parse HEAD 2>/dev/null), not $TREE_HEAD_FULL"
  [ -z "$(git -C "$R" status --porcelain -- server)" ] || die "tree $R has modified or untracked server source"
  local so want
  for so in "engine/_fast:$EXT_ENGINE_SHA" "ai/_cwv_math:$EXT_CWV_SHA" "ai/_endgame_fast:$EXT_ENDGAME_SHA"; do   # all three, pinned
    want=${so#*:}; so=$R/server/shengji/${so%%:*}.cpython-314-x86_64-linux-gnu.so
    [ -f "$so" ] && [ ! -L "$so" ] || die "tree $R has no compiled $so"
    [ "$(sha256sum "$so" | cut -d" " -f1)" = "$want" ] || die "compiled extension $so is not its pinned sha256 $want"
  done
}
predispatch_guard () {   # rule 3: immediately before EVERY dispatch; rule 6: the deadline only before the FIRST window
  hold_guard
  [ "$FIRST_DISPATCH_DONE" -eq 1 ] || deadline_guard "before the first window"
  release_present || die "RELEASE $RELEASE removed before dispatch"
  release_ok
  verify_tree
}

# --- waits (rule 3: every turn guarded; rule 6: the deadline re-checked on LEAVING every wait) ----------------------
wait_release () { until release_present; do wait_guarded "without RELEASE"; done; deadline_guard "as RELEASE arrived"; hold_guard; release_ok; }
# Releasing a lock DIRECTORY that has contents is not a no-op: rmdir fails on a non-empty directory, and a suppressed
# failure leaves the lock standing forever, blocking every later job on this host (Codex, 2026-09-23).  So remove the
# owner file -- only if it is OURS -- and say so loudly if the rmdir still fails.  Rule 5: nothing not ours is touched.
release_locks () {
  if [ "$LEGACY_OWNED" -eq 1 ]; then
    rmdir "$LEGACY" 2>/dev/null || say "WARNING: could not release the legacy marker $LEGACY; it still holds: $(ls -A "$LEGACY" 2>/dev/null | tr "\n" " ")"
  fi
  if [ "$HOST_OWNED" -eq 1 ]; then
    if [ -f "$HOSTLOCK/owner" ] && [ "$(head -1 "$HOSTLOCK/owner" | cut -d" " -f1)" = "$$" ]; then rm -f "$HOSTLOCK/owner"; fi
    rmdir "$HOSTLOCK" 2>/dev/null || say "WARNING: could not release $HOSTLOCK; it still holds: $(ls -A "$HOSTLOCK" 2>/dev/null | tr "\n" " ")"
  fi
}
lane_exit () { release_locks; }   # cloud: no training-pause handshake
# START GATE (rule 1): ONE SHARED HOST LOCK.  Every job on this host -- screen, corpus store, duel, launcher -- takes
# THIS ONE lock, atomically.  Reading a peer's lock and then taking your own is NOT mutual exclusion: between the read
# and the mkdir the peer can take its lock and both start.  A single contended lock has no such window.  Arbitration
# is START-TIME ONLY (rule 2): the loser waits for the winner to exit, nothing preempts anything.
take_host_lock () {
  local noted=0
  until mkdir "$HOSTLOCK" 2>/dev/null; do
    [ "$noted" -eq 1 ] || { say "$LANE: shared host lock $HOSTLOCK busy ($(cat "$HOSTLOCK/owner" 2>/dev/null)); waiting for it"; noted=1; }
    wait_guarded "while the shared host lock stayed busy"
  done
  HOST_OWNED=1; trap lane_exit EXIT
  deadline_guard "as the shared host lock was taken"
  echo "$$ $LANE $(date -u +%FT%TZ)" > "$HOSTLOCK/owner"
  say "$LANE holds the host lock (pid $$)"
}
# The host lock is taken FIRST and held while the legacy peers are waited out.  The other order would reopen the
# race: a peer can be armed in the instant between "legacy clear" and the mkdir.
# LEGACY PEERS.  Jobs written before the host lock (the runPV1..runPV6 corpus stores) take /root/.claude-datagen.lock
# and know nothing about this one, so they are waited out separately -- but ONLY while such a job is actually RUNNING,
# which is exactly what holding its lock means.  Never wait on a merely ARMED peer: a legacy store's own gate waits for
# this lane's supervisor to be gone, so two "wait for the armed other" rules would wait on each other forever.
# Holding the host lock through this wait cannot deadlock, because legacy jobs never wait on the host lock.
# Delete this block once no pre-host-lock job can be armed on the box.
legacy_processes_running () { ps -eo stat,args | awk '$1 !~ /^T/' | grep -qE "$LEGACY_PS_RE"; }
wait_legacy_peers () {
  while [ -d "$DATAGEN" ] || [ -d "$LEGACY" ]; do wait_guarded "while a legacy lock stayed present"; done
  while legacy_processes_running; do wait_guarded "while a legacy process stayed alive"; done
  deadline_guard "as the legacy peers cleared"
}
# Compatibility marker: legacy stores gate on this directory, so hold it for this lane's whole life (rule 5: checked).
take_legacy_marker () {
  mkdir "$LEGACY" 2>/dev/null || die "could not take the legacy screen marker $LEGACY ($(ls -ld "$LEGACY" 2>&1)); nothing started"
  LEGACY_OWNED=1
}

# --- lane-specific checks ----------------------------------------------------------------------------------------------
check_packages () {
  local vol local sha got
  while IFS== read -r vol local sha; do
    [ -f "$local" ] && [ ! -L "$local" ] || die "package $local missing or symlinked"
    got=$(sha256sum "$local" | cut -d" " -f1); [ "${#got}" -eq 64 ] && [ "$got" = "$sha" ] || die "package $local sha256 $got, expected $sha"   # lint-ok: the length test refuses an empty or partial hash before the comparison
  done <<< "$PKGS"
}
mem_guard () {   # 12 workers x the rehearsal's per-process peak (rehearsal/host/), plus margin; MemAvailable was 28 GiB on 2026-10-26
  local avail; avail=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
  [ -n "$avail" ] && [ "$avail" -ge "$MEM_MIN_KB" ] || die "MemAvailable ${avail:-?} kB < $MEM_MIN_KB kB"
}
toml_bot () { sed -n "s/^ *SHENGJI_BOT *= *'\(.*\)'.*/\1/p" "$1" | head -n 1; }
check_toml () {   # the tree's fly.toml is R48 as served: pinned bytes and the combo name; the harness files at their pinned shas
  [ "$(sha256sum "$R/fly.toml" | cut -d" " -f1)" = "$FLY_SHA" ] || die "tree fly.toml sha256 is not $FLY_SHA"
  [ "$(toml_bot "$R/fly.toml")" = "$COMBO_NAME" ] || die "tree fly.toml SHENGJI_BOT is '$(toml_bot "$R/fly.toml")', not $COMBO_NAME"
  [ -f "$DUEL" ] && [ ! -L "$DUEL" ] && [ "$(sha256sum "$DUEL" | cut -d" " -f1)" = "$DUEL_SHA" ] || die "$DUEL missing, symlinked or not its pinned sha256 $DUEL_SHA"
  [ -f "$HYP" ] && [ ! -L "$HYP" ] && [ "$(sha256sum "$HYP" | cut -d" " -f1)" = "$HYP_SHA" ] || die "$HYP missing, symlinked or not its pinned sha256 $HYP_SHA"
}
# the arm names, derived through the harness's OWN variant_factory from fly.toml + the overrides (never typed), the knobs each side built, and the plan's head
check_names () {
  ( cd "$R/server" && FIND_GAPS_SERVER="$R/server" FIND_GAPS_PKG=/root/models/smv3out-491ee4bf.npz FIND_GAPS_PATH_MAP="$PATH_MAP" SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
    "$PY" -B - "$DUEL" "$COMBO_NAME" "$CAND_NAME" "$EX_ENV" "$E2PATH" <<'PY'
import dataclasses, importlib.util, os, sys
duel, r48, cand, exenv, e2 = sys.argv[1:6]
sys.path.insert(0, duel.rsplit('/', 1)[0])
spec = importlib.util.spec_from_file_location('exploit_duel_s61', duel); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
assert m.R45 == r48, ('fly.toml SHENGJI_BOT on the tree', m.R45)
assert os.environ['SHENGJI_PV_BELIEF_CKPT'] == e2 and os.environ['SHENGJI_PV_CKPT'] == '/root/models/smv3out-491ee4bf.npz', ('the path map', os.environ.get('SHENGJI_PV_BELIEF_CKPT'))
assert (os.environ.get('SHENGJI_PV_WORLDS'), os.environ.get('SHENGJI_PV_CANDIDATES')) == ('64', '8'), ('the served widths in the process env', os.environ.get('SHENGJI_PV_WORLDS'), os.environ.get('SHENGJI_PV_CANDIDATES'))
assert (os.environ.get('SHENGJI_PV_SERVING_BUDGET_SECONDS'), os.environ.get('SHENGJI_PV_LEAF_GREEDY_DEADLINE'), os.environ.get('SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS')) == ('3', '2', '2'), ('the served budgets in the process env', os.environ.get('SHENGJI_PV_SERVING_BUDGET_SECONDS'), os.environ.get('SHENGJI_PV_LEAF_GREEDY_DEADLINE'), os.environ.get('SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS'))
sw = ('SHENGJI_PV_ENCODE_PREFIX_CACHE', 'SHENGJI_PV_LEAF_GREEDY_STREAM', 'SHENGJI_PV_ENCODE_BATCH_FAST')
assert all(os.environ.get(k) == '1' for k in sw) and not os.environ.get('SHENGJI_PV_SINGLE_CANDIDATE_FAST'), ('the fly.toml latency switches in the process env', {k: os.environ.get(k) for k in sw})
eenv = m._parse_env(exenv.split(' '))   # the run's nine --exploiter-env arguments, parsed as the harness parses them
assert eenv == (('SHENGJI_PV_CANDIDATES', '32'), ('SHENGJI_PV_EXACT_DEEP_CARDS', '8'), ('SHENGJI_PV_EXACT_DEEP_MAX_NODES', '200000000'), ('SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS', '8'), ('SHENGJI_PV_EXACT_FOLLOW_MAX_NODES', '200000000'), ('SHENGJI_PV_EXACT_LEAD_MAX_SECONDS', '9.0'), ('SHENGJI_PV_LEAF_GREEDY_DEADLINE', ''), ('SHENGJI_PV_SERVING_BUDGET_SECONDS', '60'), ('SHENGJI_PV_WORLDS', '256')), eenv
lat = ('encode_prefix_cache', 'leaf_greedy_stream', 'encode_batch_fast', 'single_candidate_fast')
knobs = ('worlds', 'candidates', 'exact_deep_cards', 'exact_follow_max_cards', 'exact_lead_max_seconds', 'exact_deep_max_nodes', 'exact_follow_max_nodes', 'serving_budget_seconds', 'leaf_greedy_deadline_ms')
keep = ('bury_serving_budget_seconds', 'bury_arm')   # R48's on both sides
cfg = lambda b: dataclasses.asdict(b.config)
dn, dmake = m.variant_factory(()); db = dmake(7)
en, emake = m.variant_factory(eenv); eb = emake(7)
assert dn == r48, ('defender name', dn); assert en == cand, ('exploiter name', en); assert dn != en
assert type(db).__name__ == type(eb).__name__ == 'PVSearchBuryBot', ('classes', type(db).__name__, type(eb).__name__)
assert [getattr(db, a, False) for a in lat] == [getattr(eb, a, False) for a in lat] == [True, True, True, False], ('latency switches', [getattr(db, a, None) for a in lat], [getattr(eb, a, None) for a in lat])
assert db.belief_model.package_sha256 == eb.belief_model.package_sha256 == os.environ['SHENGJI_PV_BELIEF_SHA256'] and str(db.belief_checkpoint) == str(eb.belief_checkpoint) == e2, ('belief', db.belief_checkpoint, eb.belief_checkpoint)
assert abs(db.belief_model.temperature - 1.0129481491372179) < 1e-15 and eb.belief_model.temperature == db.belief_model.temperature, ('belief temperature', db.belief_model.temperature, eb.belief_model.temperature)
dk, ek = [cfg(db)[k] for k in knobs], [cfg(eb)[k] for k in knobs]
assert dk == [64, 8, 7, 7, 2.25, 50000000, 50000000, 3.0, 2000], ('defender knobs (R48 as served)', dk)
assert ek == [256, 32, 8, 8, 9.0, 200000000, 200000000, 60.0, 0], ('exploiter knobs (the M27 expert budget, no lgfd)', ek)
assert [getattr(b, k, None) for b in (db, eb) for k in knobs] == dk + ek, ('built attributes vs config', [getattr(b, k, None) for b in (db, eb) for k in knobs])
assert [getattr(db, a, None) for a in keep] == [getattr(eb, a, None) for a in keep] == [2.0, 'hybrid'], ('bury budget / bury arm', [getattr(db, a, None) for a in keep], [getattr(eb, a, None) for a in keep])
diff = sorted(x for x in set(cfg(db)) | set(cfg(eb)) if cfg(db).get(x) != cfg(eb).get(x))
assert diff == sorted(knobs), ('config differs beyond the nine knobs', diff)
plan = [m.round_plan('r2', i) for i in range(13)]
assert [p[0] for p in plan] == ['first' if i % 10 in (0, 3, 5, 8) else 'fixed_banker' for i in range(13)] and plan[1] == ('fixed_banker', '3', 1) and plan[12] == ('fixed_banker', 'A', 0)
print('names: defender', dn, '| exploiter', en, '| config diff', diff, '| exploiter knobs', ek, '| switches 3 of 3 on both | same S58', db.belief_model.package_sha256[:8], 'T', db.belief_model.temperature, '| bury 2 s hybrid on both | plan head', plan[:4])
PY
  ) || die "the harness does not derive the pinned arm names, knobs, switches, belief or the r2 plan"
}
check_compiled () {
  ( cd "$R/server" && SHENGJI_FAST=1 PYTHONPATH="$R/server" "$PY" -B -c "
from shengji.ai.endgame_compact import HAVE_FAST, default_backend
import shengji.engine.fast as ef
assert HAVE_FAST and default_backend() == 'compiled', (HAVE_FAST, default_backend())
print('compiled backend ok')" ) >/dev/null || die "compiled endgame backend / engine not importable in $R"
}
write_recipe () {   # recipe.json for --recipe: the sealed fly.toml copy and the volume->cloud map
  "$PY" -I -B -c '
import json, sys
fly, pkgs, out = sys.argv[1:4]
pairs = [line.split("=")[:2] for line in pkgs.strip().splitlines()]
with open(out, "x") as fh:
    json.dump({"fly_toml": fly, "map": pairs}, fh, sort_keys=True)
    fh.write("\n")' "$OUT/fly.toml" "$PKGS" "$OUT/recipe.json"
}
# OUTPUT CONTRACT.  The DEV wrapper seals child output and process metadata only.
# It never parses duel.jsonl or stdout: terminal status and rc are evidence for the
# separate reviewed reader/qualifier, not a strength qualification.

# RUN CLEANUP.  While the run is active its pgid and the watchdog pid live in RUN_PGID / RUN_WD, and this lane's own EXIT trap
#   (lane_exit_s35 = run_cleanup, then the verbatim block's lane_exit) and TERM/INT/HUP traps are installed.  So EVERY exit path
#   stops and reaps the owned run group BEFORE release_locks: TERM to the group, a 5 s grace, KILL, reap, then
#   a check that no non-zombie member of the group is alive.  If one still is, the host lock and legacy marker are LEFT HELD
#   (HOST_OWNED/LEGACY_OWNED cleared, so release_locks does not remove them) and the status says so: overlap is worse than a
#   stuck lock.  Only this lane's own group and watchdog are signalled.
RUN_PGID=; RUN_WD=; ABORT_SAID=0
run_group_live () { ps -eo pgid=,pid=,stat= | awk -v g="$1" '$1 == g && $3 !~ /^Z/ {print $2}' | tr "\n" " "; }
stop_watchdog () { [ -n "$RUN_WD" ] || return 0; kill "$RUN_WD" 2>/dev/null; wait "$RUN_WD" 2>/dev/null; RUN_WD=; }
run_cleanup () {
  local i live
  stop_watchdog
  [ -n "$RUN_PGID" ] || return 0
  [ "$ABORT_SAID" -eq 1 ] || { say "ABORT: $LANE exiting while run group $RUN_PGID is active; stopping it before releasing the host lock"; ABORT_SAID=1; }
  kill -TERM -- "-$RUN_PGID" 2>/dev/null; kill -TERM "$RUN_PGID" 2>/dev/null
  for i in 1 2 3 4 5 6 7 8 9 10; do [ -z "$(run_group_live "$RUN_PGID")" ] && break; sleep 0.5; done
  kill -KILL -- "-$RUN_PGID" 2>/dev/null; kill -KILL "$RUN_PGID" 2>/dev/null
  wait "$RUN_PGID" 2>/dev/null
  for i in 1 2 3 4 5 6 7 8 9 10; do live=$(run_group_live "$RUN_PGID"); [ -z "$live" ] && break; sleep 0.5; done
  if [ -n "$live" ]; then
    HOST_OWNED=0; LEGACY_OWNED=0
    say "ABORT: $LANE run group $RUN_PGID still has live members ($live) after TERM+KILL; host lock $HOSTLOCK and marker $LEGACY LEFT HELD; clear by hand"
  else
    say "$LANE: run group $RUN_PGID stopped and reaped; no live member"
  fi
  RUN_PGID=
}
lane_exit_s35 () { run_cleanup; lane_exit; }
lane_signal () {   # lane_signal NAME CODE
  trap '' TERM INT HUP
  ABORT_SAID=1
  say "ABORT: $LANE interrupted by SIG$1 (pid $$)$([ -n "$RUN_PGID" ] && echo "; run group $RUN_PGID active: stopping and reaping it before the host lock is released")"
  exit "$2"
}
install_lane_traps () { trap 'lane_signal TERM 143' TERM; trap 'lane_signal INT 130' INT; trap 'lane_signal HUP 129' HUP; trap lane_exit_s35 EXIT; }
dev_checks () { check_packages; check_toml; check_compiled; check_names; mem_guard; }   # every check before a child starts (the lane and the host rehearsal)
run_child () {   # the child itself, in its own process group under timeout + the backstop watchdog; writes $OUT/duel.*; sets RUN_RC / RUN_WALL / RUN_RSS
  local pid pg rc t0 t1 wall rss i live
  t0=$(date +%s.%N)
  ( cd "$R/server" && exec setsid env SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
      NUMEXPR_NUM_THREADS=1 PYTHONPATH="$R/server" \
      FIND_GAPS_SERVER="$R/server" FIND_GAPS_PKG=/root/models/smv3out-491ee4bf.npz FIND_GAPS_PATH_MAP="$PATH_MAP" \
      timeout --signal=KILL "$KILL_AFTER" "$TIME_BIN" -v -o "$OUT/duel.time" \
      "$PY" -B "$DUEL" --arm identity --seed0 "$SEED0" --deals "$DEALS" --workers "$WORKERS" --round-plan "$PLAN" --history --out "$OUT/duel.jsonl" \
      --exploiter-env SHENGJI_PV_WORLDS=256 --exploiter-env SHENGJI_PV_CANDIDATES=32 --exploiter-env SHENGJI_PV_EXACT_DEEP_CARDS=8 --exploiter-env SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS=8 --exploiter-env SHENGJI_PV_EXACT_LEAD_MAX_SECONDS=9.0 --exploiter-env SHENGJI_PV_EXACT_DEEP_MAX_NODES=200000000 --exploiter-env SHENGJI_PV_EXACT_FOLLOW_MAX_NODES=200000000 --exploiter-env SHENGJI_PV_SERVING_BUDGET_SECONDS=60 --exploiter-env SHENGJI_PV_LEAF_GREEDY_DEADLINE= \
      > "$OUT/duel.stdout" 2> "$OUT/duel.stderr" < /dev/null ) &
  pid=$!; RUN_PGID=$pid
  pg=; for i in 1 2 3 4 5 6 7 8 9 10; do pg=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d " "); [ "$pg" = "$pid" ] && break; sleep 0.5; done
  if [ "$pg" != "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; RUN_PGID=
    die "run pid $pid is not its own process-group leader (pgid '${pg}'); killed it before any result"
  fi
  ( trap 'kill $s 2>/dev/null; exit 0' TERM; sleep "$BACKSTOP" & s=$!; wait $s; kill -KILL -- "-$pid" 2>/dev/null ) & RUN_WD=$!
  say "$LANE run pid/pgid $pid (setsid; timeout KILL at $KILL_AFTER s; backstop watchdog pid $RUN_WD at $BACKSTOP s)"
  wait "$pid"; rc=$?
  t1=$(date +%s.%N)
  stop_watchdog
  kill -KILL -- "-$pid" 2>/dev/null && say "$LANE: swept surviving members of process group $pid"
  for i in 1 2 3 4 5 6 7 8 9 10; do live=$(run_group_live "$pid"); [ -z "$live" ] && break; sleep 0.5; done
  [ -z "$live" ] || die "run group $pid still has live members ($live) after the sweep"   # EXIT -> run_cleanup keeps the lock if so
  RUN_PGID=
  wall=$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.1f", b-a}')
  rss=$(sed -n 's/.*Maximum resident set size (kbytes): //p' "$OUT/duel.time" 2>/dev/null)
  say "$LANE DEV END rc=$rc wall_s=$wall maxrss_kb=${rss:-?}$( { [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; } && echo " (KILLED: rc $rc = the $KILL_AFTER s hard stop; process group swept)")"
  RUN_RC=$rc; RUN_WALL=$wall; RUN_RSS=${rss:-}
}
run_dev () {
  predispatch_guard; dev_checks
  FIRST_DISPATCH_DONE=1
  [ ! -e "$OUT/duel.jsonl" ] && [ ! -e "$OUT/duel.stdout" ] || die "DEV output already exists in $OUT"
  install_lane_traps
  say "$LANE DEV start: defender $COMBO_NAME (R48 as served) vs exploiter $CAND_NAME (S69 exploiter: $EX_ENV); deals $DEALS seed0 $SEED0 plan $PLAN, paired and seat-swapped, play histories kept (--history); workers $WORKERS; group KILL at $KILL_AFTER s (backstop $BACKSTOP s)"
  run_child
}

run_lane () {
  placeholder_guard
  verify_tree; check_packages; check_toml; check_compiled
  [ "$(nproc)" -ge "$WORKERS" ] || { echo "REFUSING: fewer than $WORKERS cores on this host"; exit 3; }
  command -v setsid >/dev/null && command -v timeout >/dev/null && [ -x "$TIME_BIN" ] || { echo "REFUSING: setsid/timeout/time missing"; exit 3; }
  free=$(df -BG / | awk 'NR==2{gsub(/G/,"",$4); print $4}'); [ "$free" -ge 5 ] || { echo "REFUSING: ${free} GB free"; exit 9; }
  if [ "${DRYRUN:-0}" = "1" ]; then
    NAMES_LINE=$(check_names) || exit 3
    echo "DRYRUN ok (cloud): launcher sha256 $SELF_SHA; tree $R = $(git -C $R rev-parse HEAD) clean, built, compiled backend, extensions pinned ${EXT_ENGINE_SHA:0:8} / ${EXT_CWV_SHA:0:8} / ${EXT_ENDGAME_SHA:0:8}; no predecessor gate (host-lock order)"
    echo "DRYRUN ok (cloud): fly.toml sha256 $FLY_SHA serves $COMBO_NAME; harness $DUEL sha256 $DUEL_SHA + $HYP sha256 $HYP_SHA; packages sha-verified; $NAMES_LINE"
    echo "DRYRUN ok (cloud): $WORKERS workers, deals $DEALS seed0 $SEED0 plan $PLAN (paired, seat-swapped, --history; exploiter = S69 exploiter: $EX_ENV, defender = R48 as served), setsid + timeout --signal=KILL $KILL_AFTER (backstop $BACKSTOP); out $OUT ($([ -e $OUT ] && echo PRESENT || echo absent)); MemAvailable $(awk '/^MemAvailable:/ {print $2}' /proc/meminfo) kB (need $MEM_MIN_KB)"
    echo "DRYRUN ok (cloud): host lock $([ -e $HOSTLOCK ] && echo "PRESENT ($(cat $HOSTLOCK/owner 2>/dev/null))" || echo absent); RELEASE $([ -e $RELEASE ] && echo PRESENT || echo absent); HOLD $([ -e $HOLD ] && echo PRESENT || echo absent); status $([ -e $S ] && echo PRESENT || echo absent)"
    exit 0
  fi

  [ ! -e "$OUT" ] || { echo "REFUSING: output root $OUT already exists"; exit 3; }
  (set -o noclobber; : > "$S") 2>/dev/null || { echo "REFUSING: cannot exclusively create status $S"; exit 3; }
  STATUS_OWNED=1
  trap 'lane_signal TERM 143' TERM; trap 'lane_signal INT 130' INT; trap 'lane_signal HUP 129' HUP   # ABORT witness while waiting too
  say "$LANE armed (pid $$, launcher sha256 $SELF_SHA): tree $R $TREE_HEAD_FULL; waiting for the RELEASE token $RELEASE, then the host lock"
  WAIT_START=$SECONDS
  wait_release
  say "$LANE: RELEASE verified; contending for the host lock"
  take_host_lock
  wait_legacy_peers
  take_legacy_marker
  say "$LANE legacy peers clear; marker $LEGACY taken"
  install_lane_traps   # take_host_lock installed `trap lane_exit EXIT`; compose run_cleanup in front of it
  predispatch_guard
  [ ! -e "$OUT" ] || die "output root $OUT already exists"
  mkdir -p "$OUT" || die "cannot create $OUT"
  cp "$R/fly.toml" "$OUT/fly.toml" || die "could not copy the release fly.toml"
  chmod a-w "$OUT/fly.toml"
  [ "$(sha256sum "$OUT/fly.toml" | cut -d" " -f1)" = "$FLY_SHA" ] || die "copied fly.toml sha256 differs"
  write_recipe || die "could not write $OUT/recipe.json"
  chmod a-w "$OUT/recipe.json"
  say "$LANE start head=$(git -C $R rev-parse --short=8 HEAD): recipe $(sha256sum "$OUT/recipe.json" 2>/dev/null | cut -d" " -f1)"
  RUN_RC=; RUN_WALL=; RUN_RSS=
  run_dev
  ( cd "$OUT" && (set -o noclobber; find . -type f ! -name 'SHA256SUMS' -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS) ) || die "could not write $OUT/SHA256SUMS"
  say "$LANE SHA256SUMS $(sha256sum "$OUT/SHA256SUMS" | cut -d" " -f1) ($(wc -l < "$OUT/SHA256SUMS") files)"
  [ "$RUN_RC" = 0 ] || die "child rc $RUN_RC: output sealed for forensics only; no LANE DONE"
  say "$LANE DEV output sealed; rc/status only (strength qualification is reader-owned); LANE DONE"
}

if [ "${LANE_FUNCTIONS_ONLY:-0}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi
run_lane
