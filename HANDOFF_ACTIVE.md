# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through `HANDOFF_ACTIVE.md` and
> `HANDOFF_REVIEW.md` on canonical `main`. Branch-local ledgers are never
> review authority. Raw review markers belong at column one in the canonical
> review ledger and must occur exactly once.
>
> This file is current executable truth only. Historical detail belongs in
> `docs_archive/`; `HANDOFF_REVIEW.md` remains the evidence authority.

Last reconciled: 2026-08-14 08:43 EDT from canonical main `0647ad4`.

## Live fleet

| host | current work | safe state and next boundary |
|---|---|---|
| **Mini** | idle | T4 is terminally reviewed `SELECT_NONE`. The PR #103 differential soak completed all 10,000,000 deterministic rounds / 744,566,732 plays, 8/8 PASS with no native/pure mismatch. It opened no sealed evidence and grants no strength authority. |
| **Air** | broad Pair-aware screen, eight workers | Exact source `cd206707`; all eight workers remain alive and CPU-bound. Latest reviewed score-free floor is `4,496/7,168` (62.72%); 0/8 terminal. Outcomes stay sealed and the timeout trajectory remains unfavorable. The selective-S6 queue remains asleep behind the supervisor. |
| **Strength Cloud** | idle | S4 finished both tranches and independent canonical terminal review `15e8dbb` reproduced final SHA `0aef1ca8…e90` and `SELECT_NONE`. The PR #103 x86 differential soak also completed 2,000,000 rounds, PASS with no mismatch. No retry/candidate action follows. |
| **Performance Cloud** | idle; S6 V2 recovery review is top priority | PR #103 terminal performance review retained 3.4074% lower wall / +1.0299% paired LCB. S6 aggregate V1 consumed its sole admission and refused on record 0 because canonical JSON reordered mode keys; no result or partial exists and V1 cannot retry. Incident/diagnosis is canonical at `0647ad4`. Distinct recovery head `1ddaefc` passed 125 pure + 125 compiled tests, the real producer round-trip witness, and a score-free host preflight (`scored_records_opened=false`); exact-head review is pending before one V2 opening. |
| **Production** | release 18, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. Running sealed jobs remain on their exact pinned trees; merged optimizations never alter them in place. |

## Review queue — precise asks

1. **PR #108 S6 aggregate recovery V2 — launch-critical top priority.** Review
   exact head `1ddaefc53733b507920b1d24b931f1f4f3b73657`, descendant of spent
   V1 `32eec425`. Independently falsify the canonical mode-order diagnosis,
   exact V1 gate/snapshot/admission hashes and absent V1 result, distinct V2
   one-shot namespace, exact canonical bytes, exact three-mode set, temporary
   validation-copy reorder, real producer serialize/reparse witness, and the
   rule that any other scorer finding still refuses. Reproduce 31 focused and
   125 pure/strict-compiled chain tests plus
   the real score-free host preflight. Exact SHAs, command and review boundary
   are in PR comments `5293412990` and `5293477106`. If clean, append only the
   generated raw V2
   recovery marker. PASS authorizes one V2 aggregate opening the same 64
   immutable records; no V1 retry, screen, REPORT or strength authority.

2. **PR #106 Pair checkpoint-screen exact-head review.** Review exact repaired
   head `8e30c44d8bd4562c74a10610dc485f1aa0794f89`, child of held
   `f1791f5`. It closes the three requested worker/live-runtime/supervisor-open
   fixtures plus a reproduced pre-import source-execution path. Reproduce 30
   focused and 194 pure/strict-compiled chain tests; falsify exact `-I -P -B`,
   authenticated capacity bytes before execution, worker/runtime rechecks and
   receipt-only supervisor. Exact SHAs and boundary are in PR comment
   `5293529904`. PASS may freeze one host packet only; no screen execution,
   outcome access, aggregation, retry, strength or deployment authority.

3. **PR #107 performance wave-two repair — not launch-critical.** Exact head
   `1982c48` is HOLD after Codex reproduced a stale mutable-world cache
   (`110.0` cached versus `90.0` recomputed) and showed 34–128-card malformed
   hands entering the bounds-check-disabled lead kernel instead of the reviewed
   pure fallback. Repair both in one head with explicit per-world preparation
   scope, fresh candidate copies and exact 33-card native admission; add the
   decisive mutation/fallback fixtures and rerun pure/strict suites. Full
   reproduction and smallest repair are in PR comment `5290233595`. Its prior
   7.05% ARM timing is exploratory and must be remeasured after repair.

4. **PR #105 PointContext/point-flow exact-head review — non-launch-critical.**
   Codex repaired all remaining gaps at exact head `f599be8c9917c5d314889c11aee81b42c1713296`;
   both CI checks and 26 focused tests in pure/strict modes pass. Independently
   falsify exact Trick/TrickPlay/card/point shape, empty-round banker/tally/
   history/kitty guards and refusal atomicity; confirm all causal language and
   the nonexistent proposal link are gone and the production import surface
   remains zero. Exact SHAs and witnesses are in PR comment `5290307266`.
   PASS is code/semantic merge-readiness only, not execution or strength.

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
   successor `8e30c44` is published, CI/review pending, and closes all held
   guards plus pre-import source authentication. Only after its raw PASS may
   one host packet be frozen and separately reviewed.

3. **S6 V3.** Terminal PASS at `482119b` verifies 64/64 closed receipts. The
   V1 aggregate admission was spent by a deterministic canonical-key-order
   refusal on record 0; no aggregate exists and V1 can never retry. Exact V2
   recovery `1ddaefc` is published and score-free-preflight-clean. After its
   raw recovery PASS, run the distinct V2 aggregate exactly once, keep the
   result unopened, and return it for independent terminal recomputation.

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
