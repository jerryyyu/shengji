# Active Claude/Codex handoff

Last update: 2026-08-06 10:09 EDT. Historical discussion and superseded gates
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
  S0b-LCB launched 8/8 exact parent-bound Mini shards at 06:58 EDT. Air remains
  duplicate fallback only; never pool its records or launch a child from Air.
  At 09:18 all eight shards completed the adaptive label and entered
  uniform-report; stderr remains empty. Do not inspect partial effects.
- Teacher-v1 mechanics/gold gates, the v11 protected-anchor compatibility block
  and the role-conditioned RL microgates remain independent parallel strength
  work; none should be folded into S0 before each wins alone. V11 and
  teacher-v1 entry-gate code is ready and tested, but neither has run a
  promotable evidence block.

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

1. **V11 protected-anchor lane (separate from S0):**
   `server/scripts/v11_revalidate.py` and policies `mc-v11anchor` /
   `mc-v11anchor-random` are code-ready; a two-cluster compiled+strict smoke
   completed cleanly and is non-promotable. Registry construction is now cwd-
   independent and the runner verifies that the policy's actual absolute
   loaded path/SHA are the same NPZ bytes named by its manifest. First run the frozen direct
   `rl-override-v11pair` versus current N=30 block at seeds 121M. That result
   can authorize only a later anchor experiment. Do not freeze that later
   experiment's reference/seeds until S0 names the terminal champion; never
   use the pairwise head as a scalar leaf.
2. **S1 teacher/model:** capture/diagnose/freeze and Stage-A/B producer/gates
   are code-ready at `server/scripts/teacher_v1_*.py`; the full server suite
   passed 405 tests (two optional skips) and a one-deal smoke passed. No
   evidence run exists. Execute
   Stage A (64 mechanics plus deterministic rerun), then disjoint Stage B (128
   production-N30 gold continuation). Stage-B freezing now requires both a
   complete/digest-valid exact Stage-A exclusion set and the PASS gate bound to
   that set; schema-only exclusion cannot advance. Only a Stage-B regret upper bound <=0.10
   signed levels authorizes implementing/launching its 2,048-state wave.
   The first packet is now predeclared in `TEACHER_V1_SPEC.md`: exact seeds
   120000000–120001023, eight capture/diagnostic shards, eight Stage-A primary
   plus rerun shards, then eight exact-parent Stage-B cheap/gold shards. Do not
   append capture after diagnostics or labels are inspected.
3. **S2 self-play RL:** role-sign antisymmetry and immutable actor/candidate
   boundaries are code-ready and tested. The audit also fixed promotion of
   different learner bytes than the candidate actually gated. A bounded
   18-round smoke is explicitly non-promotable; the full server suite passes
   415 tests with two optional skips. Exact learner/optimizer/replay
   resume remains open; do not run faithful Suphx-style feature-removal or
   DouZero-style role-Q microbaselines until interrupted/resumed output matches
   uninterrupted output.
4. **S3 structured search:** independently screen broad bury search and
   information-set-legal sampled exact solving for the final ~4 tricks.

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
a nonterminal supervisor state, packet drift or any still-live S0 worker before
removing the exact reached Mini services. Do not run cleanup while S0b/S0c is
active.
