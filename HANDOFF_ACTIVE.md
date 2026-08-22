# Active Claude/Codex handoff

> Current operational truth and review queue only. Historical reviews belong
> in `HANDOFF_REVIEW.md` and Git history. A request not listed here is not
> active.

Last reconciled: 2026-08-22 03:00 EDT.

## Immediate objective

Carry BELIEF V2/R4 to one independently reviewed scientific terminal result:
does the learned ownership model measurably improve held-out calibration over
REF-C? Offline evidence cannot authorize a sampler, gameplay/strength claim,
promotion or deployment.

## Live state — one narrow source-delta review is actionable

| field | current binding |
|---|---|
| PR | draft PR #123, `codex/belief-r4-progress-fix` |
| repaired head | `55f50432c1dabe563cbd5dd0c1983815d65656a6` |
| exact parent | `656e6d0018a007f32f6b7a5f7bc113ca32dae6ce` |
| repair delta | 3 files, `+149/-2`; worktree clean; pushed |
| host | `shengji-cloud` (`ubuntu-32gb-hel1-1`, 16 logical CPUs), idle |
| scientific run | not initialized; no scientific test split opened |

The final canonical verdict at `343214c` supersedes the concurrent PASSes and
HOLDs exact source `656e6d0`: its only source blocker was that the disposable
full-DAG rehearsal patched `_stage_gate` to a no-op. The repaired head adds one
genuine-admission integration witness which calls the real production gate at
all ten stage import altitudes with exact live source/runtime/device checks,
then proves the same traversal refuses a forged `canonical_remote_tip`.

The first fresh production input attempt at `656e6d0` also made the seed
registry refuse, correctly, on two unreviewed explicit constants: the shifted
`COHORT_SEEDS` identity and the new rehearsal-only seed namespace. The repaired
head classifies only those two as `derived-rng-stream` and adds exact-identity
witnesses. An exact clean-head rebuild now closes 5,553/5,553 candidates across
31 registered populations with zero V2 collisions; registry SHA-256 is
`8e16ab5c44f3ec79f6e603b5e9730a57e8bcd7c8c3a368a4b6846b80826ac73b`.

Validation at exact `55f5043`: focused gate/registry 4 passed; broader
`tests/test_belief_v2_*.py` 235 passed / 1 skipped in compiled mode;
`git diff --check` passes. No second rehearsal was run or requested.

The incomplete `/opt/belief-r4-656e6d0-freeze-inputs-r1` contains only H0,
seed-scan and re-entry inputs from the refused attempt. It is historical and
must not be completed, reused or treated as a receipt. Fresh inputs use a new
namespace only after the review below passes.

## Review queue — exactly two reviews before launch

### 1. PR #123 narrow repair delta — active now

Review exact head `55f50432c1dabe563cbd5dd0c1983815d65656a6`
against sole parent `656e6d0018a007f32f6b7a5f7bc113ca32dae6ce`.
This is a three-file delta only. Do not reopen the already-adjudicated 20-file
source design or request another rehearsal.

Verify in one pass:

- `test_genuine_admission_traverses_every_unpatched_stage_gate` uses an
  authentic append-only review commit and admission, leaves `_stage_gate`
  unpatched, executes exact live source/runtime/device validation at all ten
  imported stage gates, and makes every gate refuse a forged recorded tip;
- the two seed candidates are exactly the non-population cohort-init stream
  and disposable rehearsal namespace, both classified
  `derived-rng-stream`; removing either identity makes the real registry build
  refuse;
- the exact clean-head registry rebuild and test counts above reproduce.

Return one PASS or HOLD containing every blocker in this delta. On PASS append
one superseding source/design marker for exact `55f5043`. It may authorize only
fresh score-free H0/seed/capacity/device/deadline receipts and one immutable
production freeze. No initialization, scientific execution, test opening,
merge, retry or deployment.

### 2. Exact production-freeze review — queued, not yet actionable

After review 1 PASS, Codex will regenerate every source-bound input in a new
namespace on the 16-CPU cloud host and build one immutable freeze. Review only
that freeze, binding its exact source-review commit, H0 inventory/split, seed
scan/registry, capacity/device/deadline receipts, resource caps,
runtime/native/boot identities, evidence namespace, supervisor plan and
all-false downstream authority.

If review 2 passes, the user has already directed Codex to launch the full
scientific run. No additional routine approval round is requested.

## Next operator sequence

1. Claude performs review 1 only.
2. Codex builds fresh score-free receipts and one immutable freeze.
3. Claude performs review 2 only.
4. On PASS, Codex initializes and launches the scientific run with exact
   progress reporting; one terminal/reproducibility review follows completion.
