# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through `HANDOFF_ACTIVE.md` and
> `HANDOFF_REVIEW.md` on canonical `main`. Branch-local ledgers are never
> review authority. Raw review markers belong at column one in the canonical
> review ledger and must occur exactly once.
>
> This file is current executable truth only. Historical detail belongs in
> `docs_archive/`; `HANDOFF_REVIEW.md` remains the evidence authority.

Last reconciled: 2026-08-14 00:48 EDT from canonical main `47bf5ab`.

## Live fleet

| host | current work | safe state and next boundary |
|---|---|---|
| **Mini** | PR #103 native-round differential soak, eight nice-10 workers | T4 is terminally reviewed `SELECT_NONE`. The open-state soak uses PR head `3044a2f` and compares native/pure state after every play across 10,000,000 deterministic rounds. All eight workers remain CPU-bound after 47 minutes; all eight logs remain empty, so no mismatch or terminal output has appeared. It reads no sealed data and grants no benchmark, strength or merge authority. |
| **Air** | broad Pair-aware screen, eight workers | Exact source `cd206707`; all eight workers are alive and CPU-bound. Reviewed score-free counters are `[480,480,480,464,480,480,464,464]/896`, totaling `3,792/7,168` (52.90%); 0/8 terminal. Outcomes stay sealed. The 64-hour timeout trajectory remains unfavorable. The selective-S6 queue remains asleep behind the supervisor. |
| **Strength Cloud** | S4 360B point-banking confirmation, tranche two | Exact source `e7551e4`; all 16 workers are alive and CPU-bound. Reviewed score-free progress is `7,116/8,192` (86.87%); 0/16 terminal. Look one passed integrity but not early efficacy, so the reviewed controller continued automatically. No outcome has been opened and there is no hard runtime timeout. |
| **Performance Cloud** | idle; PR #103 host envelope frozen | Pair capacity invocation `b98b4e15…` exited cleanly after 34m13s with result `c120ddbb…7762` and receipt `488bf140…f005`; both remain unopened pending score-free review. S6 V3 exited successfully after 5m29s with score-free final `d5136a27…8617`, exactly 64 sealed records, zero partials and no worker; records/final remain unopened pending review. Exact PR #103 base/head/tooling are staged root-owned and the host design is frozen at `62e471e4…e075`; no A/B arm has started. |
| **Production** | release 18, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. Running sealed jobs remain on their exact pinned trees; merged optimizations never alter them in place. |

## Review queue — precise asks

1. **PR #103 concrete x86 design review — utilization blocker.** Source head
   `3044a2f` already passed Codex's exact-head review; do not repeat it. On
   Performance Cloud independently review tooling `e407d50` and frozen design
   `/var/tmp/report-lcb-perf-ab-pr103-v1.design.json`, exact SHA-256
   `62e471e44fe9191abdec177fcfcccf1f3dfca31b9bb3478dfd92c2ac54e3e075`.
   It binds base `57a1c2b` / native `05f7165b…6769`, head `3044a2f` /
   native `2c9f2474…bf95`, harness `a6de0a02…78c6`, validator
   `1e69d103…a408`, host profile `80079d92…ab0`, unit template
   `58e1b0ed…3ef`, Python `b8d8288f…9700`, 69 source paths per arm,
   six fixed alternating N=30/R=300 pairs and the dual >=3% aggregate /
   paired-LCB>0 retention gate. Re-run `check-design`, falsify ownership,
   manifest, source/native/runtime, seed/order, semantic/work/RNG/sampler and
   review-record gates. If PASS, return one canonical
   `report-lcb-perf-ab-review-v1` JSON record bound to this design. That one
   PASS authorizes exactly one no-retry performance batch, not merge, strength
   or deployment.

2. **Pair capacity V2 terminal review.** On Performance Cloud, independently
   review exact source `8a3ef59`, packet `b2d78d67…9f92f`, packet-review
   commit `7490595`, admission `e3e51d2b…0128`, result
   `c120ddbb…7762`, and execution receipt `488bf140…f005`. The root-owned,
   mode-0444, nlink-one result/receipt were produced by successful invocation
   `b98b4e15…c7c`; no refusal/partial or worker remains. Strictly recompute all
   result, projection, receipt, runtime and authority invariants. PASS may
   authorize successor screen-packet implementation/freeze only—not screen
   execution, outcome access, strength, retry, extension or deployment.

3. **S6 V3 score-free terminal review.** On Performance Cloud, authenticate
   exact source `a93c2f5`, packet `0e9ee589…bbee`, packet PASS commit
   `4679ea9`, admission `de8d6c01…d16a`, packet-review snapshot
   `8bbfa3e7…627b`, and root-owned mode-0444 nlink-one supervisor final
   `d5136a27…8617`. Re-run the exact controller `verify-final` command; require
   64 closed state receipts, no partial/refusal, clean runtime, zero workers,
   `scored_records_opened=false` and `aggregation_authorized=false`. Do not
   open any of the 64 sealed record files. PASS may authorize the next
   explicitly reviewed score-free/aggregation boundary only; it grants no
   record opening, strength, training, promotion, deployment or retry.

4. **PR #105 PointContext/point-flow repair — non-launch-critical.** Repaired
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

1. **PR #103 x86 A/B.** Exact root-owned base `57a1c2b`, head `3044a2f`,
   tooling `e407d50`, native binaries and host inputs are staged. Design
   `62e471e4…e075` validates and the evidence namespace is absent. Install the
   byte-exact Claude PASS record and reviewed environment drop-in, recheck
   idle/exclusive host plus all immutable inputs, then start exactly one
   systemd batch. No start before the concrete-design PASS; never retry/tune.

2. **Pair capacity V2.** Terminal success is preserved; never restart it.
   Await the independent score-free result/receipt review before any successor
   screen packet work.

3. **S6 V3.** Terminal success is preserved; never restart it. Keep all 64
   scored records and the score-free final sealed until the independent
   terminal review defines the next boundary.

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
- **Pair ballot:** provenance-preserving foundation #55→#60→#61→#72→#79→#84
  →#86 is on main. Reviewed design-only PR #100 and PR #101 are also merged.
  They authorize separate implementation proposals only, not execution.
- **Point-flow census:** PR #99 exact `0ee28a0` passed descriptive-tooling
  review and withdraws the old unlike-denominator headline. It grants no run,
  training, strength or deployment authority.
- **S6 V2:** the sole start refused on ignored bytecode before packet-review
  snapshot, admission, gameplay, records or final. V2 cannot retry; V3 binds
  that incident under a fresh namespace and completed cleanly; its score-free
  final awaits review and all 64 scored records remain sealed.
- **Pair capacity V2 recovery:** the first start refused before admission/work
  on a Claude-created ignored pyc. Canonical recovery PASS `9a8843b` authorized
  exact quarantine plus one start; the preserved second invocation completed
  cleanly and its score-free result/receipt await review.

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
