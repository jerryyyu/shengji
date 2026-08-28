# Active Claude/Codex handoff

> Current operational state only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> The latest authentic exact-head marker on remote main controls.

Last reconciled: **2026-08-28 17:35 EDT**. Remote main before this refresh:
`da7f0d786376a88a2f078e9c86d90e581c9c86cc`.

## Review queue

No review is currently required. PR #164 received its consolidated exact-head
PASS at main commit `da7f0d7`; the authorized one-shot Value V0 run is live.
Do not request another source/freeze review or append another execution marker.

## Live work

### BELIEF R4 — top priority, hands off

- Strength Cloud exact execution head:
  `56bd35f0c45080121d094f6906ab8d1053ca9e6b`.
- Unit `belief-r4-terminal-scientific-56bd35f-r1.service` is active with zero
  restarts. At this refresh: 1,284/1,339 units (95.89%) through the current
  test-scoring pass, with about 23 minutes estimated for that pass; cgroup peak
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

### Value-Afterstate V0 — scientific execution live, hands off

- PR #164 exact head `d9ad99f6377040424821d79071e12435fde802ae`;
  consolidated source+capacity+population+freeze PASS at main `da7f0d7`.
  Marker SHA-256 `f656200b944f3fdb618df53ea3931b7afc7df646527f79913c26eadbb999c224`.
- Perf root `/opt/value-afterstate-v0-e3e4-d9ad99f-r1`; initialization and
  dataset attempts are consumed. Unit
  `value-afterstate-v0-scientific-d9ad99f-r1.service` runs dataset → training
  → one report opening with zero retries. The separate watcher
  `value-afterstate-v0-verifier-watch-d9ad99f-r1.service` launches independent
  full reconstruction only after a successful terminal seal.
- Early dataset measurement: 336/7,446 continuations (4.51%), about 13 minutes
  estimated; 15.99 effective cores over five seconds (99.9% of 16), 2.06-GB
  cgroup memory, zero restarts. Progress ETA is for the current stage only.
- Never stop, signal, duplicate, delete, or retry this run. Do not inspect
  report outcomes before the terminal and independent verification complete.
  Merge, gameplay, strength, promotion, deployment, and R5 remain false.

## Fleet and boundaries

| host | current use |
|---|---|
| Strength Cloud | R4 sole scientific terminal + verifier watcher; hands off |
| Perf Cloud | Value V0 scientific dataset/training/report + verifier watcher; hands off |
| Mini | free; no goal-critical run |

- Keep hosts, branches, runtimes, and artifacts isolated.
- Do not merge, deploy, resume R5, or launch any additional Value work.
- Report percentages, ETA, utilization, and failures plainly. Use all cores
  for materially parallel workloads; do not add risky concurrency merely to
  make a short deterministic prep step look busy.
