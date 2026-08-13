# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through
> `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. Branch-local ledgers are
> never review authority. Raw review markers belong at column one in the
> canonical review ledger and must occur exactly once.
>
> Earlier history is archived in `docs_archive/`. This file is current
> executable truth only; the review ledger remains the evidence authority.

Last reconciled: 2026-08-13 13:06 EDT from canonical main `6a21adc`.

## Live fleet

| host | current work | safe progress and next boundary |
|---|---|---|
| **Mini** | T4 mid/late Teacher whole-round screen, eight workers | All workers are alive and CPU-bound. Treatment is complete; matched null is 500/512 on shard 3 and at least 400/512 on the other seven, so the safe lower bound is 7,396/12,288 = 60.19%; 0/8 terminal. The worker cutoff remains about 20:46:27 EDT. Keep Mini uncontended. On terminal publication, Claude reviews the score-free supervisor final before any aggregation or shard-result access. |
| **Air** | Broad Pair-aware whole-game screen, eight workers | All eight workers are alive and CPU-bound. Five reviewed score-free shard counters are 336/896 and three are 320/896, totaling 2,640/7,168 = 36.83%; 0/8 terminal. The run remains healthy but on a substantive timeout trajectory. Do not intervene or inspect shard outcomes. The reviewed S6 preflight queue remains asleep behind this run. |
| **Strength Cloud** | S4 360B point-banking sequential confirmation, tranche two | Look one completed cleanly. Integrity passed, but the predeclared early-efficacy boundary was not crossed, so the reviewed controller automatically released tranche two. All 16 tranche-two workers are live; the reviewed score-free lower bound is 888/8,192 = 10.84% of tranche two. This is continuation, not a failure or final efficacy verdict. Inspect only reviewed score-free progress; do not open either tranche. The controller has no hard runtime timeout and will publish one terminal result after tranche two. |
| **Performance Cloud** | PR #89 v2r1 spent before evidence; fresh v3 repair awaiting review | Exact design `8721aec4…ec9d` was admitted once under systemd and immediately refused before evidence creation or any arm because harness `fa0f9cf` checked systemd's invocation symlink backwards. The failed unit is preserved at `NRestarts=0`; immutable refusal receipt `bee03db2…b469` records zero arms and v2r1 must never restart. PR #89 head `52e13f2` fixes the unit-name→InvocationID mapping, pins six fresh seeds and a new experiment ID, and passes 84 pure/compiled tests on ARM and x86. It awaits source review; even PASS may freeze only a fresh v3 host design. |
| **Production** | Release 18, `kitty-xray-b5a35ae`, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. |

## Current review and implementation queue

1. **PR #89 systemd-provenance repair.** Review exact head `52e13f2`. The
   v2r1 invocation is spent with zero arms/evidence and may never restart. The
   repair binds systemd's real unit-name→InvocationID symlink, refuses the old
   inverse shape and uses six fresh seeds under a new v3 experiment. PASS may
   freeze only a fresh host-specific design; that design still needs exact PASS.
2. **Pair checkpoint capacity PR #93.** Claude PASSed repaired science/code at
   `0045139`, but the V1 raw marker was introduced by a Jerry-authored commit
   and correctly cannot satisfy the controller's independent-Claude gate.
   Current head `5451aa8` retires V1, requires a fresh Claude-authored and
   Claude-committed V2 marker, and repairs the same backwards systemd
   invocation-link check found by PR #89. Local and strict x86 design-chain
   suites are 103/103, including a live-host unit-name→InvocationID witness.
   V2 PASS may authorize packet freeze only; the packet still needs separate
   review before one capacity run.
3. **S6 scored-DEV controller PR #94.** Exact head `3ee600b` implements the
   reviewed PR #91 design; 88 focused design/scorer/controller tests pass and
   implementation review is pending. PASS may authorize packet freeze only;
   packet review, one-shot admission and later score-free terminal review remain
   separate. No S6 scored run is currently authorized.
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
