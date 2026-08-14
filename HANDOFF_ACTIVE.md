# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through `HANDOFF_ACTIVE.md` and
> `HANDOFF_REVIEW.md` on canonical `main`. Branch-local ledgers are never
> review authority. Raw review markers belong at column one in the canonical
> review ledger and must occur exactly once.
>
> This file is current executable truth only. Historical detail belongs in
> `docs_archive/`; `HANDOFF_REVIEW.md` remains the evidence authority.

Last reconciled: 2026-08-14 09:34 EDT from canonical main `e31e9a2`.

## Live fleet

| host | current work | safe state and next boundary |
|---|---|---|
| **Mini** | idle | T4 is terminally reviewed `SELECT_NONE`. The PR #103 differential soak completed all 10,000,000 deterministic rounds / 744,566,732 plays, 8/8 PASS with no native/pure mismatch. It opened no sealed evidence and grants no strength authority. |
| **Air** | broad Pair-aware screen, eight workers | Exact source `cd206707`; all eight workers remain alive and CPU-bound. Latest reviewed score-free floor is `4,496/7,168` (62.72%); 0/8 terminal. Outcomes stay sealed and the timeout trajectory remains unfavorable. The selective-S6 queue remains asleep behind the supervisor. |
| **Strength Cloud** | idle | S4 finished both tranches and independent canonical terminal review `15e8dbb` reproduced final SHA `0aef1ca8…e90` and `SELECT_NONE`. The PR #103 x86 differential soak also completed 2,000,000 rounds, PASS with no mismatch. No retry/candidate action follows. |
| **Performance Cloud** | idle | PR #103 terminal performance review retained 3.4074% lower wall / +1.0299% paired LCB. S6 V2 completed once and canonical independent terminal review `e31e9a2` reproduced result SHA `de1c4f33…d0bc` and `SELECT_NONE_FOR_FRESH_SCREEN_DESIGN`. The bury-source arm passed all criteria, but the required lead-source arm failed three; that asymmetry is hypothesis-only and authorizes no fresh design or run. |
| **Production** | release 18, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. Running sealed jobs remain on their exact pinned trees; merged optimizations never alter them in place. |

## Review queue — precise asks

1. **PR #106 Pair checkpoint-screen final test-only re-review — launch-critical.**
   Review exact `71356b2c75e2c22c3c0a54615029ca1251b3712a`, test-only child of
   held `8e30c44`. The new isolated subprocess witness covers both hostile
   wrong-`__file__` preload refusal and correctly originated preload
   command-time fresh-process refusal; neutralizing either production guard
   turns its leg red. Production remains byte-exact `7d83cae4…f0ed`; reproduce
   31 focused and 195 pure/strict-compiled chain tests. Exact SHAs and mutation
   evidence are in PR comment `5293867314`. PASS may freeze one host packet
   only; no screen execution, outcomes, aggregation, retry or strength.

2. **PR #107 performance wave-two repair — not launch-critical.** Exact head
   `1982c48` is HOLD after Codex reproduced a stale mutable-world cache
   (`110.0` cached versus `90.0` recomputed) and showed 34–128-card malformed
   hands entering the bounds-check-disabled lead kernel instead of the reviewed
   pure fallback. Repair both in one head with explicit per-world preparation
   scope, fresh candidate copies and exact 33-card native admission; add the
   decisive mutation/fallback fixtures and rerun pure/strict suites. Full
   reproduction and smallest repair are in PR comment `5290233595`. Its prior
   7.05% ARM timing is exploratory and must be remeasured after repair.

3. **PR #105 PointContext/point-flow test-only delta acknowledgment —
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

1. **PR #103 x86 A/B.** Terminal review `95e0faf` returned VERIFIED/retain at
   3.4074% lower x86 wall and positive 1.0299% paired one-sided LCB, with all
   six normalized semantic traces exact. The design is consumed forever; never
   restart or tune it. Any merge/rebase remains a separate code operation and
   grants no strength or deployment authority. Both independent differential
   soaks are complete (10,000,000 Mini rounds and 2,000,000 x86 rounds), with
   no mismatch; they do not reinterpret the frozen timing result.

2. **Pair checkpoint successor.** Capacity V2 terminal PASS at `482119b`
   confirms 47.88 projected hours <= the reviewed 52h cap. Exact PR #106
   successor `71356b2` is published and closes the final preload/origin test
   boundary with both mutations killed. Only after its raw PASS may one host
   packet be frozen and separately reviewed.

3. **S6 V3.** Terminal PASS at `482119b` verifies 64/64 closed receipts. The
   V1 aggregate admission was spent by a deterministic canonical-key-order
   refusal on record 0 and can never retry. Exact V2 recovery `2b9d8e5` passed
   at `addd03e`; its single aggregate and canonical result review `e31e9a2`
   reproduced SHA `de1c4f33…d0bc` and terminal decision
   `SELECT_NONE_FOR_FRESH_SCREEN_DESIGN`. The bury-source-only signal is
   hypothesis-generating; no retry, fresh design, screen or strength action.

4. **S4 terminal sequence.** Both tranches and the exact pinned verifier are
   complete. Canonical independent review `15e8dbb` reproduced `SELECT_NONE`,
   final SHA `0aef1ca8…e90`, `strength_claim=false` and
   `production_promotion=false`. Never retry or reinterpret the terminal
   decision. Strength Cloud is idle.

5. **Air Pair terminal/timeout sequence.** Do not intervene, resize or extend.
   If the supervisor publishes a valid score-free final, review it before any
   aggregation. If the immutable timeout fires, preserve the terminal HOLD;
   the sleeping S6 queue must not interpret that as a clean release. PR #96 is
   the separately reviewed path to capacity-size a fresh checkpoint successor.

## Landed and closed anchors

- **T4:** terminal `SELECT_NONE`; no retry or continuation.
- **S4:** exact two-look controller completed; canonical independent review
  `15e8dbb` reproduced terminal `SELECT_NONE` at final SHA `0aef1ca8…e90`.
  The lane is closed with no retry or candidate action.
- **Docs:** PR #97 exact reviewed head `316d6b7` merged at `8bc2da1`.
- **Performance:** exact measured arm `a91eb271` was 29.3203% faster with
  exact normalized semantics; PR #98 merged the byte-identical production
  runtime as `fe04fa2`. A later current-main diagnostic failed its strict
  normalizer on an explicit false flag; its post-hoc 30.359% is not a
  confirmation. PR #103 exact `3044a2f` independently retained at 3.4074%
  lower x86 wall / 1.0299% one-sided LCB under terminal review `95e0faf`;
  do not add ARM microbenchmarks or PR #107 claims. Existing jobs never
  hot-swap code.
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
  that incident under a fresh namespace, completed cleanly and terminally
  verified at `482119b`. Aggregate V1 later opened record 0 under valid
  authority but refused before exposing any score; the 64 source files remain
  immutable, records 1–63 were not opened, and distinct V2 review is pending.
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
