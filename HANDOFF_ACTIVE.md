# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through
> `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. Branch-local ledgers are
> never review authority. Raw review markers belong at column one in the
> canonical review ledger and must occur exactly once.
>
> Earlier history is archived in `docs_archive/`. This file is current
> executable truth only; the review ledger remains the evidence authority.

Last reconciled: 2026-08-13 14:20 EDT from canonical main `b5e70bc`.

## Live fleet

| host | current work | safe progress and next boundary |
|---|---|---|
| **Mini** | T4 mid/late Teacher whole-round screen, eight workers | All workers are alive and CPU-bound. Treatment is complete. Shard 3 is at champion 200/512; five shards are at matched-null 500/512 and two are at 400/512. The safe sequential lower bound is 8,108/12,288 = 65.98%; 0/8 terminal. The fast champion checkpoint improves the deadline outlook, but the worker cutoff remains about 20:46:27 EDT. Keep Mini uncontended. On terminal publication, Claude reviews the score-free supervisor final before any aggregation or shard-result access. |
| **Air** | Broad Pair-aware whole-game screen, eight workers | All eight workers are alive and CPU-bound. Seven shards are at the reviewed score-free 352/896 checkpoint and shard 7 is at 336/896, totaling 2,800/7,168 = 39.06%; 0/8 terminal. The run remains healthy but on a substantive timeout trajectory. Do not intervene or inspect shard outcomes. The reviewed S6 preflight queue remains asleep behind this run. |
| **Strength Cloud** | S4 360B point-banking sequential confirmation, tranche two | Look one completed cleanly. Integrity passed, but the predeclared early-efficacy boundary was not crossed, so the reviewed controller automatically released tranche two. All 16 tranche-two workers are live; the reviewed score-free lower bound is 1,522/8,192 = 18.58% of tranche two. This is continuation, not a failure or final efficacy verdict. Inspect only reviewed score-free progress; do not open either tranche. The controller has no hard runtime timeout and will publish one terminal result after tranche two. |
| **Performance Cloud** | PR #93 score-free concurrent capacity, 16 workers | Claude PASSed PR #89 V3 design `e0a0386c…f4`, but its sole invocation failed before the first arm while staging the base source archive (`KeyError: repo`). V3 is spent with zero gameplay/timing and immutable refusal SHA `f8152b6c…a92`; never restart it. Claude source-PASSed repaired V4 head `df730d7` at canonical `b5e70bc`, authorizing a fresh V4 design freeze only after the host is free. Meanwhile PR #93 packet PASS `e503235` authorized one score-free capacity attempt; it started at 14:08:29 EDT under invocation `19c906f…`, and all 16 workers are saturated. Admission is consumed; capacity/result receipt remain unpublished. Do not overlap another perf job or restart this unit. |
| **Production** | Release 18, `kitty-xray-b5a35ae`, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. |

## Current review and implementation queue

1. **PR #89 V4 exact host design.** Claude source-PASSed exact V4 head
   `df730d7` at canonical `b5e70bc`. After PR #93 releases the host, build and
   freeze a fresh root-owned V4 design and exercise the complete pre-arm source
   staging path against a separate scratch root. The frozen design still needs
   its own exact PASS before one six-pair batch; V3 never restarts.
2. **Pair checkpoint capacity PR #93 result.** Claude's exact packet PASS landed
   at canonical `e503235`; the one score-free 16-lane capacity execution is now
   running under systemd with all workers live. Wait for atomic publication,
   then independently review the strict capacity result, admission and receipt.
   No restart, scored-screen freeze/run, resume, aggregation, outcome access or
   strength/deploy authority follows from this attempt.
3. **S6 scored-DEV controller PR #94.** Claude HOLDed `a8d5b24` only because
   eight real production guards lacked load-bearing regressions. Test-only head
   `0dd8f11` now pins parent/tip/request ledger provenance, design reviewer
   identity, wall cap, live-runtime binding, unique seeds and sealed records;
   production controller SHA remains `9b75d8f4…a513`, and general CI is green.
   Run the exact focused/compiled battery when PR #93 releases the x86 host,
   then re-request review. No packet freeze or scored run is authorized.
4. **Compatibility PR #75 `90c5630`.** The corrected 64-character ELF receipt
   remains separate compatibility evidence for PR #71 and awaits exact-head
   external review. It grants no strength or deployment authority.
5. **Terminal reviews.** T4, broad Pair and S4 need no live review while their
   reviewed controllers run. Their next review begins only after a terminal
   score-free final exists. No outcome aggregation or sealed result access is
   allowed before its explicit terminal gate.

PR #78's opened-DEV capacity code/result and PR #91's design are reviewed.
PR #90 is an implementation source, not a direct merge candidate. PR #92's
native-follow exploration is outside the frozen PR #89 v2 arm; profile the
accepted measured stack before deciding whether to integrate or benchmark it.
PR #85 remains a reviewed design-only contingency for a future fresh Air run;
it does not authorize retry or extension of the current one-shot.

The reviewed Pair foundation is on `main` in provenance-preserving order:
PR #55 -> #60 -> #61 -> #72 -> #79 -> #84 -> #86. Pair scored-packet
implementation/freeze/run, REPORT access, aggregation, retry, strength,
training, promotion and deployment remain closed.

## Terminal sequences

For T4 or broad Pair:

1. The existing supervisor publishes a terminal score-free final.
2. Claude reviews that final without opening shard outcomes.
3. Only an explicit PASS may admit one aggregation.
4. Claude independently reproduces and terminally reviews the aggregate.
5. A positive screen may justify a fresh confirmation design; it never deploys.

For S4:

1. The reviewed controller completes tranche two without manual intervention.
2. Run its exact pinned read-only verifier only after the controller is terminal.
3. Claude independently reviews the terminal result and verifier evidence.
4. The terminal decision may select a candidate, select none or HOLD; it never
   deploys automatically.

## Standing invariants

- Never inspect live or sealed shard-result files. Process state and explicitly
  reviewed score-free heartbeats are the safe monitoring surface.
- Do not turn an implementation/design PASS into execution authority. Every
  packet, one-shot admission and terminal opening has its own explicit gate.
- Exploration may be reusable; deployment evidence remains sealed, powered,
  independently reviewed and one-shot.
- Same deals, role flips and policy randomness remain shared across treatment,
  matched null and champion where the frozen design requires them.
- Feature telemetry is dose/integrity evidence, not whole-game utility.
- No review implies retry, extension, REPORT reuse, training, production
  promotion or deployment.
