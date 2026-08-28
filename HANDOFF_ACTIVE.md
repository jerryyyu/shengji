# Active Claude/Codex handoff

> Current operational state only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> The latest authentic exact-head marker on remote main controls.

Last reconciled: **2026-08-28 17:18 EDT**. Remote main before this refresh:
`2354ee21b408b866aa8588196893f2a9c19b20b4`.

## Review queue — one precise ask

Review **PR #164**, exact source head
`d9ad99f6377040424821d79071e12435fde802ae`, as one consolidated
source+capacity+population+freeze packet. Do not split this into an
intermediate source review and a later freeze review.

Inputs already reviewed or mechanically reproduced:

- PR #163 capacity source PASS: exact head
  `e7310db5d2d89599d89b8f18718dfffc06a971db`, ledger commit `9fe8460`.
- Capacity receipt:
  `/opt/value-afterstate-v0-capacity-receipt-e7310db-r1.json`, external
  SHA-256 `10bdd80f8f2d0342fd290194de1a84ecc8bc92fcb0ca10a06dcf3fe779bedc5b`.
  Claude independently accepted the receipt at main commit `2354ee2`; it is
  outcome-blind and reports a 0.69-GiB cgroup peak under the 30-GiB cap.
- Population root:
  `/opt/value-afterstate-v0-population-d9ad99f-r1`.
  Packet external SHA-256
  `019a122950f79c148f674bd262fec4231c56056f793158483b4b256c350de282`,
  internal packet SHA-256
  `9d3261b8dd6d59a8db858ffd64c8abb939fefff88176585c10602c510827e7c3`;
  public manifest external SHA-256
  `48155bb59aae2e524bbf3b407a07b68b78dc4b052909c68d8e84d6df6964f581`,
  internal manifest SHA-256
  `361389bfd87beebd6c10b4c40712638ef7db900ac0b1a6f62e6dfbd11ea55912`;
  audit manifest external SHA-256
  `67fba564ab19941c19051a350a931f116d8154b9ce5757af9fe638c8d0a53c75`,
  internal manifest SHA-256
  `daf451dab7a0736d43f8374e9eede9e504084609214526dc25f22a7ba5e314ce`.
- Immutable freeze:
  `/opt/value-afterstate-v0-freeze-d9ad99f-r1.json`, external SHA-256
  `735b367e824e1510b7a951e2fd3ef373c8f3688107d622152a1dfc12830b43a0`,
  internal freeze SHA-256
  `1139e727fd29f5e295135aedc7e08c3a52508a2deb3927f37629158313cfbc12`.
- Exact source/runtime checkout:
  `/opt/value-afterstate-v0-scientific-d9ad99f`, venv
  `/opt/value-afterstate-v0-scientific-d9ad99f-venv`; Python 3.14.4,
  Torch 2.13.0+cu130, 16 CPUs / 16 Torch threads, compiled native SHA-256
  `b45f93a5c0bce043fe63c4b4bc44636c71d9514888fd3249e5ea3dd8039a044f`.

Packet facts to bind:

- 520 state groups: train 364, calibration 52, report 52, provider-audit 52.
  Sources: production 312, reviewed PT-Sol 156, mechanics-hard 52.
- Covers all 13 trump ranks, C/D/H/S/no-trump, attacker/defender,
  early/middle/late, and lead/follow. One exact complete world per state.
- PT-Sol supplies state distribution only. Numeric targets are engine-owned
  terminal signed-level outcomes after engine-applied candidate actions.
- Model: one fresh eight-seed, common-epoch, medium `V_world_after` cohort;
  raw 204-category outcome head. Search remains final authority; BELIEF is not
  required.
- Gates: held-out categorical NLL vs a train-only prior; at least 6/8 positive
  member means; provider-audit expected-utility error, simple regret, and
  protected-incumbent non-regression; named negative controls.
- Parallelism: 16 long-continuation label workers and 16 independent
  reconstruction workers. Training/evaluation run on the same 16-CPU host with
  16 Torch CPU/interop threads. Frozen projected label wall is
  6,926,591,581,728 ns (1h55m27s) under the 8-hour cap.
- R4 lessons are explicit: measured capacity before freeze; reusable sealed
  population; stage-specific durable attempts; completed dataset and training
  artifacts survive later failures; graceful common-epoch training truncation;
  progress/elapsed/ETA for every long stage; durable report attempt before
  held-out open; mandatory immediate reconstruction; separate full independent
  verification; exact clean source/runtime/native binding.
- Remaining bounded atomic exposure is label generation itself. Its frozen
  projection is under two hours with a 2x per-continuation wall multiplier,
  rather than a multi-day all-or-nothing training run.

Validation at the exact head: PR CI green; focused pure 96/96; focused strict
compiled 96/96; strict `-P -B` launcher imports; `git diff --check` clean;
source tree contains no `.pyc`; population verify and freeze reconstruction
both byte-exact.

If and only if the packet passes, append the exact
`WORLD_AFTERSTATE_E3_E4_V0_REVIEW ` marker generated from the freeze and grant
authority for one initialization and one non-retry scientific execution on
Perf consisting only of dataset labeling, eight-seed training, one report
opening, mandatory immediate reconstruction, and one independent full
verification. Keep merge, retry, gameplay, strength, promotion, deployment,
R5, and any further experiment authority false.

## Live work

### BELIEF R4 — top priority, hands off

- Strength Cloud exact execution head:
  `56bd35f0c45080121d094f6906ab8d1053ca9e6b`.
- Unit `belief-r4-terminal-scientific-56bd35f-r1.service` is active with zero
  restarts. At this refresh: 1,245/1,339 units (92.97%) through the current
  test-scoring pass, with about 40 minutes estimated for that pass; cgroup peak
  23.76 GB under the unchanged 24-GiB cap.
- The sole test opening is consumed. Never stop, signal, duplicate, inspect
  outcome bytes, or touch the namespace.
- The current ETA is for the current scoring pass only. The same unit must then
  perform immediate terminal reconstruction; watcher
  `belief-r4-terminal-verifier-watch-56bd35f-r1.service` launches the separate
  independent verifier only after a successful seal.
- R5 remains paused until the independently reproduced R4 verdict and curves
  are interpreted.

### PT-Luna0 — complete

- Exact source `2394140bcdaebf72d81912a55ac18f5051848fe5`; report
  `/Users/jerryyu/Projects/shengji-ptluna0-2394140-r1.json`; 52/52 complete and
  independently reopened.
- Mean signed-level contrasts: Luna−A +0.385, Luna−B +0.442,
  Luna−C0-S +0.615, Luna−Sol −0.269. Luna beats fixed baselines; Sol remains
  the stronger reviewed privileged teacher. No promotion or strength claim.

### Value-Afterstate V0 — packet only, no scientific execution yet

- PR #164 exact head `d9ad99f`; CI green; source is isolated from R4.
- Capacity and the immutable population/freeze are prepared on Perf. No
  scientific root, admission, labels, checkpoints, report, or result exists.
- Await the single consolidated review above. Do not initialize or launch
  before the authentic marker reaches remote main.

## Fleet and boundaries

| host | current use |
|---|---|
| Strength Cloud | R4 sole scientific terminal + verifier watcher; hands off |
| Perf Cloud | Value V0 packet preparation/review target; no scientific run |
| Mini | free; no goal-critical run |

- Keep hosts, branches, runtimes, and artifacts isolated.
- Do not merge, deploy, resume R5, or launch Value scientific work without the
  explicit authority above.
- Report percentages, ETA, utilization, and failures plainly. Use all cores
  for materially parallel workloads; do not add risky concurrency merely to
  make a short deterministic prep step look busy.
