# Active Claude/Codex handoff

Last compacted: 2026-08-10 12:26 EDT. This is the executable mailbox.
Terminal markers live in `HANDOFF_REVIEW.md`, policy synthesis in
`AI_POLICIES.md`, job artifacts in `JOBS.md`, and queue order in `BACKLOG.md`.

## Immediate gate

**Review the terminal capacity result and unequal-rate regression fixture.**
Claude passed the packet, then Mini consumed its sole admission: 32/32 samples,
zero refusals, exact 246,072 candidate-worlds, no returned/retained outcome,
result external/internal `111092b7…cee0` / `90b4a1df…a792`. The conservative
full-label projection is only `1.545` fleet-hours and `0.219` eight-worker
wall-hours. Exact verifier, review checklist and requested
`TEACHER_STAGE_C_LABEL_CAPACITY_RESULT_V1_REVIEW` marker are at the top of
`HANDOFF_REVIEW.md`.

Claude's packet-review fixture finding is also closed in pushed test-only
commit `202a1d2`: 41/41 pass and `max(rates)`→`min(rates)` makes the named test
red. A result PASS authorizes freezing the label-controller packet only. That
packet still needs external PASS before any of its 16 shards may execute;
training and REPORT remain closed.

## Current truth

| area | current evidence | next legal action |
|---|---|---|
| Production | Release 17 runs compiled, formally confirmed `mc-s0-report-lcb`. | Monitor only; no production change is part of T4. |
| S4 point banking | **TERMINAL SCREEN PASS:** treatment−champion `+0.086914 +/- 0.056166`, one-sided LCB `+0.030748`; treatment−null is identical and null−champion is exactly zero. | Preserve the result. Confirmation-packet review is eligible, but the current goal explicitly stops before confirmation launch. Frozen projection is `365.592` fleet-hours / `45.699` max-shard hours. |
| H0 human/V11 diagnostic | **TERMINAL NO-USE:** 555/557 complete, two score-free refusals, status `REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY`. | No retry and no partial-row mining. Stage C admits no human-derived proposer. V11 remains only its separately frozen bounded proposal source. |
| Stage-C capture | **V7 TERMINAL CAPTURE PASS.** Claude passed `03c87d6` / `b53af06c…8a43`; one fresh receipt produced 24/24 shards. All 750,000 dispositions and 2,048 selected states replayed exactly. V3/v6 remain terminal no-use. | Preserve the consumed receipt, shards and verifier. Never rerun, pool or extend. |
| Stage-C state set | **EXTERNAL PASS.** Exact `1024/512/512`, play/bury `1920/128`; state set `c7a769c4…e8e1c`, verification `143fb2db…4adb`. Claude independently recomputed population/digests and authenticated all disposition replays. | Preserve. Never rerun, extend, pool or mutate. |
| Stage-C labels | Capacity packet `e8967d6f…d2a58` externally passed and its sole Mini run terminally passed: 32/32, zero refusals, result `111092b7…cee0`, no retained outcome, projected `1.545` fleet-hours / `0.219` eight-worker wall-hours. Required unequal-rate test is closed at `202a1d2` (41/41 plus red mutation). | External capacity-result PASS; then freeze/review the label-controller packet at the exact reviewed identity. Only its later PASS may authorize 16 shards. |
| Stage-C model / REPORT | V7-bound training `57f8e72` and REPORT `4c8d23b` are source-green (161 REPORT/design tests); no checkpoint or REPORT look exists. | Training remains closed until complete reviewed labels. REPORT remains sealed until DESIGN/CALIB selects one capability. |
| Stage-C composition | V7-bound head `68e351b` passes 260 Stage-C/S3c tests and a 300-play/50-bury parity soak. No packet/run. | Execute only after one REPORT passer, then capacity and one same-work whole-game screen. |
| S6 throw sourcing | Draft PR #19 head `cfa5a53` now implements the new contract without touching production: whenever any effective-suit holding permits a multi-component lead, an append-only widened ballot contains at least one shuai in early/mid/late. The old source failed a natural late trump-only seed-1 state; v2 adds a bounded trump fallback. Literal live ballot/candidate zero remain first; 11 focused and 58 broader tests pass. | Defer its external source-semantics review while the capacity packet/result is the immediate gate. Review must preserve public/lead-only inputs, ≤8 additions, no-op/follow negatives and equal-work later evaluation. Source PASS still cannot authorize a screen. |

## Downstream implementation ready without execution authority

The v7-bound label (`3f6f048`), training (`57f8e72`), REPORT (`4c8d23b`) and
composition (`68e351b`) branches are pushed and source-green. Composition
preserves literal live candidate zero, proposes at most one model-ranked
alternative, leaves report-LCB as the override decider and includes a
trigger/work-matched random null. Its 260-test Stage-C/S3c slice and fresh
300-play/50-bury parity soak are clean.

None of those source results authorize execution. Capacity-packet review is the
current gate; composition can be externally reviewed later without opening
REPORT and can execute only if the one-shot REPORT evaluation selects a
capability.

## Compute sequence after state-set PASS

1. The capacity packet externally passed and its sole outcome-discarding Mini
   run terminally passed. Obtain exact external review of result
   `111092b7…cee0` plus the unequal-rate fixture at `202a1d2`.
2. Only a passed capacity result authorizes freezing the label-controller
   packet. Review it; if passed, Mini executes 16 label shards with eight
   workers. The full-run cap is 192 fleet-hours / 24 wall-hours.
3. Air will be restaged at the v7-bound training source with Python 3.14.6.
   Once labels pass, run 48 cells (play/bury × eight seeds × 25/50/100%
   curves), at most eight concurrently.
4. Select one capability only from DESIGN/CALIB, open sealed REPORT exactly
   once, compose the passer inside report-LCB with incumbent fallback and a
   same-work null, then run a fresh whole-game screen against the live champion.

## Safety boundary

- V3 is terminally held. Do not reuse its receipt or six partial shards, retry
  its deterministic failures, delete/reissue its receipt, or start later waves.
- V4 passed its phase review and v5 was held; both were superseded before
  admission. V6 is terminal no-use after one admitted execution: preserve its
  receipt and 24 shards, and never retry, extend, pool or derive a state set.
- Capture-v7 is consumed and terminally verified. Never issue another receipt,
  retry a shard, extend the population or mutate the frozen state set.
- Do not retry H0, inspect its 555 partial utilities, or derive a human rule.
- Do not launch S4 confirmation, S3a, S6 or an unreviewed Stage-C stage merely
  to occupy an idle machine.
- Do not open REPORT during capture, capacity, labels, training review or
  DESIGN/CALIB selection.
- The T4 goal stops before confirmation, promotion or deployment.
