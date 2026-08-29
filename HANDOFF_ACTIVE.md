# Active Claude/Codex handoff

> Current operational state only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> The latest authentic exact-head marker on remote main controls.

Last reconciled: **2026-08-29 09:53 EDT**. Remote main at this refresh:
`6692243c04c868e773220dc743ada117110950bf`.

## ACTIVE — Value V1 train-only P0/capacity at reviewed `bd400a68`

Claude independently reviewed PR #166 at exact head
`bd400a6855b83de263838cabdee1f07de6839ba2`; canonical main `6692243`
contains the exact machine-generated marker. Its authority is one fresh,
non-retry, train-only Perf P0/capacity packet. Calibration, report,
provider-audit, scientific P1, gameplay, strength, merge, deployment and R5
remain false.

### Pre-launch DAG audit

The reviewed command has one composed two-hour internal deadline, a 30-GiB
cgroup-v2 memory limit and a 16-logical-CPU host requirement. Its full
learning-bearing and integrity DAG is:

1. authenticate exact Git/runtime/native/review and the immutable V0 input
   hashes before opening a training row;
2. reopen the same 3,906 already-open V0 train rows at 1/2/4/8/16 workers,
   requiring byte-identical populations — five intentional full passes used
   only to measure the fastest safe row-reader configuration;
3. derive P0 in memory and stop immediately with
   `STOP_NO_REPRODUCIBLE_ACTION_LABEL` if the two matched continuation
   replicates do not support stable action selection;
4. only after P0 passes, train four one-epoch eight-member capacity cohorts at
   1/2/4/8 member workers, each receiving only the positive remainder of the
   same packet deadline — four intentional repeats used only to select
   throughput; and
5. atomically seal and independently reopen the small receipt/artifact packet,
   with no engine-continuation replay and no held-out-data pass.

Rows are streamed under each measured worker count; cohort configurations use
`torch_threads = max(1, 16 // member_workers)`, so every scheduled measurement
targets all 16 logical CPUs without oversubscribing the intended worker/thread
product. The receipt records wall, CPU utilization, peak cgroup memory and
throughput for each configuration rather than assuming scaling.

Recovery is deliberately narrow: there is no mid-packet checkpoint or retry;
an expiry or process failure publishes no receipt and consumes this capacity
admission. That is accepted for this bounded diagnostic because P0 is the
first output, before model training, and the total packet cannot exceed two
hours. It is not acceptable as the later scientific-run pattern: PR #167 must
retain durable per-cohort stage boundaries, graceful best-common-epoch
truncation and an independently reconstructible terminal before its one
source+freeze review.

The exact staged source is
`/opt/value-afterstate-v1-capacity-bd400a6-r1-src`; the new output is
`/opt/value-afterstate-v1-capacity-bd400a6-r1`. Immediately before launch,
refetch canonical GitHub main, require local/real equality, recheck the clean
source/native/runtime/input hashes and require both the unit and output to be
absent. Authority ends after publishing and independently reopening the
receipt. PR #167 is not reviewable until that receipt exists and the freeze
binds every prior spent capacity incident plus this exact result.

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

### Value-Afterstate V1 — repaired capacity launch authorized

- Capacity PR #166 is reviewed at repaired exact head
  `bd400a6855b83de263838cabdee1f07de6839ba2`. The old-head `-r1` and `-r2`
  invocations failed before data opening on operator-path guards; `-r3` then
  reached the train population and correctly exposed the missing singleton
  eligibility projection before publishing a receipt. All three old-head
  outputs are absent and none is an ML/capacity result.
- The new manifest-bound selector proves the entire declared candidate and
  replicate population before excluding only singleton ballots. The repaired
  review authenticator accepts the append-only exact-head marker after the old
  same-prefix marker. Pure and strict compiled/void batteries pass 80/80 each.
  The pre-launch audit above is the active instruction; never launch another
  command at an old source head.
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
| Perf Cloud | Immutable V0 inputs preserved; reviewed PR #166 train-only P0/capacity packet is the sole authorized launch |
| Mini | free; no goal-critical run |

- Keep hosts, branches, runtimes, and artifacts isolated.
- Do not merge, deploy, resume R5, or launch Value capacity/scientific work
  without the exact review authority described above.
- Report percentages, ETA, utilization, and failures plainly. Use all cores
  for materially parallel workloads; do not add risky concurrency merely to
  make a short deterministic prep step look busy.
