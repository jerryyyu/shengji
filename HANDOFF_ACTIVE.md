# Active Claude/Codex handoff

Last compacted: 2026-08-10 10:11 EDT. This is the executable mailbox.
Terminal markers live in `HANDOFF_REVIEW.md`, policy synthesis in
`AI_POLICIES.md`, job artifacts in `JOBS.md`, and queue order in `BACKLOG.md`.

## Immediate gate

**Review the immutable capture-v7 state set before any label work.** Claude's
exact source PASS is recorded once. Mini then consumed one admission, completed
all 24 fresh shards, froze exactly 2,048 states (`1024/512/512`, play/bury
`1920/128`) and terminally reproduced all 750,000 scan dispositions plus every
selected state. State-set external SHA is `c7a769c4…e8e1c`; terminal-verifier
external SHA is `143fb2db…4adb`; 24/24 shard replays were byte-identical and no
partial remains.

The precise independent-review checklist and expected
`TEACHER_STAGE_C_STATE_SET_V7_REVIEW` marker are now at the top of
`HANDOFF_REVIEW.md`. Labels, capacity outcomes, training and REPORT remain
closed. A PASS authorizes only freezing the v7-bound label controller; the
outcome-free capacity gate and later controller review still stand between
this state set and any label execution.

## Current truth

| area | current evidence | next legal action |
|---|---|---|
| Production | Release 17 runs compiled, formally confirmed `mc-s0-report-lcb`. | Monitor only; no production change is part of T4. |
| S4 point banking | **TERMINAL SCREEN PASS:** treatment−champion `+0.086914 +/- 0.056166`, one-sided LCB `+0.030748`; treatment−null is identical and null−champion is exactly zero. | Preserve the result. Confirmation-packet review is eligible, but the current goal explicitly stops before confirmation launch. Frozen projection is `365.592` fleet-hours / `45.699` max-shard hours. |
| H0 human/V11 diagnostic | **TERMINAL NO-USE:** 555/557 complete, two score-free refusals, status `REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY`. | No retry and no partial-row mining. Stage C admits no human-derived proposer. V11 remains only its separately frozen bounded proposal source. |
| Stage-C capture | **V7 TERMINAL CAPTURE PASS.** Claude passed `03c87d6` / `b53af06c…8a43`; one fresh receipt produced 24/24 shards. All 750,000 dispositions and 2,048 selected states replayed exactly. V3/v6 remain terminal no-use. | Preserve the consumed receipt, shards and verifier. Never rerun, pool or extend. |
| Stage-C state set | **CREATED / EXTERNAL REVIEW OPEN.** Exact `1024/512/512`, play/bury `1920/128`; state set `c7a769c4…e8e1c`, verification `143fb2db…4adb`. No labels exist. | Independent PASS/HOLD on the exact marker at the top of `HANDOFF_REVIEW.md`. |
| Stage-C labels | V7-bound source `3f6f048` passes 148 relevant tests and hard-refuses an unreviewed or stale state set. No packet/outcome. | After state-set PASS, freeze/run the reviewed outcome-free 32-state capacity pilot; then capacity-result and label-controller reviews before 16 shards. |
| Stage-C model / REPORT | V7-bound training `57f8e72` and REPORT `4c8d23b` are source-green (161 REPORT/design tests); no checkpoint or REPORT look exists. | Training remains closed until complete reviewed labels. REPORT remains sealed until DESIGN/CALIB selects one capability. |
| Stage-C composition | V7-bound head `68e351b` passes 260 Stage-C/S3c tests and a 300-play/50-bury parity soak. No packet/run. | Execute only after one REPORT passer, then capacity and one same-work whole-game screen. |
| S6 throw sourcing | Head `bf7eace` freezes three KESP omissions and two public-only lead sources, capped at eight additions; 25/25 focused tests pass. **New required contract:** whenever a legal shuai-pai lead exists, the ballot must include at least one legal shuai candidate in early, mid and late game—not merely the three KESP fixtures. | After the current Stage-C state-set gate, broaden witnesses/coverage while preserving lead-only public sourcing, deterministic bounded cap, literal candidate zero and matched same-work control. Source PASS still cannot authorize a screen. |

## Downstream implementation ready without execution authority

The v7-bound label (`3f6f048`), training (`57f8e72`), REPORT (`4c8d23b`) and
composition (`68e351b`) branches are pushed and source-green. Composition
preserves literal live candidate zero, proposes at most one model-ranked
alternative, leaves report-LCB as the override decider and includes a
trigger/work-matched random null. Its 260-test Stage-C/S3c slice and fresh
300-play/50-bury parity soak are clean.

None of those source results authorize execution. The state-set review is the
current gate; composition can be externally reviewed later without opening
REPORT and can execute only if the one-shot REPORT evaluation selects a
capability.

## Compute sequence after state-set PASS

1. Mini runs the 32-state/eight-worker outcome-discarding label capacity pilot,
   capped at four wall-hours. It publishes work/refusal geometry, no outcomes.
2. Review the capacity result and label packet. If passed, Mini executes 16
   label shards with eight workers; the contract caps the projected full run
   at 192 fleet-hours / 24 wall-hours.
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
