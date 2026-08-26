# Active Claude/Codex handoff

Last reconciled: 2026-08-26 00:31 EDT.

Current operational truth only. Historical review evidence belongs in
`HANDOFF_REVIEW.md`. There is no active review ask; do not repeat the PT1 r7
review or any earlier PT/R4/R5 review.

## Live PT1 r7 — reviewed scientific execution on Mini

- Source: draft PR #149, exact head
  `76508ec9c15638e715dc8d48ee6719412233918b`.
- Freeze: `/Users/jerryyu/Projects/pt1-freeze-76508ec-r7.json`, SHA-256
  `d05070d755d12f1a7c9a67471599377e0e590ed100f6beb315f7d8ccd915bc90`.
- Consolidated PASS/marker commit:
  `5824d512d93f353730178b7697ed746b52a53680`.
- Exact launcher: `/Users/jerryyu/Projects/launch-pt1-76508ec-r7.sh`, SHA-256
  `061acb97850f9727d4721ea5bf6402f63ada36f5105134e7f23a6f1d882222f6`.
- Evidence root:
  `/Users/jerryyu/Projects/shengji-pt1-evidence-76508ec-r7`.
- Frozen runtime: Mini, 10 workers, strict compiled engine, 416 natural states,
  38.7-minute deadline ceiling.

The reviewed launcher first refused before initialization because one ignored
top-level `shengji/__pycache__/__init__.pyc` was present. The evidence root was
proven absent, so no admission, deadline, group, scientific byte or attempt was
spent. The cache was moved intact to
`/private/tmp/pt1-r7-prelaunch-pyc-20260826-002811`; an exact `-P -B` import
then proved `dont_write=True`, `safe_path=True`, strict native activation and
no regenerated cache. Invoking the unchanged reviewed launcher subsequently
authenticated the marker, initialized r7 once and entered scientific work.

At the first durable sample r7 was `RUNNING`, 10/416 groups (2.4%), ETA about
10.4 minutes, with all ten workers active around 93–98% CPU. Monitor only. Do
not signal, restart, mutate, inspect score/action payloads, merge the PR, or
create another review. The launcher will fetch canonical main again and run
the reviewed terminal verifier after execution.

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
