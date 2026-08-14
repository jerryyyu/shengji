# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through
> `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. Branch-local ledgers are
> never review authority. Raw review markers belong at column one in the
> canonical review ledger and must occur exactly once.
>
> Earlier history is archived in `docs_archive/`. This file is current
> executable truth only; the review ledger remains the evidence authority.

Last reconciled: 2026-08-13 21:31 EDT from canonical main `eee36c2`.

## Live fleet

| host | current work | safe progress and next boundary |
|---|---|---|
| **Mini** | T4 terminal closeout complete | Canonical terminal review `a165274` independently verified PR #80's recursive reconstruction of aggregate `f30a77c7…e652` and posted the unique result marker: `SELECT_NONE`. T4 has no live worker and no confirmation, retry, strength, promotion or deployment authority. |
| **Air** | Broad Pair-aware whole-game screen, eight workers | All eight workers are alive and CPU-bound. Four shards are 432/896 and four are 448/896: 3,520/7,168 = 49.11%; 0/8 terminal. The timeout trajectory remains substantive. Do not intervene or inspect shard outcomes; the reviewed S6 queue remains asleep behind it. |
| **Strength Cloud** | S4 360B point-banking confirmation, tranche two | All 16 workers are live and CPU-bound. Reviewed score-free progress is 5,318/8,192 = 64.92%; 0/16 terminal. Look-one integrity passed but its early-efficacy boundary did not, so tranche two continues automatically; this is not a terminal efficacy verdict. No hard runtime timeout. The exact read-only terminal verifier is pinned at Git `e7551e4`, runner `a6586be…dda`, and controller `cd69a712…bb0a`; run it only after the controller exits. |
| **Performance Cloud** | S6 V2 packet review; host idle | Claude terminally VERIFIED the immutable PR #89 V5 bundle at canonical `e5818ee`: exact semantics, 29.3203% lower wall and 27.8619% one-sided paired lower bound; retain the exact measured arm only and never rerun V5. PR #94 source head `08ee055` PASSed at `ec4cdd2`; fresh V2 packet `dd7709e…4adca` is frozen and verified. Its packet-review snapshot, admission, records, final and unit installation remain absent pending packet review. |
| **Production** | Release 18, `kitty-xray-b5a35ae`, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. |

## Current review and implementation queue

1. **PR #89 measured-stack merge preparation.** Claude's canonical
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
   pass 113/113 pure and 113/113 strict compiled; CI is green and exact merge
   review is pending. The result grants no deploy or strength authority.

   **Landing/compute sequence:** obtain exact merge review for PR #71 and
   exact-head review for PR #98; if both PASS, preserve commits, merge PR #71
   first and retarget/recheck PR #98. Do not merge experimental PRs #77, #81,
   #83, #89 or #90; #90's reviewed runtime bytes are already inside #98 and
   PR #75 remains separate compatibility evidence. Defer PR #92 because it is
   outside the measured arm. Existing sealed runners keep their exact pinned
   trees; only future worktrees/binaries may be rebuilt after merge and any
   current-source receipt rebind gets separate review. Park further perf
   exploration except lightweight memory-aware-rollout design/profile work.
   Use the freed host for S6 V2 first, then PR #96 capacity, then the reviewed
   feed-anticipation design lane; no step inherits authority from the prior one.
2. **S6 scored-DEV PR #94.** A cross-lane audit found that source-PASSed
   `0dd8f11` authenticated a frozen unit file and basic systemd properties but
   not the loaded fragment/reload state. Preserve but never attest or execute
   V1 packet `6489d9b8…b9983`; its admission/records/final remain absent. Fresh
   exact head `08ee055` uses V2 run/path/schema/marker namespaces and requires
   canonical fragment bytes, no drop-ins, `NeedDaemonReload=no`, exact loaded
   environment, nice, timeout, invocation and cgroup before admission. The
   full chain passes 101/101 pure plus 101/101 strict compiled. Claude's exact
   source PASS is canonical at `ec4cdd2`. On the unchanged idle x86 host, the
   controller froze and independently verified fresh packet
   `dd7709e9…4adca` (internal `1fb61cb7…e589`, runtime profile
   `69906c5a…a775`), bound to host profile `11b5237a…c0260`, frozen unit
   `83b04930…e35f`, native `d2e20db3…910f` and Python `b8d8288f…9700`.
   Implementation snapshot `10808ed6…1466` is exact; packet-review snapshot,
   admission, records, final and installed unit remain absent. Await the exact
   packet marker before one serial 64-state run. After a terminal run, the built-in
   `verify-final` reopens only the score-free final, admission and review
   snapshot; it must pass before terminal review, and no scored record may be
   opened. No downstream authority follows.
3. **Pair capacity successor PR #96.** Draft exact head `8a3ef59` preserves
   the full 7,168-cluster population and 1.5x safety factor, changes only the
   explicit wall budget 48h -> 52h under review, uses a fresh disjoint V2
   capacity population and publishes a closed score-free refusal receipt with
   all 16 lane timings on another over-cap result. It also binds a canonical
   generated systemd fragment into the runtime/packet and refuses fragment,
   drop-in or cgroup drift before admission. A final adversarial repair also
   requires `NeedDaemonReload=no` plus the exact loaded environment, nice level
   and four-hour runtime limit, closing stale cached-unit execution. Suites are
   109/109 pure and 109/109 strict compiled. Await superseding exact-head
   source review; no packet or run authority.
4. **Point-census repair PR #99.** Exact stacked head `0ee28a0` closes PR
   #95's four scientific/provenance blockers: P1 uses the exact legal-action
   denominator in human and rollout states; E2/E3 binds complete RNG/world/
   sampler/work evidence and refuses drift; the private corpus is held behind
   exact manifest SHA `8d6cc27f…aeeb`; and all five stdout-only routes are
   tested. Pure and strict-compiled batteries pass 23/23. The corrected P1
   table retracts the old 70%-vs-23% headline; all 150 E2/E3 pairs bind.
   Await exact-head external review. This is descriptive exploration tooling,
   with no packet, run, strength, training, promotion or deployment authority.
5. **Pair scored-controller design PR #100.** Draft exact head `7a27a52`
   reconstructs the reviewed PR #86 design as a declarative controller
   boundary: exact 1,024-state/16-lane/32-output schedule, work, distinct
   request/attestation namespaces, one-shot admission, score-free progress,
   sealed shards and terminal-review sequence. It has no controller,
   evaluator/gameplay import, writer, launcher, scored-artifact reader or
   aggregate path; every implementation, freeze, run, output, retry, strength
   and deploy authority is false. Focused tests pass 21/21 and the Pair
   capacity chain passes 161/161. Await exact-head design review; a PASS may
   open only a separate controller implementation.
6. **Champion natural-dose design PR #101.** Draft exact head `df93de1`
   closes PR #86's remaining design prerequisite for whole-game/value-for-
   compute interpretation: an exact `mc-s0-report-lcb` self-play census of
   every natural search-reachable pair omission by DEV/CALIB split, attacker/
   defender role and early/mid/late band. It freezes 8,192 fresh deals in 16
   exact 512-deal lanes, proves the complete game/actor seed domain disjoint
   from known Pair populations and requires an RNG-neutral instrumented run to
   remain byte-identical to a reference champion run. Outputs are closed,
   score-free counts/work/sampler/commitments only. Focused tests pass 30/30
   on Python 3.11/3.12/3.14 with byte-identical design SHA `4629ccde…a93c`;
   the full Pair chain passes 205/205. Await exact design review. There is no
   census implementation, packet, writer, launcher or execution authority.
7. **PR #93 capacity HOLD.** Canonical terminal review `27c6860` records the
   real negative capacity result: projection over wall cap, fail-closed after
   complete measurement. Admission is spent; no result/receipt, retry or screen
   authority. Any future checkpoint screen needs a revised design and fresh
   packet chain.
8. **Compatibility PR #75 `90c5630`.** The corrected 64-character ELF receipt
   remains separate compatibility evidence for PR #71 and awaits exact-head
   external review. It grants no strength or deployment authority.
9. **Other terminal reviews.** Broad Pair and S4 need no live review while
   their reviewed controllers run. No outcome aggregation or sealed result
   access is allowed before each explicit terminal gate.

Documentation-only PR #97 exact `f93abbf` records the same terminal/fleet
truth; accuracy/merge review follows. It changes no handoff or authority.

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
