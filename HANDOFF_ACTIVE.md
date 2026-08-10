# Active Claude/Codex handoff

Last compacted: 2026-08-10 06:42 EDT. This is the executable mailbox.
Terminal markers live in `HANDOFF_REVIEW.md`, policy synthesis in
`AI_POLICIES.md`, job artifacts in `JOBS.md`, and queue order in `BACKLOG.md`.

## Immediate gate

**Review capture v3 before anything else.** The v1 PASS at `cc19133` is
superseded and cannot issue a receipt. Later terminal-path audits proved v1's
population witness forgeable and v2's rejection/uncertainty disposition still
forgeable. The exact runnable successor is draft PR #9:

- source `0b697b6e5eee1891ca73737cb689591f8f2879df`;
- packet commit `2547592`;
- packet `server/runs/logs/teacher-v3-hard-tail-stage-c-capture-controller-v3/controller_packet.json`;
- external packet SHA `d58a9308…c91`;
- exact requested marker: `TEACHER_STAGE_C_CAPTURE_CONTROLLER_V3_REVIEW ` in
  the latest `HANDOFF_REVIEW.md` entry.

Mini is staged cleanly at that exact source. It reopens the live compiled
`mc-s0-report-lcb` parent and every frozen dependency; the capture namespace,
receipt and durable admission slot are absent. The focused/transitive capture
slice passes 50/50. A v3 PASS permits one score-free execution only.

## Current truth

| area | current evidence | next legal action |
|---|---|---|
| Production | Release 17 runs compiled, formally confirmed `mc-s0-report-lcb`. | Monitor only; no production change is part of T4. |
| S4 point banking | **TERMINAL SCREEN PASS:** treatment−champion `+0.086914 +/- 0.056166`, one-sided LCB `+0.030748`; treatment−null is identical and null−champion is exactly zero. | Preserve the result. Confirmation-packet review is eligible, but the current goal explicitly stops before confirmation launch. Frozen projection is `365.592` fleet-hours / `45.699` max-shard hours. |
| H0 human/V11 diagnostic | **TERMINAL NO-USE:** 555/557 complete, two score-free refusals, status `REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY`. | No retry and no partial-row mining. Stage C admits no human-derived proposer. V11 remains only its separately frozen bounded proposal source. |
| Stage-C capture | **V3 REVIEW REQUIRED / ZERO STATES.** V1 PASS is stale authority. | External PASS/HOLD on exact `0b697b6` / `d58a9308…c91`; on PASS admit once and run 24 shards with eight workers. |
| Stage-C state set | Not created. | After capture, freeze exactly 2,048 states (`1024/512/512`, play/bury `1920/128`) and replay all 750,000 dispositions with eight workers; then external state-set review. |
| Stage-C labels | Source ready on PR #13 at `6e51fd3`; no packet or outcome exists. | After state-set PASS, freeze/review a 32-state score-free capacity pilot. Only a reviewed capacity PASS may open the 16-shard label packet. |
| Stage-C model | Model/training stack ready through PRs #14–#17; no Stage-C checkpoint exists. | After complete labels, train play/bury surfaces across eight seeds and three DESIGN curves; select only on DESIGN/CALIB and open REPORT once. |
| Stage-C composition | PR #18 HOLD repairs are pushed at `e93417d`; source rereview is open. | Source PASS may authorize only a later score-free capacity preflight. No composition run exists. |
| S6 throw sourcing | PR #19 at `bf7eace` freezes three KESP witnesses and two bounded candidate families. | Source semantics review only. Even PASS does not authorize a screen. |

## Compute sequence after capture-v3 PASS

1. Mini: consume the one capture admission; run 24 shards in three waves of
   eight workers over 750,000 deals, with JSON progress every 250 deals.
2. Mini: freeze the exact 2,048-state set and replay-authenticate all 750,000
   dispositions with eight workers. Stop on any underfilled quota or mismatch.
3. Review the immutable state set. Then Mini runs the 32-state/eight-worker
   outcome-discarding label capacity pilot, capped at four wall-hours.
4. Review the capacity result and label packet. If passed, Mini executes 16
   label shards with eight workers; the contract caps the projected full run
   at 192 fleet-hours / 24 wall-hours.
5. Air is already staged cleanly at training source `2767a05` with Python
   3.14.6, NumPy 2.5.1, Torch 2.13.0 and a passing 44-test no-data slice. Once
   labels pass, run 48 cells (play/bury × eight seeds × 25/50/100% curves), at
   most eight concurrently.
6. Select one capability only from DESIGN/CALIB, open sealed REPORT exactly
   once, compose the passer inside report-LCB with incumbent fallback and a
   same-work null, then run a fresh whole-game screen against the live champion.

## Safety boundary

- Do not launch from the v1 marker or substitute a v1/v2 namespace.
- Do not retry H0, inspect its 555 partial utilities, or derive a human rule.
- Do not launch S4 confirmation, S3a, S6 or an unreviewed Stage-C stage merely
  to occupy an idle machine.
- Do not open REPORT during capture, capacity, labels, training review or
  DESIGN/CALIB selection.
- The T4 goal stops before confirmation, promotion or deployment.
