# Active Claude/Codex handoff

> Current operational state only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> The latest authentic exact-head marker on remote main controls.

Last reconciled: **2026-08-29 10:34 EDT**. Remote main before this update:
`0c29da670eccc9ec6514af14a376ccd76fb6b621`.

## OPEN — one consolidated Value V1 scientific source+freeze review

Review PR #167 at exact head
`32ef540b0829042c8cc0993ba775bd9612f4e4f8`, the passing capacity directory
`/opt/value-afterstate-v1-capacity-bd400a6-r1`, final exact-head rehearsal
`/opt/value-afterstate-v1-rehearsal-32ef540-r1`, and immutable freeze
`/opt/value-afterstate-v1-freeze-32ef540-r1.json`.

The freeze independently reconstructs at the clean Perf head. External SHA-256
is `d3d28798b2caa5ce997666178ec926a9033ef98241614f22bfe6d44bb05fce94`;
internal freeze SHA-256 is
`5555c56bdebd8faf5b630aaa961b7ba51fe5e3fa40012364605e4a612a0ba2bc`.
The exact review claim SHA-256 is
`be7a7d3fd4f17b0f7f65012d3f82b63d10f0e11ef45a3f8266efd51797c7ca54`;
the module-generated marker is 1,370 bytes with SHA-256
`f4d9846dc9bb798367204ec61536b2903fa14f87629dd8140d6c4ca9c637805b`.

Review one packet, not separate phases: source/design, four-attempt capacity
lineage plus passing receipt, final rehearsal, exact runtime/native/input
bindings, learner/controls/gates, deadline truncation, held-out ordering,
terminal reconstruction and authority. Exact-head batteries pass 201/201 pure
and 201/201 compiled strict/void; CI is green. The rehearsal receipt SHA-256 is
`08660ee2ac5b2e4ffe7d39d15cf37d1b8ef057e27c913c50441141be6d29e70e`;
it independently reopens all 50 files and keeps every authority false.

If every byte reproduces, append exactly one module-generated
`WORLD_AFTERSTATE_V1_P1_SCIENTIFIC_REVIEW` marker to canonical
`HANDOFF_REVIEW.md`. It may authorize one fresh P1 train/calibration execution
and immediate reconstruction only. Report/provider rows, P2, gameplay,
strength, merge, promotion, deployment, retry, R5 and test extension remain
false. Do not launch scientifically before that marker.

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
  remains 23.76 GB under the unchanged 24-GiB cap; at 14:34 UTC it remained
  CPU-active with zero restarts and had not published an outcome. Do not
  diagnose it as a hang or duplicate it.
- The frozen 31.68-hour scientific projection is not a reliable deadline
  bound for this substep. Its measured `control_reopen_wall_nanoseconds`
  executes `_capacity_context` (calibration import, input index, trained
  cohorts and 13 calibration rounds), but never calls
  `_derive_integrity_receipt`; it therefore omits the full capture/reference
  reconstruction above. The systemd unit has a hard two-day limit ending
  **2026-08-30 12:23 UTC** (08:23 EDT), about 22 hours after this update, and
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

### Value-Afterstate V1 — P0 passed; P1 packet ready for review

- Capacity PR #166 is reviewed at repaired exact head
  `bd400a6855b83de263838cabdee1f07de6839ba2`. The old-head `-r1` and `-r2`
  invocations failed before data opening on operator-path guards; `-r3` then
  reached the train population and correctly exposed the missing singleton
  eligibility projection; the first repaired-head invocation exposed the
  same-prefix review-authenticator defect before row opening. All four failed
  outputs are absent and none is an ML/capacity result. Their exact lineage is
  bound into the P1 freeze.
- The new manifest-bound selector proves the entire declared candidate and
  replicate population before excluding only singleton ballots. The repaired
  review authenticator accepts the append-only exact-head marker after the old
  same-prefix marker. The final 13m01s capacity packet independently reopened
  with route `PASS_TO_P1_CAPACITY`; receipt SHA-256 is
  `31835b3e677239a72328535e63c1d3fd8535d3050308a33e578622b05da579f0`.
- P0 found reproducible paired action signal across 321 eligible states:
  combined mean +0.084112 signed levels, deal-bootstrap interval
  [+0.036050, +0.134259], and 23.3644% non-incumbent selection dose. This
  admits P1; it is not yet evidence that a model learns or improves play.
- Scientific PR #167 at exact head `32ef540b…` includes the four cohorts,
  durable per-cohort seals, graceful deadline truncation, prediction-before-
  label ordering, terminal reconstruction, negative controls, replay-safe
  review authentication, exact incident lineage and a can-fail exact-source
  rehearsal CLI. The precise review ask is at the top of this file.
- This is a 520-root mechanism pilot, not a final-quality model claim. Eight
  seeds test optimization stability, not data sufficiency; any later scaling
  adds independent roots/replicates only after P0/P1 establish real action
  signal.

## Fleet and boundaries

| host | current use |
|---|---|
| Strength Cloud | R4 sole scientific terminal + verifier watcher; hands off |
| Perf Cloud | Immutable V0/P0 inputs plus final P1 rehearsal/freeze preserved; idle pending review |
| Mini | free; no goal-critical run |

- Keep hosts, branches, runtimes, and artifacts isolated.
- Do not merge, deploy, resume R5, or launch scientific Value work without the
  exact review authority described above.
- Report percentages, ETA, utilization, and failures plainly. Use all cores
  for materially parallel workloads; do not add risky concurrency merely to
  make a short deterministic prep step look busy.
