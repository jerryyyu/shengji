# Active Claude/Codex handoff

> Current operational state only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> The latest authentic exact-head marker on remote main controls.

Last reconciled: **2026-08-29 10:15 EDT**. Remote main before this refresh:
`62d85079beebf5ba362d47585f2c9515e0d6bba2`.

## OPEN — one consolidated Value V1 capacity source+launch review

Review **PR #166 at repaired exact head
`bd400a6855b83de263838cabdee1f07de6839ba2`**. The already-reviewed
`34409006ed9ecafdddd41e060936c2e3a8421aee` capacity command was consumed and
failed after 2.093 s wall / 3.357 s CPU, before any training-row read or output
publication, with `capacity review marker introduction drift`. Do not
authorize that spent old head again.

Review only
`34409006ed9ecafdddd41e060936c2e3a8421aee..bd400a6855b83de263838cabdee1f07de6839ba2`
(two files, 11 insertions / 2 deletions). The source defect was that review
authentication required the current ledger to contain exactly one marker with
this prefix and the parent to contain none. Because the prior `aa0595c` review
uses the same prefix, every honest repaired-head review was formally
unusable. The repair requires the current prefix-matched sequence to equal all
parent matches followed by exactly one new marker, and refuses if that exact
new marker already existed in the parent. The permanent witness includes a
real prior same-prefix marker, accepts one append and refuses both a missing
append and a duplicated append. Reverting only the production guard to the old
logic makes that named test fail; restored source passes it. Full V1 batteries
pass **80/80 pure and 80/80 strict compiled/void**; `git diff --check` is
clean. This is one source-interaction repair, not a new scientific design.

If this narrow delta passes, append one fresh exact-head marker and authorize
exactly one fresh, non-retry, train-only, score-free Perf capacity execution at
this repaired head, after a
clean exact-head checkout and local/real canonical-ref equality check. It must
use the existing immutable V0 population/dataset/freeze, corrected dataset
root (not `rows/`), a new output namespace, strict native/void `-P -B`, the
composed two-hour internal deadline, cgroup-v2 resource envelope and the
existing outcome-blind progress contract. Authority ends after publishing and
independently reopening the capacity receipt. Calibration/report rows,
scientific P1 training, PR #167 freeze authority, gameplay, strength, merge,
deployment and R5 all remain false.

PR #167 remains deliberately **not** reviewable until that receipt exists and
its freeze binds all three spent attempts plus this repaired-head capacity
lineage. It then gets the one remaining consolidated source+freeze review. R4
and PT-Luna0 need no repeated review while in their current states.

## Live work

### BELIEF R4 — top priority, hands off

- Strength Cloud exact execution head:
  `56bd35f0c45080121d094f6906ab8d1053ca9e6b`.
- Unit `belief-r4-terminal-scientific-56bd35f-r1.service` is active with zero
  restarts. The first synthetic scoring pass completed 1,339/1,339 and all five
  human transfer groups completed. The visible phase remains 3/6, but the
  quiet substep is **not** bootstrap statistics: the exact source runs those
  three reports in a three-thread executor, while the live main process has
  one thread; an exact 1,339-round-shape benchmark completes the whole wrapper
  in about 0.15 s. R4 is therefore inside the following single-threaded
  `_derive_integrity_receipt` pass. That pass sequentially reconstructs all
  13,312 capture rounds (14.55 GB), 3,991 REF-C jobs (6.29 GB), the human
  artifacts, the 311-MB/778,064-decision input index, and 27.82 GB of tensor
  cache before phase 4 can publish. Its exact internal item is not externally
  observable and it has no progress counter or trustworthy ETA. Cgroup peak
  remains 23.76 GB under the unchanged 24-GiB cap; it remains CPU-active and
  has not published an outcome. Do not diagnose it as a hang or duplicate it.
- The frozen 31.68-hour scientific projection is not a reliable deadline
  bound for this substep. Its measured `control_reopen_wall_nanoseconds`
  executes `_capacity_context` (calibration import, input index, trained
  cohorts and 13 calibration rounds), but never calls
  `_derive_integrity_receipt`; it therefore omits the full capture/reference
  reconstruction above. The systemd unit has a hard two-day limit ending
  **2026-08-30 12:23 UTC** (08:23 EDT), about 29 hours after this update, and
  immediate reconstruction repeats scoring plus integrity. Treat deadline
  exhaustion as a real open risk, not a predicted failure or permission to
  interrupt the only valid attempt.
- Deadline expiry is now pre-adjudicated from the reviewed source. If
  `terminal.partial/` remains and `terminal/` is absent, no inner decision
  sealed and `recover-terminal-binding` is ineligible: preserve the namespace
  and draw no model conclusion. If `terminal/` exists, `terminal.partial/` is
  absent, and only `r4-completion-terminal.json` is missing, the narrow
  reviewed recovery may independently reopen that immutable inner terminal and
  publish only the missing outer binding after the scientific unit stops; it
  cannot reopen the test or choose a second result. If both inner and outer
  exist, recovery is forbidden and only the independent verifier remains.
- The sole test opening is consumed. Never stop, signal, duplicate, inspect
  outcome bytes, or touch the namespace.
- After statistics and the first terminal derivation, the same unit must
  perform immediate full terminal reconstruction; watcher
  `belief-r4-terminal-verifier-watch-56bd35f-r2.service` launches the separate
  independent verifier only after a successful seal. The watcher refreshes
  canonical `origin/main` immediately before authentication; this closes the
  stale-remote-ref handoff failure observed during Value V0 without touching
  the scientific process or evidence.
- Fail-safe watcher
  `belief-r4-terminal-recovery-watch-56bd35f-r1.service` is also active with a
  64-MiB envelope and has launched neither recovery nor verification. It waits
  until the scientific unit stops. A normal outer seal makes it exit without
  action; an unsealed `terminal.partial/` also makes it refuse without action.
  Only the already-reviewed inner-only state (`terminal/` present, partial and
  outer absent) can launch exact-head `recover-terminal-binding`; after that
  succeeds it launches verifier `belief-r4-terminal-independent-verifier-
  56bd35f-r2`. This closes the operator-attention gap without signalling,
  duplicating or modifying the live scientific process.
- R5 remains paused until the independently reproduced R4 verdict and curves
  are interpreted.

### PT-Luna0 — complete

- Exact source `2394140bcdaebf72d81912a55ac18f5051848fe5`; report
  `/Users/jerryyu/Projects/shengji-ptluna0-2394140-r1.json`; 52/52 complete and
  independently reopened.
- Mean signed-level contrasts: Luna−A +0.385, Luna−B +0.442,
  Luna−C0-S +0.615, Luna−Sol −0.269. Luna beats fixed baselines; Sol remains
  the stronger reviewed privileged teacher. No promotion or strength claim.

### Value-Afterstate V0 — independently verified refusal

- PR #164 exact head `d9ad99f6377040424821d79071e12435fde802ae`;
  consolidated source+capacity+population+freeze PASS at main `da7f0d7`.
  Marker SHA-256 `f656200b944f3fdb618df53ea3931b7afc7df646527f79913c26eadbb999c224`.
- Perf root `/opt/value-afterstate-v0-e3e4-d9ad99f-r1`; all attempts are
  consumed. Dataset generation sealed 7,446 rows. Eight members trained for
  seven common epochs and stopped for patience, selecting common epoch 2;
  training was not deadline-truncated. Heavy phases used about 16 effective
  cores. Independent verification re-executed every continuation and returned
  `verified=true`, terminal SHA-256 `53b2afc9…`.
- Terminal decision: `REFUSE_MECHANICS_OR_NEGATIVE_CONTROL`. The natural model
  passed held-out NLL (mean +0.404495 nats, one-sided lower +0.062702, 8/8
  seeds), but geometry-label permutation and complete-world shuffle also
  passed essentially the same gate. The model therefore learned a broad
  outcome/base-rate signal rather than the required action/world-sensitive
  value. Its action gate was negative on expected-utility error, simple regret,
  and incumbent non-regression. Pre-action ablation, rotation, and all five
  integrity mutations behaved correctly.
- No gameplay, E5a, retry, strength, merge, promotion, deployment, or R5
  authority exists. Preserve the artifacts; any successor needs a new design,
  not a retry or post-hoc threshold change.

### Value-Afterstate V1 — repaired capacity review pending

- Capacity PR #166 is now at repaired exact head
  `34409006ed9ecafdddd41e060936c2e3a8421aee`. The old-head `-r1` and `-r2`
  invocations failed before data opening on operator-path guards; `-r3` then
  reached the train population and correctly exposed the missing singleton
  eligibility projection before publishing a receipt. All three old-head
  outputs are absent and none is an ML/capacity result.
- The new manifest-bound selector proves the entire declared candidate and
  replicate population before excluding only singleton ballots. Pure and
  strict compiled/void batteries pass 80/80 each. Await the one consolidated
  repaired-head review above; do not launch another `aa0595c` command.
- Scientific PR #167 exact staged head
  `917176f33ede097f5c8328ac22b6c317789e8376` passes 195/195 pure and strict
  compiled tests. Its test-only final delta witnesses the CLI wiring that
  durably consumes the calibration and reconstruction attempts before either
  held-out label reader can run. Initialization checks exact live
  source/runtime before spending the durable admission; the freeze builder
  authenticates and content-binds the first failed invocation and re-entry
  marker, and refreshes canonical main from the real GitHub URL rather than a
  staging-local origin. Its next delta will bind the second incident/re-entry
  too, before the same single consolidated source+freeze review. It is staged
  cleanly on Perf. Do not review it before the capacity receipt and freeze
  exist.
- This is a 520-root mechanism pilot, not a final-quality model claim. Eight
  seeds test optimization stability, not data sufficiency; any later scaling
  adds independent roots/replicates only after P0/P1 establish real action
  signal.

## Fleet and boundaries

| host | current use |
|---|---|
| Strength Cloud | R4 sole scientific terminal + verifier watcher; hands off |
| Perf Cloud | Idle; immutable V0 inputs preserved; repaired PR #166 capacity awaits one consolidated source+launch review |
| Mini | free; no goal-critical run |

- Keep hosts, branches, runtimes, and artifacts isolated.
- Do not merge, deploy, resume R5, or launch Value capacity/scientific work
  without the exact review authority described above.
- Report percentages, ETA, utilization, and failures plainly. Use all cores
  for materially parallel workloads; do not add risky concurrency merely to
  make a short deterministic prep step look busy.
