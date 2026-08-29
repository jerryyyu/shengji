# Active Claude/Codex handoff

> Current operational state only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> The latest authentic exact-head marker on remote main controls.

Last reconciled: **2026-08-29 03:00 EDT**. Remote main before this refresh:
`334ac33fd7297d8ff05808a0c70f46e162e23714`.

## Review queue

Exactly one command-only adjudication is actionable; **no source re-review is
requested**. PR #166 passed at exact head
`aa0595cce9b626941c9cc4fd64062b4e06d10cf1` in canonical commit
`cad30be4d0168f5ab0ec148e39e5de99b60c9852`. The authorized Perf invocation
`40a4c998a71e4b74befb46feddd2dd52` then failed after 5.405 s because Codex
supplied `--row-root .../artifacts/dataset/rows` while every manifest path
already starts with `rows/`. The first attempted path was therefore the
nonexistent `.../dataset/rows/rows/train/...`; the traceback is at
`value-afterstate-v1-capacity-aa0595c-r1.service`. No capacity output exists,
no progress record was emitted, and no train-row byte could open because the
entire erroneous `rows/rows` tree is absent. This is an operator-path failure,
not a source, model, or data result.

Please independently confirm the failed unit, absent output, manifest-relative
path, and real first-row existence under `.../artifacts/dataset/rows/...`.
If they match, append the following exact single line to `HANDOFF_REVIEW.md`
in one Claude-authored append-only commit. It authorizes exactly one corrected
Perf execution at output `...-r2`; all scientific and downstream authority
remains false:

```text
WORLD_AFTERSTATE_V1_CAPACITY_OPERATOR_REENTRY_V1 {"authority":{"calibration_row_opening_authorized":false,"deployment_authorized":false,"gameplay_authorized":false,"merge_authorized":false,"p2_execution_authorized":false,"promotion_authorized":false,"provider_audit_row_opening_authorized":false,"r5_authorized":false,"report_row_opening_authorized":false,"retry_beyond_corrected_execution_authorized":false,"scientific_p1_training_authorized":false,"strength_claim_authorized":false,"train_only_corrected_capacity_execution_authorized":true},"corrected_row_root":"/opt/value-afterstate-v0-e3e4-d9ad99f-r1/artifacts/dataset","failed_invocation_id":"40a4c998a71e4b74befb46feddd2dd52","failed_output_absent":true,"failed_service":"value-afterstate-v1-capacity-aa0595c-r1.service","prior_review_commit":"cad30be4d0168f5ab0ec148e39e5de99b60c9852","schema":"world-afterstate-v1-capacity-operator-reentry-v1","source_git":"aa0595cce9b626941c9cc4fd64062b4e06d10cf1","target_output":"/opt/value-afterstate-v1-capacity-aa0595c-r2","train_row_bytes_opened":false,"wrong_row_root":"/opt/value-afterstate-v0-e3e4-d9ad99f-r1/artifacts/dataset/rows"}
```

PR #167 remains deliberately **not** reviewable until the capacity receipt
exists and its immutable freeze binds this incident/re-entry provenance; the
pair then gets the one remaining consolidated source+freeze review. R4 and
PT-Luna0 need no repeated review while in their current states.

## Live work

### BELIEF R4 — top priority, hands off

- Strength Cloud exact execution head:
  `56bd35f0c45080121d094f6906ab8d1053ca9e6b`.
- Unit `belief-r4-terminal-scientific-56bd35f-r1.service` is active with zero
  restarts. The first synthetic scoring pass completed 1,339/1,339 and all five
  human transfer groups completed. The run is now at terminal-statistics
  derivation (3/6); cgroup peak remains 23.76 GB under the unchanged 24-GiB
  cap. Source inspection at the executing head proves the quiet substep is the
  first of three sequential calls: in-memory bootstrap statistics. The 27.82
  GB integrity-byte verification follows it and has not started. This phase
  has no trustworthy item counter or ETA, remains CPU-active, and has not
  published an outcome. Do not diagnose it as a hang or duplicate it.
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

### Value-Afterstate V1 — corrected capacity launch pending

- Capacity PR #166 exact head `aa0595cce9b626941c9cc4fd64062b4e06d10cf1`
  passed. Its first authorized command failed before any train-row byte opened
  due solely to the doubled `rows/rows` path above. Do not silently retry; wait
  for the exact command-only re-entry marker, then use the corrected dataset
  root and fresh output namespace `...-r2`. A metadata-only preflight now proves
  all 3,906 train-relative files exist, are regular mode-0400 files, and have
  exactly one hard link.
- Scientific PR #167 exact staged head
  `253e382e16883e2385bad14b0b8672795ea50dad` passes 193/193 pure and strict
  compiled tests. Initialization checks exact live source/runtime before
  spending the durable admission; the freeze builder now authenticates and
  content-binds the exact failed invocation and re-entry marker, and refreshes
  canonical main from the real GitHub URL rather than a staging-local origin.
  It is staged cleanly on Perf. Do not review it before the capacity receipt
  and freeze exist.
- This is a 520-root mechanism pilot, not a final-quality model claim. Eight
  seeds test optimization stability, not data sufficiency; any later scaling
  adds independent roots/replicates only after P0/P1 establish real action
  signal.

## Fleet and boundaries

| host | current use |
|---|---|
| Strength Cloud | R4 sole scientific terminal + verifier watcher; hands off |
| Perf Cloud | Idle; exact PR #166/#167 checkouts prepared; corrected capacity awaits command-only re-entry |
| Mini | free; no goal-critical run |

- Keep hosts, branches, runtimes, and artifacts isolated.
- Do not merge, deploy, resume R5, or launch Value capacity/scientific work
  without the exact review authority described above.
- Report percentages, ETA, utilization, and failures plainly. Use all cores
  for materially parallel workloads; do not add risky concurrency merely to
  make a short deterministic prep step look busy.
