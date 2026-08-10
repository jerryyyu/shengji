# Active Claude/Codex handoff

Last compacted: 2026-08-10 08:42 EDT. This is the executable mailbox.
Terminal markers live in `HANDOFF_REVIEW.md`, policy synthesis in
`AI_POLICIES.md`, job artifacts in `JOBS.md`, and queue order in `BACKLOG.md`.

## Immediate gate

**Capture v6 is admitted once and RUNNING on Mini.** Claude's exact independent
PASS landed at `8d6ce71`. (Attribution correction: the 07:53 v5 HOLD was
Codex's adversarial audit, not Claude's.) V6 source `2bdb094`, packet commit
`055a196` and external packet SHA `40c602ea…20ffd` are unchanged.

The one-shot receipt exists at external SHA `8580b336…f8c66` (internal
`cc24b5b7…0bd10`), authorizes capture only, and permanently consumes the v6
admission slot. Mini session `13568` is running all 24 shards in three waves of
eight, then will freeze exactly 2,048 states and replay-authenticate all
750,000 dispositions. Do not label or train. The next evidence gate is exact
state-set review after terminal replay succeeds; any refusal or mismatch
preserves the artifacts and stops the lane.

## Current truth

| area | current evidence | next legal action |
|---|---|---|
| Production | Release 17 runs compiled, formally confirmed `mc-s0-report-lcb`. | Monitor only; no production change is part of T4. |
| S4 point banking | **TERMINAL SCREEN PASS:** treatment−champion `+0.086914 +/- 0.056166`, one-sided LCB `+0.030748`; treatment−null is identical and null−champion is exactly zero. | Preserve the result. Confirmation-packet review is eligible, but the current goal explicitly stops before confirmation launch. Frozen projection is `365.592` fleet-hours / `45.699` max-shard hours. |
| H0 human/V11 diagnostic | **TERMINAL NO-USE:** 555/557 complete, two score-free refusals, status `REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY`. | No retry and no partial-row mining. Stage C admits no human-derived proposer. V11 remains only its separately frozen bounded proposal source. |
| Stage-C capture | **V6 PASS / RUNNING ON MINI.** Claude's exact marker is committed at `8d6ce71`; source `2bdb094`, packet `40c602ea…20ffd`, receipt external SHA `8580b336…f8c66`; session `13568`. V3 partials remain no-use and v4/v5 were superseded before admission. | Finish all three waves, freeze 2,048 states and replay all 750,000 dispositions. Stop on any refusal or mismatch. |
| Stage-C state set | Not created. | After capture, freeze exactly 2,048 states (`1024/512/512`, play/bury `1920/128`) and replay all 750,000 dispositions with eight workers; then external state-set review. |
| Stage-C labels | V6-bound source `7d3e6ad`; capture-through-label lineage passes 110/110. No packet/outcome. | Wait for state-set PASS, then freeze/review the 32-state capacity packet. |
| Stage-C model / REPORT | V6-bound training `8ca347f` passes 145/145 locally and on staged Air; REPORT `e788fde` passes 158/158. No checkpoint or REPORT result exists. | Training remains closed until reviewed labels; Air is ready without more source work. |
| Stage-C composition | PR #18 head `268ebeb` is rebound to v6 and repaired. Its 12-file diff is composition-only over REPORT base `e788fde`; the full Stage-C/S3c/live slice passes 257/257 and the fresh 350-state parity soak passes. No packet/run. | Capture-v6 passed, so source rereview is now eligible in parallel. Later execution remains conditional on one REPORT passer. |
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

Capture-v6 has now passed, so this source-only review may proceed while Mini
computes. Review should falsify:

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

## Active compute sequence

1. **RUNNING:** Mini consumed the one fresh v6 admission and is running all 24
   shards in three waves of eight workers over the unchanged 750,000 deals,
   with JSON scan progress every 250 deals and per-candidate uncertainty
   progress.
2. Mini: freeze the exact 2,048-state set and replay-authenticate all 750,000
   dispositions with eight workers. Stop on any underfilled quota or mismatch.
3. Review the immutable state set. Then Mini runs the 32-state/eight-worker
   outcome-discarding label capacity pilot, capped at four wall-hours.
4. Review the capacity result and label packet. If passed, Mini executes 16
   label shards with eight workers; the contract caps the projected full run
   at 192 fleet-hours / 24 wall-hours.
5. Air will be restaged at the v6-bound training source with Python 3.14.6.
   Once labels pass, run 48 cells (play/bury × eight seeds × 25/50/100%
   curves), at most eight concurrently.
6. Select one capability only from DESIGN/CALIB, open sealed REPORT exactly
   once, compose the passer inside report-LCB with incumbent fallback and a
   same-work null, then run a fresh whole-game screen against the live champion.

## Safety boundary

- V3 is terminally held. Do not reuse its receipt or six partial shards, retry
  its deterministic failures, delete/reissue its receipt, or start later waves.
- V4 passed its phase review and v5 was held; both are superseded before
  admission. Only an exact v6 PASS and fresh v6 namespace may issue the one
  capture receipt; all older markers and artifacts grant it no authority.
- Do not retry H0, inspect its 555 partial utilities, or derive a human rule.
- Do not launch S4 confirmation, S3a, S6 or an unreviewed Stage-C stage merely
  to occupy an idle machine.
- Do not open REPORT during capture, capacity, labels, training review or
  DESIGN/CALIB selection.
- The T4 goal stops before confirmation, promotion or deployment.
