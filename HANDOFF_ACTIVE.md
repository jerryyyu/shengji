# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through `HANDOFF_ACTIVE.md` and
> `HANDOFF_REVIEW.md` on canonical `main`. Branch-local ledgers are never
> review authority. Raw review markers belong at column one in the canonical
> review ledger and must occur exactly once.
>
> This file is current executable truth only. Historical detail belongs in
> `docs_archive/`; `HANDOFF_REVIEW.md` remains the evidence authority.

Last reconciled: 2026-08-14 00:27 EDT from canonical main `2ca5122`.

## Live fleet

| host | current work | safe state and next boundary |
|---|---|---|
| **Mini** | PR #103 native-round differential soak, eight nice-10 workers | T4 is terminally reviewed `SELECT_NONE`. The open-state soak uses the repair bytes now pushed at PR head `3044a2f` and compares native/pure state after every play across 10,000,000 deterministic rounds. All eight workers remain CPU-bound after 27 minutes; no mismatch or terminal output has appeared. It reads no sealed data and grants no benchmark, strength or merge authority. |
| **Air** | broad Pair-aware screen, eight workers | Exact source `cd206707`; all eight workers are alive and CPU-bound. Reviewed score-free counters are `[464,480,480,464,480,464,464,464]/896`, totaling `3,760/7,168` (52.46%); 0/8 terminal. Outcomes stay sealed. The 64-hour timeout trajectory remains unfavorable. The selective-S6 queue is asleep behind the supervisor. |
| **Strength Cloud** | S4 360B point-banking confirmation, tranche two | Exact source `e7551e4`; all 16 workers are alive and CPU-bound. Reviewed score-free progress is `6,944/8,192` (84.77%); 0/16 terminal. Look one passed integrity but not early efficacy, so the reviewed controller continued automatically. No outcome has been opened and there is no hard runtime timeout. |
| **Performance Cloud** | Pair successor score-free capacity, 16 workers | PR #96 recovery PASS `9a8843b` bound the pre-admission ignored-pyc incident. The exact pyc is quarantined intact and invocation `b98b4e15…` started at 00:01 EDT after exact re-verification. The controller plus all 16 workers remain active and saturated after 25 minutes; packet snapshot and admission exist, while result/refusal is absent. The systemd deadline is 04:01 EDT. S6 V3 packet `0e9ee589…bbee` passed at `4679ea9` and waits only for zero Pair workers. |
| **Production** | release 18, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. Running sealed jobs remain on their exact pinned trees; merged optimizations never alter them in place. |

## Review queue — precise asks

1. **PR #103 x86 benchmark-envelope freeze.** Exact final head `3044a2f`
   passed Codex's independent delta review: fresh ARM build, 41 native-route,
   33 engine/action and 74 combined focused tests; malformed cached values
   fall back before C casts and normal trusted states remain native. Freeze
   one host-specific six-pair N=30/R=300 envelope for base `57a1c2b` versus
   exact head `3044a2f`, using the reviewed V5 source/runtime/manifest and
   exact-semantic gate. Codex prepared the two-file tooling rebind locally at
   `e407d50` in `/private/tmp/shengji-perf-pr103-tooling.5a4IDg`; 52 contract
   tests pass. Populate host identities after the strength queue frees, then
   request one concrete-envelope review before running. No x86 A/B, merge,
   deploy or strength authority exists yet.

2. **PR #105 PointContext/point-flow repair — non-launch-critical.** Exact
   `e22bfff` is HOLD. Repair rejected-round accumulator mutation, mutable
   `Memory` exposure, malformed trick/bool-seat admission, causal `fed` /
   `discarded` naming, and the nonexistent proposal link. Preserve the
   zero-production-import boundary, push one bounded child, then request one
   exact-head delta review.

This block is the canonical hourly-review input. Posting, closing or changing
any review request requires updating this block in the same operational pass;
PR comments alone are not queue state.

## Execution and terminal queue

1. **Pair capacity V2.** Monitor systemd invocation `b98b4e15…` only. Never
   restart it. After exit, preserve all artifacts and request independent
   score-free result/refusal review before any screen packet work.

2. **S6 V3.** Packet PASS `4679ea9` authorizes one serial 64-state scored-DEV
   execution. Install/start the exact staged unit only after Pair capacity
   exits and zero Pair workers remain. Keep all scored records sealed; after
   terminal, review only the score-free final before any record access.

3. **S4 terminal sequence.** Let the controller finish tranche two naturally.
   Only after it exits, run the exact pinned read-only verifier at Git
   `e7551e4`; then request independent terminal review. Do not inspect shard
   outputs directly. The result may select a candidate, select none or HOLD;
   it never deploys automatically.

4. **Air Pair terminal/timeout sequence.** Do not intervene, resize or extend.
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
- **Pair ballot:** provenance-preserving foundation #55→#60→#61→#72→#79→#84
  →#86 is on main. Reviewed design-only PR #100 and PR #101 are also merged.
  They authorize separate implementation proposals only, not execution.
- **Point-flow census:** PR #99 exact `0ee28a0` passed descriptive-tooling
  review and withdraws the old unlike-denominator headline. It grants no run,
  training, strength or deployment authority.
- **S6 V2:** the sole start refused on ignored bytecode before packet-review
  snapshot, admission, gameplay, records or final. V2 cannot retry; V3 binds
  that incident under a fresh namespace and now has a frozen packet.
- **Pair capacity V2 recovery:** the first start refused before admission/work
  on a Claude-created ignored pyc. Canonical recovery PASS `9a8843b` authorized
  exact quarantine plus one start; the preserved second invocation is live.

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
