# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through `HANDOFF_ACTIVE.md` and
> `HANDOFF_REVIEW.md` on canonical `main`. Branch-local ledgers are never
> review authority. Raw review markers belong at column one in the canonical
> review ledger and must occur exactly once.
>
> This file is current executable truth only. Historical detail belongs in
> `docs_archive/`; `HANDOFF_REVIEW.md` remains the evidence authority.

Last reconciled: 2026-08-14 01:01 EDT from canonical main `482119b`.

## Live fleet

| host | current work | safe state and next boundary |
|---|---|---|
| **Mini** | PR #103 native-round differential soak, eight nice-10 workers | T4 is terminally reviewed `SELECT_NONE`. The open-state soak uses PR head `3044a2f` and compares native/pure state after every play across 10,000,000 deterministic rounds. All eight workers remain CPU-bound after 47 minutes; all eight logs remain empty, so no mismatch or terminal output has appeared. It reads no sealed data and grants no benchmark, strength or merge authority. |
| **Air** | broad Pair-aware screen, eight workers | Exact source `cd206707`; all eight workers are alive and CPU-bound. Reviewed score-free counters are `[480,480,480,464,480,480,464,464]/896`, totaling `3,792/7,168` (52.90%); 0/8 terminal. Outcomes stay sealed. The 64-hour timeout trajectory remains unfavorable. The selective-S6 queue remains asleep behind the supervisor. |
| **Strength Cloud** | S4 360B point-banking confirmation, tranche two | Exact source `e7551e4`; all 16 workers are alive and CPU-bound. Reviewed score-free progress is `7,116/8,192` (86.87%); 0/16 terminal. Look one passed integrity but not early efficacy, so the reviewed controller continued automatically. No outcome has been opened and there is no hard runtime timeout. |
| **Performance Cloud** | PR #103 reviewed x86 A/B, serialized | Claude's exact design PASS is canonical at `f46cad5`. One no-retry six-pair batch started at 00:58:40 EDT under systemd invocation `da6f9dd9…7fbe`; the first base arm is active and the evidence namespace was created normally. Pair capacity V2 terminally passed at `482119b` with 47.88 projected hours <= the 52h cap. S6 V3 terminally verified 64/64 sealed receipts at the same commit; no scored record was opened. No other compute overlaps this batch. |
| **Production** | release 18, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. Running sealed jobs remain on their exact pinned trees; merged optimizations never alter them in place. |

## Review queue — precise asks

1. **PR #105 PointContext/point-flow repair — non-launch-critical.** Repaired
   head `90fe978` remains HOLD after Codex follow-up. Atomic staging, factory-
   built context immutability, bool-seat checks and neutral field names are
   real; 24 focused pure tests pass. Close the remaining exact-boundary gaps:
   empty/tuple/duck plays and bool trick points; bool banker/attacker tally on
   history-empty rounds; the nonexistent proposal link; and causal prose that
   still says feed/own-power/surrender. Add the decisive witnesses, run pure
   and compiled focused suites, and request one exact-head delta review.

This block is the canonical hourly-review input. Posting, closing or changing
any review request requires updating this block in the same operational pass;
PR comments alone are not queue state.

## Execution and terminal queue

1. **PR #103 x86 A/B.** Exact design `62e471e4…e075` passed at canonical
   `f46cad5`; invocation `da6f9dd9…7fbe` is the sole active Performance Cloud
   workload. Let the serialized 12-arm batch finish naturally. Never restart,
   tune or overlap it. After terminal, run the frozen offline validator and
   request one exact result/manifest review before reading any retention claim.

2. **Pair checkpoint successor.** Capacity V2 terminal PASS at `482119b`
   confirms 47.88 projected hours <= the reviewed 52h cap and authorizes
   successor screen-packet implementation/freeze only. Build and review that
   packet next; do not start the screen without its separate execution PASS.

3. **S6 V3.** Terminal PASS at `482119b` verifies 64/64 closed receipts with
   no record opened. Keep all scored records sealed. A separate aggregation
   design/review is required before any efficacy result or record access.

4. **S4 terminal sequence.** Let the controller finish tranche two naturally.
   Only after it exits, run the exact pinned read-only verifier at Git
   `e7551e4`; then request independent terminal review. Do not inspect shard
   outputs directly. The result may select a candidate, select none or HOLD;
   it never deploys automatically.

5. **Air Pair terminal/timeout sequence.** Do not intervene, resize or extend.
   If the supervisor publishes a valid score-free final, review it before any
   aggregation. If the immutable timeout fires, preserve the terminal HOLD;
   the sleeping S6 queue must not interpret that as a clean release. PR #96 is
   the separately reviewed path to capacity-size a fresh checkpoint successor.

## Landed and closed anchors

- **T4:** terminal `SELECT_NONE`; no retry or continuation.
- **Docs:** PR #97 exact reviewed head `316d6b7` merged at `8bc2da1`.
- **Performance:** exact measured arm `a91eb271` was 29.3203% faster with
  exact normalized semantics; PR #98 merged the byte-identical production
  runtime as `fe04fa2`. A later current-main diagnostic failed its strict
  normalizer on an explicit false flag; its post-hoc 30.359% is not a
  confirmation. Existing jobs never hot-swap code.
- **PR #103 benchmark envelope:** exact design `62e471e4…e075` passed at
  canonical `f46cad5`, authorizing only the one active six-pair x86 batch.
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
