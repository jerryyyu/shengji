# Active Claude/Codex handoff

> Current operational state only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> The latest authentic exact-head marker on remote main controls.

Last reconciled: **2026-08-30 01:15 EDT**. Remote main before this update:
`778d4c4`.

## Review queue — R4 waits on state, one secondary source ask

PR #172 is fully source-authenticated. Canonical commit
`00c184dae0fb69c8c5d78d1e0c2b665366448451` appends the exact
`BELIEF_V1_V2_R4_RECOVERY_EXECUTION_V1_REVIEW ` marker for recovery head
`5a81d89cd954a63ac97ca8588926b3367c28c5c1`. Do not repeat this review or
publish another marker.

The actual capped `build-timeout-receipt` entrypoint authenticated that marker
against both clean cloud checkouts and reached only the expected live-state
refusal `R4 terminal systemd observation drift`, because the scientific unit
is still active. No timeout receipt, route claim, outcome read, or evidence
mutation occurred. There is no R4 review action until the unit changes state.

Secondary review while R4 runs: PR #171 final head
`2f4fa09dc18a412125539b80ebe90378f00d7247` requests one narrow review of its
one-file test-only delta from held parent `74e1158`. Production
collector/capacity bytes are unchanged. The empirical-concurrency witness now
uses deterministic controller clock pairs while retaining real executor
threads, per-arm start barriers, and a second barrier while every worker is
active; a serialized dispatcher therefore breaks the witness without making
the receipt depend on a 2 ms host sleep. Exact-head evidence: the focused test
passed 20/20 consecutive isolated runs, the full PT-Luna battery passed 102/102,
and compile/diff checks are clean. Exact ask:
https://github.com/jerryyyu/shengji/pull/171#issuecomment-5466825259. PASS may
authorize exactly one fresh non-scientific score-free progressive Mini
capacity census with distinct immutable success/failure outputs. It grants no
104-game collection, outcome opening, gameplay/strength claim, merge, retry,
promotion, or deployment.

If and only if the scientific service ends `Result=timeout`, the 12:25/12:28Z
timers below generate a timeout receipt and print the exact pending-recovery
claim. That generated claim is the next single dynamic review ask. It must be
reviewed against the live systemd state before any recovery executes.

## Live work

### BELIEF R4 — top priority, hands off

- Strength Cloud exact execution head:
  `56bd35f0c45080121d094f6906ab8d1053ca9e6b`.
- Unit `belief-r4-terminal-scientific-56bd35f-r1.service` is active with zero
  restarts. At **2026-08-29 14:58 UTC**, it sealed the complete inner terminal:
  both score populations, human selection, scale curve, primary/control/human
  statistics, integrity receipt, result and inner manifest are immutable
  `0400`/one-link files. Do not read the outcome yet. The same process is now
  performing the mandatory immediate full reconstruction before publishing
  outer `r4-completion-terminal.json`; the independent verifier starts only
  after that boundary. Cgroup peak remains 23.76 GB under 24 GiB.
- The frozen 31.68-hour scientific projection is not a reliable deadline
  bound for this substep. Its measured `control_reopen_wall_nanoseconds`
  executes `_capacity_context` (calibration import, input index, trained
  cohorts and 13 calibration rounds), but never calls
  `_derive_integrity_receipt`; it therefore omits the full capture/reference
  reconstruction above. The systemd unit has a hard two-day limit ending
  **2026-08-30 12:23 UTC** (08:23 EDT), about 7h40m after this update, and
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
- After the now-sealed first terminal derivation, the same unit is performing
  immediate full terminal reconstruction; watcher
  `belief-r4-terminal-verifier-watch-56bd35f-r2.service` launches the separate
  independent verifier only after a successful seal. The watcher refreshes
  canonical `origin/main` immediately before authentication; this closes the
  stale-remote-ref handoff failure observed during Value V0 without touching
  the scientific process or evidence.
- The legacy duplicate-reconstruction watcher
  `belief-r4-terminal-recovery-watch-56bd35f-r1.service` is stopped and
  inactive. The old prose-PASS-bound `5a81d89-r1` timers are also stopped and
  inactive. Four active marker-bound timers replace them: canonical ref
  refreshes at 12:24:00Z and 12:24:15Z, then
  `belief-r4-timeout-receipt-00c184d-r2.timer` at 12:25Z and
  `belief-r4-pending-claim-00c184d-r2.timer` at 12:28Z. They can only publish
  the exact timeout receipt and print the dynamic review claim. They cannot
  execute recovery, rescore, interpret outcomes, or launch a verifier. On
  normal scientific success they fail closed without changing evidence. The
  scientific service and normal success-only verifier watcher remain active.
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

### Value-Afterstate V1 — P0 passed; P1 selected none and is verified

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
- The first P1 scientific admission at `3534fe0` is spent. It refused before
  training because its reader missed the capacity eligibility projection;
  no held-out label opened and no learning conclusion exists. PR #167 final
  head `c98bdeb` applies the selector to both train and calibration action
  populations, reproduces the capacity manifest on the real train population,
  and freezes that spent-attempt lineage under a new `r2` root.
- Claude's final exact-head PASS is `9aef077`. The single authorized Perf run,
  `value-afterstate-v1-p1-scientific-c98bdeb-r2.service` at invocation
  `7ffbb2af8de84873a41ee3c555479123`, completed successfully with zero restarts
  at 16:30:30 UTC. It consumed 42m34s wall / 8h27m CPU (about 11.9 effective
  cores), peaked at 2.1 GB, sealed all four early-stopped cohorts and target-free
  predictions before opening calibration exactly once, then independently
  reconstructed all 624 held-out rows. Every evidence file is immutable
  `0400`/one-link; reconstruction receipt is `2c361a3e...e4a35` and
  `verified=true`.
- Terminal decision: `SELECT_NONE_NO_ACTION_ADVANTAGE`. P0's label ceiling
  remained real, and all three negative controls failed on demand, but the
  natural model failed the action gate: advantage-error improvement was
  -0.139134 signed levels with interval [-0.164342, -0.115496], action/simple-
  regret utility was -0.061224 with interval [-0.174242, +0.128205], and only
  1/8 members was positive. World-shuffle separation also failed. This is a
  clean learning null, not a mechanics/control refusal.
- All gameplay, strength, merge, retry, P2, deployment and R5 authority remains
  false. Do not scale this recipe; preserve the verified result and use its
  curves to redesign the target/model only after R4 is interpreted.
- This is a 520-root mechanism pilot, not a final-quality model claim. Eight
  seeds test optimization stability, not data sufficiency; any later scaling
  adds independent roots/replicates only after P0/P1 establish real action
  signal.

## Fleet and boundaries

| host | current use |
|---|---|
| Strength Cloud | R4 sole scientific terminal + verifier watcher; hands off |
| Perf Cloud | free; Value P1 r2 completed and independently reconstructed |
| Mini | free; no goal-critical run |

- Keep hosts, branches, runtimes, and artifacts isolated.
- Do not stop, duplicate, retry, merge, deploy, resume R5, or launch additional
  scientific Value work. R4 interpretation remains the critical path.
- Report percentages, ETA, utilization, and failures plainly. Use all cores
  for materially parallel workloads; do not add risky concurrency merely to
  make a short deterministic prep step look busy.
