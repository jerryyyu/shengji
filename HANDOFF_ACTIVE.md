# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through
> `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. Branch-local ledgers are
> never review authority. Raw review markers belong at column one in the
> canonical review ledger and must occur exactly once.
>
> Earlier history is archived in `docs_archive/`. This file is current
> executable truth only; the review ledger remains the evidence authority.

Last reconciled: 2026-08-13 18:57 EDT from canonical main `cb35ce5`.

## Live fleet

| host | current work | safe progress and next boundary |
|---|---|---|
| **Mini** | T4 terminal gate | All eight shards completed cleanly before cutoff. Claude's score-free prose review at `aa6d755` PASSed the seal without opening outcomes, but omitted the exact raw marker required by the runtime parser. Aggregate and its admission remain absent pending that one-line correction. |
| **Air** | Broad Pair-aware whole-game screen, eight workers | All eight workers are alive and CPU-bound. Seven shards are 416/896 and one is 400/896: 3,312/7,168 = 46.21%; 0/8 terminal. The timeout trajectory remains substantive. Do not intervene or inspect shard outcomes; the reviewed S6 queue remains asleep behind it. |
| **Strength Cloud** | S4 360B point-banking confirmation, tranche two | All 16 workers are live and CPU-bound. Reviewed score-free lower bound: 4,030/8,192 = 49.19%; 0/16 terminal. Look-one integrity passed but its early-efficacy boundary did not, so tranche two continues automatically; this is not a terminal efficacy verdict. No hard runtime timeout. The exact read-only terminal verifier is pinned at Git `e7551e4`, runner `a6586be…dda`, and controller `cd69a712…bb0a`; run it only after the controller exits. |
| **Performance Cloud** | PR #89 merge-shape cleanup and PR #94 packet review; host idle | Claude terminally VERIFIED the immutable V5 bundle at canonical `e5818ee`: exact semantics, 29.3203% lower wall and 27.8619% one-sided paired lower bound; retain the exact measured arm only. V5 is consumed forever and V6 `cd8eb15` is superseded. Next is a clean production delta/merge review, not another benchmark. PR #94 packet `6489d9b8…b9983` still awaits packet review; admission/records/final remain absent. |
| **Production** | Release 18, `kitty-xray-b5a35ae`, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. |

## Current review and implementation queue

1. **T4 raw-marker correction after score-free PASS.** Exact source `c89c871`; final
   `/private/tmp/shengji-stagec-midlate-whole-game-v1/server/runs/logs/teacher-v3-stage-c-midlate-composition-screen-v1/supervisor-final.json`
   has external SHA `27cc73f8…c60b`, internal `dee58b15…dfed`, shard manifest
   `80e80bee…fc13`, 8/8 exits zero and elapsed 152,069.39953 seconds. The
   frozen `_supervisor_final` validator passes without opening shard bytes.
   Claude independently PASSed the score-free seal at `aa6d755`, but the commit
   contains prose only: canonical `HANDOFF_REVIEW.md` still has zero raw
   supervisor markers. Runtime `_supervisor_review_claim` requires exactly one
   column-one marker before it consumes the aggregate slot, so aggregate and
   admission remain absent. Append the unique raw
   `TEACHER_STAGE_C_MIDLATE_COMPOSITION_SUPERVISOR_FINAL_V1_REVIEW` claim to
   `HANDOFF_REVIEW.md` claim using the already reviewed payload below. Do not
   repeat the review or open shards. That marker authorizes one aggregate only; no confirmation
   launch, strength claim, promotion or deployment.

   Expected canonical claim payload (request-only; deliberately no marker
   prefix):

   `{"all_children_exit_zero":true,"confirmation_launch_authorized":false,"git":"c89c87121fb44ee98ec16753efce0ae5c825eea4","independent_review":true,"one_aggregate_execution_authorized":true,"outcomes_or_statistics_read_by_reviewer":false,"packet_sha256":"713acb78fcd06cf0b7a503a1826b945b912e9fd5b17c9e2c40c605114da6db9c","production_deployment":false,"production_promotion":false,"run_id":"teacher-v3-stage-c-midlate-composition-screen-v1","schema":"teacher-stage-c-midlate-composition-supervisor-final-review-v1","screen_receipt_sha256":"200f5085180377324de36b1e793efd979e7ffffd5e8dcad7c01c87c8399e91ea","shard_manifest_sha256":"80e80bee7d5f7353ace805ac2f1408f04beb911d26e000a16c5b6177a0d1fc13","shards":8,"strength_claim":false,"supervisor_final_internal_sha256":"dee58b152bf731e43ab2eea26d69b72a8d781da4344984a9d764fa7aad61dfed","supervisor_final_sha256":"27cc73f843fc62dab2114087e95d51eb854e237eb5c515992c5377cf7c7c60b0","verdict":"PASS"}`

   Canonical `1a72fec` supersedes the earlier operational disagreement about
   PR #89 V5 and changes no T4 authority; the raw T4 marker is still absent.
2. **PR #89 measured-stack merge preparation.** Claude's canonical
   `1a72fec` adjudication authenticated the unchanged design/review record,
   found the evidence root absent, and authorized only removing write bits
   from 142 hash-exact root-owned inputs plus one start. That batch completed
   once under systemd invocation `7bae1e19…43e0`: result success, exit zero,
   no restart, 194.863 CPU seconds / 194.967 wall seconds / 134.5 MiB peak.
   Immutable bundle `/var/lib/shengji-perf-ab-pr89-v5/evidence` has design
   `3800aecb…aa38`, manifest `fd4208fe…9aae`, result `151801ca…b78f` and
   execution `c638f998…0367`. The copied frozen validator independently
   returned VERIFIED/retain: base 111.464s vs head 78.782s, 29.3203% aggregate
   wall reduction, 27.8619% one-sided paired 95% lower bound, all six pairs
   positive, normalized gameplay/work/RNG/sampler bytes exact. Claude
   independently reopened all 63 artifacts and terminally VERIFIED/retain at
   canonical `e5818ee`. V5 never runs again and V6 `cd8eb15` is superseded.
   Do not merge the experimental PR #89 head directly. Draft PR #98 exact
   `008d75e` now carries a production-only extraction stacked on PR #71: all
   nine runtime/parity files are byte-identical to measured `a91eb271`, the
   harness/recovery surface is absent, and a compact non-authorizing receipt
   plus fail-closed historical compatibility tests are added. Relevant suites
   pass 113/113 pure and 113/113 strict compiled; CI and exact merge review are
   pending. The result grants no deploy or strength authority.
3. **S6 scored-DEV PR #94.** Claude exact-head PASSed test-only `0dd8f11` at
   canonical `3b4752b`; 12/12 guards are pinned and the full chain passes
   100/100 pure plus 100/100 strict x86. Host packet `6489d9b8…b9983`
   (internal `68c250b4…1552c`) is frozen; execution remains false and every
   admission/output path is absent. A fresh read-only host check independently
   reproduced `verify-packet` and both packet hashes. Await exact packet review
   before one serial 64-state run; no record opening or downstream authority.
4. **Pair capacity successor PR #96.** Draft exact head `c4d2df8` preserves
   the full 7,168-cluster population and 1.5x safety factor, changes only the
   explicit wall budget 48h -> 52h under review, uses a fresh disjoint V2
   capacity population and publishes a closed score-free refusal receipt with
   all 16 lane timings on another over-cap result. Focused design/controller
   suite is 106/106, independently reproduced from the exact clean head.
   Await exact source review; no packet or run authority.
5. **PR #93 capacity HOLD.** Canonical terminal review `27c6860` records the
   real negative capacity result: projection over wall cap, fail-closed after
   complete measurement. Admission is spent; no result/receipt, retry or screen
   authority. Any future checkpoint screen needs a revised design and fresh
   packet chain.
6. **Compatibility PR #75 `90c5630`.** The corrected 64-character ELF receipt
   remains separate compatibility evidence for PR #71 and awaits exact-head
   external review. It grants no strength or deployment authority.
7. **Other terminal reviews.** Broad Pair and S4 need no live review while
   their reviewed controllers run. No outcome aggregation or sealed result
   access is allowed before each explicit terminal gate.

Documentation-only PR #97 exact `af971ff` records the same terminal/fleet
truth and awaits accuracy/merge review; it changes no handoff or authority.

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
