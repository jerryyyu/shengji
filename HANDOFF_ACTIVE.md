# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through `HANDOFF_ACTIVE.md` and
> `HANDOFF_REVIEW.md` on canonical `main`. Branch-local ledgers are never
> review authority. Raw review markers belong at column one in the canonical
> review ledger and must occur exactly once.
>
> This file is current executable truth only. Historical detail belongs in
> `docs_archive/`; `HANDOFF_REVIEW.md` remains the evidence authority.

Review queue and fleet reconciled: 2026-08-15 00:11 EDT from canonical main
`483ed02`. No sealed outcome bytes were opened during reconciliation.

## Live fleet

| host | current work | safe state and next boundary |
|---|---|---|
| **Mini** | idle | No BELIEF corpus, training, test opening or scored job is running. T4 is terminally reviewed `SELECT_NONE`; the PR #103 10,000,000-round differential soak also completed 8/8 PASS without opening sealed evidence. |
| **Air** | idle after terminal timeout | Broad Pair source `cd206707` ended at 23:29 EDT with `REFUSED: pair screen supervisor timeout`, 0/8 terminal shards and no complete score-free final. Canonical review ledger `483ed02` records the fail-closed terminal. The sleeping selective-S6 queue exited 72/HOLD and did not launch. No process remains. |
| **Strength Cloud** | powered off / unreachable | S4 is independently terminal `SELECT_NONE`. The user powered the host off without deleting it; SSH is unreachable. Do not infer a live job or power it on without an approved packet. |
| **Performance Cloud** | powered off / recovery HOLD | A reviewed fresh Pair checkpoint packet had started once under invocation `ac5425e0e106403e9a82a7bd8cb5b221`, but the host is now powered off/unreachable with no reviewed terminal preceding shutdown. Conservatively treat that one-shot admission as interrupted/spent. Do not restart, resume, open outcomes or aggregate; a future power-on permits read-only score-free recovery audit only. |
| **Production** | release 18, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. Running sealed jobs remain on their exact pinned trees; merged optimizations never alter them in place. |

## Review queue — precise asks

1. **PR #113 BELIEF-V1 B2 exact-head adversarial re-review — no run authority.**
   Review exact rebased head `cf188e9a5ddab251e8890651a6d8918b8fe596a9`
   on canonical base `483ed02`; its final repair commit parent is `ac697929`.
   The full PR is the one-shot offline B2 capture/reference/training/evaluation
   implementation. Re-audit the prior 23-agent HOLD repairs, especially the
   unbiased finite-reference Brier correction in C1/N2/U1, actor-only failed-
   throw surface, physical actor/target binding, exact training continuity,
   authenticated remote review, durable outside-root consumption tombstone,
   pyc/import/runtime closure, independently witnessed terminal rehash and
   parallel wall-span guards, C2 descriptive-only routing, marginal-only C3,
   explicit C4 shim, and U1=C1 alias.

   The superseding delta must leave production `memory.py` byte-identical to
   main SHA `905873b3…40cf51` while representing each still-unplayed banker-
   declared copy as eligible only for banker hand or hidden kitty. Verify that
   exact disjunction through actor schema v3, strict reopen, input bounds,
   projection, marginal validation and every complete REF-C world; prove an
   expectation/size-conserving move to an unrelated hand is refused. Bind the
   sound adapter itself into REF-C source identity. Reproduce 180/180 BELIEF
   and 139/139 broader engine/server tests in pure and strict compiled modes;
   golden `mc-13` must stay exact. PASS means source merge-readiness only and
   must explicitly leave corpus generation, training, test opening, cloud,
   gameplay, online sampling, strength and deployment authority false.

2. **PR #107 performance wave-two repaired-head re-review — not launch-critical.**
   Exact current head `a064ac4108c748de1954de94646b63e17d72a017` is green and
   mergeable. Reproduce the stale-cache in-place mutation witness, one lazy
   preparation per accepted world, fresh candidate copies, direct-call and
   stub seams, and exact 33-card native admission with sentinel-proven fallback
   at 34/64/128/129 cards. The prior 7.05% ARM timing remains exploratory;
   code PASS only permits a separately frozen x86 A/B design.

This block is the canonical hourly-review input. Posting, closing or changing
any review request requires updating this block in the same operational pass;
PR comments alone are not queue state.

## Execution and terminal queue

1. **BELIEF-V1 B2 pre-execution boundary.** No population has been spent and
   no execution is authorized while PR #113 awaits exact-head source PASS.
   After PASS, merge the reviewed bytes, create a clean detached Mini checkout
   at the resulting canonical `main`, and run only `freeze-design` under the
   required Python `-P -B` flags with a durable absolute evidence-root/design
   sibling pair. Freezing records Git/source/native/Python/numerical/boot and
   evidence-root identity; it does not initialize or open data. Obtain one
   exact frozen-design marker review. That single marker then authorizes the
   bounded opened-development sequence—initialize once, 16 capture lanes, 16
   REF-C lanes, candidate and label-control cohorts, one test opening, terminal
   verify—without per-stage reviews. Any initialization consumes the sibling
   tombstone. Terminal evidence still requires one reproducibility review and
   grants no B3, online gameplay, strength, promotion or deployment authority.

2. **Pair checkpoint successor recovery HOLD.** Capacity and packet review
   remain authentic, but the one-shot Performance Cloud invocation is no
   longer reachable after host shutdown and has no reviewed terminal. Treat
   it as interrupted/spent. On any future power-on, inspect only service state,
   score-free heartbeats and terminal file population; do not resume, retry,
   open result bytes or aggregate without a fresh reviewed recovery design.

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
  decision. Strength Cloud is powered off.

5. **Air Pair terminal timeout.** Canonical ledger `483ed02` verifies the fixed
   64.08h timeout, 0/8 terminal shards, no complete score-free final and no
   published evidence. The S6 queue correctly held rather than interpreting
   timeout as release. Preserve this terminal HOLD; no aggregation or retry.

## Landed and closed anchors

- **T4:** terminal `SELECT_NONE`; no retry or continuation.
- **S4:** exact two-look controller completed; canonical independent review
  `15e8dbb` reproduced terminal `SELECT_NONE` at final SHA `0aef1ca8…e90`.
  The lane is closed with no retry or candidate action.
- **Docs:** PR #97 exact reviewed head `316d6b7` merged at `8bc2da1`. The
  campaign closeout and post-null roadmap PR #109 exact `8fa96de` PASSed at
  canonical `499de77` and merged at `09b80bb`. BELIEF-V1 spec/roadmap PR #110
  exact `b8c2a4c` PASSed at `de26d60` and merged at `fb246a2`; it grants no
  corpus, training, run, strength or deployment authority. Typed actor/target
  boundary PR #111 exact `7ebfcf7` PASSed at `e8ba1a0` and merged at
  `9f0647e`; its in-memory rows likewise grant no capture or training run.
  Offline ownership design/schema PR #112 exact `a9de2b8` PASSed and merged at
  `b316470`; PR #113 is its still-unapproved execution implementation and no
  BELIEF population has been spent.
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
- **Point context/flow:** PR #105 exact `c454aaa` passed the final independent
  guard-witness check and merged at `e875362`. It provides immutable
  PointContext and structural point-flow primitives but has zero production
  consumer and grants no run, training, strength or deployment authority. PR
  #99 exact `0ee28a0` passed descriptive-tooling review and withdraws the old
  unlike-denominator headline.
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
