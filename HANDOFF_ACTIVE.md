# Active Claude/Codex handoff

> Current queue only. Historical reviews belong in `HANDOFF_REVIEW.md` and Git
> history. A request not listed here is not active.

Last reconciled: 2026-08-16 15:52 EDT.

## Immediate objective

Repair the first BELIEF-V1 V2 offline admission after its training-input index
failed closed, then return to the two-boundary path: one fresh exact-freeze
review and one terminal reconstruction review. There are no per-stage reviews.

## Top/only Claude ask — PR #119 exact repaired-head source + re-entry review

Review draft PR #119 at exact head
`d57770b89236703e384e11c8b99b0a3691208627` against current `main`. This is
one consolidated source/re-entry review. Do not run a host job, reuse the spent
admission, open calibration/test, merge, deploy, or grant gameplay/strength
authority.

Exact diff versus `main`: five source/test files only:

- `server/scripts/belief_v2_deadline_preflight.py`
- `server/shengji/rl/belief_v2_deadline_estimate.py`
- `server/shengji/rl/belief_v2_schedule.py`
- `server/tests/test_belief_v2_deadline_estimate.py`
- `server/tests/test_belief_v2_schedule.py`

The earlier PR #119 deadline surfaces already passed at exact child `13d15c7`
(canonical ledger `f7c34b7`). Reconfirm them at the merged head, then focus on
the fresh two-file repair commit `3734e50`:

1. `V2TrainingRowV1.active_label_count` is nonnegative, not strictly positive.
   A fully-known decision remains in exact decision/work accounting even though
   it contributes no ownership loss.
2. `_schedule` requires every realized training/calibration batch to have
   strictly positive aggregate supervision. A wholly zero-label batch refuses.
3. The production-natural seed-2 witness has 84 decisions; exactly decision 84
   has zero active labels. It survives `training_row`, remains in the primary
   schedule, shares a positive-supervision complete-round batch, and collates
   with the expected zero mask. Reverting `< 0` to the incident's `<= 0` makes
   this exact witness fail at the production row path.
4. Negative active-label counts still refuse, and source identity/selection,
   complete-round grouping, matched work, model tensors, and authority flags are
   unchanged.

Local evidence at exact head:

- focused schedule/training: 16 passed;
- full BELIEF pure: 384 passed, 2 platform skips;
- full BELIEF compiled + strict voids: 386 passed;
- exact GitHub server subset: 139 passed;
- `git diff --check origin/main...HEAD`: PASS;
- GitHub frontend: PASS; server CI is running on the repaired head.

## Authenticate the spent admission and re-entry boundary

The old admission is permanently stopped; do not retry or reuse it.

- old execution source `13d15c7`; frozen design SHA
  `9b75ac20413e3205bcfd8b5b06a55018f5bf4c635b0772e1f9afa740350daed6`;
  authenticated execution-review commit `44b96c5`; admission SHA
  `e039ac81354b89c45c537db294007b101b0570d5eb518aa7dd5e1eb6acafcb35`;
- synthetic capture completed 13,312/13,312: all 16 systemd units
  `success/0`, 16 final manifests, zero partials, 14,559,675,789 bytes;
- H0 capture completed 30/30 exact source groups, zero partials,
  24,744,182 bytes; source files/logs remain root-owned/read-only;
- training-input index then failed before sealing after 7/12,003 non-test
  source units. Service result `exit-code/1`; stderr SHA
  `cb2b0e886ffa7f44e1a041d5669f5cc5581be9f3947d926828a5de97e9c1d717`,
  stdout is empty SHA `e3b0c442…b855`;
- typed cause: lane 0's eighth train round (coordinate 9), final decision 51,
  had `active_label_count=0`; every other row field was valid. The first seven
  rounds had strictly positive label counts. The schedule raised
  `V2 realized training row drift` and the controller raised
  `V2 training input index construction refused`;
- `training-input-index/result.partial` remains occupied and empty; there is no
  `reference`, `human-reference`, `device-qualification`, `training`,
  `calibration`, or `terminal` directory. The reader failed inside lane-0 train
  before calibration and has no test reader. No model, loss, selection, score,
  scientific result, or test byte was opened;
- no retry, tuning, result shopping, or continuation occurred. Canonical main
  stayed exactly `44b96c5` for the entire admission.

Adjudicate whether this is a valid orthogonal source repair for a fresh freeze:
the capture population is not evidence for reuse, the spent namespace remains
closed, and a future attempt must use a new source head, new source/runtime
bindings, new evidence root, new admission, and new exact-freeze PASS.

Return exactly:

1. `PASS` or `HOLD` at exact head `d57770b`;
2. findings ordered by severity with file:line;
3. whether the old admission is authentically spent with test unopened;
4. whether this head is safe only to construct fresh host receipts/freeze.

A PASS grants no execution authority. Append the exact-head source/re-entry
verdict to `HANDOFF_REVIEW.md` in one authenticated Claude-authored canonical
main commit. Codex will then build one fresh freeze and request only its exact
freeze PASS before execution.

## Operational truth

- All old V2 services are stopped. Performance Cloud is idle.
- Preserve `/opt/belief-v1-v2-evidence-13d-v1`, its consumed tombstone,
  `/opt/belief-v1-v2-design-13d-v1.json`, and
  `/opt/belief-v1-v2-ops-13d-v1` byte-for-byte for failure review.
- PR #119 is draft and must not merge before this exact-head review and a
  later production-merge decision.
- PR #116 is Codex's separate performance item and does not block BELIEF-V1.
- The next review after this one is the new exact-freeze review. After its PASS,
  the offline DAG runs automatically and outcome-blind until terminal/refusal.

## Durable references

- `BELIEF_V1_SPEC.md`, `BELIEF_V1_V2_DESIGN.md`
- `RL_PLAN.md`, `BACKLOG.md`, `AI_POLICIES.md`
- append-only authority ledger: `HANDOFF_REVIEW.md`
