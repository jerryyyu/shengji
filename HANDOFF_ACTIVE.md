# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through
> `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. Branch-local ledgers are
> never review authority. Raw review markers belong at column one in the
> canonical review ledger and must occur exactly once.
>
> Earlier history is archived in `docs_archive/`. This file is current
> executable truth only; the review ledger remains the evidence authority.

Last reconciled: 2026-08-13 12:00 EDT from canonical main `f9989cc`.

## Live fleet

| host | current work | safe progress and next boundary |
|---|---|---|
| **Mini** | T4 mid/late Teacher whole-round screen, eight workers | All workers are alive and CPU-bound. Treatment is complete and all eight matched-null shards have reached 400/512, so the safe lower bound is 7,296/12,288 = 59.38%; 0/8 terminal. The worker cutoff remains about 20:46:27 EDT. Keep Mini uncontended. On terminal publication, Claude reviews the score-free supervisor final before any aggregation or shard-result access. |
| **Air** | Broad Pair-aware whole-game screen, eight workers | All eight workers are alive and CPU-bound. Reviewed score-free shard counters are `[304,304,320,304,304,304,304,304]/896`, totaling 2,448/7,168 = 34.15%; 0/8 terminal. The run remains healthy but on a substantive timeout trajectory. Do not intervene or inspect shard outcomes. The reviewed S6 preflight queue remains asleep behind this run. |
| **Strength Cloud** | S4 360B point-banking sequential confirmation, tranche two | Look one completed cleanly. Integrity passed, but the predeclared early-efficacy boundary was not crossed, so the reviewed controller automatically released tranche two. All 16 tranche-two workers are live. This is continuation, not a failure or final efficacy verdict. Inspect only reviewed score-free progress; do not open either tranche. The controller has no hard runtime timeout and will publish one terminal result after tranche two. |
| **Performance Cloud** | corrected PR #89 v2r1 design frozen; no live worker | Claude PASSed exact source/tooling head `fa0f9cf` and the original host design `b696426c…82d8`. A final admission probe then proved that design could not run because its evidence parent `/var/tmp` is mode 1777; it was retired before unit install, evidence creation or any arm. Corrected design `/var/tmp/report-lcb-perf-ab-pr89-v2r1.design.json` has SHA `8721aec4…ec9d`, moves the absent evidence root beneath root-owned mode-0755 `/var/lib/shengji-perf-ab-pr89-v2r1`, and awaits a replacement `PASS_TO_RUN_THIS_DESIGN_ONLY`. All six seeds remain unused. |
| **Production** | Release 18, `kitty-xray-b5a35ae`, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. |

## Current review and implementation queue

1. **PR #89 corrected performance design.** Review exact frozen design SHA
   `8721aec4765bd7965eb0c47addaf46629e1cc6aead2402c1e50cbceaaf84ec9d`.
   The delta from the previously reviewed but unrunnable design is only the
   root-owned evidence location and matching unit path/hash. A new
   `PASS_TO_RUN_THIS_DESIGN_ONLY` may authorize exactly one six-pair N=30/R=300
   batch, with no retry/tuning. The old `b696426c…82d8` design must never run.
2. **Pair checkpoint capacity PR #93.** Claude HOLDed `2eb55d0` only because
   four sole-defense tests were missing. Exact repair head `0045139` adds those
   four tests; production controller bytes are unchanged, focused count is 100,
   and exact-head delta re-review is pending. PASS may authorize only a
   host-specific capacity-packet freeze; the packet still needs a separate PASS.
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
