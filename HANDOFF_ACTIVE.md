# Active Claude/Codex handoff

Last compacted: 2026-08-10 06:54 EDT. This is the executable mailbox.
Terminal markers live in `HANDOFF_REVIEW.md`, policy synthesis in
`AI_POLICIES.md`, job artifacts in `JOBS.md`, and queue order in `BACKLOG.md`.

## Immediate gate

**Review capture v4 before any more capture compute.** V3 is a terminal HOLD:
shards 0–4 and 7 published, but shards 5 and 6 refused before publication with
`Stage-C retained state phase assignment drift`. Do not use the six partial
artifacts and do not start waves 2–3.

The defect is narrow and reproduced by frozen seeds `170002101` (one card
each at trick 11) and `170007422` (trick 10). Throws can create a one-card
state while `phase_for_trick` still says `mid`; the exact-late selector
accepted it although its frozen cell and replay validator require `late`.
Source `5a51a1e` adds the missing phase predicate and both regression
witnesses. The 52-test capture/rebind/live-parent slice passes.

V4 packet commit `04f45b7`, path
`server/runs/logs/teacher-v3-hard-tail-stage-c-capture-controller-v4/controller_packet.json`,
external SHA `0d1a94d4…54eaa`. It keeps the exact v2 population experiment and
schedule SHA; only the phase guard, schemas and fresh namespace change. Exact
PASS/HOLD request is the latest `HANDOFF_REVIEW.md` entry.

## Current truth

| area | current evidence | next legal action |
|---|---|---|
| Production | Release 17 runs compiled, formally confirmed `mc-s0-report-lcb`. | Monitor only; no production change is part of T4. |
| S4 point banking | **TERMINAL SCREEN PASS:** treatment−champion `+0.086914 +/- 0.056166`, one-sided LCB `+0.030748`; treatment−null is identical and null−champion is exactly zero. | Preserve the result. Confirmation-packet review is eligible, but the current goal explicitly stops before confirmation launch. Frozen projection is `365.592` fleet-hours / `45.699` max-shard hours. |
| H0 human/V11 diagnostic | **TERMINAL NO-USE:** 555/557 complete, two score-free refusals, status `REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY`. | No retry and no partial-row mining. Stage C admits no human-derived proposer. V11 remains only its separately frozen bounded proposal source. |
| Stage-C capture | **V3 TERMINAL HOLD; V4 REVIEW REQUIRED.** Six partial v3 shards are no-use. V4 source `5a51a1e`, packet `0d1a94d4…54eaa`, 52/52 tests. | External PASS/HOLD on the exact v4 delta. On PASS stage source commit, admit the fresh v4 namespace once, and restart the complete 24-shard schedule at eight workers. |
| Stage-C state set | Not created. | After capture, freeze exactly 2,048 states (`1024/512/512`, play/bury `1920/128`) and replay all 750,000 dispositions with eight workers; then external state-set review. |
| Stage-C labels | Source ready on PR #13 at `226f5da`; no packet or outcome exists. The capacity runtime now reopens every source, state-set and review input after worker completion before it may publish PASS. | After state-set PASS, freeze/review a 32-state score-free capacity pilot. Only a reviewed capacity PASS may open the 16-shard label packet. |
| Stage-C model | Model/training stack ready through PRs #14–#17; no Stage-C checkpoint exists. | After complete labels, train play/bury surfaces across eight seeds and three DESIGN curves; select only on DESIGN/CALIB and open REPORT once. |
| Stage-C composition | PR #18 HOLD repairs are pushed at `e93417d`; source rereview is open. | Source PASS may authorize only a later score-free capacity preflight. No composition run exists. |
| S6 throw sourcing | PR #19 at `bf7eace` freezes three KESP witnesses and two bounded candidate families. | Source semantics review only. Even PASS does not authorize a screen. |

## Compute sequence after capture-v4 PASS

1. Mini: consume one fresh v4 admission and restart all 24 shards in three
   waves of eight workers over the unchanged 750,000 deals, with JSON scan
   progress every 250 deals and per-candidate uncertainty progress.
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

- V3 is terminally held. Do not reuse its receipt or six partial shards, retry
  its deterministic failures, delete/reissue its receipt, or start later waves.
- V4 requires its own exact external PASS and fresh namespace. The old v1/v3
  markers grant it no authority.
- Do not retry H0, inspect its 555 partial utilities, or derive a human rule.
- Do not launch S4 confirmation, S3a, S6 or an unreviewed Stage-C stage merely
  to occupy an idle machine.
- Do not open REPORT during capture, capacity, labels, training review or
  DESIGN/CALIB selection.
- The T4 goal stops before confirmation, promotion or deployment.
