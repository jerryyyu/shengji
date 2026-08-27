# Active Claude/Codex handoff

> **Purpose:** current operational state only. Do not append historical
> overrides or completed review packets here. Durable review evidence and raw
> markers belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and
> `RL_PLAN.md`.
>
> **Canonical paths:** coordinate through
> `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. Branch-local copies are
> not review authority. If this snapshot conflicts with an exact marker on
> remote main, the latest authentic exact-head marker controls.

Last reconciled: **2026-08-27 08:52 EDT**. Remote main:
`69be1e211e0ae55bbe161a042109f009da99fbb2`.

## Review queue

**No active review ask.** Do not repeat PR #152, #153, #154, or #155 reviews.
The only live work is already authorized and must be monitored without source,
freeze, or rehearsal review churn.

The next legitimate review request is whichever of these materializes first:

1. a completed PT-Sol0 report needing one exact-source reopen/result review;
2. a load-bearing defect or changed bytes in the R4 cutover path; or
3. the future single consolidated R5 source + rehearsal + freeze packet.

Do not create an intermediate R5 review. Do not treat a progress update as a
review request.

## Live fleet

| host | job | exact source | current state | authority |
|---|---|---|---|---|
| Mini | PT-Sol0 | `e73f970ec6831847c99c68aa0e08648994a3858b` | launchd active; 2/52 roles complete (3.84%), two more Sol role processes live | monitor only; no retry/merge/strength claim |
| Perf Cloud | optimized R4 calibration | `d82ba224eb59a25014b076fb07116eaa6513934a` | systemd active, zero restarts, 16 workers, synthetic REF0 complete and REF1 397/1,326 | finish calibration, verify, then reviewed cutover |
| Strength Cloud | serial R4 fallback | `e10cb3d3426d758f2d757d41462aba6a06bc60c8` | systemd active, zero restarts, outer milestone 1/6 | preserve until optimized calibration seals and reopens |
| Air | none | — | idle | none |

No R5 process is running.

## PT-Sol0 — live Mini diagnostic

- PR #155 received canonical PASS on remote main `69be1e2` for exact head
  `e73f970e` and frozen design SHA
  `31f0be8fa06ff65b73f90d633491b94816c1804364dd2a609e9fd99a4481a7e8`.
- One authorized 26-root / 52-role open-DEV execution is live under launchd
  label `org.shengji.ptsol0-e73f970-r1`, with two roots concurrent.
- Public output:
  `/Users/jerryyu/Projects/shengji-ptsol0-e73f970-r1.json`.
- Private evidence root:
  `/Users/jerryyu/Projects/shengji-ptsol0-e73f970-r1-private`.
- Monitor log:
  `/Users/jerryyu/Projects/shengji-ptsol0-e73f970-r1.log`.
- The exact Git/native/Python/Codex/design checks passed at launch. Two fresh
  ephemeral `gpt-5.6-sol` processes run at high reasoning in isolated temporary
  workspaces. The engine retains the real `Round`, legal ballot, rollout
  execution, budgets, and completion token.
- Expected progress is one `PT_SOL0_PROGRESS` record per completed role
  (1.92%). The first two roles completed in about ten wall minutes with two
  roots concurrent; the emitted observed ETA after role 2 was 4.18 hours.
  Early throughput is not yet stable, so retain the 4.5–6.5-hour planning
  range until more roles complete.
- Never restart or substitute this attempt. When the public report appears,
  independently reopen it at the exact source and request only the terminal
  interpretation needed by the protocol.

## R4 — optimized completion and one-shot cutover

### Current measurement

At 2026-08-27 08:52 EDT the Perf unit
`belief-r4-parallel-completion-d82ba22-r1.service` was active with zero
restarts, 36 tasks, and 15.2/24 GiB memory. It completed all 1,326 synthetic
REF0 rounds and 397/1,326 synthetic REF1 rounds: 1,723/2,652 (**64.97%**) of
the two dominant synthetic passes. Recent REF1 pace is about 39–40 seconds per
round, implying roughly 10–11 hours for the rest of REF1 if that pace holds.
Two much smaller human-reference passes plus derivation/publication follow.
The test split remains unopened.

**Counter interpretation:** `score-r4-calibration-populations: 1/6` is a
heterogeneous milestone counter: synthetic REF0, synthetic REF1, human REF0,
human REF1, statistic derivation, and publication. It is not six equal
1,326-round populations. Do not project 6 × the first synthetic pass or quote
the resulting 88–101 hour estimate. The later human/finalization wall remains
unmeasured; preserve the live lane and use actual phase telemetry.

The serial Strength fallback
`belief-r4-completion-e10cb3d-r3.service` remains active at outer milestone
1/6. The user is willing to stop it, but the reviewed cutover contract requires
waiting until Perf calibration seals and independently reopens.

### Already-reviewed operator sequence

No new review is needed if all bytes and identities remain unchanged.

1. Require the Perf calibration unit to exit successfully. At exact source
   `d82ba224`, run `r4-verify-calibration` and retain its canonical readiness
   JSON. Reconfirm that both test namespaces are unopened.
2. Only after step 1, stop
   `belief-r4-completion-e10cb3d-r3.service` on `shengji-cloud` exactly once.
   Never restart it.
3. From `/private/tmp/shengji-r4-cutover-receipt` at exact reviewed head
   `c1232854a193b34c3e7f6d3117780ec518a3b167`, run the cutover controller once
   with review commit `11ad63777c9f484bf09402691dafdcd0ab062cbb` and output
   `/Users/jerryyu/Projects/shengji-r4-cutover-c123285-r1.json`.
4. Only a canonical `READY` receipt permits PR #152's single optimized
   `r4-open-test` invocation on Perf at source `d82ba224`, under a fresh
   no-restart, 24-GiB, 48-hour unit. PR #152 review authority is
   `394354fc922fc00810296da4be3ed299112363b9`.
5. On success, run `r4-verify-terminal` independently at the same exact
   source/runtime and compare the reopened terminal bytes and verdict.

Do not open test early, stop the serial fallback early, retry a one-shot step,
or infer an R4 answer from partial calibration output.

## R5 — source ready, execution intentionally pending

- Exact source: `9c5928f2ea1b6faa43684689735c9cec32e5207c`.
- No PR/freeze/review/run is active for this exact packet.
- Exact-head local validation is green: 495 passed / 6 skipped pure; 497 passed
  / 4 skipped strict compiled/native; high-risk subset 122/122 in both modes.
- Host-independent inputs are sealed under
  `/private/tmp/shengji-r5-9c5928f-freeze-inputs-local`: current seed registry,
  H0 inventory/split, authenticated V1 resource-failure receipt, and named
  re-entry rationale. Do not regenerate them solely because host evidence is
  pending. Do not use the obsolete project-level `belief-v2-h0-inventory-v1`.
- After R4 releases Perf, run one fresh clean-head 104-round full-DAG rehearsal
  on that same Perf runtime, collect fresh all-rank capacity/deadline/runtime
  evidence, and build the immutable freeze.
- Request exactly one consolidated review binding source, rehearsal identity,
  runtime/device identity, freeze, caps, registry, and all-false authority map.
  Do not split this into intermediate approvals.

## Closed results that must not be repeated

- PT-Full and PT/C0 source/result evidence are complete and serve only as
  immutable parents for PT-Sol0.
- C0 terminal verdict: **SELECT NONE**. C0-S was least bad, but no C0 arm had a
  positive mean against both PT-Full A and B. Bare-point avoidance did not
  transport into positive whole-round value.
- PR #153 canonical reopen repair is PASSed and spent for interpretation; no
  rerun is authorized.
- No completed PT result authorizes BELIEF integration, production behavior,
  promotion, deployment, or a strength claim.

## Immediate operator priorities

1. Monitor PT-Sol0 and publish progress only; do not interfere.
2. Monitor optimized R4 until calibration seals, then execute the reviewed
   five-step cutover without another review round.
3. Keep the serial R4 fallback alive until that cutover gate.
4. Keep R5 source-only until Perf is released, then form one consolidated
   review packet.
