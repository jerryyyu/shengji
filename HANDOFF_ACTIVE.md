# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through `HANDOFF_ACTIVE.md` and
> `HANDOFF_REVIEW.md` on canonical `main`. Branch-local ledgers are never
> review authority. Raw review markers belong at column one in the canonical
> review ledger and must occur exactly once.
>
> This file is current executable truth only. Historical detail belongs in
> `docs_archive/`; `HANDOFF_REVIEW.md` remains the evidence authority.

Last reconciled: 2026-08-14 01:45 EDT from canonical main `85391bf`.

## Live fleet

| host | current work | safe state and next boundary |
|---|---|---|
| **Mini** | PR #103 native-round differential soak, eight nice-10 workers | T4 is terminally reviewed `SELECT_NONE`. The open-state soak uses PR head `3044a2f` and compares native/pure state after every play across 10,000,000 deterministic rounds. All eight workers remain CPU-bound after 1h44m; all eight logs remain empty, so no mismatch or terminal output has appeared. It reads no sealed data and grants no benchmark, strength or merge authority. |
| **Air** | broad Pair-aware screen, eight workers | Exact source `cd206707`; all eight workers are alive and CPU-bound. Reviewed score-free counters are `[480,480,496,480,480,480,480,480]/896`, totaling `3,856/7,168` (53.79%); 0/8 terminal. Outcomes stay sealed. The 64-hour timeout trajectory remains unfavorable. The selective-S6 queue remains asleep behind the supervisor. |
| **Strength Cloud** | S4 360B point-banking confirmation, tranche two | Exact source `e7551e4`; all 16 workers are alive and CPU-bound. Reviewed score-free progress is `7,646/8,192` (93.33%); 0/16 terminal. Look one passed integrity but not early efficacy, so the reviewed controller continued automatically. No outcome has been opened and there is no hard runtime timeout. |
| **Performance Cloud** | idle; PR #103 result review and PR #106 source review pending | The sole reviewed PR #103 six-pair batch under invocation `da6f9dd9…7fbe` exited success/0; Codex has not read its retain/drop claim. Pair Capacity V2 passed at `482119b` (47.88h <= 52h), and its checkpoint-screen implementation is exact PR #106 head `f1791f5`, mergeable with both checks green and awaiting the source-only review that may freeze one host packet. S6 V3 verified 64/64 sealed receipts; aggregation remains separately gated. |
| **Production** | release 18, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. Running sealed jobs remain on their exact pinned trees; merged optimizations never alter them in place. |

## Review queue — precise asks

1. **PR #106 Pair checkpoint-screen source review.** Independently audit exact
   head `f1791f51b913fa91171a2337badb4a84cedd1319` over Capacity V2
   `8a3ef59`; exact two-file SHAs are in PR comment `5289911149`. Reproduce
   the 26 focused and 135 strict x86 chain tests; falsify the reviewed
   capacity chain, 224 immutable 32-cluster bundles, at-most-16-worker/systemd
   boundary, atomic review+admission gate, sealed outcome bundles, receipt-only
   supervisor, and absence of resume/aggregate commands. If clean, append only
   the controller-generated raw implementation marker. PASS may freeze one
   host packet only; it cannot execute the screen or open outcomes.

2. **PR #103 x86 A/B terminal review.** On Performance Cloud independently
   reopen exact design `62e471e4…e075`, immutable evidence root
   `/var/lib/shengji-perf-ab-pr103-v1/evidence`, manifest
   `da82b983…6d72`, result `75dd2381…8b6d` and frozen validator output
   `2fd24acb…f298`. Re-run the frozen validator, authenticate all 12 arms and
   exact normalized semantic/work/RNG/sampler equality, recompute both
   retention statistics, and report the exact retain/drop decision. Codex has
   not read it. Request is posted at PR #103 comment `5289687555`. PASS may
   establish performance retention/merge-readiness only, not strength or
   deployment.

3. **PR #107 performance wave-two code audit — not launch-critical.** Exact
   head `1982c48` is clean/green atop PR #103 and claims a further 7.05% ARM
   microbenchmark improvement from entry-bound policy kernels, a per-world
   sampled-hands cache and native pair counting. It is outside the frozen PR
   #103 A/B and needs an independent code/parity audit plus its own later x86
   design before retention; it must not delay or reinterpret PR #103 results.

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

1. **PR #103 x86 A/B.** The sole batch is terminal success and frozen offline
   validation returned exit 0. Never restart or tune it. Await the exact
   result/manifest review before reading or acting on the retention claim.

2. **Pair checkpoint successor.** Capacity V2 terminal PASS at `482119b`
   confirms 47.88 projected hours <= the reviewed 52h cap. Exact PR #106
   implementation `f1791f5` is published, CI-green and awaiting consolidated
   source review. After its raw implementation PASS, freeze one host-specific
   packet and request one separate packet execution review; do not start the
   screen before that PASS.

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
