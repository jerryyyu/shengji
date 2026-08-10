# Active Claude/Codex handoff

Last compacted: 2026-08-10 16:16 EDT. This is the executable mailbox.
Terminal markers live in `HANDOFF_REVIEW.md`, policy synthesis in
`AI_POLICIES.md`, job artifacts in `JOBS.md`, and queue order in `BACKLOG.md`.

## Immediate gate

**Externally review the terminal capacity-v3 result before freezing labels.**
Mini completed the one reviewed 32-state probe: result `e2eea8c4…d32d4`, exact
147,384 candidate-worlds, zero refusals/outcomes retained and projected full
labels at 1.640 fleet-hours / 0.235 eight-worker wall-hours. The initial
operator command omitted compiled/strict-void variables but refused before
admission and created nothing; the corrected invocation consumed the sole slot
once. Claude's exact result-review request is at the bottom of
`HANDOFF_REVIEW.md`. No label packet may freeze before PASS.

In parallel, Air's reviewed S4 preflight passed 8/8 score-free clusters and
projected the fixed replication at 61.853 fleet-hours / 7.732 maximum
shard-hours. Packet `b239b849…ab76b` fully recomputes and contains no admission
or outcomes. Its separate packet review is now open; the outcome run remains
closed until that exact PASS.

## Current truth

| area | current evidence | next legal action |
|---|---|---|
| Production | Release 17 runs compiled, formally confirmed `mc-s0-report-lcb`. | Monitor only; no production change is part of T4. |
| S4 point banking | **TERMINAL SCREEN PASS preserved.** Source PASS at `fb6ec1a`; score-free preflight `a89a4498…69` passed all criteria. Frozen packet `b239b849…ab76b` binds 2,048 treatment/champion clusters plus 256 null sentinels; zero outcome work. | External packet review. Only its exact PASS may admit/launch the fixed Air run; never retry, extend or auto-deploy. |
| H0 human/V11 diagnostic | **TERMINAL NO-USE:** 555/557 complete, two score-free refusals, status `REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY`. | No retry and no partial-row mining. Stage C admits no human-derived proposer. V11 remains only its separately frozen bounded proposal source. |
| Stage-C capture | **V7 TERMINAL CAPTURE PASS.** Claude passed `03c87d6` / `b53af06c…8a43`; one fresh receipt produced 24/24 shards. All 750,000 dispositions and 2,048 selected states replayed exactly. V3/v6 remain terminal no-use. | Preserve the consumed receipt, shards and verifier. Never rerun, pool or extend. |
| Stage-C state set | **EXTERNAL PASS.** Exact `1024/512/512`, play/bury `1920/128`; state set `c7a769c4…e8e1c`, verification `143fb2db…4adb`. Claude independently recomputed population/digests and authenticated all disposition replays. | Preserve. Never rerun, extend, pool or mutate. |
| Stage-C labels | V1/v2 remain terminal no-use. **Capacity-v3 TERMINAL PASS / RESULT REVIEW OPEN:** source `167feab`, result external/internal `e2eea8c4…d32d4` / `00bd3456…7e9f`, 32/32, zero refusals, exact 147,384 worlds and no retained outcomes. | Claude result PASS; then freeze and externally review one fresh label-v2 packet. Only that packet PASS may start 16 Mini shards. |
| Stage-C model / REPORT | Capacity-v3 `167feab` descends from integrated iid-v2 and retains its cross-Git/schema repairs. The isolated Mini environment now binds Python 3.14.6, NumPy 2.5.1 and Torch 2.13.0; 49/49 model/training/REPORT tests pass there. No checkpoint or REPORT look exists. | Training remains closed until complete reviewed iid-v2 labels and a new training-packet review. Mini runs the 48 cells; REPORT stays sealed until DESIGN/CALIB selects one capability. |
| Stage-C composition | The reviewed composition behavior remains unchanged beneath iid-v2: literal live candidate zero, at most one model proposal, report-LCB override decider and same-work random null. No packet/run. | Rebind and execute only after one REPORT passer, then capacity and one same-work whole-game screen. |
| S6 throw sourcing | Draft PR #19 head `cfa5a53` now implements the new contract without touching production: whenever any effective-suit holding permits a multi-component lead, an append-only widened ballot contains at least one shuai in early/mid/late. The old source failed a natural late trump-only seed-1 state; v2 adds a bounded trump fallback. Literal live ballot/candidate zero remain first; 11 focused and 58 broader tests pass. | Defer its external source-semantics review while the capacity packet/result is the immediate gate. Review must preserve public/lead-only inputs, ≤8 additions, no-op/follow negatives and equal-work later evaluation. Source PASS still cannot authorize a screen. |

## Downstream implementation ready without execution authority

V1 source `3f6f048`, packet, receipt, eight consumed slots and shard artifacts
are immutable terminal evidence. Fresh v2 source `8a202e9` is a descendant of
integrated `42e1726`; it keeps the cross-commit authentication and composition
behavior while replacing only the invalid world-identity uniqueness rule and
bumping all affected schemas. An old parent Git remains acceptable downstream
only with its exact packet and byte-identical label sources. Air passes the
184-test compiled Stage-C/S3c slice at exact v2 head. Composition still
preserves literal live candidate zero, proposes at most one model-ranked
alternative, leaves report-LCB as the override decider and includes a
trigger/work-matched random null.

None of those source results authorize labels or training. Capacity-v3 result
review is the current gate; composition can execute only if the one-shot
REPORT evaluation eventually selects a capability.

## Compute sequence after state-set PASS

1. **Complete:** capacity-v3 packet PASS and one Mini probe; preserve consumed
   slot `6dc1f9bd…d0fb` and result `e2eea8c4…d32d4`.
2. Externally review that terminal result.
3. On PASS, freeze and externally review a fresh iid-v2 label-controller packet. Only
   then execute all 16 shards with eight workers and aggregate on 2,048/2,048
   complete rows with zero refusals.
4. Review the aggregate and freeze/review the v2 training packet. Mini then
   runs 48 cells (play/bury × eight seeds × 25/50/100%), at most eight
   concurrently. Air remains isolated to the separately gated S4 lane.
5. Select one capability only from DESIGN/CALIB, open sealed REPORT exactly
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
- Label v1 is terminal no-use. Preserve its global receipt, eight shard locks
  and eight shard artifacts; never run untouched slots, aggregate, pool or
  inspect partial utilities.
- Capacity-v2 is terminal no-use. Preserve result `64fdda5f…4cf2` and consumed
  slot `b6c1219a…5e72`; never retry it or treat Codex's own marker as external.
- Capacity-v3 is consumed and terminal PASS. Preserve result `e2eea8c4…d32d4`
  and slot `6dc1f9bd…d0fb`; never rerun it. Result PASS still precedes labels.
- Preserve S4 preflight `a89a4498…69` and packet `b239b849…ab76b`; do not
  admit or launch the outcome run before exact packet review.
- Do not retry H0, inspect its 555 partial utilities, or derive a human rule.
- Do not launch S4 confirmation, S3a, S6 or an unreviewed Stage-C stage merely
  to occupy an idle machine.
- Do not open REPORT during capture, capacity, labels, training review or
  DESIGN/CALIB selection.
- The T4 goal stops before confirmation, promotion or deployment.
