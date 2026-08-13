# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through
> `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. Branch-local ledgers are
> never review authority. Raw review markers belong at column one in the
> canonical review ledger and must occur exactly once.
>
> Earlier history is archived in `docs_archive/`. This file is current
> executable truth only; the review ledger remains the evidence authority.

Last reconciled: 2026-08-13 13:50 EDT from canonical main `8daef0b`.

## Live fleet

| host | current work | safe progress and next boundary |
|---|---|---|
| **Mini** | T4 mid/late Teacher whole-round screen, eight workers | All workers are alive and CPU-bound. Treatment is complete. Shard 3 has completed matched null and reached champion 100/512; shards 1 and 2 are at matched-null 500/512 and the other five are at least 400/512. The safe sequential lower bound is therefore 7,708/12,288 = 62.73%; 0/8 terminal. The fast champion checkpoint improves the deadline outlook, but the worker cutoff remains about 20:46:27 EDT. Keep Mini uncontended. On terminal publication, Claude reviews the score-free supervisor final before any aggregation or shard-result access. |
| **Air** | Broad Pair-aware whole-game screen, eight workers | All eight workers are alive and CPU-bound. Shard 2 has reached the reviewed score-free 352/896 checkpoint and the other seven are at 336/896, totaling 2,704/7,168 = 37.72%; 0/8 terminal. The run remains healthy but on a substantive timeout trajectory. Do not intervene or inspect shard outcomes. The reviewed S6 preflight queue remains asleep behind this run. |
| **Strength Cloud** | S4 360B point-banking sequential confirmation, tranche two | Look one completed cleanly. Integrity passed, but the predeclared early-efficacy boundary was not crossed, so the reviewed controller automatically released tranche two. All 16 tranche-two workers are live; the reviewed score-free lower bound is 1,312/8,192 = 16.02% of tranche two. This is continuation, not a failure or final efficacy verdict. Inspect only reviewed score-free progress; do not open either tranche. The controller has no hard runtime timeout and will publish one terminal result after tranche two. |
| **Performance Cloud** | PR #89 v3 exact host design awaiting review | V2r1 remains spent after its zero-arm fail-closed systemd-provenance refusal and may never restart. Claude source-PASSed repaired head `52e13f2` at canonical `91024a7`. The fresh root-owned v3 design is frozen at SHA `e0a0386c…f4`, binding exact base `093ec33`, optimized arm `a91eb27`, six fresh alternating seeds, immutable x86/runtime inputs and the dual ≥3%/positive-LCB gate. It reopens VALID; the evidence root and unit remain absent. Exact-design review is pending and no benchmark may start before its SHA-bound PASS. |
| **Production** | Release 18, `kitty-xray-b5a35ae`, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. |

## Current review and implementation queue

1. **PR #89 exact v3 design.** Claude source-PASSed repaired head `52e13f2`.
   Review frozen host design SHA `e0a0386c…f4`; its unit/evidence remain absent
   and V2r1 remains spent. Exact PASS may authorize one six-pair performance
   batch only, with no retry, merge, strength or deployment authority.
2. **Pair checkpoint capacity PR #93 packet.** Claude's exact V2 implementation
   marker landed at canonical `8daef0b`. The independently verified score-free
   capacity packet is frozen at external SHA `3a282f51…aa3`, internal SHA
   `0748bb8e…ad99` and runtime-profile SHA `287dde15…2649`; all execution slots
   and the unit remain absent. Review these exact packet bytes. PASS may
   authorize one 16-lane score-free capacity run only; the scored screen,
   resume, aggregation and every strength/deploy path remain closed.
3. **S6 scored-DEV controller PR #94.** Current head `a8d5b24` implements the
   reviewed PR #91 design and repairs the same backwards systemd invocation
   check before packet freeze. Its local controller suite is 29/29 and the
   fresh strict x86 design/scorer/controller suite is 91/91, including a
   live-host unit-name→InvocationID witness. Implementation review is pending.
   PASS may authorize packet freeze only; packet review, one-shot admission and
   later score-free terminal review remain separate. No S6 scored run is
   currently authorized.
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
