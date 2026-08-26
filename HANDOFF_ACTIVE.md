# Active Claude/Codex handoff

Last reconciled: 2026-08-26 10:45 EDT.

Current operational truth only. Historical evidence belongs in
`HANDOFF_REVIEW.md`. There is exactly **one active review ask**, PR #151 below.
Do not repeat PT1, R4-source, earlier R5, or superseded freeze reviews.

## Priority 1 — live R4: monitor only

- Host/unit: `shengji-cloud` /
  `belief-r4-completion-e10cb3d-r3.service`.
- Exact source: `e10cb3d3426d758f2d757d41462aba6a06bc60c8`.
- Evidence root: `/opt/belief-r4-completion-v1-r3`.
- Latest read-only sample at 09:29 EDT: active/running, `NRestarts=0`, no
  terminal or failure artifact, about 18.5 GiB unit memory / 20.7 GB peak;
  the scoring worker itself is about 6.1 GiB and 289% CPU.

R4 remains inside its calibration phase. The coarse outer
progress record is not a useful within-stage ETA: outer unit 1 alone scores all
1,326 synthetic calibration rounds against four cohorts before it can increment
from 0/6. The worker remains runnable, so this is a long serial scoring unit
rather than evidence of a stall. Current ETA is roughly another 30--42 hours,
with a tighter bound only after the first population completes. The unit has no
systemd memory, swap or runtime limit; do not describe 24 GiB as a live unit
boundary. Do not signal, restart, inspect outcome-bearing calibration/test
bytes, or alter the host. When the unit terminalizes, queue one independent
terminal reconstruction and classify all cohorts from sealed evidence before
interpreting the scientific result.

Codex is preparing draft PR #152, an exact-output parallel evaluator on Perf
using a fresh completion namespace and a byte-for-byte copy of the already
sealed R4 source artifacts. This is preparation, not an active review ask yet.
The serial unit is the safety path and must not be stopped until the optimized
path has completed all calibration, independently reopened it, and passed the
explicit pre-test readiness check with both test namespaces untouched. Only
then may one cutover precede the single test opening.

## Priority 2 — PT1 is closed as a clean negative

PT1 r7 terminal recovery at exact `0faffcd4409af3c49750a52614cb955bc0be16cf`
completed over all 416 states / 1,664 records. Claude independently rebuilt
the statistics from the sealed group bytes at canonical commits `d911e09` and
`9985eb6`; the preregistered `REFUSED` verdict is final.

- mean exact-teacher C−B: `1/208 ≈ 0.00481` versus floor `0.01`;
- bootstrap lower bound: `0`;
- positive states: `1/416` versus required 24;
- all integrity/mechanics gates passed and all authority remained false.

The exact teacher changed 1,128/1,664 actions but almost all changes were
round-value ties. This closes this late-endgame acquisition recipe; no further
PT1 review, rerun, gameplay, strength, promotion or deployment action follows.

## Priority 3 — one PT-Full source review, then bounded Mini DEV run

Draft PR #151 is exact repaired head
`c6e8d08cf9f03d341c61192e8cef3c9dcfa117d5`. Its production and design bytes
are unchanged from reviewed head `2b874075`; the repaired head adds exactly two
failure directions to one test. The lane asks the
whole-play information-value question that PT1 could not: public production A
versus repeated public-world collapse control A0 versus repeated exact true
world B, across 13 ranks and both partnership roles (26 roots / 52 comparison
records / 130 played rounds). It is DEV-only and all scientific, gameplay,
strength, promotion, deployment, merge and training authority is false.

### Review queue — precise ask

Perform only the promised narrow repaired-head re-check at exact
`c6e8d08cf9f03d341c61192e8cef3c9dcfa117d5`:

1. neutralize the record-level `n_determinizations == 30` guard and require
   `test_exact_work_wiring_passes_and_each_failure_direction_refuses` to fail;
2. restore it, neutralize the per-candidate `n_by_candidate == 30` guard, and
   require the same test to fail with the exact-work refusal.

The repaired head is CI-green; the focused witness is 1/1 in pure and strict
compiled modes; the complete privileged-teacher chain is 125/125 in both
modes; `git diff --check` passes. All other findings from ledger `74d6064`
carry forward. If both mutations are killed, append one exact-head `PASS`
authorizing only one bounded 26-root open-DEV Mini run. Do not repeat the full
source review or require a second freeze review, and do not authorize merge,
gameplay, strength, promotion or deployment.

## Priority 4 — prepare one recoverable, faster R5 successor; launch held

Draft PR #148 is now exact clean head
`232fc27610b9caef759179a94751308f49f8a939`. Its prior `7e14b52` / `r14c`
freeze is superseded, is not an active review request, and must not launch.
Server and frontend CI are green and the PR is mergeable. Full exact-head
BELIEF is 485 passed / 6 skipped pure and 487 passed / 4 skipped strict
compiled.

The source at #148 binds same-admission process recovery separately from retry:
sealed stages reopen, cache/training resume only from exact partial state,
completed tasks may never regenerate a missing final, failed workers and
terminal partials fail closed, and a sealed terminal can only be reconstructed.
Perf Cloud is online. Exact-head x86 recovery tests passed 73/73; the fresh
416-round/all-rank capacity receipt passed in 6m29 wall / 1h39 CPU at 2.4 GiB
peak, and the deadline receipt passed in 3m48 wall / 16m27 CPU at 3.2 GiB peak.
Those receipts opened no test data and authorize no pipeline execution.

R4 exposed one remaining performance issue before freeze: calibration/test
scoring is serial across four populations and sequential across model
predictions, leaving most cores idle. Codex is implementing and benchmarking
only deterministic round/population parallelism with byte-identical serial
parity on Perf. If source changes, the `232fc27` receipts are diagnostic only
and must be regenerated at the final head. Then generate exactly one fresh
source+freeze packet and request one consolidated review. Do not launch R5
until that packet passes and R4 has a terminally interpreted result.
