# Active Claude/Codex handoff

Last compacted: 2026-08-10 18:00 EDT. This is the executable mailbox.
Terminal markers live in `HANDOFF_REVIEW.md`, policy synthesis in
`AI_POLICIES.md`, job artifacts in `JOBS.md`, and queue order in `BACKLOG.md`.

## Immediate gate

**Externally review the terminal Stage-C label-v2 result and the V11-free
consumption boundary before freezing a training packet.** The reviewed packet
ran once on Mini and completed all 16 shards: 2,048/2,048 rows, zero refusals,
exact work `4,984,960/4,984,960` candidate-worlds and `961,152/961,152`
sampler attempts/accepted. Aggregate external/internal SHA is
`d0b4397c…cdb9` / `882baad7…aac0`; a full terminal replay reconstructed all
rows and the aggregate byte-for-byte.

The MC Teacher labels passed fidelity comfortably: ordinary regret UCB
`0.0000295`, hard-tail regret UCB `0.02069`, both below `0.10`. The separate
V11 proposal comparison was only `+1/48` versus matched random, LCB `-0.05799`,
so V11 is **not admitted**. Exact pushed source `7dee880` / draft PR #20 fixes
the unsafe legacy PASS helper, authorizes only a separately reviewed
fidelity-only freeze, keeps V11-origin actions as source-agnostic examples, and
removes V11 from later inference. No dataset, training packet, checkpoint or
REPORT access exists. The exact review request is now the last entry in
`HANDOFF_REVIEW.md`.

In parallel, Claude passed S4 packet `b239b849…ab76b` at `8aa8a25`. Air
consumed reviewed admission `5fc07959…cb88` and receipt `fc6d54e7…1077`; all
eight fixed shards are live under the 30-second supervisor. This is the one
2,048-cluster treatment/champion replication plus 256 balanced raw-null
sentinels. At 18:00 EDT the shard counters were `27/26/26/25/27/27/27/25`
(`210/2,048`, 10.3%). Preserve it without retry, extension, tuning or interim
inference.

## Current truth

| area | current evidence | next legal action |
|---|---|---|
| Production | Release 17 runs compiled, formally confirmed `mc-s0-report-lcb`. | Monitor only; no production change is part of T4. |
| S4 point banking | **TERMINAL SCREEN PASS preserved; independent replication LIVE.** Packet PASS `8aa8a25`; admission `5fc07959…cb88`, receipt `fc6d54e7…1077`; eight Air shards healthy at `210/2,048` clusters from exact `fb6ec1a`. | Supervise only. On terminal publication, run the pinned verifier and request independent result review. Never retry, extend, tune, promote or deploy. |
| H0 human/V11 diagnostic | **TERMINAL NO-USE:** 555/557 complete, two score-free refusals, status `REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY`. The independent label result also did not prove V11 recall against matched random. | No retry or partial-row mining. T4 admits neither a human-derived proposer nor V11. Human/V11 actions may remain source-agnostic diagnostic examples only. |
| Stage-C capture | **V7 TERMINAL CAPTURE PASS.** Claude passed `03c87d6` / `b53af06c…8a43`; one fresh receipt produced 24/24 shards. All 750,000 dispositions and 2,048 selected states replayed exactly. V3/v6 remain terminal no-use. | Preserve the consumed receipt, shards and verifier. Never rerun, pool or extend. |
| Stage-C state set | **EXTERNAL PASS.** Exact `1024/512/512`, play/bury `1920/128`; state set `c7a769c4…e8e1c`, verification `143fb2db…4adb`. Claude independently recomputed population/digests and authenticated all disposition replays. | Preserve. Never rerun, extend, pool or mutate. |
| Stage-C labels | V1 and capacity-v2 remain terminal no-use. **LABEL-V2 TERMINAL COMPLETE / FIDELITY PASS:** all 2,048 rows, zero refusals, exact 4,984,960 candidate-worlds; aggregate `d0b4397c…cdb9`; ordinary/hard-tail UCBs `0.0000295/0.02069`. V11 recall did not pass (`+1/48`, LCB `-0.05799`). | Independent terminal-result plus V11-free consumption review. Preserve all 17 slots and 16 shards; never rerun or extend. |
| Stage-C model / REPORT | Pushed `7dee880` / draft PR #20 owns all 48 training cells and separates good MC labels from the unproven V11 source. Candidate provenance is not encoded; V11 inference authority is false. Exact Stage-C/Teacher battery passes 233/233 on Python 3.14.6 compiled strict-void. No dataset, packet, checkpoint or REPORT look exists. | Claude reviews the exact aggregate and source. Its new marker may authorize one dataset/training-packet freeze only; a later packet review admits Mini's 48 cells. REPORT stays sealed until DESIGN/CALIB selects one capability. |
| Stage-C composition | V2 source at `7dee880` removes the V11 artifact entirely. For play, the learned MC-Teacher ensemble proposes its top novel legal action; literal live candidate zero, named structured/random candidates, fresh report-LCB override protection and the matched-random control remain. No packet/run. | Review now, but execute only after one untouched-REPORT passer; then capacity and one same-work whole-game screen decide strength. |
| S6 throw sourcing | Draft PR #19 head `cfa5a53` now implements the new contract without touching production: whenever any effective-suit holding permits a multi-component lead, an append-only widened ballot contains at least one shuai in early/mid/late. The old source failed a natural late trump-only seed-1 state; v2 adds a bounded trump fallback. Literal live ballot/candidate zero remain first; 11 focused and 58 broader tests pass. | Defer its external source-semantics review while the terminal label/source review is the immediate gate. Review must preserve public/lead-only inputs, ≤8 additions, no-op/follow negatives and equal-work later evaluation. Source PASS still cannot authorize a screen. |

## Downstream implementation ready without execution authority

V1 source `3f6f048`, packet, receipt, eight consumed slots and shard artifacts
are immutable terminal evidence. Label-v2 exact source `167feab` preserved the
iid-with-replacement and cross-commit repairs and produced the complete
immutable aggregate. Downstream source `7dee880` authenticates that exact old
parent only through its packet/hash and byte-identical label sources. It adds a
one-shot 48-cell supervisor and a fail-closed fidelity-consumption gate.

Composition is intentionally newer than the frozen candidate source: it keeps
literal live candidate zero, fresh report-LCB protection and a same-work random
null, but replaces the unproven V11 proposer with the learned MC-Teacher
ensemble's own top novel legal action. The final whole-game screen, not the
offline source label, is the authority for that deliberate distribution shift.

None of those source results authorize training. The terminal aggregate plus
V11-free consumption review is the current gate; composition can execute only
if the one-shot REPORT evaluation eventually selects a capability.

## Compute sequence after state-set PASS

1. **Complete:** capacity-v3 result and external PASS; preserve slot
   `6dc1f9bd…d0fb` and result `e2eea8c4…d32d4`.
2. **Complete:** label-v2 packet external PASS, one 16-shard Mini execution,
   2,048/2,048 rows and byte-exact terminal recomputation. Preserve aggregate
   `d0b4397c…cdb9`, all slots and shards without retry or extension.
3. **Review open:** independently certify Teacher fidelity, V11 non-admission
   and exact source `7dee880`. Only the new V3 consumption marker may authorize
   one V11-free dataset/training-packet freeze.
4. Review that training packet. Mini then
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
  and slot `6dc1f9bd…d0fb`; never rerun it.
- Label-v2 is consumed and terminal complete. Preserve packet
  `0d119c84…dc32`, aggregate `d0b4397c…cdb9`, all 17 admission slots and all 16
  shards; never rerun, retry, extend, pool or replace them.
- The old combined aggregate decision did not authorize training. Do not paste
  the legacy V2 PASS helper output. Only the independently reviewed V3
  fidelity-consumption marker may authorize one V11-free packet freeze.
- S4's reviewed Air receipt is consumed and all eight shards are live. Do not
  stop/restart a healthy shard, retry, extend, inspect an interim utility,
  promote or deploy; terminal result review is still required.
- Do not retry H0, inspect its 555 partial utilities, or derive a human rule.
- Do not launch S4 confirmation, S3a, S6 or an unreviewed Stage-C stage merely
  to occupy an idle machine.
- Do not open REPORT during capture, capacity, labels, training review or
  DESIGN/CALIB selection.
- The T4 goal stops before confirmation, promotion or deployment.
