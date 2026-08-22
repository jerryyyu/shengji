# Active Claude/Codex handoff

> Current operational truth and review queue only. Historical reviews belong
> in `HANDOFF_REVIEW.md` and Git history. A request not listed here is not
> active.

Last reconciled: 2026-08-22 01:33 EDT.

## Immediate objective

Carry BELIEF V2/R4 to one independently reviewed scientific terminal result:
does the learned ownership model measurably improve held-out calibration over
REF-C? Offline evidence cannot authorize a sampler, gameplay/strength claim,
promotion or deployment.

## Live state — exact-head rehearsal, not a scientific run

| field | current binding |
|---|---|
| PR | draft PR #123, `codex/belief-r4-progress-fix` |
| source | `656e6d0018a007f32f6b7a5f7bc113ca32dae6ce` |
| parent | `b78f802b81f86b7c88d529ad62f180eeef558665` |
| exact delta | 20 files, `+2323/-104`; CI green; worktree clean |
| host | `shengji-cloud` (`ubuntu-32gb-hel1-1`, 16 logical CPUs) |
| service | `belief-r4-rehearsal-656e6d0.service` |
| evidence | `/opt/belief-r4-rehearsal-656e6d0/evidence` |
| receipt | `/opt/belief-r4-rehearsal-656e6d0/receipt.json` (pending) |
| hard cutoff | 2026-08-22 04:34:45 EDT |

This is the one authorized non-scientific 104-round full-DAG rehearsal. It is
clean, exact-head, zero-resume, and cannot support a BELIEF/REF-C or strength
claim. Capture, 30 human fixtures, input index, five tensor caches, CPU device
qualification, all 25 reference tasks, and all four eight-member training
cohorts completed. Calibration selected `synthetic-primary` before any test
opening and is now independently reopening the persisted training/calibration
bytes. Terminal and receipt are not yet published. The service is healthy with
ample memory and deadline margin. Do not stop, restart or modify it.

Non-scientific training diagnostics only: calibration loss fell about 16.2%
for synthetic-primary and human-mixture, 17.3% for scale-50, and 10.5% for the
permuted-label control. Human-mixture exercised patience-3 early stopping;
the others reached the rehearsal's 30-epoch cap. These are pipeline signals,
not held-out evidence against REF-C.

## Review queue — one consolidated source review, then one freeze review

### 1. PR #123 source/design + eligible-rehearsal review — active

Claude may begin the code audit now, but must not issue PASS until the service
finishes and Codex appends the receipt path, SHA-256 and independent reopen
facts here. Review exact head `656e6d0018a007f32f6b7a5f7bc113ca32dae6ce`
against sole parent `b78f802b81f86b7c88d529ad62f180eeef558665`.

Audit the whole 20-file delta in one pass, especially:

- live canonical-main authorization by ancestry rather than mutable-tip
  equality, including can-fail history-rewrite witnesses;
- truthful phase-scoped progress and patience-3 early stopping;
- exact projection fallback for zero-support/unknown-card cases;
- fixed-order checkpoint/epoch reopen and exact source-population replay in
  calibration and terminal scoring;
- the prior self-consistent substituted-population failure class;
- the full-DAG rehearsal's exact source/runtime/device identity, all ten stage
  transitions, zero resume/retry/drop, closed artifact population and all-false
  authority map.

Return one PASS or HOLD containing every blocker found in this pass. On PASS,
append one canonical `HANDOFF_REVIEW.md` source/design marker. It may authorize
only fresh score-free H0/seed/capacity/device/deadline receipts and one new
immutable production freeze at this exact source. It does not authorize
initialization, scientific execution, test opening, merge or deployment.

### 2. Exact production-freeze review — queued, not yet actionable

After review 1 PASS, Codex will regenerate every source-bound score-free input
on the 16-CPU cloud host and build one fresh freeze. Claude then performs one
short exact-freeze review binding the final head, source-review commit, H0
inventory/split, seed scan/registry, capacity/device/deadline receipts,
resource caps, runtime/native/boot identities, evidence namespace, supervisor
plan and all-false downstream authority. No subsystem review is requested
between reviews 1 and 2.

If review 2 passes, the user has directed Codex to launch the full scientific
run overnight. No further routine approval round is requested.

## Retired state that must not be revived

- The prior `b78f802` R4 admission is spent and failed before scientific
  evidence because a mutable-main equality guard killed it. Its partial capture
  remains historical evidence only and is not reusable.
- The current rehearsal is disposable and cannot be promoted into scientific
  evidence or reused as a production input.
- Do not merge PR #123, open an old sealed outcome, reuse an old freeze,
  initialize early, or add review layers not named above.

## Next operator sequence

1. Let the rehearsal finish; Codex independently validates the receipt and
   updates this file with exact receipt evidence.
2. Claude finishes review 1 and writes one source/design PASS or HOLD.
3. On PASS, Codex runs fresh score-free inputs and seals one production freeze.
4. Claude performs review 2 only.
5. On PASS, Codex launches and monitors the scientific run with exact percent
   progress, then requests one terminal/reproducibility review.
