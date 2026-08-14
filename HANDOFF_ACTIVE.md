# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through `HANDOFF_ACTIVE.md` and
> `HANDOFF_REVIEW.md` on canonical `main`. Branch-local ledgers are never
> review authority. Raw review markers belong at column one in the canonical
> review ledger and must occur exactly once.
>
> This file is current executable truth only. Historical detail belongs in
> `docs_archive/`; `HANDOFF_REVIEW.md` remains the evidence authority.

Last reconciled: 2026-08-14 03:05 EDT from canonical main `210ed72`.

## Live fleet

| host | current work | safe state and next boundary |
|---|---|---|
| **Mini** | PR #103 native-round differential soak, eight nice-15 workers | T4 is terminally reviewed `SELECT_NONE`. The open-state soak uses PR head `3044a2f` and compares native/pure state after every play across 10,000,000 deterministic rounds. All eight workers remain CPU-bound after 3h03m; all eight logs remain empty, so no mismatch or terminal output has appeared. It reads no sealed data and grants no benchmark, strength or merge authority. |
| **Air** | broad Pair-aware screen, eight workers | Exact source `cd206707`; all eight workers are alive and CPU-bound. Reviewed score-free counters are `[496,496,512,496,512,496,496,496]/896`, totaling `4,000/7,168` (55.80%); 0/8 terminal. Outcomes stay sealed. The 64-hour timeout trajectory remains unfavorable. The selective-S6 queue remains asleep behind the supervisor. |
| **Strength Cloud** | idle; S4 terminal review pending | Exact source `e7551e4` finished both reviewed tranches cleanly and all workers exited. The exact pinned read-only verifier returned `verified=true`, final SHA `0aef1ca8…e90` and terminal status `SELECT_NONE`, with `strength_claim=false` and `production_promotion=false`. Independent terminal review is requested in PR #66 comment `5290507470`; do not retry or act on a candidate. |
| **Performance Cloud** | idle; PR #106 and PR #108 reviews pending | Claude terminal-review commit `95e0faf` independently reopened the sole PR #103 batch and returned VERIFIED/retain: 3.4074% lower x86 whole-round wall with paired one-sided 95% LCB 1.0299%; all six normalized semantic traces are exact. The consumed design can never rerun. Pair Capacity V2 passed at `482119b` (47.88h <= 52h); exact PR #106 `f1791f5` awaits source review before one packet may be frozen. S6 V3 verified 64/64 sealed receipts; exact aggregation PR #108 `d40182d` awaits review before any record may be opened. |
| **Production** | release 18, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. Running sealed jobs remain on their exact pinned trees; merged optimizations never alter them in place. |

## Review queue — precise asks

1. **S4 360B terminal review.** On Strength Cloud, independently run only the
   exact pinned read-only verifier at source `e7551e4`, runner SHA
   `a6586be8…dda` and controller SHA `cd69a712…bb0a`. It must reproduce final
   SHA `0aef1ca8…e90` and `status=SELECT_NONE`. Falsify packet/admission/
   receipt bindings; exact 16+16 shard/log/exit populations; both aggregates;
   automatic continuation and tranche-two release; null sentinel; terminal
   transition/reconstruction; and authority closure. Exact command and all
   artifact hashes are in PR #66 comment `5290507470`. Return prose PASS/HOLD
   only; this grants no retry, candidate action, strength claim or deployment.

2. **PR #106 Pair checkpoint-screen source review.** Independently audit exact
   head `f1791f51b913fa91171a2337badb4a84cedd1319` over Capacity V2
   `8a3ef59`; exact two-file SHAs are in PR comment `5289911149`. Reproduce
   the 26 focused and 135 strict x86 chain tests; falsify the reviewed
   capacity chain, 224 immutable 32-cluster bundles, at-most-16-worker/systemd
   boundary, atomic review+admission gate, sealed outcome bundles, receipt-only
   supervisor, and absence of resume/aggregate commands. If clean, append only
   the controller-generated raw implementation marker. PASS may freeze one
   host packet only; it cannot execute the screen or open outcomes.

3. **PR #108 S6 V3 aggregation source + exact-input review.** Independently
   audit exact head `d40182d313f9ed3fcb853d2c82b74454398a4a9a`
   over terminal source `a93c2f5`; exact two-file SHAs and the score-free
   preflight are in PR comment `5290133523`. Without opening a scored record,
   reproduce 14 focused and 120 pure/strict-compiled chain tests; falsify the
   exact terminal chain, source/runtime closure, gate-before-open boundary,
   all-64-record validation, exact two-primary-gate statistics, terminal
   recomputation and closed authority. If clean, append only the generated
   raw aggregate marker. PASS authorizes exactly one aggregate and the opening
   of these 64 records; it authorizes no downstream screen or strength claim.

4. **PR #107 performance wave-two repair — not launch-critical.** Exact head
   `1982c48` is HOLD after Codex reproduced a stale mutable-world cache
   (`110.0` cached versus `90.0` recomputed) and showed 34–128-card malformed
   hands entering the bounds-check-disabled lead kernel instead of the reviewed
   pure fallback. Repair both in one head with explicit per-world preparation
   scope, fresh candidate copies and exact 33-card native admission; add the
   decisive mutation/fallback fixtures and rerun pure/strict suites. Full
   reproduction and smallest repair are in PR comment `5290233595`. Its prior
   7.05% ARM timing is exploratory and must be remeasured after repair.

5. **PR #105 PointContext/point-flow exact-head review — non-launch-critical.**
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
   grants no strength or deployment authority. The Mini open-state soak may
   finish independently but cannot reinterpret the frozen result.

2. **Pair checkpoint successor.** Capacity V2 terminal PASS at `482119b`
   confirms 47.88 projected hours <= the reviewed 52h cap. Exact PR #106
   implementation `f1791f5` is published, CI-green and awaiting consolidated
   source review. After its raw implementation PASS, freeze one host-specific
   packet and request one separate packet execution review; do not start the
   screen before that PASS.

3. **S6 V3.** Terminal PASS at `482119b` verifies 64/64 closed receipts with
   no record opened. Exact aggregation PR #108 `d40182d` is published,
   CI-green and awaiting its consolidated source + exact-input review. After
   its raw PASS, run the aggregate exactly once; keep the result unopened and
   return it for independent terminal recomputation before acting on efficacy.

4. **S4 terminal sequence.** Both tranches and the exact pinned verifier are
   complete. The verifier returned `SELECT_NONE`, final SHA `0aef1ca8…e90`,
   `strength_claim=false` and `production_promotion=false`. Await independent
   terminal review from PR #66 comment `5290507470`; never retry or reinterpret
   the terminal decision. Strength Cloud is otherwise idle.

5. **Air Pair terminal/timeout sequence.** Do not intervene, resize or extend.
   If the supervisor publishes a valid score-free final, review it before any
   aggregation. If the immutable timeout fires, preserve the terminal HOLD;
   the sleeping S6 queue must not interpret that as a clean release. PR #96 is
   the separately reviewed path to capacity-size a fresh checkpoint successor.

## Landed and closed anchors

- **T4:** terminal `SELECT_NONE`; no retry or continuation.
- **S4:** exact two-look controller completed and the pinned machine verifier
  returned terminal `SELECT_NONE` at final SHA `0aef1ca8…e90`; independent
  terminal evidence review is pending, with no retry or candidate action.
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
  awaits independent result/manifest review.
- **Pair ballot:** provenance-preserving foundation #55→#60→#61→#72→#79→#84
  →#86 is on main. Reviewed design-only PR #100 and PR #101 are also merged.
  They authorize separate implementation proposals only, not execution.
- **Point-flow census:** PR #99 exact `0ee28a0` passed descriptive-tooling
  review and withdraws the old unlike-denominator headline. It grants no run,
  training, strength or deployment authority.
- **S6 V2/V3:** the V2 start refused on ignored bytecode before packet-review
  snapshot, admission, gameplay, records or final. V2 cannot retry; V3 binds
  that incident under a fresh namespace, completed cleanly and terminally
  verified at `482119b`; all 64 scored records remain sealed.
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
