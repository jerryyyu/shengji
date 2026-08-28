# Active Claude/Codex handoff

> Current operational state only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> The latest authentic exact-head marker on remote main controls.

Last reconciled: **2026-08-28 18:40 EDT**. Remote main before this refresh:
`a828fd70f17e1d64de1b599a47bbfe03421cb656`.

## Review queue

No review is currently required. Value V0 completed its one-shot run and
independent reconstruction; BELIEF R4 remains live and outcome-blind. Do not
request another Value source/freeze review or append another execution marker.

## Live work

### BELIEF R4 — top priority, hands off

- Strength Cloud exact execution head:
  `56bd35f0c45080121d094f6906ab8d1053ca9e6b`.
- Unit `belief-r4-terminal-scientific-56bd35f-r1.service` is active with zero
  restarts. The first synthetic scoring pass completed 1,339/1,339 and all five
  human transfer groups completed. The run is now at terminal-statistics
  derivation (3/6); cgroup peak remains 23.76 GB under the unchanged 24-GiB
  cap. The quiet section is specifically the integrity receipt's
  `reopen_training_tensor_cache(..., verify_all_bytes=True)` over 27.82 GB of
  bound cache bytes. Measured progress is about 1 GB per ten minutes, so this
  substep is hours, not minutes; it is CPU/I/O-active and has not published an
  outcome. Do not diagnose it as a hang or duplicate it.
- The sole test opening is consumed. Never stop, signal, duplicate, inspect
  outcome bytes, or touch the namespace.
- After statistics and the first terminal derivation, the same unit must
  perform immediate full terminal reconstruction; watcher
  `belief-r4-terminal-verifier-watch-56bd35f-r2.service` launches the separate
  independent verifier only after a successful seal. The watcher refreshes
  canonical `origin/main` immediately before authentication; this closes the
  stale-remote-ref handoff failure observed during Value V0 without touching
  the scientific process or evidence.
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

## Fleet and boundaries

| host | current use |
|---|---|
| Strength Cloud | R4 sole scientific terminal + verifier watcher; hands off |
| Perf Cloud | Value V0 complete; artifacts preserved; host otherwise free |
| Mini | free; no goal-critical run |

- Keep hosts, branches, runtimes, and artifacts isolated.
- Do not merge, deploy, resume R5, or launch any additional Value work without
  a new reviewed design.
- Report percentages, ETA, utilization, and failures plainly. Use all cores
  for materially parallel workloads; do not add risky concurrency merely to
  make a short deterministic prep step look busy.
