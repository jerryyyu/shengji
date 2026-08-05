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

## Return packet — 10:54 audit items closed (11:49 EDT)

```text
STATE: READY_FOR_CODEX_GATE
RUN-CODE HEAD / origin HEAD: 8897e41 / 8897e41
PACKET HEAD / origin HEAD: 8897e41 / 8897e41
  (previous packet mis-stated this as 4b1b6cd when HEAD was 2bd99b0 — the
   run-code and packet commits were the same object and I reported the older
   one. Corrected.)
workspace timestamp and dirty files: 2026-08-05 11:49:34 EDT; 0 dirty
live pilot/evaluator processes: none
v6 DEV hash / CALIB hash / artifact-ledger lines: UNCHANGED, no re-freeze
  DEV   af78748586034f6f97e96a167008b2c540c0e4b1670a683ef6b5f05ec85d3e7b
  CALIB 3872350f57a4dd602d958182c0a0aecc27c6bf99c9330e8265bcf84c9c3dce05
  PILOT_ARTIFACTS.md top table authoritative: v3/v4/v5 SUPERSEDED, v6 gate.
  The lower v3 section is now headed HISTORICAL with its GATE SET labels
  struck through; RL_PLAN's planned "NOT YET FROZEN" pilot-v4 row is gone.
G1 — dedup now refuses ANY non-identical duplicate:
  full canonical row compared, not band/role/tricks/size. Regression covers
  n_candidates 5-vs-9 and is_banker_seat true-vs-false — both outside the
  marginals, which is why the subset check missed them — plus a positive case
  asserting identical copies are still accepted.
  ALSO FIXED, found while testing: an unsatisfiable tightest cell raised
  IndexError instead of reporting. Fail closed now means a message.
v6 needs NO re-freeze, verified through the REAL freezer:
  dry run at salt dev512-v6 reproduces the frozen DEV artifact 512/512.
  (My hand-rebuilt probe said 506/512; the probe was unfaithful, not the code.
   Recording it because I nearly reported it as drift.)
band-size-role-source audit for both sides (IDENTICAL, exact):
  band 170/171/171; size 0/72/98, 11/131/29, 152/19/0;
  role 85/85, 86/85, 86/85; source 129/41/0, 17/154/0, 0/1/170
DEV-CALIB overlap / REPORT leakage / all-row replay:
  overlap 0; 512 unique exact identities per side; 0 REPORT rows; all 1,024
  rows replay; 0 replay errors
source-order + row-order + duplicate-deal regressions:
  SOURCE PERMUTATION now verified FAITHFULLY, closing the gap I flagged last
  cycle: SHENGJI_SOURCES_ORDER=deep,late,original and late,original,deep each
  reproduce v6 512/512 through the real freezer; a direct unit test added.
  Real-corpus forward-vs-reversed exact-state difference remains 0/0.
  Negative controls retained: v5-style cell-keyed dedup FAILS invariance; an
  order-dependent selector FAILS; salt and side each change selection.
pure targeted / compiled targeted / full-suite tests:
  126 passed + 21 pure-only skips / 147 passed / 319 passed + 2 skipped
two identical v6 smoke hashes and manifest identity:
  650ac2139e176ebe211f086177ff032658b2291e699b6e015294fd6df0cd2099
  650ac2139e176ebe211f086177ff032658b2291e699b6e015294fd6df0cd2099
  retained at server/runs/logs/smoke_v6/smoke{3,4}.json (+ .log); smoke{1,2}
  are the pre-fix pair at 9fbb530e1c9fd055 and are kept for comparison
  manifest: phase=smoke, tree_dirty=false, git=8897e41, all three sampler
  flags false, states_sha256 == expected_states_sha256
full registered protocol and exact eight-shard commands: unchanged from the
  previous packet except HEAD; FULL_DEV_PROTOCOL pins the v6 DEV hash and an
  altered ARMS tuple is refused.
  SHA=af78748586034f6f97e96a167008b2c540c0e4b1670a683ef6b5f05ec85d3e7b
  SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 uv run python scripts/pilot_run.py \
    --states rl_data/pilot_dev512.v6.json --expected-states-sha256 $SHA \
    --budget 14 --work 168 --band 0.05 \
    --full-proposal-worlds 12 --oracle-worlds 12 --report-worlds 12 \
    --salt pilot-run-v1 --shard-index <N> --shard-count 8 \
    --out runs/logs/dev512_shard<N>.json
  Mini N=0..3, Air N=4..7, one process per shard, no --limit.
Mini/Air HEAD, artifact, ballot and compiled-binary preflight:
  HEAD        mini 8897e41        air 8897e41        (both clean)
  v6 DEV sha  af78748586034f6f... air identical
  _fast .so   9c9e77fbdc4c6cac... air identical (Mini-built, rsynced)
  ballot      mc_candidates@v1[a68f7b8bced6]
if BLOCKED: n/a
```

No launch. DEV 0/512. CALIB and REPORT unscored and untouched.

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
