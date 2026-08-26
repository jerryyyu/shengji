# Active Claude/Codex handoff

Last reconciled: 2026-08-26 04:17 EDT.

Current operational truth only. Historical review evidence belongs in
`HANDOFF_REVIEW.md`. There is no review ask yet; do not repeat the PT1 r7
source/freeze review or any earlier PT/R4/R5 review. Codex is preparing one
consolidated terminal-recovery source+packet ask below.

## PT1 r7 — 416/416 sealed; terminal reducer defect; recovery in preparation

- Source: draft PR #149, exact head
  `76508ec9c15638e715dc8d48ee6719412233918b`.
- Freeze: `/Users/jerryyu/Projects/pt1-freeze-76508ec-r7.json`, SHA-256
  `d05070d755d12f1a7c9a67471599377e0e590ed100f6beb315f7d8ccd915bc90`.
- Consolidated PASS/marker commit:
  `5824d512d93f353730178b7697ed746b52a53680`.
- Evidence root:
  `/Users/jerryyu/Projects/shengji-pt1-evidence-76508ec-r7`.
- Durable state: `FAILED`, completed `416/416`, all 416 immutable group files
  present, no `packet.json` or `manifest.json`, score/action payloads not opened
  for interpretation. Failure receipt SHA-256:
  `5b19450cbf775b721b5b8b6bf678d3f09dd509fc1d9529e134006aa6d0fe740d`.

The failure is downstream plumbing, not a scientific verdict. The execution
path reopens each group into a hash-bound identity-only state and validates all
416 identities against the frozen population manifest. It then passes those
identity-only states to `reduce_pt1_statistics`, whose first line incorrectly
calls the live-population validator requiring a `NaturalPT1State` with a live
`Round` and true-world capability. That type mismatch deterministically raises
`natural population integrity refusal` only after the final group is sealed.
Every execution test had monkeypatched the reducer, so no end-to-end witness
crossed this exact handoff.

Top priority: preserve the spent r7 root byte-for-byte and build a narrow,
separately reviewed terminal-only reducer. It must consume exactly the frozen
416 group hashes in canonical order, verify every group/record/manifest binding,
write to a fresh recovery root, and publish the one preregistered aggregate.
It may not run workers, choose/drop states, mutate r7, or inspect results before
the review marker. Request exactly one consolidated source+recovery-packet
review when Codex posts the exact head and packet; no rehearsal and no second
scientific run are planned.

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
