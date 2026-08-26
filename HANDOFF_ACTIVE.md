# Active Claude/Codex handoff

Last reconciled: 2026-08-26 05:18 EDT.

Current operational truth only. Historical review evidence belongs in
`HANDOFF_REVIEW.md`. There is exactly one active review ask: the consolidated
PT1 r7 terminal-recovery source+freeze review below. Do not repeat the PT1 r7
scientific source/freeze review or any earlier PT/R4/R5 review.

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

The spent r7 root remains byte-for-byte unchanged. No score/action outcome was
opened while preparing the recovery; only file identity, terminal receipts and
SHA-256 hashes were read. No rehearsal and no second scientific run are
planned.

### Review queue — one consolidated PT1 recovery ask

The earlier `d1a7901` / `-r1` draft freeze and launcher are superseded and must
not be reviewed or executed; they never initialized a recovery root. Codex
strengthened the marker before review so every load-bearing receipt and runtime
field is authenticated.

Review draft PR #150 at exact head
`0faffcd4409af3c49750a52614cb955bc0be16cf`, stacked directly on reviewed
PR #149 head `76508ec9c15638e715dc8d48ee6719412233918b`, together with the exact
score-blind recovery freeze:

- freeze path:
  `/Users/jerryyu/Projects/pt1-recovery-freeze-0faffcd-r2.json`;
- freeze SHA-256:
  `f44db7a822e201ca0f880a1646c42e60183ab71d889f52912e1840b63cb2b813`;
- original r7 freeze SHA-256:
  `d05070d755d12f1a7c9a67471599377e0e590ed100f6beb315f7d8ccd915bc90`;
- original terminal failure SHA-256:
  `5b19450cbf775b721b5b8b6bf678d3f09dd509fc1d9529e134006aa6d0fe740d`;
- ordered 416-group tree SHA-256:
  `0a7b1e5523b883b051c0e99cbc7af0b68c47b6b66c6e98257189d69ef5041f74`;
- fresh recovery root, which must still be absent before execution:
  `/Users/jerryyu/Projects/shengji-pt1-recovery-0faffcd-r2`;
- exact marker file:
  `/Users/jerryyu/Projects/pt1-recovery-review-marker-0faffcd-r2.json`,
  SHA-256
  `8eac41b2449cc2b5461688d0de6d89cf11fd4708cd75c9fe401e346b655bd1fc`.
- exact one-shot launcher:
  `/Users/jerryyu/Projects/launch-pt1-r7-recovery-0faffcd-r2.sh`, mode `0500`,
  SHA-256
  `8963bd94ed0bf030249b072a0357d7acf4f5cb3587a463e3e0b2c91017501e6c`.

Review the exact type-handoff fix, all-416 ordered hash binding, immutable
source-root rule, record/manifest/statistics reconstruction, outcome packet
published last, and failure/no-retry witnesses. The repaired marker now also
binds the source progress/deadline receipts, original review commit and exact
recovery runtime hash; mutating the runtime while retaining the marker is a
permanent red test. Independently reproduce the
freeze, marker claim and launcher without parsing group result payloads.
Evidence at the head: **66/66 PT1 pure** and **66/66 strict compiled**, CI
server/frontend green, clean tree, diff-check and `zsh -n` launcher check. If
and only if all boundaries PASS, append
the exact marker line from the marker file to `HANDOFF_REVIEW.md` in one
single-file authenticated review commit. That marker authorizes only one
terminal-only recovery into the named fresh root; it authorizes no worker,
capture, evaluation, retry, state choice/drop, gameplay, strength, promotion,
deployment, training, merge or source-root mutation. No additional review
round is requested unless this review finds a load-bearing defect.

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
