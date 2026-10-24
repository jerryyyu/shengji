# Deploying Sheng Ji

The operator runbook: what is serving now, how to roll it back, and how to ship the next release.
Policy evidence lives in `AI_POLICIES.md` (the ladder table); measurement rules live in `RL_PLAN.md`.
Release records through release 46 in full: [docs_archive/deploy-through-2026-10-16.md](docs_archive/deploy-through-2026-10-16.md).

## Terms

| term | meaning |
|---|---|
| served name | the `SHENGJI_BOT` value; the registry derives it from the `fly.toml` env, and `/healthz` reports it as `bot` |
| play package | the NumPy value/policy net, `smv3out-491ee4bf.npz` |
| prior | the JS-M1 package `js-m1-0d17fd03.npz`, kept under the `SHENGJI_CWV_PRIOR_*` keys |
| belief package | the hidden-hand model: S58's `s58-e6-42444515.npz` in release 48; S17's `s17long-e2-763b5e05.npz` in release 46 (the rollback) |
| volume | the Fly volume mounted at `/data`; packages in `/data/models`, room logs in `/data/logs` |
| image | `registry.fly.io/shengji:<image>`; Fly numbers each deploy `vNN` |
| smoke | a run of the served bot through the server path (`_paced_bot_step` / `_commit_bot_turn`) |
| first-room reader | the Python snippet in step 9 of the Release checklist, run once on the first live room's log |

Every deploy so far ran on machine `48e7e35a9597e8`, app `shengji`.

## Current production

**Release 48** (release 46 with the S58 belief package, `dtrx`, the guarded greedy-finished value leaf
`lgf lgfx lgfd2000`, and three latency switches).

| field | value |
|---|---|
| deployed | 2026-10-24 10:18 ET (14:18Z), at 0 rooms, on Jerry's in-session word |
| Fly version | v47 |
| image | `deployment-01M5Q4ACYEJ901SQB3BNMPC55A` |
| source | main `f14ace152b5491be53b5a1088728f47f6755f393` (#1147; Codex PASS at `0c1e9965`) |
| evidence | `AI_POLICIES.md` ladder row 17 (r48cloud, confirmed r48confirm, latency v105lat QUALIFIED) |
| deploy record | [#1075 issuecomment-6385303349](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6385303349) |
| comparator | new screens compare against release 48 as served (Jerry 2026-10-24)[^cmp] |

Served name:

```
pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-rc252e656-bury-hybrid-bwv-cd6dd3d2b02a
```

### Packages

| package | path on the volume | sha256 | `/healthz` field |
|---|---|---|---|
| play | `/data/models/smv3out-491ee4bf.npz` | `491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670` | `pv_search.sha256` |
| prior | `/data/models/js-m1-0d17fd03.npz` | `0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747` | `prior` |
| belief (new in 48) | `/data/models/s58-e6-42444515.npz` | `424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e` | not reported[^belief] |
| belief (release 46, kept for the rollback) | `/data/models/s17long-e2-763b5e05.npz` | `763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343` | — |

S58 (d192, 4 + 4 layers) is served at its stored temperature 1.0129. Both belief packages are also assets of the
`serving-packages` GitHub release.

### `fly.toml` keys

The lines release 48 added to or changed in release 46's environment (every other line byte-identical):

| change | `fly.toml` | name token |
|---|---|---|
| belief package: S58 replaces S17 e2 | `SHENGJI_PV_BELIEF_CKPT = '/data/models/s58-e6-42444515.npz'`, `SHENGJI_PV_BELIEF_SHA256 = '424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e'` | none (the play digest moves) |
| dtrx (#1120) | `SHENGJI_PV_DOOMED_THROW_RESELECT_EXACT_GUARD = '1'` | `dtrx` |
| greedy-finished value leaf (S33) | `SHENGJI_PV_LEAF_GREEDY_FINISH = '1'` | `lgf` |
| its exact-stage yield | `SHENGJI_PV_LEAF_GREEDY_FINISH_EXACT_SKIP = '1'` | `lgfx` |
| its deadline | `SHENGJI_PV_LEAF_GREEDY_DEADLINE = '2'` | `lgfd2000` |
| latency switches (no name, payload or digest) | `SHENGJI_PV_ENCODE_PREFIX_CACHE = '1'`, `SHENGJI_PV_LEAF_GREEDY_STREAM = '1'`, `SHENGJI_PV_ENCODE_BATCH_FAST = '1'` | none |

Inherited from release 46, unchanged except the belief package above:

| group | keys | name token |
|---|---|---|
| play worlds | `SHENGJI_PV_WORLD_HISTORY_LEGAL = '1'`, `SHENGJI_PV_WORLD_HISTORY_DRAW = '1'`, `SHENGJI_PV_BELIEF_WORLDS = '1'` | `whl whd bw` |
| exact endgame | `SHENGJI_PV_EXACT_LEAD_ENDGAME = '1'`, `SHENGJI_PV_EXACT_DEEP_CARDS = '7'` | `ele ed7` |
| exact follow | `SHENGJI_PV_EXACT_FOLLOW = '1'`, `SHENGJI_PV_EXACT_FOLLOW_SOLVER = 'compact-level'`, `SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS = '7'`, `SHENGJI_PV_EXACT_FOLLOW_MAX_NODES = '50000000'` | `xf7 xfcompactlevel` |
| declaration | `SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST = '1'` | `vdef` |

Inherited from release 45 and earlier, unchanged:

| what | keys |
|---|---|
| search rules, each `'1'` | `SHENGJI_PV_ADMISSION_DIVERSITY`, `SHENGJI_PV_REFUSAL_CONSTRAINTS`, `SHENGJI_PV_TIEBREAK_POINTS`, `SHENGJI_PV_LEAD_ANCHOR` (r38), `SHENGJI_PV_DOOMED_THROW_RESELECT` (r43), `SHENGJI_PV_VALUE_DECLARE` (r44) |
| search width and budget | `SHENGJI_PV_WORLDS = '64'`, `SHENGJI_PV_CANDIDATES = '8'`, `SHENGJI_PV_CAP = '4000'`, `SHENGJI_PV_SERVING_BUDGET_SECONDS = '3'` |
| bury | `SHENGJI_PV_BURY_ARM = 'hybrid'`, `SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS = '2'`, `SHENGJI_PV_BURY_WIDE_VALUE = '1'`, `SHENGJI_PV_BURY_WIDE_K = '64'` (r45) |
| packages | `SHENGJI_PV_CKPT`, `SHENGJI_PV_SHA256`; prior `SHENGJI_CWV_PRIOR_CKPT`, `_SHA256`, `_THRESHOLD = '1000'`, `_TOP = '256'` |
| engine and logs | `SHENGJI_FAST = '1'` (compiled engine and solver), `SHENGJI_LOG_DIR = '/data/logs'` |

`server/tests/test_release48_fly_config.py` builds the served bot from this env on the pinned packages, with the env
exported into the process as Fly does, and plays one turn through the server path; it also builds the release-46
rollback on S17's package. `server/tests/test_bury_fly_config.py` pins the name chain 48 → 46 → 45 and the deeper
rollbacks.

### What the recipe does at serving time

- **Belief worlds.** Each sampled world is history-legal and its hidden hands come from the belief package (S58
  since release 48). A belief error, including a preparation over 0.25 s, falls back to the history-legal draw for
  that decision and is recorded (`belief_fallback`, `belief_error`).
- **Belief log** (on by default). Each sampled decision record gains `belief_seed` and a marginal snapshot;
  `server/scripts/belief_debug.py` replays it. No decision depends on the log.
- **Exact endgame.** At ≤ 7 cards a LEAD is re-scored by exact minimax per world and a FOLLOW is re-ranked on the
  compiled solver, inside the 3 s budget. A stage that does not finish plays the baseline and says so
  (`exact_lead_status` `abandoned`/`skipped_budget`, `exact_follow_abandoned`).
- **dtrx.** The doomed-throw re-select never overrides a complete exact lead stage.
- **Greedy-finished leaf.** Before the value pass, each candidate's trick is finished with greedy replies (`lgf`).
  On decisions an exact stage is eligible for, the plain leaf is used instead (`lgfx`). Past 2 s into a decision
  the finish stops and every remaining leaf is the plain one (`lgfd2000`; record `leaf_greedy_deadline_fired`).
- **Latency switches.** Prefix-cached and batched encoding and a streamed greedy finish; on completed decisions
  the cards played are the switch-off ones. They are read from the process environment where the bot is built, so
  `/healthz` reports them as `pv_search.latency_switches`.
- **Declaration.** In the first round the value declaration is consulted at every declare chance (record
  `gate`, `every_first`).
- **Dependencies.** Serving imports only NumPy and the standard library. The solver `ai/_endgame_fast` is built
  in the Dockerfile's `fastbuild` stage[^fast].

### Evidence

Each read compares the candidate with release 46, production when it ran (paired common-control, ten 520-cluster
windows, r2 rank-mixed round plan: 4 first-round windows at rank 2 and 6 fixed-banker windows at ranks 2..A).

| read | host, seeds | result [95% CI] | validity | splits (descriptive) | pointer |
|---|---|---|---|---|---|
| r48cloud (guarded R48 screen) | cloud, 231060910 + 100000·i | **+0.0765 [+0.0571, +0.0958]**, POSITIVE; every window positive | VALID; 0 play and 0 belief fallbacks on both arms | rank 2 +0.0884, rank ≠ 2 +0.0661 | [#1075 issuecomment-6383298163](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6383298163) |
| r48confirm (fresh-seed confirmation) | perf, 232060910 + 100000·i | **+0.0843 [+0.0575, +0.1111]**, POSITIVE, judged alone | VALID; 0 play and 0 belief fallbacks | rank 2 +0.0909, rank ≠ 2 +0.0792 | [#1075 issuecomment-6384251320](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6384251320) |
| v105lat (latency and peak memory, the exact recipe) | one pinned cloud core, one room, ABBA 4 × 100 full rounds | QUALIFIED, bars B1–B9 PASS | 0 budget fallbacks, 0 plays ≥ 3 s, exact abandons 2 / 2920 (release 46 1 / 2837), 0 belief fallbacks over 12,692 | see below | [#1075 issuecomment-6384912469](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6384912469) |

v105lat, candidate vs release 46 on the same seeds: play wall p50 0.098 / p95 0.566 / p99 0.746 / max 2.408 s over
12,692 plays (release 46 0.096 / 0.155 / 0.319 / 2.407 s over 12,868); on plays where the finish ran, p95 0.598 s,
p99 0.835 s; the 2 s deadline fired on 14 of 12,692 decisions; belief_ms p95 25.8 (release 46 20.7); peak RSS
+26,792 kB. The Fly projection in that read is descriptive, not a measurement; the first-room read is the Fly check.

The unguarded S58 combo (without the deadline and the latency switches) read INVALID on play budget fallbacks
([readout](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6376318200)); the deadline and switches are
that read's repair. The screens measure the combined recipe: they do not attribute the gain among S58, dtrx and the
greedy finish. Archive: `~/shengji-archive/2026-09-13/readouts/{r48cloud,r48confirm,v105lat}/`.

### Post-deploy checks as read

| check | result |
|---|---|
| `/healthz` | name above, `fast: true`, `pv_search.sha256` `491ee4bf…`, `prior` `0d17fd03…`, budget 3, bury `hybrid` at 2, `latency_switches` `{"encode_prefix_cache": true, "single_candidate_fast": false, "leaf_greedy_stream": true, "encode_batch_fast": true}` |
| in-machine compiled/belief line | printed `True compiled 42444515` |
| first live room **UBWB** | PARTIAL: the room stopped after 3 tricks (12 plays); read once |
| UBWB fallbacks | 0 `pv-search-fallback-v1`, 0 belief fallbacks |
| UBWB decision seconds | p95 1.35 / max 1.47; belief_ms p95 39 |
| verdict | no rollback trigger on the partial room; a complete first room is still to be read |

Preconditions as met: Codex PASS at `0c1e9965`, all ten CI checks green, squash-merged as `f14ace15` (the only commit
on main past #1147's base is #1148, web assets, so `server/` is the screened tree); S58 on the volume with in-machine
sha256 `424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e`, S17 kept; merged-tree full-round smoke
(10 rounds, server path) validator PASS with `bot.files` S58 `42444515`, play `491ee4bf`, prior `0d17fd03` and the
latency switches as set: 692 plays, 50 + 96 exact-eligible decisions, 0 abandons, 0 fallbacks, decision p95 0.256 s,
max 1.62 s, belief_ms p95 13 ms, and 1 belief fallback (play 1 of the first room, a cold `BeliefNumpyError`
preparation at 823 ms, the documented boot case); r48cloud and r48confirm POSITIVE; v105lat QUALIFIED; Jerry's word
in session.

**Watch list:** the first-room rollback triggers (Release checklist, step 9) on the first complete room; its
whole-decision p95 on Fly's shared CPU (UBWB's 1.35 s over 12 plays is near the 1.5 s trigger), belief_ms p95, failed
throws per round and the `leaf_greedy_deadline_fired` count; any `cwv-bury-fallback-v1` or
`pv-declare-serving-fallback-v1` record; the `/healthz` `activity` counters (step 10).

### Release note: what a player will notice

- **More failed throws.** dtrx keeps an exact-stage throw the engine will refuse unless another lead's exact
  mean is at least as high, so the bot shows more public failed-throw notices than release 46 (R47's v97dtrx
  measured about a third more). Its effect on human opponents is not measured.
- **Belief package.** S58 is trained on bot self-play plus a small human-log stream. Watch the first human
  room's belief and history fallback counts.

## Rollback

### To release 46 (the rollback target)

Release 46: Fly v46, image `deployment-01M530R14ARM0669QNJBW2RGTG`, main `ab6fd1b2`, digest
`sha256:0d2d92e5d85948309741a8486f739a751537b13d36c622a266fc33b4809c2d4a`. Same play package and prior; it reads
`/data/models/s17long-e2-763b5e05.npz`, which stays on the volume. Release 46's served name:

```
pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-vd-vdef-ed7-xf7-xfcompactlevel-r73993d62-bury-hybrid-bwv-cf77a93949b0
```

**Option 1, redeploy the release-46 image** (no build):

```bash
flyctl deploy --app shengji --ha=false --image registry.fly.io/shengji:deployment-01M530R14ARM0669QNJBW2RGTG
```

**Option 2, edit `fly.toml`:**

1. Delete the seven lines release 48 added: `SHENGJI_PV_DOOMED_THROW_RESELECT_EXACT_GUARD`,
   `SHENGJI_PV_LEAF_GREEDY_FINISH`, `SHENGJI_PV_LEAF_GREEDY_FINISH_EXACT_SKIP`, `SHENGJI_PV_LEAF_GREEDY_DEADLINE`,
   `SHENGJI_PV_ENCODE_PREFIX_CACHE`, `SHENGJI_PV_LEAF_GREEDY_STREAM`, `SHENGJI_PV_ENCODE_BATCH_FAST`.
2. Restore `SHENGJI_PV_BELIEF_CKPT = '/data/models/s17long-e2-763b5e05.npz'` and
   `SHENGJI_PV_BELIEF_SHA256 = '763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343'`.
3. Set `SHENGJI_BOT` to the release-46 name kept in the comment above it.
4. Run `fly deploy --ha=false`; `/healthz` must show the release-46 name and every latency switch false.

`test_release48_fly_config.py` and `test_bury_fly_config.py` check that this env derives release 46's name.

### To release 45

Release 45: Fly v45, image `deployment-01M4T9AVEVK51WP2GG8J34NRC9`, main `1ca97051`, digest
`sha256:6194eb27e62efab5f0e9218f453e730e7733fcacdeaf4996eef249718389dbcb`. Same play package and prior; it
does not read a belief package, so both may stay on the volume.

**Option 1, redeploy the release-45 image** (no build):

```bash
flyctl deploy --app shengji --ha=false --image registry.fly.io/shengji:deployment-01M4T9AVEVK51WP2GG8J34NRC9
```

**Option 2, edit `fly.toml`** (from release 46's env, after the release-46 steps above):

1. Delete the twelve release-46 lines (`SHENGJI_PV_WORLD_HISTORY_LEGAL`, `SHENGJI_PV_WORLD_HISTORY_DRAW`,
   `SHENGJI_PV_BELIEF_WORLDS`, `SHENGJI_PV_BELIEF_CKPT`, `SHENGJI_PV_BELIEF_SHA256`, the six `SHENGJI_PV_EXACT_*`,
   `SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST`).
2. Set `SHENGJI_BOT` to the release-45 name, kept as the comment directly above it:
   ```
   SHENGJI_BOT = 'pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7a73e8fbf1a8'
   ```
   Release 45's own additions stay: `SHENGJI_PV_BURY_WIDE_VALUE = '1'` and `SHENGJI_PV_BURY_WIDE_K = '64'`.
3. Run `fly deploy --ha=false`, then check `/healthz` reports the release-45 name.

### Deeper rollbacks

Each step removes one more set of flag lines and restores the name kept as a `fly.toml` comment, or redeploys
the image with the same `flyctl deploy --app shengji --ha=false --image …` form. No package moves until release 36.

| to release | `fly.toml` change from the release above it | image |
|---:|---|---|
| 44 | delete the two `SHENGJI_PV_BURY_WIDE_*` lines; name `…bury-hybrid-6c1fb26b80e6` | `deployment-01M4PC7724HSXC27PCEEREZWY4` (v44) |
| 43 | also delete `SHENGJI_PV_VALUE_DECLARE` | `deployment-01M4H37RYNM42YHH6ZPEC6GKCK` (v43) |
| 42 | replace the re-select line with `SHENGJI_PV_DOOMED_THROW_SWAP = '1'` | `deployment-01M49QGK2ZP18P143S8BXVW28X` (v42) |
| 38 | delete the doomed-throw line | `deployment-01M40ZWSAHNX4782CGKJ615YF7` |
| 36 | also delete the four release-38 rule lines | `deployment-01M3SG9NVC1AC3PNPEH5Y34N0D` |
| 29/30 | restore the three release-30 lines (`SHENGJI_BOT`, `SHENGJI_PV_CKPT`, `SHENGJI_PV_SHA256`) | `deployment-01M34KWRW4XWJWC6DCCYENFXTF` (r30) |
| 28 | `SHENGJI_BOT` back to the release-28 name (its keys stay in `fly.toml`) | `deployment-01M2M90VYR34R7CWKTTEA4C57V` |

The release-44 image command, verbatim:
`flyctl deploy --app shengji --ha=false --image registry.fly.io/shengji:deployment-01M4PC7724HSXC27PCEEREZWY4`.

**Prior-only rollback:** remove the four `SHENGJI_CWV_PRIOR_*` settings and restore the prior-less name;
`/healthz` must then show `"prior": null`.

## Release checklist

The gate every release passes (called "serving qualification" in `AI_POLICIES.md`); it held for releases 29–38
and 42–48. Commands below are release 48's; substitute the new release's package names and receipt.

**Before the deploy**

1. **Review and CI.** A non-author PASS on the release PR at its exact head, and all CI checks green. The
   package-gate step fetches the pinned packages from the `serving-packages` release, sha256-verifies them, and
   runs `server/tests/test_release48_fly_config.py` (release 46's `test_release46_fly_config.py` for the
   rollback), which builds the served bot from the `fly.toml` env through the server path (name, every knob,
   belief model, compiled solver, latency switches, one play with no fallback).
   `server/tests/test_bury_fly_config.py` pins the served name.
2. **Package upload, before the `fly.toml` switch.** The policy registers at server import and refuses a missing
   or mismatched package, so a deploy without it does not boot the served bot. The running machine does not read
   the new file.
   1. Verify the local copy with `shasum -a 256` against `424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e`
      (or fetch it from the `serving-packages` release asset of the same name).
   2. Upload: `fly ssh sftp shell -a shengji`, then `put <local>/s58-e6-42444515.npz /data/models/s58-e6-42444515.npz`.
   3. Verify in the machine: `fly ssh console -a shengji -C "sha256sum /data/models/s58-e6-42444515.npz"` must print
      `424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e`.
   Keep the previous release's belief package on the volume; its rollback reads it.
3. **Merged-tree full-round smoke**, against the sha-verified packages, from `server/`:
   ```
   SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python scripts/smoke_release45_bury.py --fly-toml ../fly.toml --map /data/models/smv3out-491ee4bf.npz=<local> --map /data/models/js-m1-0d17fd03.npz=<local> --map /data/models/s58-e6-42444515.npz=<local> --rounds 10 --full-round --receipt smoke48.jsonl
   ```
   Pass: validator PASS; the receipt's `bot.files` lists each package at its sha; the first-room reader (step 9)
   over `smoke48.jsonl.logs/*.jsonl` shows belief fallbacks 0, exact-eligible decisions > 0, abandons 0,
   fallbacks 0, with p95 and max recorded. The smoke must take the server path: release 25 passed the
   decision-identity gate yet stalled every live bot turn[^smoke].
4. **Evidence.** For a strength change, the served-bot screen against the current production release, read out
   (the ladder table in `AI_POLICIES.md`), plus any confirmation and latency packet the change requires.
5. **Jerry's word, in session.**

**Deploy**

6. From a clean worktree at the merge commit, when the room count is 0 (or on Jerry's word to drop idle rooms):
   `fly deploy --ha=false`.

**After the deploy**

7. **`/healthz`.** `bot` is the new served name, `fast: true`, `pv_search.sha256` `491ee4bf…`, `prior`
   `0d17fd03…`, `budget_seconds "3"`, `bury_arm hybrid`, `bury_budget_seconds "2"`, and `latency_switches` as
   the release's `fly.toml` sets them. `/healthz` does not report the belief package; the bot registering at all
   shows its sha matched.
8. **In-machine compiled/belief check** (read-only, same image and interpreter as the server):
   ```
   fly ssh console -a shengji -C "sh -c 'cd /app/server && SHENGJI_FAST=1 .venv/bin/python -c \"import sys; from shengji.ai.endgame_compact import HAVE_FAST, default_backend; from shengji.ai.belief_numpy import load_belief_numpy; m = load_belief_numpy(sys.argv[1], sys.argv[2]); print(HAVE_FAST, default_backend(), m.package_sha256[:8])\" /data/models/s58-e6-42444515.npz 424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e'"
   ```
   Must print `True compiled 42444515`. `False python` means `_endgame_fast` did not ship or does not import:
   roll back (the latency gate did not qualify the pure twin).
9. **First-room reader.** Fetch the log cache with `server/scripts/fetch_fly_logs.sh`, then read
   `logs/<CODE>.jsonl` once (read-only), over its `play` events that carry a `decision`:
   ```
   python3 - logs/<CODE>.jsonl <<'EOF'
   import json, sys
   rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
   d = [r["decision"] for r in rows if r.get("e") == "play" and r.get("decision")]
   bw = [x for x in d if "belief_fallback" in x]
   bfb = [x for x in bw if x["belief_fallback"]]
   leads = [x for x in d if x.get("exact_lead_status", "ineligible") != "ineligible"]
   follows = [x for x in d if x.get("exact_follow_attempted")]
   ab = [x for x in leads if x["exact_lead_status"] in ("abandoned", "skipped_budget")] + \
        [x for x in follows if x.get("exact_follow_abandoned")]
   fb = [x for x in d if x.get("schema") == "pv-search-fallback-v1" or not x.get("work_complete", True)]
   q = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(round(p * (len(xs) - 1))))] if xs else None
   secs = [x["seconds"] for x in d if "seconds" in x]
   endg = [x["seconds"] for x in leads + follows if "seconds" in x]
   bms = [x["belief_ms"] for x in bw if "belief_ms" in x]
   print(f"plays {len(d)} belief-drawn {len(bw)} belief fallbacks {len(bfb)} {sorted({x.get('belief_error') for x in bfb})}")
   print(f"exact-eligible leads {len(leads)} follows {len(follows)} abandons {len(ab)} fallbacks {len(fb)}")
   print(f"decision s all p50 {q(secs,.5)} p95 {q(secs,.95)} max {max(secs) if secs else None}; endgame p50 {q(endg,.5)} p95 {q(endg,.95)} max {max(endg) if endg else None}; belief_ms p50 {q(bms,.5)} p95 {q(bms,.95)}")
   EOF
   ```
   Record the lines under "Current production" with the room code. Server-side wall per decision is in the
   `bot_timing` events with `phase == "play"` (`compute_seconds`; `pacing_seconds` is the 0.7 s floor, not
   search); `model_search` events give queue/run stages; `declare_decision` records show `gate`.

   | rollback trigger | threshold |
   |---|---|
   | budget fallback | any `pv-search-fallback-v1` record |
   | belief fallbacks | above 1% of belief-drawn decisions |
   | exact abandons | above 2% of eligible decisions |
   | whole-decision p95 | above 1.5 s |
   | decisions at the 3 s budget | two or more in the first room (examine any one) |
   | bury budget fallbacks | `cwv-bury-fallback-v1` above a few percent |

   One belief fallback on the first decision after a boot (a cold preparation over 0.25 s) is recorded, not a
   trigger by itself.
10. **Room-log write check.** The first real game must create `/data/logs/<CODE>.jsonl` at its `round_start`
    (read-only: `fly ssh console -a shengji -C "ls -lt /data/logs" | head -3`) and move the `/healthz` `activity`
    counters: `rooms_created`, `games_started`, `rounds_recorded` and `records_written` all at least 1,
    `record_write_failures` 0, `last_record_write` at the game's time[^activity].
11. **Records.** Add the row to the Releases table and rewrite "Current production" and "Rollback".

**Completion criterion:** `/healthz` reports the expected `bot`, `pv_search.sha256` and `prior`, and the first
live room completes a game with no rollback trigger.

A shortlist package (releases 22–28, now only a rollback path) also needs the decision-identity gate before the
smoke: `server/scripts/cwv_serving_gate.py --serving --threshold 1000` (last run for release 28; never run for a
`pv-search` release). The older generic smoke is `server/scripts/cwv_serving_smoke.py`.

## Releases

Every deploy was `fly deploy --ha=false` on machine `48e7e35a9597e8`. Full per-release notes (served names,
evidence, smoke numbers, what else shipped from main): [docs_archive/deploy-through-2026-10-16.md](docs_archive/deploy-through-2026-10-16.md)
for releases 39–46, [docs_archive/deploy-releases-28-38.md](docs_archive/deploy-releases-28-38.md) for 28–38.

| release | deployed (ET) | what changed | bot or package | PR | image (Fly) |
|---:|---|---|---|---|---|
| 48 | 2026-10-24 10:18 | S58 belief package + `dtrx` + guarded greedy finish (`lgf lgfx lgfd2000`) + latency switches; evidence [r48cloud](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6383298163), [r48confirm](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6384251320), [v105lat](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6384912469) | new belief package `42444515…` | #1147 | `deployment-01M5Q4ACYEJ901SQB3BNMPC55A` (v47), main `f14ace15` |
| 46 | 2026-10-16 14:49 | v92 combo: belief worlds, exact endgame at 7, `vdef` | new belief package `763b5e05…` | #1072 | `deployment-01M530R14ARM0669QNJBW2RGTG` (v46), main `ab6fd1b2` |
| 45 | 2026-10-13 05:27 | wide value-only bury (`bwv`, K 64) | flag | #983 | `deployment-01M4T9AVEVK51WP2GG8J34NRC9` (v45), main `1ca97051` |
| 44 | 2026-10-11 17:05 | value-guided trump declaration (`vd`) | flag | #963 | `deployment-01M4PC7724HSXC27PCEEREZWY4` (v44), main `8ac9543e` |
| 43 | 2026-10-09 15:46 | doomed-throw re-select replaces the swap (`dtr`); correctness fix | flag | #953 | `deployment-01M4H37RYNM42YHH6ZPEC6GKCK` (v43), main `6b385b55` |
| 42 | 2026-10-06 19:08 | doomed-throw swap (`dts`); backend from main again | flag | #918 | `deployment-01M49QGK2ZP18P143S8BXVW28X` (v42), main `e3aa1724` |
| 41 | 2026-10-05 21:40 | web performance; frontend overlay[^overlay] | none | #845 | digest `sha256:4d1e796f7f2dd2c2ff337c05b09b2ebdf672c43ecf7232d2f5954b796c7b52ee` (v41) |
| 40 | 2026-10-05 11:34 | mobile landscape layout; frontend overlay | none | #829 | digest `sha256:2b24572af11b7098c32f4033956f5dde4ce39eeb6e2f95bba0b7f25d24fb6736` |
| 39 | 2026-10-05 01:47 | mobile UI, touch, accessibility; frontend overlay | none | #778 | `deployment-01M459KDH29EQFN9SDRH7P4GQ2` |
| 38 | 2026-10-03 09:41 | four search rules (`div rc tb la`) | flags | #698 | `deployment-01M40ZWSAHNX4782CGKJ615YF7` |
| 37 | 2026-10-01 01:1x | phone top bar one strip | none | #671 | `deployment-01M3TXZ85YHJM108TBPWKN8BB2` |
| 36 | 2026-09-30 11:53 | gen-5 SMV3 outcome head | play package `491ee4bf…` | #666 | `deployment-01M3SG9NVC1AC3PNPEH5Y34N0D` |
| 35 | 2026-09-28 01:49 | phone overflow menu, points bar | none | #653 | `deployment-01M3K8WQX7EXB3CYDMNGJ8MQHN` |
| 34 | 2026-09-27 20:22 | quieter phone table | none | #652 | `deployment-01M3JP62AR34FH5929FQC9GK7P` |
| 33 | 2026-09-26 11:50 | starting level in the room screen | none | #646 | `deployment-01M3F6FPRBXCK5Q4BDA0CET5A8` |
| 32 | 2026-09-26 10:2x | play on past Ace[^ace] | none | #644 | `deployment-01M3F1Q968BKYT8CD9GGE7XYMX` |
| 31 | 2026-09-25 12:51 | `create_room` accepts `start_level` | none | #638 | `deployment-01M3CQK3KMH55NDZRED6PDJ6XW` |
| 30 | 2026-09-22 09:13 | hybrid-bury duplicate fix | none | #607 | `deployment-01M34KWRW4XWJWC6DCCYENFXTF` |
| 29 | 2026-09-22 00:29 | `pv-search` W64/K8, soft head | package `ccade130…` | #588 | `deployment-01M33NZERJS18A0G2NNG7S5FJ8` |
| 28 | 2026-09-16 00:5x | JS-M1 joint net in the MC shortlist | package `0d17fd03…` | #425 / #435 | `deployment-01M2M90VYR34R7CWKTTEA4C57V` |
| 22–27 | — | W32 and shortlist era | see archive | — | [w32-fly-serving-through-2026-09-22.md](docs_archive/w32-fly-serving-through-2026-09-22.md)[^r22] |

## Infrastructure

### Ground rules (any host)

The server is a **single stateful process**: rooms and games live in memory, and clients hold WebSockets to it.

| rule | why |
|---|---|
| exactly one instance: no replicas, autoscaling or serverless | two instances would each hold half the rooms |
| deploy when quiet (0 rooms) | a restart drops games ("That game has ended.") |
| TLS at the platform or proxy | the frontend picks `wss://` on https pages itself |
| bot chosen by `SHENGJI_BOT` | source fallback is `mc` (N=10); Fly sets the served name |

`smart` and `heuristic` are cheaper difficulty choices, not strength-equivalent replacements;
`mc-s0-report-lcb` is the broader W32 play-policy rollback (`docs_archive/w32-fly-serving-through-2026-09-22.md`).

**Health check `GET /healthz`.** Reports `bot`, `fast`, `pv_search` (sha256, budgets, bury arm) and `prior`. Its
`activity` block counts, since the process started: rooms created, games started, rounds recorded (a
`round_start` record reached disk), records written, write failures, the last successful write (ISO UTC) and the
last failure's exception class and errno. `games_started` ahead of `rounds_recorded` is a room-log write failure;
all zeros for days is inactivity. The counters never gate the room path and carry no room code, path or payload,
so the endpoint stays unauthenticated.

**The `pv-search` mode** (production since release 29) is `train/pv_search_policy.py`, registered when
`SHENGJI_PV_CKPT` is set and refusing a package without its `SHENGJI_PV_SHA256` pin. Per play: heuristic anchor,
W sampled worlds, the policy head admits K candidates, the value head scores each, the best mean plays. On budget
expiry or error the anchor plays with a `pv-search-fallback-v1` record; otherwise the record is
`pv-search-decision-v1`. Mechanism detail: `AI_POLICIES.md` and the archive.

### Option A: Fly.io (recommended)

```bash
brew install flyctl && fly auth login
fly launch --copy-config --no-deploy   # uses fly.toml; pick an app name
fly volumes create shengji_data --size 1   # ONE volume (see below)
fly deploy --ha=false                      # ONE machine (see below)
```

`fly.toml` pins an always-on 512MiB machine with `auto_stop_machines = "off"` so idle games are not killed.
Custom domain: `fly certs add yourdomain.com` + a CNAME.

Two Fly defaults to override:
- **`--ha=false` is required.** Plain `fly deploy` creates TWO machines; the proxy would split players between
  them and rooms would appear missing. If you end up with two, `fly machine destroy <id> --force` one.
- **Ignore the volume redundancy warning** (`-n 2`). Extra volumes get claimed by phantom machines and wedge
  deploys ("volume already claimed" / "needs an unattached volume"); destroy extras with
  `fly volumes destroy <vol_id>`.

### Option B: any VPS with Docker

```bash
docker build -t shengji .
docker run -d --restart unless-stopped -p 127.0.0.1:8000:8000 shengji
```

Put Caddy in front for TLS (Caddyfile: `yourdomain.com { reverse_proxy
localhost:8000 }`); Caddy proxies WebSockets automatically.

### Option C: zero-deploy for friends

Tailscale (invite friends to your tailnet, run the server locally) or a Cloudflare Tunnel. No changes needed.

### Capacity

Policy cost, not the rules engine, sets CPU capacity.

| policy (measured on the Mini) | decision p50 / p95 |
|---|---|
| SmartBot | 0.05 ms / 0.13 ms |
| direct v11pair (NumPy) | 0.25 ms / 0.52 ms |
| `mc` (N=10) | 77 ms / 150 ms |
| production report-LCB vs `mc-strong` (earlier matched benchmark) | 0.390 s vs 0.127 s |
| release 48 play, one pinned cloud core (v105lat) | p95 0.566 s, p99 0.746 s, max 2.408 s; peak RSS +26,792 kB over release 46 |
| release 46 combo play, one perf core (v93lat) | p95 0.187 s, p99 0.400 s, max 2.404 s; peak RSS +48 MiB over release 45 |

- Fly's shared-cpu-1x is slower and shared, so the release-48 tail may reach the 3 s budget there and play the
  baseline; the first-room reader checks that.
- The 512MiB machine fits bounded serving probes; that is not a concurrency or worst-case memory guarantee.
- Off-loop execution hides event-loop blocking and overlaps the 0.7 s pacing floor; it does not make search free.
  Each turn snapshots after the latest play, computes, then revalidates before commit.
- Load-test the chosen policy and room mix before advertising capacity. Memory per room is small; more than one
  process would need external state and room-affinity routing.

[^cmp]: Jerry, in session 2026-10-24: "Yes screens should compare vs our prod policy of r48". Before that, release 46
    (Jerry 2026-10-16, #707 issuecomment-6223485189), and before that release 45 (Jerry 2026-10-13, #988 issuecomment-6142666693). Confirmations keep their parent's comparator.
[^belief]: Registration refuses a missing or mismatched belief file, so a served bot at all means the sha matched;
    the in-machine line (Release checklist, step 8) prints its first eight hex digits.
[^fast]: Its `ls` fails the build if a `.so` is missing; `.dockerignore` keeps a local Darwin `_endgame_fast*.so`
    out of the build context. The pure-Python twin returns identical results, only slower: a `python` backend in
    production is a latency regression, not a wrong play.
[^smoke]: `server/scripts/cwv_serving_smoke.py` builds the `pv-search` bot when `SHENGJI_PV_CKPT` is set; the
    full-round smoke runs the 7-card endgames and the belief proposal through the server path.
[^activity]: Production wrote no room log between 2026-10-09 19:04Z and at least 10-15, and nothing could tell
    inactivity from a silent write failure; release 46 is the first deploy with the counters. `games_started`
    moving while `rounds_recorded` stays 0 is a write failure, named by `last_record_failure` and the warning line
    `room <CODE> event logging failed (<class> errno=<name>)`. Whether to play that game deliberately is Jerry's call.
[^overlay]: Releases 39–41 were frontend-only overlays on the immutable release-38 image; the recipe is in the
    [#778 release record](https://github.com/jerryyyu/shengji/pull/778#issuecomment-5988860620). Do not replace
    main's normal Dockerfile with it. Release 42 superseded the recipe.
[^ace]: Rolling back past release 32 reverts the Ace rule (restores one-game-and-stop).
[^r22]: Heading "Moved from DEPLOY.md on 2026-10-01": the release-28 plan as approved, release 27
    (`deployment-01M2M1B48P44H5HJXEP6ETYQXE`), the release-26 image rollback, release 25, and the release-22
    boundary. Release 24's image is `deployment-01M2BGBXE7JXWYBEVWNMG2YM5A`.
