# Active Claude/Codex handoff

Last compacted: 2026-08-10 09:09 EDT. This is the executable mailbox.
Terminal markers live in `HANDOFF_REVIEW.md`, policy synthesis in
`AI_POLICIES.md`, job artifacts in `JOBS.md`, and queue order in `BACKLOG.md`.

## Immediate gate

**Review capture v7 before any new capture compute.** V6's one-shot run
completed all 24 shards but terminally refused dataset freeze: every exact-late
follow quota was empty (`0/40` twice in DESIGN; `0/20` twice in CALIB and
REPORT). All 58,623 assigned follow deals were unreachable because v6 required
all hands to contain one card even after earlier players had played theirs.
No state set or terminal verification exists. Receipt and shards are preserved
as terminal no-use; no retry, extension, pooling, label or training is legal.

V7 source `03c87d6`, packet commit `101021d`, external packet SHA
`b53af06c…8a43` defines the intended boundary: each seat had one card at trick
start, reconstructed from current hands plus prior single-card plays. Named
real shortage witnesses pass, the old predicate is red, 60/60 focused tests
pass, all six actual assigned quota streams fill in a bounded replay, and the
350-state hand-order soak is clean. V6/v7 schedule, parents, inputs,
exclusions, authority and ceilings are unchanged. Exact PASS/HOLD instructions
and marker are at the top of `HANDOFF_REVIEW.md`; zero v7 states/worlds and no
v7 admission exist.

## Current truth

| area | current evidence | next legal action |
|---|---|---|
| Production | Release 17 runs compiled, formally confirmed `mc-s0-report-lcb`. | Monitor only; no production change is part of T4. |
| S4 point banking | **TERMINAL SCREEN PASS:** treatment−champion `+0.086914 +/- 0.056166`, one-sided LCB `+0.030748`; treatment−null is identical and null−champion is exactly zero. | Preserve the result. Confirmation-packet review is eligible, but the current goal explicitly stops before confirmation launch. Frozen projection is `365.592` fleet-hours / `45.699` max-shard hours. |
| H0 human/V11 diagnostic | **TERMINAL NO-USE:** 555/557 complete, two score-free refusals, status `REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY`. | No retry and no partial-row mining. Stage C admits no human-derived proposer. V11 remains only its separately frozen bounded proposal source. |
| Stage-C capture | **V6 TERMINAL HOLD / V7 REVIEW OPEN.** V6 has 24 complete no-use shards (ordered digest `89af231f…8d6`) but no state set: six exact-late follow cells were structurally empty. V7 `03c87d6` / `b53af06c…8a43` repairs only that final-trick semantic and passes 60/60 plus bounded quota replay. | External PASS/HOLD on v7. On PASS, consume one fresh v7 admission and rerun all 24 shards from scratch. |
| Stage-C state set | Not created. | After capture, freeze exactly 2,048 states (`1024/512/512`, play/bury `1920/128`) and replay all 750,000 dispositions with eight workers; then external state-set review. |
| Stage-C labels | V6-bound source `7d3e6ad` passed 110/110 but cannot consume v7. No packet/outcome. | After v7 source PASS, rebind the capture identity without changing label geometry; then wait for reviewed state set and capacity. |
| Stage-C model / REPORT | V6-bound training `8ca347f` and REPORT `e788fde` remain source-green but cannot consume v7. No checkpoint or REPORT result exists. | Rebind after v7 PASS. Training remains closed until reviewed labels. |
| Stage-C composition | PR #18 head `268ebeb` is source-green over v6 REPORT, with 257/257 plus the 350-state parity soak. No packet/run. | Narrative source review may proceed, but exact execution lineage must be rebound to v7 after capture review and remains conditional on one REPORT passer. |
| S6 throw sourcing | PR #19 at `bf7eace` freezes three exact KESP omissions (partial near-boss, AKQ/boss bundle, 876/whole-suit evacuation) and two public-information families, capped at eight additions. Codex's compiled source audit passes the 25-test throw/current-ballot slice: the human submissions stood as full throws, hidden hands do not affect sourcing, and follow positions emit nothing. | Source semantics review only. A later packet must union these additions with the literal live ballot while preserving candidate zero, let rollouts price failed-throw/ruff risk, and include a same-work control. Even source PASS does not authorize a screen. |

## Secondary source review repaired; now eligible in parallel

PR #18 source rereview is ready at exact head
`268ebebeeb452d014a65f6626644a2de0aed4644` on v6 REPORT base
`e788fde`. Its merge-base diff is composition-only: six source files and six
test files. Ordered material recipe is exactly
`shasum -a 256 <the 12 paths listed by git diff --name-only, in lexical order> | shasum -a 256`;
result `47519c087aa53761d999b11f1fbbf5bb1e64f1c7390d385a88de2285e7845993`.
The optional incumbent path now canonicalizes and unconditionally restores the
hand exactly like capture v6; caller-provided live candidate zero remains
literal. Named tie/exception regressions pass, the complete Stage-C slice is
220/220, Stage-C plus S3c/live is 257/257, and capture/source parity passed on
300 eligible play plus 50 eligible bury states.

This source-only review may proceed while capture-v7 is reviewed. Review should
falsify:

1. candidate generation is public-only, invariant to incidental hand order,
   preserves literal live candidate zero and restores the hand on exceptions;
2. treatment proposes at most one model-ranked alternative but report-LCB
   still makes the override decision; random null has the same trigger/work,
   and champion remains unmodified;
3. no training label, REPORT row, opponent hand or sampled world enters
   inference sourcing;
4. capacity, per-shard work, supervisor failure/timeout cleanup, durable slots,
   terminal hashes and final aggregation cannot publish partial evidence; and
5. current missing REPORT authority makes packet freeze refuse. A source PASS
   authorizes only later packet construction from the single REPORT passer—no
   capacity, screen, confirmation, strength claim, promotion or deployment.

## Compute sequence after capture-v7 PASS

1. Mini consumes one fresh v7 admission and runs all 24 shards in three waves
   of eight workers over the unchanged 750,000 deals, with JSON progress every
   250 deals and per-candidate uncertainty progress.
2. Mini: freeze the exact 2,048-state set and replay-authenticate all 750,000
   dispositions with eight workers. Stop on any underfilled quota or mismatch.
3. Review the immutable state set. Then Mini runs the 32-state/eight-worker
   outcome-discarding label capacity pilot, capped at four wall-hours.
4. Review the capacity result and label packet. If passed, Mini executes 16
   label shards with eight workers; the contract caps the projected full run
   at 192 fleet-hours / 24 wall-hours.
5. Air will be restaged at the v7-bound training source with Python 3.14.6.
   Once labels pass, run 48 cells (play/bury × eight seeds × 25/50/100%
   curves), at most eight concurrently.
6. Select one capability only from DESIGN/CALIB, open sealed REPORT exactly
   once, compose the passer inside report-LCB with incumbent fallback and a
   same-work null, then run a fresh whole-game screen against the live champion.

## Safety boundary

- V3 is terminally held. Do not reuse its receipt or six partial shards, retry
  its deterministic failures, delete/reissue its receipt, or start later waves.
- V4 passed its phase review and v5 was held; both were superseded before
  admission. V6 is terminal no-use after one admitted execution: preserve its
  receipt and 24 shards, and never retry, extend, pool or derive a state set.
- Only an exact v7 PASS and fresh v7 namespace may issue the next capture
  receipt; every v6/v5/v4/v3 marker and artifact grants it no authority.
- Do not retry H0, inspect its 555 partial utilities, or derive a human rule.
- Do not launch S4 confirmation, S3a, S6 or an unreviewed Stage-C stage merely
  to occupy an idle machine.
- Do not open REPORT during capture, capacity, labels, training review or
  DESIGN/CALIB selection.
- The T4 goal stops before confirmation, promotion or deployment.
