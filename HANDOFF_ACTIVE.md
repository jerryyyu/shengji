# Active Claude/Codex handoff

Last reconciled: 2026-08-26 01:32 EDT.

Current operational truth only. Historical review evidence belongs in
`HANDOFF_REVIEW.md`. There is exactly one active review ask: independently
reproduce the PT1 r7 recovered terminal result below. Do not repeat any PT1
source/freeze review or any earlier PT/R4/R5 review.

## PT1 r7 — recovered terminal packet says `REFUSED`; reproduce once

- Recovery source: draft PR #150, exact head
  `0faffcd4409af3c49750a52614cb955bc0be16cf`.
- Recovery authorization/PASS commit:
  `6d700051b78f0b5a7c437e7e426733ef0b7b556a`.
- Recovery root:
  `/Users/jerryyu/Projects/shengji-pt1-recovery-0faffcd-r2`.
- Packet SHA-256:
  `bffaafef27cec6b0b37f0bdd1d1011531bbb1f38064421b47a8ae30b22a2b39a`;
  internal packet identity
  `c3f16d9fe72b67288934192e54bb02b8b93b34c9456e681dab1c873fa8e9df96`.
- Manifest SHA-256:
  `ca1c613256c569a25f9378564956e6aae3699da0f2c7ab9784cce3a8703c649d`.
- Statistics report identity:
  `4d49af2bcca32b2257a8a4f79ea6a0fed5850a7179e09078471f930eaf13908d`.

Codex ran the exact reviewed launcher after moving Claude-review-created
ignored bytecode caches intact to
`/private/tmp/pt1-recovery-review-pyc.GzlkxN`. The first invocation refused
before recovery-root creation; the unchanged second invocation completed, and
its built-in verifier plus one independent repeat verifier both PASSed. The
spent r7 source root retains the exact freeze/failure/progress/deadline hashes
and all 416 groups.

The preregistered result is `REFUSED`: 416 states / 1,664 records complete;
mean C−B `1/208 ≈ 0.00481` signed levels (floor `0.01`), bootstrap lower bound
`0`, and only **1/416** positive states (required 24). All integrity/mechanics
gates pass: zero C regret, no negative C−B/C−A states, nonnegative role and
horizon means. The exact teacher changed B's action in 1,128/1,664 records but
almost every change was a value tie. B−A was positive in 5/416 states with
mean `1/64`; C−A was positive in 6/416 with mean `17/832`.

### Review queue — one terminal reproducibility ask

At exact source head `0faffcd`, independently run the reviewed recovery
verifier over the immutable root and reconstruct the statistics report from
all ordered 416 groups. Confirm the four packet/manifest/report hashes above,
the exact failed gates and metrics, all-false authority, original-r7 root
immutability, and that no group was omitted, retried or selected by outcome.
Then append one terminal verdict entry to `HANDOFF_REVIEW.md`. No marker or new
authority is requested, and no further PT1 review round is needed unless this
reproduction finds a load-bearing discrepancy.

## Live R4 — monitor only, do not touch

- Host/unit: `shengji-cloud` /
  `belief-r4-completion-e10cb3d-r3.service`.
- Exact source: `e10cb3d3426d758f2d757d41462aba6a06bc60c8`.
- Evidence root: `/opt/belief-r4-completion-v1-r3`.
- Last read-only sample: active/running, `NRestarts=0`, calibration outer
  stage 1/4 (25%), test unopened, inner worker about 969% CPU, memory
  current/peak about 18.3/20.7 GB below the 24-GiB boundary.

The 25% file is a coarse outer-stage counter, not a stall. R4 remains the first
BELIEF scientific verdict and must be independently reopened after terminal.

## R5 — held

Do not launch or request another R5 review until R4 is terminally interpreted
and PT1 r7 is terminally verified. Preserve the isolated successor work and
all prior evidence; there is no active R5 review ask.
