# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through
> `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. Branch-local ledgers
> are never review authority. Raw review markers belong at column 1 in the
> canonical review ledger and must occur exactly once.
>
> Full history is preserved in
> `docs_archive/handoff-active-through-2026-08-11-10-22.md` and
> `docs_archive/handoff-review-2026-08-08-through-2026-08-11-10-22.md`.

Last reconciled: 2026-08-13 00:53 EDT.

## CURRENT LAUNCH BLOCKER — read before the older lane detail below

The lower lane table is the last merged snapshot and is being replaced by docs
PR #64. Current executable truth is:

- **S5 x86 portability PR #74 is scientifically reviewed but operationally
  HOLD.** Claude's 00:18 PASS validates the x86 construction and explicitly
  says `retry_authorized:false`. Before that PASS existed, the defective
  request/attestation gate had already consumed the one-shot admission and
  started a partial attempt. No result exists, but the old authority is spent.
  Do not run, retry or reuse its queue/admission. A distinct-attestation repair
  is being implemented; any recovery also needs a new namespace and explicit
  retry authorization.
- **PR #71 repair `093ec33` PASSed narrowly.** Claude reproduced 14/14 strict
  and pure RLCB tests and lifted the old HOLD. Stacked PR #75 `ee6dc48` is now
  the performance review priority: it records behavior compatibility without
  rewriting historical evidence. Neither request grants deploy/experiment
  authority; #71 remains unmerged until #75 resolves.
- **Other pending reviews:** Pair ballot capacity PR #72 `373de84` now has a
  source-derived corrected marker request at main `97547af`; PR #75
  `ee6dc48` awaits its compatibility review; docs PR #64 `b55fe5d` awaits
  prose-only review; conditional Pair-cap PR #73 `8c436ab` remains behind
  #72.
- **S5 repair PR #76 `e285f47` awaits validation-only review under the
  superseding main request `9e73694`.** Do not review the stale `6e4377d`
  request. The final head passes 21/21 on both ARM and clean x86. It permanently
  disables the spent PR #74 run path and requires a distinct pinned reviewer
  attestation. It creates no retry or recovery namespace and authorizes no run.
- **Live compute:** T4 is healthy on Mini at 4,896/12,288 counter-only
  arm-rounds (39.8%); broad Pair is healthy on Air; S6's reviewed score-free
  queue sleeps behind it; S4 is healthy on strength Cloud at 2,835/8,192
  look-one clusters (34.6%). Outcomes remain sealed.
- **Performance Cloud:** bounded performance measurement and current-parent
  compatibility replay are safe uses. Do not give it to S5 under PR #74; the
  old admission is spent and no recovery execution is authorized. Never
  substitute optimized code into frozen strength evidence.
- **Prepared-world performance seam:** an exact-head independent audit passed
  semantics across every MC mode. Six fresh x86 round pairs measured 2.62%
  lower wall time (2.69% greater throughput; one-sided lower bound 1.51%) with
  identical transcripts and work counters. The older quoted 3.37% pooled
  figure mixed two revisions and is retired. Three extra call-count
  regressions are being added before publication.

Nothing below this section supersedes these exact priorities or authorities.

### ⛔ 00:16 incident HOLD — do not run or retry PR #74

Codex's durable x86 queue incorrectly treated the column-one marker **template
inside its own 00:02 review request** as Claude's external PASS. The PR #74
wrapper likewise authenticated prefix + payload but not reviewer provenance.
It consumed the one-shot admission and began the exact S5 producer before any
Claude review existed. Exact systemd telemetry shows 41.722 seconds of wall
time and 41.333 seconds of CPU for the whole scope, with at most about 36.4
seconds after admission. Codex terminated the exact process tree. No result,
partial output, temporary result or terminal log was published; no process
remains. The consumed admission at
`human-v8-s5-final-champion-replay-x86-v1.execution.consumed.json` is preserved
and will not be deleted or overwritten.

The launch queue also checked the wrong admission filename; the wrapper's
`O_EXCL` lock still prevented silent reuse, but the queue's status/re-entry
guard was false. Never reuse that queue.

**Review state:** Claude's later PR #74 PASS is a valid portability review, but
its marker explicitly says `retry_authorized:false`; it cannot revive the
already consumed authority. Codex is preparing a marker-provenance repair plus
incident evidence. Any retry requires a new, explicit external review that
acknowledges the spent partial attempt and authorizes a fresh admission/path;
the old one-shot authority cannot be reused.

## Immediate objective

Carry the admitted T4 mid/late hybrid through a reviewed whole-game verdict.
While the compute hosts run reviewed work, prepare the next reviewed step without bypassing its
gates: the fresh S4 point-banking confirmation, S6 shuai-pai sourcing, and
bury/lead exploration. Pair-aware rollouts already own Air.

## Current truth

| lane | plain-English progress | exact next gate |
|---|---|---|
| **T4 mid/late Teacher hybrid** | The model may propose one move after trick five; fresh Monte Carlo search still prices it and preserves the live champion as fallback. Its 256-state test passed both controls. The sole 2,048-cluster whole-round screen started on Mini at 23:20 EDT; at 10:32 all eight workers remained CPU-bound after 11h12m and every shard's reviewed score-free heartbeat had reached `treatment 200/512`. Outcomes remain sealed. | Monitor only. After all workers finish, Claude reviews the score-free `supervisor-final.json`; only a PASS permits aggregation and outcome access. The aggregate then needs terminal external review. |
| **S4 point banking** | The one reviewed Cloud preflight finished 4/4 score-free. All integrity/dose checks passed, but the old eight-shard profile projects 869.30 fleet-hours / 108.66 hours per shard and correctly HOLDs its 768/96 caps. PR #56 `9f9d80b` preserves artifact `70a15405…413e`, makes coherent HOLD reviewable, prevents packet freeze and bounds ARM/x86 display roundoff. PR #59 `f0c2a6d` keeps 8,192/16,384 clusters and automatic stopping but uses all 16 cores, fresh 300B seeds and a 1,024/64-hour envelope; 50 tests and rendered digest `ea00b1ad…ad9` match on ARM/x86. | Claude reviews the exact capacity HOLD and then the C2 design. A design PASS permits implementation only. Freeze/review a new 16-shard packet afterward; scored execution still needs separate authority. Never retry the spent preflight. |
| **S6 shuai-pai sourcing** | Selector review passed. The actor-visible selector realized `+0.307` levels versus its incumbent (LCB `+0.175`) on reused DEV; a separate literal-champion census found 13 triggers in 512 rounds (`2.54%`). Source `a48542d` closes the unit-map, singleton-freeze and factual-native-runtime HOLDs. Its exact v2 packet `19f3b2a3…79dd0` and receipt are preserved at PR #50 `936345b`; 62 S6 tests pass. | Claude reviews the v2 packet requested at 07:36. A PASS authorizes one four-cluster **score-free** Air capacity preflight only. Air is currently occupied, so do not run it yet. |
| **Pair-aware rollout** | V3 capacity passed externally after changing 6/8 mirrored roots. The reviewed 7,168-cluster packet (`4ece02b9…ae47`) was admitted once and launched on Air at about 07:24. At 10:32 its detached supervisor and all eight workers remained healthy and CPU-bound after 3h08m; its score-free heartbeat still reported 0/8 terminal shards. | Monitor process state and score-free supervisor heartbeat only; never inspect shard outcomes. After completion Claude reviews `supervisor-final.json`, then and only then may aggregation be admitted. |
| **Pair ballot retention** | Claude passed the content boundary and Codex verified the exact million-round artifact (`557df627…61f3`). Current ballots omit a legal pair on 15,187/18,618,281 leads (`0.0816%`): 14,826 early, 352 mid and 9 late. PR #55 `24b421d` preserves the artifact and regression. This is a real availability gap but much too diluted for an immediate uniform whole-game test. | Freeze a fresh disjoint, score-free capture of affected states, weighted toward the dominant early band while retaining named mid/late witnesses. Then run retention versus current at identical ballot width and search work. No strength or deployment authority follows from prevalence. |
| **Bury hand-shape exploration** | Claude passed PR #51's composition at old head `59cc2c6`; current `a1d107b` still needs its two-change delta review. PR #52 `fd7b434` pins the opened 32+32 population and resumable state journal. Stacked draft PR #54 `959cdbd` now makes later shuai-pai explicit without recursive MC: `all_boss` requires every component to be publicly boss and no public ruff warning, while the engine still prices hidden ruffs; `boss_near` is an aggressive DEV sensitivity. Baseline remains literal `HeuristicBot`; manifest and output bind mode and dose. Fifty-nine focused/parent tests pass in strict compiled mode; no census, real rollout, job or policy ran. | Review #51, then #52, then the bounded actor-information/action semantics of #54. Afterward run the source-only census and one-state/one-world capacity when a host frees. These are reusable diagnostics, not strength authority. |

## Review queue — precise asks

1. **S4 Cloud capacity HOLD / PR #56:** review exact preflight
   `70a15405…413e` and current repair head `9f9d80b` under the 10:55 canonical
   request. Confirm only the two capacity caps failed, HOLD cannot freeze a
   packet, and the ARM/x86 tolerance is restricted to named derived fields.
2. **S4 C2 design / PR #59:** after the HOLD review, inspect exact `f0c2a6d`.
   Confirm unchanged 8,192/16,384 evidence and alpha, 16-way geometry, fresh
   300B population, measured 1,024/64 envelope and all-false run authority.
3. **Selective S6 v2 packet / PR #50:** review exact source `a48542d`, artifact
   commit `936345b`, packet `19f3b2a3…79dd0` and singleton receipt
   `df54dcfe…aebba` under the 07:36 canonical request. The old v1 request is
   explicitly superseded. A PASS permits one score-free four-cluster preflight.
4. **Narrow PR #51 delta:** inspect exact current head `a1d107b` versus passed
   parent `59cc2c6`. Confirm only the pre-rollout hidden-kitty refusal and JSON
   `null` one-world SE changed, both tests are real, and no authority changed.
5. **Nonblocking PR #52 follow-up:** after higher-priority S4/S6 reviews and
   the #51 delta, inspect exact head `fd7b434` for pinned reconstruction,
   outcome-blind 32+32 selection, per-state resume, and refusal on changed
   manifests or corrupt records. Both asks are prose-only; no run or strength
   marker is requested.
6. **Nonblocking PR #54 follow-up:** after #52, inspect exact head `959cdbd`.
   Confirm later-lead selection is actor-visible, the ruff-warning signal is
   only public evidence, the `all_boss`/`boss_near` distinction is literal,
   and hidden ruffs remain priced by the determinized engine. Baseline stays
   unchanged, recursive MC is impossible, and journal mode/dose cannot mix.
   This is prose-only and grants no run, policy or strength authority.

The spent S4 controller PASS grants no further launch. The terminal capacity
HOLD and C2 design are separate reviews; neither authorizes scored work.

Pair has no current review blocker because its one authorized screen is
running. T4's next review starts only after its supervisor publishes a terminal
score-free final.

## Fleet and launch order

| host | current use | next authorized use |
|---|---|---|
| **Mini** | T4 eight-shard whole-round screen; projected maximum about 45.4 wall hours. | Keep isolated until T4 terminal seal; Cloud is now the canonical S4 target. |
| **Air** | Pair-aware 7,168-cluster whole-game screen, eight workers under detached supervisor PID 88455. | Keep isolated until the pair supervisor terminal seal and review. S4/S6 preflights remain queued, not competing with the live run. |
| **Cloud** | Idle by gate after the one reviewed S4 preflight completed 4/4 and HOLDed the old eight-shard envelope. Pair census is reviewed and preserved. | Review capacity HOLD and C2 design; then implement/freeze/review the 16-shard packet. No scored S4 work runs without its later execution gate. |
| **Production** | Release 18 image `kitty-xray-b5a35ae`, `mc-s0-report-lcb`; only PR #11 kitty X-ray differs from release 17. | Runtime rollback is release 17 / `latency-cd6789e`; no further deploy, restart, room wipe or policy mutation without explicit user approval. |

Do not inspect T4 or pair `shard-*.json`. Process state, CPU, tmux and only
explicitly reviewed score-free heartbeats are safe. The old pair census log
was never needed and remains unopened. Do not
launch S4/S6/pair scored work from
an implementation review; each requires its later packet/execution review.

## T4 terminal sequence

1. Eight Mini shards finish under the existing supervisor.
2. Claude reviews the score-free supervisor final; no outcome file is opened.
3. If and only if that review passes, Codex admits one aggregation.
4. Claude independently reproduces and terminally reviews the aggregate.
5. A positive screen may authorize confirmation **design**; it never deploys.
   A failed screen closes this exact composition while preserving the learned
   mid/late capability result as diagnostic evidence.

## Standing invariants

- Exploration may be fast and reusable; deployment evidence remains sealed,
  powered, independently reviewed and one-shot.
- Never pool old S4 outcomes post hoc. The new design uses only fresh future
  populations and an automatic predeclared transition.
- Same deals, role flips and policy RNG are shared across treatment, matched
  null and champion. Null must be behavior-identical to champion.
- Feature telemetry is dose/integrity evidence, never a substitute for
  whole-game utility.
- No retry, extension, tuning on REPORT, production promotion or deployment
  is implied by a screen or controller PASS.
