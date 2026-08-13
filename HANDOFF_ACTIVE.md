# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through
> `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. Branch-local ledgers are
> never review authority. Raw review markers belong at column one in the
> canonical review ledger and must occur exactly once.
>
> Earlier history is archived in `docs_archive/`. This file is current
> executable truth only; the review ledger remains the evidence authority.

Last reconciled: 2026-08-13 16:45 EDT from canonical main `37374f9`.

## Live fleet

| host | current work | safe progress and next boundary |
|---|---|---|
| **Mini** | T4 mid/late Teacher whole-round screen | Three workers remain CPU-bound and five shards have sealed terminally. Champion checkpoints are (500,500,500,500,500,400,400,200). Heartbeat lower bound: 11,692/12,288 = 95.15%; 5/8 terminal. Worker cutoff remains about 20:46:27 EDT. Keep Mini uncontended. |
| **Air** | Broad Pair-aware whole-game screen, eight workers | All eight workers are alive and CPU-bound. Six shards are 384/896 and two are 368/896: 3,040/7,168 = 42.41%; 0/8 terminal. The timeout trajectory remains substantive. Do not intervene or inspect shard outcomes; the reviewed S6 queue remains asleep behind it. |
| **Strength Cloud** | S4 360B point-banking confirmation, tranche two | All 16 workers are live and CPU-bound. Reviewed score-free lower bound: 2,702/8,192 = 32.98%; 0/16 terminal. Look-one integrity passed but its early-efficacy boundary did not, so tranche two continues automatically; this is not a terminal efficacy verdict. No hard runtime timeout. |
| **Performance Cloud** | Review-gated PR #89 and PR #94; no execution live | PR #89 V4 remains spent after its fail-closed bytecode refusal. V5 source `603f1db` PASSed at canonical `37374f9`; fresh design `3800aecb…aa38`, native builds and closed pre-arm rehearsal are frozen under new paths, with evidence/review/unit still absent pending exact-design review. PR #94 packet `6489d9b8…b9983` still awaits packet review; admission/records/final remain absent. PR #93 remains a reviewed over-cap negative with its admission spent. |
| **Production** | Release 18, `kitty-xray-b5a35ae`, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. |

## Current review and implementation queue

1. **PR #89 V5 bytecode-isolation repair.** V4 design `98af5a3c…ab78` received
   run authority and was consumed once under invocation `b5d046d6…`; the first
   child returned 1 after 17.8 seconds because `-I` ignored
   `PYTHONDONTWRITEBYTECODE`. The closure check prevented raw/result publication.
   Exact V5 head `603f1db` uses `-I -B -P`, fresh disjoint seeds and a new
   namespace; 50 focused and 87 broader tests pass in pure and strict-compiled
   modes, with CI green. Source PASS is canonical at `37374f9`. Fresh host
   design `3800aecb…aa38` and rehearsal manifest `af4129f1…5119f` reopen
   exactly; evidence, review record and unit invocation remain absent. Await
   exact-design `PASS_TO_RUN_THIS_DESIGN_ONLY`. V2r1/V3/V4 never restart.
2. **S6 scored-DEV PR #94.** Claude exact-head PASSed test-only `0dd8f11` at
   canonical `3b4752b`; 12/12 guards are pinned and the full chain passes
   100/100 pure plus 100/100 strict x86. Host packet `6489d9b8…b9983`
   (internal `68c250b4…1552c`) is frozen; execution remains false and every
   admission/output path is absent. A fresh read-only host check independently
   reproduced `verify-packet` and both packet hashes. Await exact packet review
   before one serial 64-state run; no record opening or downstream authority.
3. **Pair capacity successor PR #96.** Draft exact head `c4d2df8` preserves
   the full 7,168-cluster population and 1.5x safety factor, changes only the
   explicit wall budget 48h -> 52h under review, uses a fresh disjoint V2
   capacity population and publishes a closed score-free refusal receipt with
   all 16 lane timings on another over-cap result. Focused design/controller
   suite is 106/106, independently reproduced from the exact clean head.
   Await exact source review; no packet or run authority.
4. **PR #93 capacity HOLD.** Canonical terminal review `27c6860` records the
   real negative capacity result: projection over wall cap, fail-closed after
   complete measurement. Admission is spent; no result/receipt, retry or screen
   authority. Any future checkpoint screen needs a revised design and fresh
   packet chain.
5. **Compatibility PR #75 `90c5630`.** The corrected 64-character ELF receipt
   remains separate compatibility evidence for PR #71 and awaits exact-head
   external review. It grants no strength or deployment authority.
6. **Terminal reviews.** T4, broad Pair and S4 need no live review while their
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
