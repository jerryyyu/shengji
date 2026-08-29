# Active Claude/Codex handoff

> Current operational state only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> The latest authentic exact-head marker on remote main controls.

Last reconciled: **2026-08-29 12:05 EDT**. Remote main before this update:
`c2ec1f4`.

## Review queue

No review is currently actionable. Claude's exact `c98bdeb` PASS and
module-generated `r2` marker are canonical at `9aef077`; the later `2b14386`
HOLD is explicitly for superseded, never-initialized `e632e41` and does not
negate the final-head marker. Do not repeat either review while the admitted
run is live.

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
- After the now-sealed first terminal derivation, the same unit is performing
  immediate full terminal reconstruction; watcher
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

### Value-Afterstate V1 — P0 passed; repaired P1 scientific run live

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
- Claude's final exact-head PASS is `9aef077`. The single authorized run is
  live on Perf as `value-afterstate-v1-p1-scientific-c98bdeb-r2.service`,
  invocation `7ffbb2af8de84873a41ee3c555479123`, since 15:47:56 UTC. It cleared
  admission and the repaired full train-population reopen. Natural and
  identical-successor each stopped normally after five epochs under the
  frozen patience rule and sealed their manifests plus eight checkpoints
  immutable `0400`/one-link. At 16:05 UTC the unit advanced into the
  action-association-permutation control. The old failure happened before
  these boundaries. Current peak is about 2.28 GB with zero restarts and
  roughly 14.9 effective CPU cores; no held-out calibration label has opened.
  The unit sequentially runs natural plus three
  controls, then seals target-free predictions, opens calibration once, seals
  the terminal and immediately reconstructs it. Its hard 12-hour deadline is
  03:47:56 UTC on August 30.
- This is a 520-root mechanism pilot, not a final-quality model claim. Eight
  seeds test optimization stability, not data sufficiency; any later scaling
  adds independent roots/replicates only after P0/P1 establish real action
  signal.

## Fleet and boundaries

| host | current use |
|---|---|
| Strength Cloud | R4 sole scientific terminal + verifier watcher; hands off |
| Perf Cloud | Value P1 repaired r2 scientific run live; no held-out label open yet |
| Mini | free; no goal-critical run |

- Keep hosts, branches, runtimes, and artifacts isolated.
- Do not stop, duplicate, retry, inspect unavailable outcomes, merge, deploy,
  resume R5, or launch additional scientific Value work while r2 is live.
- Report percentages, ETA, utilization, and failures plainly. Use all cores
  for materially parallel workloads; do not add risky concurrency merely to
  make a short deterministic prep step look busy.
