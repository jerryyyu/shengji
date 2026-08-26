# Active Claude/Codex handoff

Last reconciled: 2026-08-26 02:43 EDT.

Current operational truth only. Historical evidence belongs in
`HANDOFF_REVIEW.md`. There is **no active review ask**. Do not repeat PT1,
R4-source, or earlier R5 reviews.

## Priority 1 — live R4: monitor only

- Host/unit: `shengji-cloud` /
  `belief-r4-completion-e10cb3d-r3.service`.
- Exact source: `e10cb3d3426d758f2d757d41462aba6a06bc60c8`.
- Evidence root: `/opt/belief-r4-completion-v1-r3`.
- Latest read-only sample: active/running, `NRestarts=0`, no terminal or
  failure artifact, about 18.5 GB current / 20.7 GB peak memory.

R4 remains inside its calibration phase. The coarse outer progress record is
not a useful within-stage ETA. The unit has no systemd memory, swap or runtime
limit; do not describe 24 GiB as a live unit boundary. Do not signal, restart,
inspect outcome-bearing calibration/test bytes, or alter the host. When the
unit terminalizes, queue one independent terminal reconstruction and classify
all cohorts from sealed evidence before interpreting the scientific result.

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

## Priority 3 — prepare one recoverable R5 successor; launch held

Draft PR #148 remains at reviewed-source candidate
`7e14b529065383baee152c9dd2b8d3473627235c`.
Its prior `r14c` freeze is not an active review request and must not launch.
Perf Cloud is currently unreachable/powered off.

Codex is hardening the isolated successor so same-admission process recovery
is explicit and separately bound from scientific retry: sealed stages reopen,
the cache and training resume only from exact partial state, failed workers and
terminal partials fail closed, and a sealed terminal can only be reconstructed.
This work must pass the full pure/strict BELIEF suites and a score-free Perf
Cloud rehearsal before one fresh source+freeze review is queued. Do not review
or launch R5 until that exact head/packet replaces this paragraph and R4 has a
terminally interpreted result.
