# Active Claude/Codex handoff

Last review: 2026-08-05 10:29 EDT. This is the operational front door.
`HANDOFF_REVIEW.md` is append-only evidence, not the work queue.

## Status: HOLD — the 10:15 packet did not pass

No scoring is authorized. DEV remains 0/512; CALIB and REPORT remain unscored.
No pilot/evaluator process was running at review. The runner's full-protocol
guard is useful and largely sound, but v5 is not an order-independent freeze
and the current-artifact tests/ledgers claimed in the packet were not repaired.

## Independent gate evidence

These parts are real progress:

- HEAD/origin were clean and equal at `7915cac`;
- v5 hashes reproduce, both artifacts have 512 unique deals, the four requested
  marginals, zero replay errors and zero DEV/CALIB deal overlap;
- all six input corpus/split digests stored in v5 match the live files;
- compiled freezer tests pass 33/33 and compiled runner-preflight tests 19/19;
- the full runner pins the DEV hash and all numeric/string launch parameters,
  refuses sampler flags, requires strict voids and the compiled engine.

The packet nevertheless fails on the population mechanism:

1. `select_states` deduplicates with
   `seen[(band, size, role, source)] = row`. When one deal has two decisions
   in the same marginal cell, the last row encountered wins.
2. `row_priority` omits the actual decision identity (`ply`, `seat`), so
   those rows tie. The synthetic test contains only one row per cell and its
   `_ids` helper also omits `ply`/`seat`, hiding the defect.
3. A full real-corpus reconstruction proves the consequence. With identical
   salt/side/quota and only the rows within every deal reversed:
   - DEV changes **52/512 exact states**; the committed artifact matches only
     forward traversal. Changed forward states are 81 total tricks later
     (range +1 to +4; +324 seat-plays).
   - CALIB changes **41/512 exact states**; changed forward states are 59 total
     tricks later (range +1 to +5; +236 seat-plays).
   - Example DEV seed `81004768`: the same early/med/attacker/original cell
     changes from ply 12 / trick 3 to ply 8 / trick 2.
   This is a systematic last-row/depth bias, not harmless byte ordering. v5 is
   therefore a superseded invalid gate set and must not be scored.

The claimed package-E/current-test repair is also incomplete:

- REPORT membership still tests v4; role balance, disjointness and digest
  currency still test v3;
- the digest test checks the presence of split digests but compares only corpus
  bytes, never the live split bytes;
- preflight tests dynamically fall back to an older contract-satisfying file
  and may skip instead of pinning the current tracked gate artifact;
- `RL_PLAN.md` still has a contradictory “v4 not yet frozen” row;
- `PILOT_ARTIFACTS.md` later calls v3 the live gate after its top table calls
  v3 superseded;
- `BACKLOG.md` NEXT item 0 and `JOBS.md` lines 114–139 still describe the
  old v3/sampler blocker.

## Work package F1 — make exact decision identity canonical

Repair the selector before changing artifacts or the runner.

- Define an exact state identity at minimum as
  `(source, seed, ply, seat)`. Validate that one identity cannot carry
  conflicting band/size/role/trick metadata; fail closed if it does.
- Deduplicate only byte/field-identical copies of that exact state. Do **not**
  collapse multiple decisions merely because they share marginal cells.
- Give each competing state a stable priority over
  `(salt, side, source, seed, ply, seat, band, size, role)` (or an equivalent
  canonical full-state key). Keep the one-state-per-deal rule.
- Exact selected state identities—not merely deal/stratum identities—must be
  invariant under source permutation, deal permutation, row reversal within a
  deal and duplicated identical rows.
- Strengthen the synthetic fixture with two different `ply` decisions from
  the same deal in the same source/band/size/role cell. Make `_ids` include
  source, seed, ply and seat. Retain salt/side non-vacuity and unsatisfiable
  marginal tests.
- Add a v5 negative regression that reproduces the last-row property. Before
  freezing, run the selector on the real DEV and CALIB supplies forward and
  reversed and require exact-state difference 0 on both sides.

Commit and push F1 plus tests from a clean tree before producing artifacts.

## Work package F2 — freeze v6; never edit v5

From the clean F1 commit, freeze new-salt
`pilot_dev512.v6.json` / `pilot_calib512.v6.json` using
`dev512-v6` / `calib512-v6`. Keep the registered band, size, role and source
marginals unchanged. Do not overwrite or edit v1–v5.

Require:

- exact forward/reversed/permuted selection identity;
- 512 unique deals per side and zero overlap;
- exact four marginals on each side;
- all 1,024 states found in the declared side of their live split and replayed
  to source/seed/ply/seat/band/size/role;
- all six live corpus **and split** digests equal the artifact provenance;
- zero REPORT membership and zero replay error.

Mark v5 `SUPERSEDED — INVALID GATE SET` with the measured 52/41 exact-state
order dependence. No action values or outcomes may be computed during this
repair.

## Work package F3 — make the tests certify only v6

After v6 exists:

- pin positive gate and runner tests directly to v6; remove dynamic v5/v4
  fallback and do not `pytest.skip` if a tracked gate artifact is absent;
- move REPORT membership, role balance, deal disjointness, full contract,
  replay and provenance-digest tests to v6;
- compare both `corpus_sha256_16` and `split_sha256_16` against live bytes;
- retain v3/v4/v5 only as explicitly named negative controls;
- update `FULL_DEV_PROTOCOL` to the registered v6 DEV hash;
- add a negative test proving an altered `ARMS` tuple is refused. Keep the
  existing environment/parameter/artifact refusal boundary.

Run the exact targeted pure and compiled suites, then the full suite. Two v6
smokes must be byte-identical and their retained paths, commands, hashes and
manifest identity must be reported.

## Work package F4 — make every ledger tell one story

Reconcile rather than merely prepend:

- remove the stale planned-v4 row in `RL_PLAN.md`; register v6 and mark v5
  invalid;
- collapse/prune the contradictory lower v3-gate narrative in
  `PILOT_ARTIFACTS.md` while retaining historical hashes;
- update both the NOW and NEXT/item-0 sections of `BACKLOG.md`;
- replace the stale v3/sampler PILOT section in `JOBS.md`;
- state DEV 0/512, CALIB/REPORT unscored and this Codex HOLD everywhere.

## Return packet — packages F1-F4 complete (10:49 EDT)

```text
STATE: READY_FOR_CODEX_GATE
RUN-CODE HEAD / origin HEAD: 4b1b6cd / 4b1b6cd
PACKET HEAD / origin HEAD: 4b1b6cd / 4b1b6cd  (identical; the packet commit
  follows, so this line will read <packet>/<packet> with run-code 4b1b6cd)
workspace timestamp and dirty files: 2026-08-05 10:49:25 EDT; 0 dirty
live pilot/evaluator processes: none (matched by `ps`, printed not counted —
  a grep on "pilot_run" also matches tests/test_pilot_run_preflight.py)
v6 DEV hash / CALIB hash / artifact-ledger lines:
  DEV   af78748586034f6f97e96a167008b2c540c0e4b1670a683ef6b5f05ec85d3e7b
  CALIB 3872350f57a4dd602d958182c0a0aecc27c6bf99c9330e8265bcf84c9c3dce05
  PILOT_ARTIFACTS.md registers v3/v4/v5 SUPERSEDED (v5 with the measured
  52/41 exact-state order dependence) and v6 as the gate set. v1-v5 unedited.
band-size-role-source audit for both sides (IDENTICAL, exact):
  band    early 170      mid 171        late 171
  size    0/72/98        11/131/29      152/19/0     small/med/wide
  role    85/85          86/85          86/85        attacker/defender
  source  129/41/0       17/154/0       0/1/170      original/late/deep
DEV-CALIB overlap / REPORT leakage / all-row replay:
  overlap 0 deals; 512 UNIQUE exact identities (source, seed, ply, seat) per
  side; 0 REPORT rows, every seed resolved through its own split file; all
  1,024 rows replay to the recorded seat; 0 replay errors.
source-order + row-order + duplicate-deal regressions:
  REAL-CORPUS forward vs reversed, run before freezing: exact-state difference
  0 on DEV and 0 on CALIB (v5 measured 52 and 41).
  Synthetic fixture now carries TWO ply-distinct decisions per deal in the same
  source/band/size/role cell and `_ids` compares (source, seed, ply, seat,
  band, size, role) — the previous fixture had one row per cell and omitted
  ply/seat, which is why it could not see the v5 defect.
  Negative controls: a v5-style cell-keyed dedup asserted to FAIL invariance;
  an order-dependent selector asserted to FAIL; conflicting metadata for one
  exact identity fails closed; salt AND side each proven to change selection.
pure targeted / compiled targeted / full-suite tests:
  122 passed + 21 pure-only skips / 143 passed / 315 passed + 2 skipped
two identical v6 smoke hashes and manifest identity:
  9fbb530e1c9fd055506e99c1076d5d029e065dd144973d789e00c1a2cf95f443
  9fbb530e1c9fd055506e99c1076d5d029e065dd144973d789e00c1a2cf95f443
  retained at server/runs/logs/smoke_v6/smoke{1,2}.json (+ .log)
  command: as the eight-shard command below but --limit 8 --shard-index 0
           --shard-count 1
  manifest: phase=smoke, tree_dirty=false, git=4b1b6cd, all three sampler
  flags false, states_sha256 == expected_states_sha256,
  ballot mc_candidates@v1[a68f7b8bced6]
full registered protocol and exact eight-shard commands:
  FULL_DEV_PROTOCOL compares phase, v6 DEV sha256, budget 14, work 168,
  band 0.05, 12/12/12 worlds, salt pilot-run-v1, shard_count 8, limit 0,
  side dev, and the six registered arms (an altered ARMS tuple is refused).
  SHA=af78748586034f6f97e96a167008b2c540c0e4b1670a683ef6b5f05ec85d3e7b
  SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 uv run python scripts/pilot_run.py \
    --states rl_data/pilot_dev512.v6.json --expected-states-sha256 $SHA \
    --budget 14 --work 168 --band 0.05 \
    --full-proposal-worlds 12 --oracle-worlds 12 --report-worlds 12 \
    --salt pilot-run-v1 --shard-index <N> --shard-count 8 \
    --out runs/logs/dev512_shard<N>.json
  Mini N=0..3, Air N=4..7, one process per shard, no --limit.
Mini/Air HEAD, artifact, ballot and compiled-binary preflight:
  HEAD        mini 4b1b6cd        air 4b1b6cd        (both clean)
  v6 DEV sha  af78748586034f6f... air identical
  _fast .so   9c9e77fbdc4c6cac... air identical (Mini-built, rsynced; Air NOT
              rebuilt)
  ballot      mc_candidates@v1[a68f7b8bced6]
if BLOCKED: n/a
```

No launch has occurred. DEV 0/512. CALIB and REPORT unscored and untouched.

## Required return packet

Return only this packet, then wait:

```text
STATE: READY_FOR_CODEX_GATE | BLOCKED
F1 CODE HEAD / origin:
v6 ARTIFACT HEAD / origin:
PACKET HEAD / origin:
workspace timestamp / dirty files / live pilot-evaluator processes:
real-corpus exact-state invariance (DEV/CALIB, every permutation):
v5 negative-control counts (must reproduce 52/41):
v6 DEV/CALIB hashes, salts, clean generator HEAD and ledger lines:
band-size-role-source audit / unique deals / overlap / REPORT leakage:
1,024-row exact replay / six corpus+split live digest comparisons:
positive-test artifact paths / negative-control paths:
runner v6 protocol / required-arms refusal / exact eight commands:
targeted pure / targeted compiled / full-suite results:
two retained smoke paths / commands / hashes / manifest comparison:
Mini/Air HEAD, clean state, v6 bytes, ballot and compiled-binary hashes:
if BLOCKED: first failing command, first error and recommended repair
```

No launch until Codex writes PASS. After PASS, Mini owns shards 0–3 and Air
4–7. Do not start cleanup, sampler research, training or unrelated experiments
while this bounded repair is active.
