# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through
> `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. Branch-local ledgers are
> never review authority. Raw review markers belong at column one in the
> canonical review ledger and must occur exactly once.
>
> Earlier history is archived in `docs_archive/`. This file is current
> executable truth only; the review ledger remains the evidence authority.

Last reconciled: 2026-08-13 11:29 EDT from canonical main `586c390`.

## Live fleet

| host | current work | safe progress and next boundary |
|---|---|---|
| **Mini** | T4 mid/late Teacher whole-round screen, eight workers | All workers are alive and CPU-bound. Treatment is complete and all eight matched-null shards have reached 400/512, so the safe lower bound is 7,296/12,288 = 59.38%; 0/8 terminal. The worker cutoff remains about 20:46:27 EDT. Keep Mini uncontended. On terminal publication, Claude reviews the score-free supervisor final before any aggregation or shard-result access. |
| **Air** | Broad Pair-aware whole-game screen, eight workers | All eight workers are alive and CPU-bound. Reviewed score-free shard counters are `[304,304,320,304,304,304,304,304]/896`, totaling 2,448/7,168 = 34.15%; 0/8 terminal. The run remains healthy but on a substantive timeout trajectory. Do not intervene or inspect shard outcomes. The reviewed S6 preflight queue remains asleep behind this run. |
| **Strength Cloud** | S4 360B point-banking sequential confirmation, tranche two | Look one completed cleanly. Integrity passed, but the predeclared early-efficacy boundary was not crossed, so the reviewed controller automatically released tranche two. All 16 tranche-two workers are live. This is continuation, not a failure or final efficacy verdict. Inspect only reviewed score-free progress; do not open either tranche. The controller has no hard runtime timeout and will publish one terminal result after tranche two. |
| **Performance Cloud** | PR #89 v2 design frozen; no live worker | Exact PR #89 head `fa0f9cf` PASSed at canonical `586c390`. Frozen design `/var/tmp/report-lcb-perf-ab-pr89-v2.design.json` has SHA `b696426c…82d8`; evidence root is absent and the unit is not installed. Await the second exact-design `PASS_TO_RUN_THIS_DESIGN_ONLY` before the one-shot six-pair A/B. |
| **Production** | Release 18, `kitty-xray-b5a35ae`, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. |

## Current review and implementation queue

1. **PR #89 frozen performance design.** Claude PASSed exact source/tooling head
   `fa0f9cf`; PR #90's accepted implementation commits are integrated into the
   measured arm `a91eb271` rather than merged wholesale. Review frozen design
   SHA `b696426c7dc6af5ea9cc28302dc0353581ccc6f3056116a21c30aa6fb2b782d8`.
   A second `PASS_TO_RUN_THIS_DESIGN_ONLY` may authorize exactly one six-pair
   N=30/R=300 batch, with no retry/tuning. It grants no merge, strength or
   deployment authority.
2. **Pair checkpoint capacity PR #93.** Review exact head
   `2eb55d0dfb5bcf21e0c1a935848c16d10f09d2fa`. PASS may authorize only a
   host-specific capacity-packet freeze. The packet needs a separate PASS before
   one capacity attempt. The current Air screen remains untouched and
   non-resumable.
3. **S6 scored-DEV controller.** PR #91 design `d31995d` PASSed design-only at
   canonical `dbed4ae`. Finish and publish the controller/scorer child, then
   request exact-head implementation review. Even a code PASS may only open a
   packet freeze; packet review, one-shot admission and later score-free
   terminal review remain separate. No S6 scored run is currently authorized.
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
