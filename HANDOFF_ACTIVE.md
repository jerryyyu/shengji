# Active Claude/Codex handoff

Last update: 2026-08-06 16:14 EDT. Historical discussion and superseded gates
are in `HANDOFF_REVIEW.md`; this file contains only executable current work.

## Status

- Production remains compiled `mc-strong` (N=30). No S0 policy is deployed.
- Sampler package H is **ACCEPTED / CLOSED** at `aea3774`; the strict v3
  certificate hash is
  `e31e67f9aeb4739aa598faa66051ec4004fd47751b297457242dc95a30cc224c`.
- The DEV-512 ballot screen is **SELECT NONE / CLOSED**. CALIB-512 and REPORT
  remain sealed and unscored; do not revive that lane by adding DEV arms.
- The S0 implementation/code gate is complete. S0a is **COMPLETE / ACCEPTED**
  on authoritative Mini: 8/8 clean shards and 2,048 clusters selected
  `mc-s0-report-lcb` (`+0.353 +/- 0.069` versus current and direct
  `+0.293 +/- 0.066` versus equal-work uniform; null `+0.008 +/- 0.070`).
  Registered aggregate SHA-256:
  `0fcd53d4f782a705bfef9ea8ec6155c49db45d76ec71ce25891a9f864413de49`.
  S0b-LCB launched 8/8 exact parent-bound Mini shards at 06:58 EDT. For S0,
  Air remains duplicate fallback only; never pool its records or launch an S0
  child from Air.
  At 16:10 all eight workers were live near full CPU with eight partial
  manifests, no final or FAILED marker, and matching clean frozen
  compiled+strict provenance. The registered singleton supervisor and
  keepawake service are also live. Adaptive, report-uniform, random and equal-
  work-uniform arms are complete; all shards were 200–300/512 through the null
  arm, with current-reference still remaining. This is score-free progress;
  do not inspect partial effects.
- Teacher-v1 mechanics/gold gates, the V11 protected-anchor lane
  and the role-conditioned RL microgates remain independent parallel strength
  work; none should be folded into S0 before each wins alone. The frozen V11
  direct-current block completed 8/8 and was aggregated exactly once. As run it
  **FAILED**: v11-current was `-0.132 +/- 0.070` paired level utility per seed,
  v11-null was `-0.159 +/- 0.069`, and the true null was sane at
  `+0.027 +/- 0.068`; `anchor_test_authorized=false`. Aggregate SHA-256 is
  `112f2c756235d69ac60efbd0f263ef096d311145d0151931ce2a2b8b0099eaec`.
  That cleanly rejects the exact `e66b90b` implementation, but not the learned
  hypothesis: it used the now-proved drifted banker encoder described below.
  Air was immediately repointed to minimal clean commit `0183cdd`. Its exact
  teacher entry attempt is now **REFUSED / CLOSED BEFORE DIAGNOSTICS**: all
  eight captures finished, then validation compared the in-memory ballot's
  tuple config to the semantically identical JSON list config and falsely
  reported actor drift. No diagnostic, state-set, receipt, label or gate was
  launched. Preserve that namespace and its refusal; do not resume, overwrite
  or reuse it. A fresh versioned 143M packet must canonicalize JSON identity,
  reject every experimental flag, pin Python 3.14.6 and use disjoint seeds.
- **Encoder incident closed at code level, follow-up evidence required.**
  `encode_obs` inherited `Memory(..., own_kitty=True)` after the Memory default
  changed while `ENC_VERSION` stayed 1. Banker inference therefore received a
  private-kitty-dependent unseen plane that historical v11 training never saw.
  Commit `66aad44` restores explicit `own_kitty=False` for version 1, names the
  public/no-private-kitty schema, binds encode+Memory source hashes, and adds a
  real counterfactual banker test. Any post-default encoded asset must prove its
  producer semantics before use. The protected-anchor lane may not mix the old
  drifted direct block with corrected-encoder inference; a fresh versioned
  direct block on disjoint seeds is now the prerequisite. Full byte replay
  proves `rl_data/highn_enc` contaminated: all 5,923 banker rows match only
  drifted semantics, while 14,922 nonbanker rows are invariant. The same audit
  found 509/551/551 private-only banker rows in `human_v4/v5/v6`; their other
  rows are nonbanker-invariant. Quarantine those four derived assets and rebuild
  from retained raw JSONL. `gen_v4_all`, v11pair's actual training corpus, is
  definitively clean (503,354 public-v1 banker rows and zero private-only).
  `ckpt_v13abs.pt` is incompatible because it trained from contaminated
  `highn_enc`; regeneration alone cannot rehabilitate that checkpoint.
- Corrected V11 v2 is **RUNNING 8/8 ON AIR** from exact clean commit
  `cde0fecf4151685e7174be8a7aa64b0ee6478edd`. At 15:25 eight detached shards
  launched over fresh seeds 142,000,000–142,002,047; immediate verification
  found eight workers, eight record partials, eight manifest partials and zero
  final/FAILED artifact. Do not inspect partial scores or combine it with v1.
- Teacher 143M-v2 entry is **CODE GATE CLOSED / WAITS FOR AIR** at `2038b31`.
  It JSON-canonicalizes actor identity, pins Python 3.14.6, refuses all four
  posterior-changing flags by key presence, requires exact 8-shard/1,024-deal
  capture admission, byte-binds capture -> diagnostics -> selected states,
  recomputes coverage, enforces 64 unique in-range states and Stage-A/B
  disjointness, publishes exclusively and reopens the full parent chain after
  freeze. Nonzero-SE and collision/invented/reordered-state falsifications are
  included; the broader teacher matrix passed 204/204. This authorizes only a
  clean fresh 143M-v2 capture -> diagnose -> 64-state freeze after Air is free.
  Receipt/label/gate publication remains a separate post-freeze code gate; no
  teacher label or strength evidence exists.
- Claude independently revalidated the live S0 chain: S0a hash/statistics,
  cluster additivity, exact 4,096-record coverage, null identity, work parity,
  source isolation and the live flags-off environment all hold. The result and
  live S0b remain admissible. Commit `4dc5302` closes the **main-only durability
  gap**: future smoke/full runs refuse all four posterior-changing
  sampler/ballot flags by environment-key presence, manifests record an exact
  empty list, and aggregation rejects missing/nonempty/cross-phase drift. The
  focused S0 matrix passes 39/39. The frozen Mini worktree and live chain were
  not changed, so at live S0c launch independently verify its inherited
  environment is still clean and record that external receipt in terminal
  review.
- Commit `7ecffd5` blind-froze a *separate* protected-composition question
  before any direct-V11 effect was opened. It preserves the original direct
  verdict but recognizes that standalone superiority is not necessary for an
  MC-protected proposal to help. A protocol-valid direct block with a sane null
  plus terminal S0 may admit the non-promotable 137M screen; only a screen PASS
  admits the independent 138M confirmation. Corrected-parent v2 is now frozen
  at `b361836`, with empty-valued environment-key refusal repaired at `1354cac`.
  Its deliberate `DIRECT_AGGREGATE_SHA256=None` launch lock may be replaced
  only by the exact sealed corrected-V11 v2 aggregate hash; terminal S0 is the
  other prerequisite.
- Six parallel code gates are now closed and pushed. `e946696` independently
  redraws/re-scores the S3a evidence; `d2229d0` binds the exact direct-V11
  parent and reopens raw screen evidence before confirmation; and `e49cf60`
  closes S2's interruption/RNG/hidden-state/publication boundaries. `868b6d8`
  adds the concrete two-role, from-scratch direct-Q microbaseline and proves
  exact resumed batch/action/model/optimizer/replay/RNG identity. `79985a2`
  adds the terminal-champion-matched S3b screen/confirmation protocol and its
  score-free throughput gate. `cde0fec` freezes the corrected-encoder V11 v2
  direct gate at 8x256 fresh 142M clusters with exact accepted-dose and raw
  reopening checks. None is a strength result. S3a/S3b still wait for terminal
  S0; V11 v2 is now running 8/8 on Air. `f5ff2f9` closes Claude's direct-Q
  provenance HOLD by binding and falsifying all 16 material implementation
  dependencies. Commit `d5d71d2` also closes legacy DMC2's exact-promotion
  seam: PASS returns the immutable candidate actually evaluated, FAIL keeps the
  incumbent and generator drift refuses; 32/32 focused tests pass. Historical
  DMC2 evidence remains invalid. Commit `b27be23` closes Direct-Q's explicit
  exact candidate-to-actor refresh boundary: only the already-published current
  candidate can rotate, exact resume is preserved and integrity drift poisons
  until checkpoint restore. The bounded learning/held-out evaluation spec is
  now the next S2 gate; actor rotation itself is not strength evidence.
- The frontend ship gate is **COMPLETE / PASS**. The real multi-socket server
  suite passes 33/33 and browser connection/intent tests pass 14/14, including
  the newly exercised >50-message history rollover. Lint reports only the
  existing fast-refresh warnings and the production build passes. No frontend
  behavior change was needed by this final gate.
- The legacy full-game evaluator cutoff boundary is **COMPLETE / PASS**.
  `play_game` raises typed `FullGameCutoff` on any unfinished max-round
  exhaustion, even with unequal partial levels, and legacy mirrored `evaluate`
  returns no partial score. Completed games and the registered one-round
  evaluator are unchanged. Focused independent verification passes 25/25;
  the author also passed the broader game/invariant/evaluator set 46/46.

## S0 implementation packet — S0a accepted, S0b-LCB running

Base implementation commit: `df0a7b9`; calibration/freeze commit: `316542a`
(both pushed). End-to-end parent-bound S0a/S0b/S0c protocol commit: `476e400`.
The independent terminal return-packet verifier is durable at `751ef50`, with
cross-phase runtime binding at `a114716` and frozen-source routing at `6fe5f44`
(`server/scripts/s0_packet.py` and `server/scripts/s0_aggregate.py`). The live
supervisor pins those audit-tool hashes and refuses drift.
The calibration commit adds the immutable audit artifact and freezes its
selected report dose; the protocol commit freezes exact coverage, controls and
the independent confirmation before any S0a result is inspected.

### What is now closed

1. Per-decision state resets occur before tractor-lock, candidate generation or
   any return. Tests force both early exits and prove all prior record/allocation
   sentinels are gone.
2. Every contested decision records registry policy, class, git/dirty/code
   identity, derived `BallotSpec`, full pre-selection RNG state, named report and
   allocation seeds, candidates/means/paired SE, raw winner, report challenger,
   final played index/card/reason, selection/report work, elapsed time and
   before/after/delta sampler counters. The server refuses a record whose played
   multiset differs from the actual move. JSON-decoded RNG state has a tested
   restore helper and exactly reproduces card, values and candidate counts.
3. Report worlds use a named RNG stream that does not advance or reuse the
   selection stream. A fold must fill its exact frozen dose or candidate 0 is
   returned with `report_underfilled`; finite partial folds cannot override.
4. Adaptive pruning uses direct candidate-vs-current-leader paired moments on
   overlapping worlds, never re-admits a pruned candidate, preserves candidate
   0 plus one challenger, and consumes exact N*K selection work. An unavoidable
   residual smaller than the survivor set is executed and explicitly marked as
   decision-excluded dummy work rather than silently stranded.
5. Random allocation uses a separate named RNG and matches adaptive's exact
   selection budget; the equal-work uniform control consumes the same total
   N*K+2R candidate rollouts as a report arm. Report work is included in both
   `rollouts` and `search_secs`; sampler attempts reconcile as accepted+failed.
6. The incident fixture is minimised and sanitised. The old fixed-margin seeds
   still reproduce `DJ`, the report policy refuses it, deterministic positive
   and negative paired-delta tests force both branches, and the frozen audit has
   genuine LCB-positive attacker and defender witnesses so a never-override
   implementation cannot pass.
7. Runtime provenance is fail-closed across the whole chain. Every aggregate
   carries the exact host, Python, strict-mode flags and all source/native
   digests; the parent aggregate hash binds that identity into its child. The
   Mini supervisor probes the runtime before child launch, and the terminal
   verifier rejects within-phase, cross-phase or frozen-identity drift. A
   changed child binary is a tested refusal. The durable aggregator explicitly
   imports policy/evaluator code from frozen `be1e39c`, never mutable `main`.

The per-move LCB is deliberately a named, conservative one-sided Student-t
decision heuristic (`1.70`, valid for the registered R>=30 normal approximation),
not the promotion inference. Strength is established only by fresh paired full
games and their clustered interval.

### Margin and report-dose decisions

- Incumbent `mc-strong` keeps point-estimate `MARGIN=5.0`.
- New report policies use a separate `REPORT_MIN_GAIN=0.0`: report mean/LCB must
  support that the nominated challenger is better at all. LCB>5 would instead
  require a true gain above five and collapses toward SmartBot.
- `server/tests/data/s0_override_audit.v1.json` is the immutable DEV diagnostic:
  first 150 frozen DEV-512 states, named N=30 selection seeds, first 20 actual
  overrides, and all 300 signed paired report deltas. Artifact SHA-256:
  `9703b50817fb03622c3739e44f73e19083b1e8337300be7054774e2308e13ef5`.
- Reproducible result: 48/150 current overrides; among the frozen first 20,
  12 have positive N=300 gaps, mean `+0.570`, median absolute gap `2.775`.
  LCB>0 retains 2/12, 3/12, 5/12 and 6/12 positive references at
  R=30/60/120/300, with zero N=300-negative supports. The predeclared rule
  therefore freezes **R=300**. This replaces the unreproducible prose headline
  `+1.69`; neither small selected sample is a population strength claim.

### Registered policies and exact work

For K candidates on every contested decision:

| policy | selection | report | total candidate rollouts |
|---|---|---|---:|
| `mc-strong` | uniform N=30, incumbent margin 5 | none | `30K` |
| `mc-s0-report-mean` | uniform N=30 | paired mean >0, R=300 | `30K+600` |
| `mc-s0-report-lcb` | uniform N=30 | paired LCB >0, R=300 | `30K+600` |
| `mc-s0-uniform-work` | uniform, whole common worlds + explicit residual | none, incumbent margin 5 | `30K+600` |
| `mc-s0-adaptive[-mean]` | deterministic adaptive, exact `30K` | same rule, R=300 | `30K+600` |
| `mc-s0-random[-mean]` | random attribution, exact `30K` | same rule, R=300 | `30K+600` |

Production flags remain off. A short current search now loudly falls back to
candidate 0 and increments `short_search_decisions`; that is a correctness/
observability change, not deployment of an S0 strength policy.

The final dirty-tree two-cluster mechanics smoke used the frozen R=300 dose and
completed all five S0a arms: 20 mirrored records, zero short/zero-world searches,
reconciled sampler counters and no manifest problems. It is deliberately marked
`promotable:false`; its game scores are not evidence.

## Authoritative current job — S0b-LCB

S0a sealed all eight final manifests at 06:58 EDT. Independent frozen-source
recomputation matched the stored aggregate byte-for-byte except for its missing
terminal newline. All labels contain 4,096 mirrored records over the exact
2,048-cluster seed block; every sampler failure/short/zero-world/void-fallback
counter is zero, and all eight manifests agree on Mini host, Python 3.14.6,
strict voids, frozen SHA `be1e39c` and native digest `9c9e77fb...e4c1`.

The supervisor then launched exactly one `s0b-lcb` block. Its eight child
manifests cover contiguous seeds 134,000,000–134,002,047, bind the exact S0a
aggregate hash and survivor, and repeat the frozen runtime identity with no
dirty files. S0b compares deterministic adaptive allocation, the surviving
uniform report-LCB rule and matched random allocation. It retains adaptive only
if adaptive-minus-uniform and adaptive-minus-random are both positive by the
registered paired point-estimate rule; otherwise report-LCB remains the sole
S0c candidate. Do not inspect partial effects, relaunch workers or pool Air.

### Completed S0a launch and aggregation reference

S0a separates the report decision rule from extra compute. It is a diagnostic
screen, not promotion: 2,048 fresh mirrored deal clusters, eight shards of 256,
seeds 132,000,000-132,002,047. Each shard runs report-mean, report-LCB,
equal-work uniform, the true N=30 null and the current reference on the same
deals. The runner refuses dirty trees, wrong flags, policy/dose drift, duplicate
coverage, short work or unreconciled counters and writes only complete shards.

The already-running shards were launched with the following frozen command
shape (reference only; do not launch duplicates), substituting I=0..7:

```bash
cd server
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 .venv/bin/python \
  scripts/s0_run.py s0a --shard-index I
```

After all eight manifests return, the singleton supervisor owns aggregation.
For independent reproduction only (do not race the supervisor), invoke the
pushed verifier while routing all policy/evaluator imports to the frozen source:

```bash
cd /Users/jerryyu/Projects/shengji-s0-mini/server
S0_SOURCE_SERVER="$PWD" /opt/homebrew/bin/python3.14 \
  /Users/jerryyu/Projects/shengji/server/scripts/s0_aggregate.py s0a \
  --pattern 'runs/logs/s0-protocol-v2_s0a_shard0?_be1e39cd92.jsonl.manifest.json'
```

The live supervisor pins SHA-256
`a3e33086019c2a140963d06851591f3cea3ed2b23ffb9e1dd7bc0f6c58d7a255`
for that aggregator. A different script or missing `S0_SOURCE_SERVER` is not an
authoritative aggregate.

The frozen screen rule carries forward the larger of report-mean/report-LCB only
if its paired point estimate is positive versus current and its direct paired
contrast versus the equal-work uniform control is positive; ties choose
report-mean. The aggregate explicitly states `promotion: false`.

Only the selected rule may launch its corresponding `s0b-mean` or `s0b-lcb`
block. S0b promotes adaptive allocation over uniform report selection only if
adaptive-minus-uniform and adaptive-minus-random paired point estimates are both
positive. Every child shard requires `--parent` and refuses unless the aggregate
names the exact expected survivor, git SHA and 2,048-cluster parent block.

After S0a, run the one admitted S0b phase on eight workers with `I=0..7`:

```bash
cd server
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 .venv/bin/python \
  scripts/s0_run.py s0b-mean --parent runs/logs/s0a-v1.aggregate.json \
  --shard-index I
# Substitute s0b-lcb only when the S0a aggregate names mc-s0-report-lcb.
```

Aggregate that phase with `s0_aggregate.py` and freeze its survivor. Exactly one
corresponding confirmation protocol may then run:

| S0b survivor | confirmation phase |
|---|---|
| `mc-s0-report-mean` | `s0c-report-mean` |
| `mc-s0-adaptive-mean` | `s0c-adaptive-mean` |
| `mc-s0-report-lcb` | `s0c-report-lcb` |
| `mc-s0-adaptive` | `s0c-adaptive-lcb` |

S0c is frozen at 8,192 independent clusters, seeds
135,000,000–135,008,191, eight shards of 1,024. Each shard runs the survivor,
`mc-strong-null`, and current `mc-strong` on identical mirrored deals and binds
the S0b aggregate by SHA-256. Example:

```bash
cd server
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 .venv/bin/python \
  scripts/s0_run.py s0c-adaptive-mean \
  --parent runs/logs/s0b-mean-v1.aggregate.json --shard-index I
```

Production promotion requires all three machine-checked criteria: the paired
two-sided 95% lower bounds for survivor-minus-current and survivor-minus-null
are both above zero, and the null-minus-current lower bound is not above zero.
Otherwise S0 closes **SELECT NONE**. S0a/S0b/S0c are disjoint and may never be
pooled. The v2 runner records host, Python, compiled binary digest, strict mode,
literal seed coverage, parent digest and exact counters; the aggregator refuses
any drift.

The production control point is `fly.toml`'s explicit
`SHENGJI_BOT='mc-strong'`, not the source fallback (`mc`). A terminal
**SELECT NONE** leaves that setting unchanged. A terminal **PROMOTE** requires a
separate reviewed commit changing it to the exact confirmed survivor and a
post-deploy `/healthz` check for both policy name and compiled-engine activation.
The live Fly deploy itself remains an explicit quiet-room operation because a
restart disconnects in-progress games; evidence completion does not silently
authorize that external mutation.

## Other active strength lanes

1. **V11 direct compatibility v1 (terminal FAIL as run; historical):**
   The immutable `e66b90bc3a50d514472670ea99909add5ea30d19` block completed
   all 2,048 clusters / 8 shards on exact 121M seeds with zero sampler failure,
   rejection or short search. Frozen aggregation produced v11-current
   `-0.1323 +/- 0.0697`, v11-null `-0.1592 +/- 0.0693`, and null-current
   `+0.0269 +/- 0.0679`; neither efficacy LCB cleared and the null interval did.
   Artifact: Air
   `server/runs/logs/v11-current-v1.aggregate.json`, SHA-256
   `112f2c756235d69ac60efbd0f263ef096d311145d0151931ce2a2b8b0099eaec`.
   Preserve `anchor_test_authorized=false`. Because its encoder digest
   `a2022b...` contains the silent banker-private-kitty drift, this is a valid
   verdict only for that exact implementation, not a clean v11pair-model
   verdict. A fresh corrected-encoder v2 direct block must use disjoint seeds.
2. **V11 protected composition (code gate closed; waits for corrected direct + S0):**
   `7ecffd5` preserves the direct gate's original verdict and separately
   predeclares the missing composition estimand. A protocol-valid direct block
   with a null interval containing zero plus S0's terminal champion admits a
   non-promotable 2,048-cluster screen on exact seeds
   137,000,000–137,002,047, even if standalone v11 does not clear superiority.
   Compare a champion-matched v11 anchor, same-trigger random anchor, literal
   champion and champion-matched null at the complete champion work contract.
   Require anchor-minus-champion/random/null LCBs >0 and a null interval
   containing zero. Only PASS admits the independent 8,192-cluster confirmation
   on seeds 138,000,000–138,008,191. Never use the pairwise head as a scalar
   leaf or rewrite the direct aggregate's stored authorization bit. Commit
   `5d0c5a1` makes the anchor copy the literal reachable S0 champion
   (`mc-strong`, report-LCB or adaptive), including all uppercase search
   settings. `d2229d0` closes the runner: it hard-binds the exact direct commit
   and source hashes, requires a sane direct null without rewriting the stored
   standalone verdict, uses exact champion-matched nulls, publishes exclusively
   and forces confirmation to reopen/recompute all raw screen evidence. Root
   acceptance is 44/44; the broader independent gate is 78/78 and the full
   server suite was 552 passed, 2 skipped. Those frozen source checks correctly
   refuse main after `66aad44`; version the direct parent and composition gate
   rather than weakening them.
3. **S1 teacher/model — v1 entry REFUSED; fresh v2 repair required:** pushed commit
   `23a9e0b` carries packet id, exact 120000000–120001023 range, eight-shard
   coverage and parent hashes through capture, diagnostic, frozen state,
   label and gate artifacts. Labels are the independently reconstructed
   `sorted(state_id)[shard::8]` partition of the exact state-set bytes. Before
   each label population, create one exclusive producer receipt: primary and
   rerun have different roles, run ids, SHA values and nonces; every shard in
   one population binds the same receipt. Real gates reopen receipts and exact
   state/label bytes, repeat source/runtime checks, and fail stale, smoke,
   copied, swapped, missing or repeated artifacts. Independent review is PASS;
   py-compile plus teacher/pilot acceptance reports **134 passed, 23 skipped**.
   Commit `0183cdd` added the fail-closed singleton transition supervisor. At
   14:55 its clean corrected-encoder worktree admitted exact packet
   `teacher-v1-entry-120m-v1`; all eight 128-deal captures completed. The
   supervisor then correctly stopped the chain, but for a validator defect:
   JSON serialization converted ballot config tuples to lists, so direct dict
   comparison falsely labelled every otherwise identical actor as drifted.
   There are zero diagnostics and no frozen state set, receipts or labels.
   Preserve the refused v1 directory. The replacement must be a newly frozen
   `143m-v2` packet on disjoint seeds with JSON-canonical actor identity, exact
   Python 3.14.6 and experimental flags OFF enforced and falsified in tests.
   Stage A is 64 states plus
   an independently receipted deterministic rerun; only PASS authorizes the
   disjoint 128-state Stage B. Only Stage-B gold regret U95 <=0.10 authorizes
   implementing Stage C. Never append capture or mix executable identities.
4. **S2 self-play RL — concrete direct-Q code gate CLOSED / evidence next:**
   `e49cf60` now transactionally binds and replays learner, optimizer, replay,
   named RNG, runtime, progress and immutable actor/candidate identity; poisons
   every `BaseException`; forbids process-global RNG consumption; binds hidden
   learner/optimizer configuration; freezes collector-visible state; and uses
   exclusive persistent candidate ownership/publication. Root acceptance is
   46/46. Commit `868b6d8` then adds one concrete Shengji-specific DouZero-style
   microbaseline: independent attacker/defender action-Q networks, chronological
   public history, direct signed terminal bracket return, immutable actor,
   narrow ordinary-play ballot and explicit Smart declaration/bury controls.
   Its exact interruption test matches canonical actor-batch bytes, ordered
   actions, candidate SHA and all mutable state; root matrix is 73/73. It is a
   bounded one-round code gate, not paper faithfulness or strength. Review found
   its algorithm digest omitted three execution-contract modules. Commit
   `f5ff2f9` binds those plus heuristic/MC-ballot/legal transitive dependencies;
   every one of the 16 source identities is mutation-falsified and the root
   contract matrix passes 77/77. Next freeze a small learning/evaluation spec
   before using fleet compute. Separately, legacy DMC2 still needs one exact-
   candidate promotion seam test: PASS must publish the evaluated candidate,
   never whatever newer learner generation exists when the gate returns.
5. **S3a structured bury search — code gate closed / waits for S0:** the pure source sees
   only the banker's 33-card hand, public ordering and incumbent; it emits a
   deterministic, deduplicated, capped point/trump/pair/void ballot with the
   incumbent at index zero. The scorer uses common sampled worlds, an explicit
   candidate-world cap, replayable RNG/work telemetry and loud incumbent
   fallback on underfill. Production and the ordinary lead/follow ballot are
   unchanged while flags are off. `e946696` registers a 512-state runner with a
   disjoint 120-world report fold, exact equal candidate-world work and
   legacy-four plus trigger/K-matched random controls, storing raw values and
   limiting a PASS to fresh-duel design. Its independent consumer reconstructs
   each named deal, redraws selection/report worlds, verifies full sampler
   transcripts and replays every raw score in frozen call order. Digest and
   wholesale-score falsifications fail; focused acceptance is 27/27. Its
   evidence run and any duel reference still wait for terminal S0.
6. **S3b sampled exact endgame — strength code gate CLOSED / waits for S0:** all
   distinct submitted legal actions are enumerated inside the <=4-card bound,
   including attempted throws; the engine resolves failures and partnership
   minimax optimizes final attacker points. MC may call it only on a marked
   fully determinized rollout clone. Live-room calls, over-cap states and node-
   budget exhaustion refuse rather than silently mix exact and heuristic work.
   One `ExactWorldSession` now spans all candidate frontiers in one sampled
   ordinary-play world, never different sampled worlds or bury candidates; its
   key binds banker/trump/kitty context and invalid hidden-hand sizes or card
   conservation refuse. Independent parity checks matched 58 candidate
   frontiers across five real four-card states, and sharing reduced measured
   repeated work/time by roughly 1.9–6.1x / 1.9–5.7x. Commit `2370a27` then
   froze and passed the bounded challenge: four real states x four named worlds,
   140/140 exact candidate-frontier evaluations, 16 sessions, 130,989 nodes,
   97,834 hits and zero refusal/overflow under the cumulative 250k-node/session
   cap. Commit `79985a2` now registers feature-on clones for all three reachable
   S0 champions plus a score-free two-cluster throughput receipt, a
   non-promotable 2,048-cluster 139M complete-round screen, and an independent
   8,192-cluster 140M confirmation. Both efficacy LCBs must clear, the
   champion-matched null must stay sane, exact use must be nonzero and
   refusal/overflow must be zero. Confirmation reopens raw screen bytes. Root
   acceptance is 82 tests across the protocol/mechanics/evaluator matrix. Run
   only after terminal S0 names the champion and a same-host throughput receipt
   clears the predeclared operational caps. The precise claim remains an exact perfect-
   information oracle inside each sampled world, not exact imperfect-
   information Shengji; no S3 strength evidence exists.

## Live execution queue for Claude/Codex

1. **Do not score either live partial.** Mini S0b and Air corrected-V11 v2 are
   the two live evidence blocks. Monitor only worker count, process health,
   final/partial/failure counts, frozen identity and score-free progress.
2. **Keep Air's refused teacher v1 namespace immutable.** The supervisor
   stopped after eight captures and before every diagnostic/label path. The
   independently reviewed JSON-canonical, flags-off, Python-pinned 143M-v2
   entry packet is pushed at `2038b31`; it closes diagnostic->state provenance
   and exclusive publication through the 64-state freeze. Never resume or
   reinterpret `teacher-v1-entry-120m-v1`. Air is occupied by V11 v2; do not
   launch teacher v2 concurrently. Before later receipts/labels, close their
   separate exclusive-publication/parent-binding gate.
3. **Leave Mini's singleton S0 supervisor in control.** It aggregates S0b,
   selects the registered survivor and launches exact S0c automatically. Only
   inspect a phase effect after 8/8 finals and the supervisor transition. At a
   terminal state, run the independent closeout and packet byte comparison;
   cleanup only the packet-proved services.
4. **Local code while compute runs:** corrected-encoder V11 v2 is frozen and
   pushed at `cde0fec` on disjoint 142M seeds. Teacher entry v2 is closed at
   `2038b31`; Direct-Q exact actor refresh is closed at `b27be23`; corrected-
   parent protected composition is code-frozen at `b361836`/`1354cac` with its
   aggregate-SHA launch lock still engaged. Implement and independently review
   the bounded Direct-Q learning/held-out evidence protocol plus the teacher
   receipt/label publication gate. Do not weaken or rewrite sealed v1 evidence.
   S3 evidence remains subordinate to terminal S0.
5. **Production stays `mc-strong`.** No evidence completion authorizes a Fly
   restart or policy change; that remains a separately reviewed quiet-room
   action.
6. **Six-hour autonomous owner window (requested 14:29 EDT):** Codex owns the
   transitions above, keeps accepted code/doc commits small and pushed, and
   updates `BACKLOG.md`, `JOBS.md`, today's daily log and this packet after each
   real gate. Claude should intervene only with a concrete blocker/review
   finding; never duplicate a singleton aggregate, worker block or teacher
   capture. The strength target remains a clean paired win over production
   `mc-strong` N=30, not merely more generated rows or closed code gates.

## Return packet for Claude

```text
STATE: S0_COMPLETE_PROMOTE | S0_COMPLETE_SELECT_NONE | BLOCKED
HEAD / origin / dirty state:
S0a 8 manifest paths + aggregate path/hash and survivor:
S0b 8 manifest paths + aggregate path/hash and survivor (or NOT REACHED):
S0c 8 manifest paths + aggregate path/hash (or NOT REACHED):
per-label seed/flip counts and exact coverage:
host and compiled binary digest agreement:
sampler attempt = accepted + failed; short/zero counts:
S0a paired effects and direct report-rule vs uniform-work contrasts:
S0b adaptive-minus-uniform and adaptive-minus-random contrasts:
S0c arm-current, arm-null and null-current effects/95% intervals + criteria:
final production decision from the registered rule:
CALIB / REPORT confirmation: sealed and unscored
```

Do not start a child phase from an incomplete shard set, a hand-computed
aggregate, a different git SHA or a parent that does not name its exact policy.

Terminal closeout is prepared in `server/scripts/s0_closeout.py` without
changing the pinned evidence path. Its default mode independently regenerates
the final packet and requires byte identity plus every field above. Only its
explicit `--cleanup-launchctl` mode mutates process state, and that mode refuses
a nonterminal supervisor state or packet drift before removing the exact
reached Mini services. Both submitted workers and the supervisor are keep-alive:
after final artifacts seal they may restart into immutable-output collisions.
Only the exact worker labels whose 8/8 phase artifacts the verified terminal
packet proves complete are authorized. Cleanup scans the full loaded S0-worker
namespace first and refuses an unreached phase/shard instead of silently
leaving it behind; the CLI-path regression injects an unexpected S0c worker.
Keepawake and the terminal supervisor are removed last. Do not run cleanup
while S0b/S0c is active.
