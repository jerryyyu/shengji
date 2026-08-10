# Active Claude/Codex handoff

Last compacted: 2026-08-10 08:03 EDT. This is the executable mailbox.
Terminal markers live in `HANDOFF_REVIEW.md`, policy synthesis in
`AI_POLICIES.md`, job artifacts in `JOBS.md`, and queue order in `BACKLOG.md`.

## Immediate gate

**Review capture v5 before any capture compute.** Claude passed v4's exact
phase repair at `8263492`, but no v4 admission or state exists. A subsequent
source audit found a separate representation bug: reversing only the acting
hand's incidental list order left the model observation identical but changed
the extra candidate union. Across 300 play states, novel ordering changed in
80 and the seeded random proposal changed once. Named witnesses are lead seed
`170000308`, follow seed `170000133`, and bury seed `170000000`.

V5 source `a71c67e` sorts exhaustive actions by `action_key`, canonicalizes
the structured-follow helper without mutating the surviving state, and samples
random buries from a sorted hand. Same-encoding A/B regressions plus the full
capture/rebind/live-parent slice pass 55/55. Population experiment, schedule,
quotas, parents, exclusions, seeds, diagnostics and ceilings remain fixed.

Packet commit `542f82a`, external SHA `e299ac6c…cf749`; zero v5
states/worlds. The exact narrow PASS/HOLD request and raw marker are at the top
of `HANDOFF_REVIEW.md`. V3 partials remain terminal no-use; v4 is preserved as
a valid phase fix but superseded before admission.

## Current truth

| area | current evidence | next legal action |
|---|---|---|
| Production | Release 17 runs compiled, formally confirmed `mc-s0-report-lcb`. | Monitor only; no production change is part of T4. |
| S4 point banking | **TERMINAL SCREEN PASS:** treatment−champion `+0.086914 +/- 0.056166`, one-sided LCB `+0.030748`; treatment−null is identical and null−champion is exactly zero. | Preserve the result. Confirmation-packet review is eligible, but the current goal explicitly stops before confirmation launch. Frozen projection is `365.592` fleet-hours / `45.699` max-shard hours. |
| H0 human/V11 diagnostic | **TERMINAL NO-USE:** 555/557 complete, two score-free refusals, status `REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY`. | No retry and no partial-row mining. Stage C admits no human-derived proposer. V11 remains only its separately frozen bounded proposal source. |
| Stage-C capture | **V3 TERMINAL HOLD; V4 PASSED BUT WAS SUPERSEDED PRE-ADMISSION; V5 REVIEW REQUIRED.** V5 source `a71c67e`, packet `e299ac6c…cf749`, 55/55 tests, zero states/worlds. | External PASS/HOLD on the exact canonical-source delta. On PASS, admit v5 once and restart all 24 shards on Mini in three waves of eight. |
| Stage-C state set | Not created. | After capture, freeze exactly 2,048 states (`1024/512/512`, play/bury `1920/128`) and replay all 750,000 dispositions with eight workers; then external state-set review. |
| Stage-C labels | V5-bound source `c45cc8a`; no packet/outcome. It refuses v4, reopens inputs after capacity work, and passes 108/108 capture-through-label tests. | After state-set PASS, freeze/review the 32-state capacity pilot. Only a reviewed PASS may open the 16-shard label packet. |
| Stage-C model / REPORT | Training `535fc39` and REPORT `bc566ff` are v5-bound; 143/143 and 156/156 lineage tests pass. Air is cleanly restaged at `535fc39` with 80/80 staged tests. No checkpoint or REPORT result exists. | After reviewed labels, run eight seeds × play/bury × 25/50/100% on Air; select only on DESIGN/CALIB and open REPORT once. |
| Stage-C composition | V5 content `d182572` is merged onto current REPORT base at exact PR #18 head `59ae21e`; the PR now contains only 12 composition source/test files. Candidate schema/screen namespace v2 canonicalizes play/follow/bury inference. The Stage-C/S3c/live slice passes 253/253. No packet or run exists. | Source rereview is queued behind capture-v5. Later packet, capacity and screen remain conditional on a REPORT passer. |
| S6 throw sourcing | PR #19 at `bf7eace` freezes three exact KESP omissions (partial near-boss, AKQ/boss bundle, 876/whole-suit evacuation) and two public-information families, capped at eight additions. Codex's compiled source audit passes the 25-test throw/current-ballot slice: the human submissions stood as full throws, hidden hands do not affect sourcing, and follow positions emit nothing. | Source semantics review only. A later packet must union these additions with the literal live ballot while preserving candidate zero, let rollouts price failed-throw/ruff risk, and include a same-work control. Even source PASS does not authorize a screen. |

## Secondary review queued behind capture-v5

PR #18 source rereview is ready at exact head
`59ae21ea4684e25c6212415dbd90ef200a82a709` on current REPORT base
`bc566ff`. Its merge-base diff is composition-only: six source files and six
test files. Ordered material recipe is exactly
`shasum -a 256 <the 12 paths listed by git diff --name-only, in lexical order> | shasum -a 256`;
result `cdaa2554cc9ccf06a22a13afa9f5cd33588124e904d49f6fe0658bf186c38581`.
Focused candidate tests pass 14/14, the complete Stage-C slice passes 216/216,
and Stage-C plus S3c/live-parent passes 253/253.

Review should falsify:

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

## Compute sequence after capture-v5 PASS

1. Mini: consume one fresh v5 admission and restart all 24 shards in three
   waves of eight workers over the unchanged 750,000 deals, with JSON scan
   progress every 250 deals and per-candidate uncertainty progress.
2. Mini: freeze the exact 2,048-state set and replay-authenticate all 750,000
   dispositions with eight workers. Stop on any underfilled quota or mismatch.
3. Review the immutable state set. Then Mini runs the 32-state/eight-worker
   outcome-discarding label capacity pilot, capped at four wall-hours.
4. Review the capacity result and label packet. If passed, Mini executes 16
   label shards with eight workers; the contract caps the projected full run
   at 192 fleet-hours / 24 wall-hours.
5. Air is staged cleanly at v5 training source `535fc39` with Python
   3.14.6 and a passing 80-test staged slice. Once
   labels pass, run 48 cells (play/bury × eight seeds × 25/50/100% curves), at
   most eight concurrently.
6. Select one capability only from DESIGN/CALIB, open sealed REPORT exactly
   once, compose the passer inside report-LCB with incumbent fallback and a
   same-work null, then run a fresh whole-game screen against the live champion.

## Safety boundary

- V3 is terminally held. Do not reuse its receipt or six partial shards, retry
  its deterministic failures, delete/reissue its receipt, or start later waves.
- V4 passed its phase review but is superseded before admission. Only an exact
  v5 PASS and fresh v5 namespace may issue the one capture receipt; all older
  markers and artifacts grant it no authority.
- Do not retry H0, inspect its 555 partial utilities, or derive a human rule.
- Do not launch S4 confirmation, S3a, S6 or an unreviewed Stage-C stage merely
  to occupy an idle machine.
- Do not open REPORT during capture, capacity, labels, training review or
  DESIGN/CALIB selection.
- The T4 goal stops before confirmation, promotion or deployment.
