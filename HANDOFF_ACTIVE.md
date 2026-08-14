# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through `HANDOFF_ACTIVE.md` and
> `HANDOFF_REVIEW.md` on canonical `main`. Branch-local ledgers are never
> review authority. Raw review markers belong at column one in the canonical
> review ledger and must occur exactly once.
>
> This file is current executable truth only. Historical detail belongs in
> `docs_archive/`; `HANDOFF_REVIEW.md` remains the evidence authority.

Review queue reconciled: 2026-08-14 12:42 EDT from canonical main `fb246a2`.
Fleet rows retain the 11:47 EDT score-free snapshot below.

## Live fleet

| host | current work | safe state and next boundary |
|---|---|---|
| **Mini** | idle | T4 is terminally reviewed `SELECT_NONE`. The PR #103 differential soak completed all 10,000,000 deterministic rounds / 744,566,732 plays, 8/8 PASS with no native/pure mismatch. It opened no sealed evidence and grants no strength authority. |
| **Air** | broad Pair-aware screen, eight workers | Exact source `cd206707`; all eight workers remain alive and CPU-bound. Latest reviewed score-free floor is `4,640/7,168` (64.73%); 0/8 terminal. Only about 13.9 hours remain before the fixed ~23:29 EDT cutoff, so timeout is now the expected transition. Outcomes stay sealed; do not intervene. The selective-S6 queue remains asleep behind the supervisor. |
| **Strength Cloud** | idle | S4 finished both tranches and independent canonical terminal review `15e8dbb` reproduced final SHA `0aef1ca8…e90` and `SELECT_NONE`. The PR #103 x86 differential soak also completed 2,000,000 rounds, PASS with no mismatch. No retry/candidate action follows. |
| **Performance Cloud** | fresh Pair checkpoint screen, 16 workers | Packet `f2878fff…a5c9c` PASSed at `95242b4` and started exactly once under systemd invocation `ac5425e0e106403e9a82a7bd8cb5b221`. First score-free heartbeat is 0/224 microshards, 16 workers alive, `outcomes_opened=false`; admission and review snapshot are immutable, manifest absent. Runtime cap is 52h. Do not restart, resume, open outcome bytes or aggregate. |
| **Production** | release 18, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. Running sealed jobs remain on their exact pinned trees; merged optimizations never alter them in place. |

## Review queue — precise asks

1. **PR #111 BELIEF-V1 B0/B1 boundary review — no run authority.**
   Review exact head `7ebfcf7959f5254fee3b3dda1fc2fd83600540e9`,
   exactly four files: actor/target contract, in-memory corpus rows, and their
   two test files. Verify hidden-world and absolute-seat invariance, banker-
   private burial, strict physical-deck targets, and zero privileged runtime
   bytes. Falsify incomplete/reordered/mutable transcripts, loss of attempted
   failed-throw cards, round split leakage, schema/authority drift, actor-target
   mismatches and coordinated self-rehashes. Reproduce 41 focused tests in
   pure and strict compiled modes; the two mutation smokes must go red when
   transcript length or target-to-actor hash binding is neutralized. There is
   no file writer, corpus generation, model, sampler, training or run path.
   PASS means typed boundary and in-memory row merge-readiness only.

2. **PR #112 BELIEF-V1 B2 design/ownership-contract review — no run authority.**
   Review exact stacked head `290af7ee952ac646299a208101dc56eeae86624c`
   over PR #111. The exact three-file delta is the offline calibration design,
   actor-relative ownership probability schema/validator, and synthetic tests.
   Recompute file SHAs `1103215e4ee509fdbf0d131061611a3dbe192fd2b8d50c8c2e8ce47b02ed1efb`,
   `c7024e8150ed5b079891ba12f0d82c9f646cdbcb73634cf6c063c449597e31ef`,
   and `c004471203703f43b151b6c3e3e2fc65e1180d8d2b47a2f2547a1c14b535cbae`;
   reproduce 49 focused and 57 adjacent tests in both pure
   and strict compiled modes. Falsify public-twin identity, incomplete history,
   banker/kitty receiver scope, model/policy binding, bool/noncanonical counts,
   one/two-copy limits, expectation conservation, proven voids, and single vs
   pair declaration semantics. The expectation-preserving void/pair mutations
   must go red only when their named guards are neutralized. Audit the frozen
   4,096-round opened-development population, exact current constraint-
   consistent REF-C baseline, eight-seed cohort, C/N/U gates, caps, and
   two-review path. There is no model, writer, sampler, gameplay or runner.
   PASS means source/design merge-readiness only; it does not authorize corpus
   capture, training, cloud use, online screening, strength or deployment.

3. **PR #107 performance wave-two repaired-head re-review — not launch-critical.**
   Exact successor `34ea5a6f08da4b482f4cfc889c48dcf2b4bbd9a4` removes the stale
   identity cache in favor of explicit per-world prepared hands and restores
   the exact 33-card native admission. Reproduce the mutation/fresh-copy/direct
   call/route witnesses and resolve its current failing CI before any x86 A/B.
   The prior 7.05% ARM timing is exploratory and cannot retain this head.

4. **PR #105 PointContext/point-flow test-only delta acknowledgment —
   non-launch-critical.** Claude verified substantive repair `f599be8c`, then
   added two independent mutation witnesses in exact child `c454aaaf` (+17
   test lines; production unchanged): valid-banker/bool-tally refusal and exact
   `Round` duck refusal. Reproduce 26/26 pure and strict compiled and confirm
   both guards now have teeth. PASS is code/semantic merge-readiness only, not
   execution or strength.

This block is the canonical hourly-review input. Posting, closing or changing
any review request requires updating this block in the same operational pass;
PR comments alone are not queue state.

## Execution and terminal queue

1. **Pair checkpoint successor.** Capacity V2 terminal PASS at `482119b`
   confirms 47.88 projected hours <= the reviewed 52h cap. PR #106 source
   `71356b2` PASSed at `83c6909`; exact packet `f2878fff…a5c9c` PASSed at
   `95242b4` and started once at 09:56 EDT. Systemd owns all 16 workers under
   invocation `ac5425e0e106403e9a82a7bd8cb5b221`; first heartbeat is 0/224,
   outcomes unopened. Monitor score-free heartbeats only. Completion publishes
   a score-free manifest for separate review; no resume or aggregate command
   exists and any interruption spends the admission.

2. **S6 V3.** Terminal PASS at `482119b` verifies 64/64 closed receipts. The
   V1 aggregate admission was spent by a deterministic canonical-key-order
   refusal on record 0 and can never retry. Exact V2 recovery `2b9d8e5` passed
   at `addd03e`; its single aggregate and canonical result review `e31e9a2`
   reproduced SHA `de1c4f33…d0bc` and terminal decision
   `SELECT_NONE_FOR_FRESH_SCREEN_DESIGN`. The bury-source-only signal is
   hypothesis-generating; no retry, fresh design, screen or strength action.

3. **S4 terminal sequence.** Both tranches and the exact pinned verifier are
   complete. Canonical independent review `15e8dbb` reproduced `SELECT_NONE`,
   final SHA `0aef1ca8…e90`, `strength_claim=false` and
   `production_promotion=false`. Never retry or reinterpret the terminal
   decision. Strength Cloud is idle.

4. **Air Pair terminal/timeout sequence.** Do not intervene, resize or extend.
   If the supervisor publishes a valid score-free final, review it before any
   aggregation. If the immutable timeout fires, preserve the terminal HOLD;
   the sleeping S6 queue must not interpret that as a clean release. The fresh
   checkpoint successor is already running separately on Performance Cloud.

## Landed and closed anchors

- **T4:** terminal `SELECT_NONE`; no retry or continuation.
- **S4:** exact two-look controller completed; canonical independent review
  `15e8dbb` reproduced terminal `SELECT_NONE` at final SHA `0aef1ca8…e90`.
  The lane is closed with no retry or candidate action.
- **Docs:** PR #97 exact reviewed head `316d6b7` merged at `8bc2da1`. The
  campaign closeout and post-null roadmap PR #109 exact `8fa96de` PASSed at
  canonical `499de77` and merged at `09b80bb`. BELIEF-V1 spec/roadmap PR #110
  exact `b8c2a4c` PASSed at `de26d60` and merged at `fb246a2`; it grants no
  corpus, training, run, strength or deployment authority.
- **Performance:** exact measured arm `a91eb271` was 29.3203% faster with
  exact normalized semantics; PR #98 merged the byte-identical production
  runtime as `fe04fa2`. A later current-main diagnostic failed its strict
  normalizer on an explicit false flag; its post-hoc 30.359% is not a
  confirmation. PR #103 exact `3044a2f` independently retained at 3.4074%
  lower x86 wall / 1.0299% one-sided LCB under terminal review `95e0faf` and
  merged through `e3af8c3`; do not add ARM microbenchmarks or PR #107 claims.
  Existing jobs never hot-swap code.
- **PR #103 benchmark envelope:** exact design `62e471e4…e075` passed at
  canonical `f46cad5`; its sole six-pair x86 batch is terminal success and
  independent result/manifest review `95e0faf` retained it.
- **Pair ballot:** provenance-preserving foundation #55→#60→#61→#72→#79→#84
  →#86 is on main. Reviewed design-only PR #100 and PR #101 are also merged.
  They authorize separate implementation proposals only, not execution.
- **Point-flow census:** PR #99 exact `0ee28a0` passed descriptive-tooling
  review and withdraws the old unlike-denominator headline. It grants no run,
  training, strength or deployment authority.
- **S6 V2/V3:** the V2 start refused on ignored bytecode before packet-review
  snapshot, admission, gameplay, records or final. V2 cannot retry; V3 binds
  that incident under a fresh namespace and completed cleanly. Aggregate V1
  later refused on record-zero canonical ordering under valid authority and is
  spent. Exact V2 recovery then reconstructed all 64 records and terminal
  review `e31e9a2` selected none for a fresh screen design. No retry or new
  S6 screen is authorized.
- **Pair capacity V2 recovery:** the first start refused before admission/work
  on a Claude-created ignored pyc. Canonical recovery PASS `9a8843b` authorized
  exact quarantine plus one start; the preserved second invocation passed
  terminal review at `482119b`, projecting 47.88 hours against the 52h cap.

## Standing invariants

- Never inspect live or sealed result/shard bytes. Process state and explicitly
  reviewed score-free heartbeat fields are the monitoring surface.
- An implementation/design PASS is not execution authority. Every packet,
  one-shot admission and terminal opening has its own named gate.
- Never retry, extend or resize a spent namespace unless a new reviewed design
  explicitly authorizes a fresh namespace.
- Same deals, role flips, work and policy randomness remain shared wherever a
  frozen design requires them. Telemetry is dose/integrity evidence, not
  whole-game utility.
- No review implies REPORT reuse, training, strength, production promotion or
  deployment. No source merge changes already-running pinned workers.
