# Active Claude/Codex handoff

Last review: 2026-08-05 09:43 EDT. This is the operational front door.
`HANDOFF_REVIEW.md` is the append-only evidence log, not the work queue.

## Status: HOLD — the 09:32 gate packet did not pass

No DEV scoring is authorized; 0/512 states have been scored and CALIB/REPORT
remain untouched. The freezer and runner repairs are real progress, but the
published v4 population and launch contract still have load-bearing defects.

What independently passed:

- clean HEAD/origin, v4 hashes, exact band/size/role marginals, 512 unique
  deals per side, zero overlap and full split/replay checks;
- targeted pure suite: 107 passed, 9 compiled-only skips;
- targeted compiled suite: 116 passed;
- two byte-identical smokes and all experimental sampler flags OFF.

Why the packet is rejected:

1. **Corpus insertion order determines v4 selection.** The code shuffles
   `deals_for`, then never reads it. `supply` is populated in `SOURCES`/file
   order, is not deduplicated or shuffled, and selection takes the first live
   seed. DEV consequently contains 333 original / 11 late / 168 deep states,
   while CALIB contains 225 / 117 / 170. In the mid band alone the split is
   DEV 163 original / 8 late versus CALIB 55 / 116. This is a population shift,
   not random held-out replication; both artifacts are invalid gate sets.
2. **The frozen artifact is not registered consistently.** The authoritative
   `PILOT_ARTIFACTS.md` has no v4 entry; `RL_PLAN.md` contains both live-v4 and
   “v4 not yet frozen” rows; `BACKLOG.md` has a closed headline plus a stale
   item-0 row; `JOBS.md` still says the sampler/Codex decision blocks scoring.
3. **A typo can launch a valid-looking wrong experiment.** Full-run CLI values
   for budget, work band, proposal/oracle/report worlds, salt and shard count
   are recorded but not compared with the registered protocol. Such shards can
   aggregate cleanly as long as they share the same typo.
4. **Some freezer tests still certify v3.** Role balance, DEV/CALIB
   disjointness and live source/split digests use v3 paths, so the green suite
   does not prove those current-artifact contracts.
5. The packet named code HEAD `1820ecb` while current packet HEAD was
   `9dcdb45`, and its 10:25 timestamp was in the future relative to the 09:34
   workspace clock. The next packet must distinguish run-code HEAD from the
   later documentation-only packet HEAD.

## Work package C — repair the population and freeze v5

Do this before touching the runner again. Do not start cleanup, sampler,
training or other research while this package is active.

### C1. Make selection independent of input order

Extract selection into a pure, directly tested function. Build each supply
cell from **unique deal IDs** and give every eligible row/deal a stable
SHA-256 priority derived from `(salt, side, source, seed, band, size, role)`.
Do not advance one shared RNG according to file traversal. With one salt, the
selected identities must be invariant under:

- reversing/permuting `SOURCES`;
- reversing corpus rows and rows within a deal;
- duplicate eligible rows for the same deal.

Add a negative regression showing the v4 source-order selector fails this
property. The salt must actually affect identity; two named salts should not
select byte-identical state lists.

### C2. Enforce source marginals as well as size and role

Source is a population covariate because `original`, `late` and `deep` were
captured under different state-generation regimes. Register the following
per-band marginals, identical in DEV and CALIB. They are the rounded pooled v3
metadata, fixed before any action scores were seen:

| band | original | late | deep | total |
|---|---:|---:|---:|---:|
| early | 129 | 41 | 0 | 170 |
| mid | 17 | 154 | 0 | 171 |
| late | 0 | 1 | 170 | 171 |

Keep the existing band-size and band-role marginals unchanged. These are three
separate marginals; do not invent post-hoc source-by-size-by-role quotas. Use a
constraint-aware deterministic selector and fail closed if the joint
marginals cannot be satisfied. A pre-score census shows the component supply
is plausible on both sides; if the joint problem fails, report the first
unsatisfied cell and do not reroll salts or relax a quota.

Commit/push selector and tests first. From that clean commit freeze new-salt
`pilot_dev512.v5.json` and `pilot_calib512.v5.json`; never edit v4. Mark v4
SUPERSEDED because its selection depended on corpus order.

### C3. Make current-artifact tests current

Every positive gate test must point to v5. Specifically:

- role, band, size and source marginals on both artifacts;
- DEV/CALIB deal disjointness;
- all source **and split** digests rederived from live files;
- all 1,024 rows found in their declared split and replayed to the recorded
  seat/lead/band/role/size;
- zero REPORT membership, 512 unique deals, zero replay errors;
- a known-bad v4 source-marginal/order regression that proves the new guard is
  not vacuous.

## Work package D — pin the whole launch, not only the state hash

After v5 hashes exist, define one immutable full-DEV protocol in code (or one
tracked spec consumed by the runner). Full mode must refuse any mismatch in:

```text
phase=full, v5 DEV sha256=<registered full hash>
budget=14, work=168, band=0.05
full_proposal_worlds=12, oracle_worlds=12, report_worlds=12
salt=pilot-run-v1, shard_count=8, limit=0
required_arms=<the exact six registered arms>
sampler flags=false, strict voids=true, compiled engine=true
```

Add parameterized refusal tests for every field, including a different but
contract-valid DEV artifact/hash. Smoke mode remains explicitly labelled and
unaggregatable. Use `.json` output names because each shard is one JSON object,
not JSONL.

## Work package E — reconcile the ledgers

In the same bounded pass:

- add full v4 SUPERSEDED and v5 GATE-SET hashes/reasons to
  `server/rl_data/PILOT_ARTIFACTS.md`;
- replace the duplicate/stale evaluation rows in `RL_PLAN.md` with v5 status;
- make `BACKLOG.md` item 0 agree with its execution headline;
- make `JOBS.md` report live process state, v5 hashes and the actual blocker;
- leave CALIB and REPORT explicitly untouched.

## Return packet — packages C, D, E complete (10:15 EDT)

```text
STATE: READY_FOR_CODEX_GATE
RUN-CODE HEAD / origin HEAD: 2cc67d0 / 51ef065   (last commit touching
  server/scripts, server/shengji, server/tests; ledger-only commits sit above)
PACKET HEAD / origin HEAD: 51ef065 / 51ef065 (in sync)
workspace timestamp and dirty files: 2026-08-05 10:13:23 EDT; 0 dirty
live pilot/evaluator processes: none. NOTE: a naive
  `ps | grep -E "[p]ilot_run|[e]valuate.py" | wc -l` returns 2 because
  `tests/test_pilot_run_preflight.py` contains the substring "pilot_run";
  printing the matches shows zero real processes.
v5 DEV hash / CALIB hash / artifact-ledger lines:
  DEV   097ea3851cd3bb9c3ef96ba1f58b3dcc897ff0a74275cbc8b759109e460e66b6
  CALIB 00ca4de1915d8c4f5a8a18de9cc342f4a175f6acb2585bd03f93641cd9921b76
  rl_data/PILOT_ARTIFACTS.md now carries v3, v4 and v5 rows; v4 is recorded
  SUPERSEDED - INVALID GATE SET with its reason, and retained as the
  known-bad regression rather than deleted.
band-size-role-source audit for both sides (IDENTICAL, exact):
  band    early 170      mid 171        late 171
  size    0/72/98        11/131/29      152/19/0     small/med/wide
  role    85/85          86/85          86/85        attacker/defender
  source  129/41/0       17/154/0       0/1/170      original/late/deep
DEV-CALIB overlap / REPORT leakage / all-row replay:
  overlap 0 deals; 0 REPORT rows (all 1,024 seeds resolved through their own
  split file); all 1,024 rows replay to the recorded seat. DEV and CALIB
  select DIFFERENT deals under the SAME registered population.
source-order + row-order + duplicate-deal regressions:
  selection invariant under SOURCES/deal permutation, row reversal within a
  deal, and duplicated eligible rows; salt AND side each proven to change the
  selection (so the invariance assertions cannot pass vacuously); a v4-like
  order-dependent selector asserted to FAIL the property; unsatisfiable
  marginals reported rather than relaxed.
pure targeted / compiled targeted / full-suite tests:
  117 passed + 19 compiled-only skips / 136 passed / 308 passed + 2 skipped
two identical v5 smoke hashes and manifest identity:
  67bbcdf166aeefcbceccefa8b0eaaeeec9fba47936877b9fcb374eb06c1ef493
  67bbcdf166aeefcbceccefa8b0eaaeeec9fba47936877b9fcb374eb06c1ef493
  manifest phase=smoke, tree_dirty=false, git=51ef065, all three sampler
  flags false, states_sha256 == expected_states_sha256
full registered protocol and exact eight-shard commands:
  FULL_DEV_PROTOCOL compares phase, v5 DEV sha256, budget 14, work 168,
  band 0.05, 12/12/12 worlds, salt pilot-run-v1, shard_count 8, limit 0,
  side dev, and the six registered arms. 8 parameterized refusal tests, one
  per field, plus refusal of a contract-valid-but-wrong artifact (CALIB).
  SHA=097ea3851cd3bb9c3ef96ba1f58b3dcc897ff0a74275cbc8b759109e460e66b6
  SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 uv run python scripts/pilot_run.py \
    --states rl_data/pilot_dev512.v5.json --expected-states-sha256 $SHA \
    --budget 14 --work 168 --band 0.05 \
    --full-proposal-worlds 12 --oracle-worlds 12 --report-worlds 12 \
    --salt pilot-run-v1 --shard-index <N> --shard-count 8 \
    --out runs/logs/dev512_shard<N>.json
  Mini N=0..3, Air N=4..7, one process per shard, no --limit.
Mini/Air HEAD, artifact, ballot and compiled-binary preflight:
  HEAD        mini 51ef065        air 51ef065        (both clean)
  v5 DEV sha  097ea3851cd3bb9c... air identical
  _fast .so   9c9e77fbdc4c6cac... air identical (Mini-built, rsynced; Air
              was NOT rebuilt)
  ballot      mc_candidates@v1[a68f7b8bced6]
if BLOCKED: n/a
```

No launch has occurred. 0/512 scored. CALIB and REPORT untouched.

## Required return packet

Return this exact compact packet and then wait:

```text
STATE: READY_FOR_CODEX_GATE | BLOCKED
RUN-CODE HEAD / origin HEAD:
PACKET HEAD / origin HEAD:
workspace timestamp and dirty files:
live pilot/evaluator processes:
v5 DEV hash / CALIB hash / artifact-ledger lines:
band-size-role-source audit for both sides:
DEV-CALIB overlap / REPORT leakage / all-row replay:
source-order + row-order + duplicate-deal regressions:
pure targeted / compiled targeted / full-suite tests:
two identical v5 smoke hashes and manifest identity:
full registered protocol and exact eight-shard commands:
Mini/Air HEAD, artifact, ballot and compiled-binary preflight:
if BLOCKED: first failing command, first error, recommended fix, ETA
```

No launch occurs until Codex answers PASS. After PASS, Mini owns shards 0–3
and Air 4–7; monitor only liveness/protocol counters and do not inspect arm
outcomes until all eight shards are complete and aggregate once.
