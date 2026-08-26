# Active Claude/Codex handoff

Last reconciled: 2026-08-26 09:40 EDT.

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

R4 remains inside its calibration phase after about 12 hours. The coarse outer
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

Draft PR #151 is exact head
`ee1c27e708bf5323b3c1854ee6b59eec24607982`, four new files only. It asks the
whole-play information-value question that PT1 could not: public production A
versus repeated public-world collapse control A0 versus repeated exact true
world B, across 13 ranks and both partnership roles (26 roots / 52 comparison
records / 130 played rounds). It is DEV-only and all scientific, gameplay,
strength, promotion, deployment, merge and training authority is false.

### Review queue — precise ask

Review PR #151 once at exact head `ee1c27e`. Check especially:

1. private 32-byte mode-0600 seed input: only its SHA-256 commitment and root
   hashes leave the runner, so coordinates cannot reconstruct hidden deals;
2. exact-work wiring: every contested decision must prove `N=30`, report
   `R=300`, selection `30*K`, report 600, total `30*K+600`, complete sampler
   reconciliation, and aggregate equality; any short/zero path refuses;
3. A is run once per root; A0/B treat each partnership separately with shared
   initial root and policy seeds; A0 is hidden-twin invariant and B returns the
   exact current hidden world;
4. hard Mini hostname, exact clean Git/native identities, deterministic output,
   false authority, semantic re-open and progress visibility.

Evidence: 125/125 focused PT tests pure and 125/125 strict compiled; independent
Terra adversarial review found and then verified repairs for reconstructible
seeds and underfilled work. If clean, append one exact-head `PASS` authorizing
only one bounded 26-root open-DEV Mini run. Do not require a second freeze
review, and do not authorize merge, gameplay, strength, promotion or deployment.

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
