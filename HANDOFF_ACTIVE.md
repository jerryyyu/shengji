# Active Claude/Codex handoff

Last compacted: 2026-08-10 06:46 EDT. This is the executable mailbox.
Terminal markers live in `HANDOFF_REVIEW.md`, policy synthesis in
`AI_POLICIES.md`, job artifacts in `JOBS.md`, and queue order in `BACKLOG.md`.

## Immediate execution

**Capture v3 is admitted and running on Mini.** Claude's exact PASS is at
`78329b1`. Codex validated it against source `0b697b6`, packet
`d58a9308…c91`, the compiled engine and all frozen parents before consuming the
single admission. Receipt external SHA: `617ef115…512a9`; internal receipt SHA:
`e1096d16…a35a`.

Shards 0–7 are the first of three predeclared eight-worker waves. All completed
their 31,250 scheduled-deal scan and are running the N=30 champion-uncertainty
diagnostics with visible per-candidate progress. Do not start more than eight
capture shards concurrently. When all eight publish cleanly, run 8–15, then
16–23. The next gate is the frozen/terminally replayed state set, not labels.

## Current truth

| area | current evidence | next legal action |
|---|---|---|
| Production | Release 17 runs compiled, formally confirmed `mc-s0-report-lcb`. | Monitor only; no production change is part of T4. |
| S4 point banking | **TERMINAL SCREEN PASS:** treatment−champion `+0.086914 +/- 0.056166`, one-sided LCB `+0.030748`; treatment−null is identical and null−champion is exactly zero. | Preserve the result. Confirmation-packet review is eligible, but the current goal explicitly stops before confirmation launch. Frozen projection is `365.592` fleet-hours / `45.699` max-shard hours. |
| H0 human/V11 diagnostic | **TERMINAL NO-USE:** 555/557 complete, two score-free refusals, status `REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY`. | No retry and no partial-row mining. Stage C admits no human-derived proposer. V11 remains only its separately frozen bounded proposal source. |
| Stage-C capture | **V3 PASS / ADMITTED / WAVE 1 RUNNING.** Exact one-shot receipt `617ef115…512a9`; shards 0–7 are in uncertainty diagnostics after completing their scheduled scan. | Finish waves 0–7, 8–15 and 16–23 at eight workers; stop on any failed shard or identity/work mismatch. |
| Stage-C state set | Not created. | After capture, freeze exactly 2,048 states (`1024/512/512`, play/bury `1920/128`) and replay all 750,000 dispositions with eight workers; then external state-set review. |
| Stage-C labels | Source ready on PR #13 at `226f5da`; no packet or outcome exists. The capacity runtime now reopens every source, state-set and review input after worker completion before it may publish PASS. | After state-set PASS, freeze/review a 32-state score-free capacity pilot. Only a reviewed capacity PASS may open the 16-shard label packet. |
| Stage-C model | Model/training stack ready through PRs #14–#17; no Stage-C checkpoint exists. | After complete labels, train play/bury surfaces across eight seeds and three DESIGN curves; select only on DESIGN/CALIB and open REPORT once. |
| Stage-C composition | PR #18 HOLD repairs are pushed at `e93417d`; source rereview is open. | Source PASS may authorize only a later score-free capacity preflight. No composition run exists. |
| S6 throw sourcing | PR #19 at `bf7eace` freezes three KESP witnesses and two bounded candidate families. | Source semantics review only. Even PASS does not authorize a screen. |

## Compute sequence after capture-v3 PASS

1. Mini: **RUNNING** — finish the admitted 24-shard capture in three waves of
   eight workers over 750,000 deals, with JSON scan progress every 250 deals
   and per-candidate uncertainty progress.
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

- The v3 admission is consumed. Do not re-admit, delete/reissue the receipt,
  launch from the v1 marker, or substitute a v1/v2 namespace.
- Do not retry H0, inspect its 555 partial utilities, or derive a human rule.
- Do not launch S4 confirmation, S3a, S6 or an unreviewed Stage-C stage merely
  to occupy an idle machine.
- Do not open REPORT during capture, capacity, labels, training review or
  DESIGN/CALIB selection.
- The T4 goal stops before confirmation, promotion or deployment.
