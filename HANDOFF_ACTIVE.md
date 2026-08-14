# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through `HANDOFF_ACTIVE.md` and
> `HANDOFF_REVIEW.md` on canonical `main`. Branch-local ledgers are never
> review authority. Raw review markers belong at column one in the canonical
> review ledger and must occur exactly once.
>
> This file is current executable truth only. Historical detail belongs in
> `docs_archive/`; `HANDOFF_REVIEW.md` remains the evidence authority.

Last reconciled: 2026-08-13 23:11 EDT from canonical main `63fa3fb`.

## Live fleet

| host | current work | safe state and next boundary |
|---|---|---|
| **Mini** | idle after T4 | T4 is terminally reviewed `SELECT_NONE` at canonical `a165274`. Aggregate `f30a77c7…e652` passed recursive reproduction and exact work. No confirmation, retry, strength, promotion or deployment authority exists. |
| **Air** | broad Pair-aware screen, eight workers | Exact source `cd206707`; all eight workers are alive and CPU-bound. Reviewed score-free counters are `[448,464,464,448,464,464,448,448]/896`, totaling `3,648/7,168` (50.89%); 0/8 terminal. Outcomes stay sealed. The 64-hour timeout trajectory remains unfavorable. The reviewed selective-S6 queue is asleep behind the Pair supervisor and must not bypass it. |
| **Strength Cloud** | S4 360B point-banking confirmation, tranche two | Exact source `e7551e4`; all 16 workers are alive and CPU-bound. Reviewed score-free progress is `6,192/8,192` (75.59%); 0/16 terminal. Look one passed integrity but not early efficacy, so the reviewed controller continued automatically. No outcome has been opened and there is no hard runtime timeout. |
| **Performance Cloud** | review-gated Pair capacity and S6 V3 staging | No gameplay worker is live. PR #96 packet `b2d78d67…f69f92f` is frozen and verified but unreviewed/unexecuted. Optimized S6 V3 exact `a93c2f5` is staged with zero loadable shadows; no V3 packet exists. |
| **Production** | release 18, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. Running sealed jobs remain on their exact pinned trees; merged optimizations never alter them in place. |

## Immediate review and execution queue

1. **PR #96 packet review — fastest path to useful host utilization.**
   Source head `8a3ef59` passed external review and raw implementation marker
   `035bb24` authorized one packet freeze. Root-owned packet
   `b2d78d67…f69f92f` / internal `f9123d41…817f1b` binds runtime profile
   `ff2dc8f1…7945` and canonical unit `8f8d0919…ae1f`; verification passes.
   Packet-review snapshot, admission, result and installed unit are absent.
   Await the exact raw `PAIR_AWARE_ROLLOUT_CHECKPOINT_CAPACITY_PACKET_V2_REVIEW`
   marker requested on PR #96. After authenticating it, install the exact
   source-generated unit and start one score-free capacity execution. Never
   restart it. A PASS does not authorize the Pair screen, resume, aggregate,
   outcome access, strength or deployment.

2. **PR #104 repaired S6 V3 source review.** Claude HOLDed `f12df08` at
   canonical `63fa3fb` because its ignored-`.pyc` regression mocked
   `runtime_snapshot`. Exact child `a93c2f5` changes only that test; production
   controller SHA remains `744b4c5d…eaa9`. The real
   `verify_packet -> runtime_snapshot -> _shadow_paths` route now refuses the
   planted shadow, and replacing the production scan with `[]` makes the test
   fail. The named five-file battery is 123/123 pure and 123/123 compiled.
   The exact x86 checkout is staged with native `a11519ef…047`, frozen unit
   `cee32e13…f4b` and runtime profile `05bc6e4d…76bf`; no packet/admission/unit
   installation exists. Await the raw V3 implementation marker. Source PASS
   may freeze one fresh host packet only; that packet needs a separate review
   before any serial scored-DEV execution.

3. **PR #97 final documentation review.** Exact docs head `316d6b7` changes
   only `AI_POLICIES.md`, `BACKLOG.md`, `JOBS.md`, `PERF.md`, `RL_PLAN.md` and
   the August-13 daily log. CI is green; diff/table/stale-state checks pass.
   It records T4 terminal truth, current score-free fleet state, merged perf,
   PR #96 packet state and S6 recovery without opening authority. Merge only
   after exact-head documentation PASS.

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
  that incident under a fresh namespace.

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
