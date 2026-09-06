# W32 adaptive-root allocation: first bounded DEV contrast

Tracked in #248. Jerry gives this work priority on Strength. The all-world
double-shortlist follow-up is parked; this experiment does not add search depth.

## Question

Does reallocating selection rollouts among the existing W32 finalists improve
play over flat W32's uniform selection? Keep the A+B+C checkpoint, exhaustive
32-world ranking, incumbent plus four alternatives, terminal rollout evaluator,
and independent R300 MC-LCB report unchanged. The only treatment is the existing
`MCBot._decide_adaptive` allocator, exposed through a DEV-only screen option.

This allocator is not new or a previously proven winner: the S0 production-ballot
experiments did not establish an additional gain over the report fold. W32's
model-selected candidate population is different, making this a new interaction
test, not a claim that an old algorithm has been newly discovered.

## Exact first recipe

- Arm: ABC learned W32 / K4 / N30 / R300, static MLP encoding, bounded successor
  reuse, `--selection-allocation adaptive`.
- Opponent: flat W32 with the same checkpoint, ranking and N30/R300 settings,
  **uniform** allocation. This is a direct adaptive-vs-flat match, not a
  subtraction of two production-opponent results.
- Allocation: inherited common-world prefix `max(4, N//4)` (7 at N30), paired
  candidate-difference upper-bound pruning at the inherited confidence setting,
  incumbent and at least one challenger retained, survivors share additional
  worlds. Only surviving candidates can be nominated. No world is selected for
  having an attractive model value.
- Exact selection budget stays `N * actual_finalist_count`; a five-action root
  uses 150 candidate-rollouts. Any small residual is the inherited explicitly
  counted dummy work, excluded from estimates. At most 600 further rollouts
  form the independent incumbent/challenger report. This first test reallocates
  work rather than claiming to save it. Runtime can still differ with trajectories.
- Keep the independent report seed/fold, LCB threshold, root perspective,
  incumbent, sampler and hidden-information boundary unchanged. Adaptive pruning
  is a selection heuristic, not a sequentially valid confidence certificate;
  the untouched independent report remains the final acceptance check.
- No new model, optimizer, continuation, larger world dose, random allocator,
  second shortlist, registry policy or production default is bundled into it.

The repaired S0 protections must remain effective: no pruned candidate re-entry
on its stale mean, no comparison of different world subsets as if paired, exact
residual accounting, underfilled sampling/report refusal, and report work in
total counters. Consumer tests must reach the recorded decision, not merely the
allocator helper. Actual allocation counts and pruning events are retained in
the screen's decision traces; forced decisions must not inherit a previous trace.

## Population, inference and retained evidence

Use all **260 existing broader-rank DEV deals**, span `[91260904,91261164)`, rank
cycle `2,3,4,5,6,7,8,9,10,J,Q,K,A`, two mirrors per deal. This deliberately reuses
the already-opened population from #258, including its hard positions; it is
**not a fresh or confirmatory split** and requires no invented new seed window.
Keep both mirrors together in aggregation. Actual trump suit/NT coverage is
reported from generated rounds, not inferred from the rank cycle.

Reference source evidence: #258 ran flat W32 vs production over these 260 deals
in 22m53s, using 13.89 average cores with 16 workers. That is a scheduling/cost
anchor, not the new comparison's result. The new match runs W32 on both teams
and changes decisions; exact trajectories or timings are not promised.

Primary result: mean signed levels per round for adaptive versus flat, with
deal-clustered bootstrap interval. Report win rate, completed/requested pairs,
failures, role/rank/NT coverage and actual wall/CPU/rollouts. Rank breakdowns are
descriptive at 20 deals per rank. Do not call an interval spanning zero a tie or
equivalence; do not infer unchanged decisions from zero paired outcome sums.
An inconclusive screen remains useful evidence, not a reason to resize after
seeing the sign. No automatic K/W/N/depth sweep follows.

Diagnostic readout from already-retained traces: fraction of contested decisions
with pruning, survivor count, per-candidate allocated worlds, dummy work,
underfilled cases, incumbent/challenger nominations and report acceptance.
Contrast actual allocations between sides. This proves whether the intervention
reached decisions and helps interpret a null; it does not by itself prove strength.

## Execution and recovery

One isolated source checkout and output root on Strength, after source review and
Claude's explicit host handoff. At preparation time Run F2 is live and resume-safe;
do not interrupt it silently or contend for its cores while editing code.

Use 16 one-thread process workers and the same compiled engine as the matched
reference. Cost-order existing seed-matched #258 shard timings only (not outcomes)
so known wide pairs begin early. Preserve every seed and both mirrors regardless
of estimated expense. Planning estimate **35–60 minutes**, not a guarantee; new
policy trajectories can create different tails. Lightweight external safeguard:
two hours wall, 24 GiB group memory on the 32-GiB host. No new capacity census or
repeated full-population parity/reconstruction run.

Progress uses the existing per-pair publication and worker logs. Verify the first
completed pair contains real adaptive pruning/allocation metadata and a uniform
baseline; record elapsed/completed/active and revise ETA from measured work.
Keep first-pair warmup and straggler uncertainty explicit.

Each completed pair is atomically retained. A deadline or failed worker preserves
all completed shards; an identical-command resume reruns only missing work and
does not substitute another population. Do not automatically extend the wall cap
or restart a partial run. Read and publish valid partial results as partial.
The final summary consumes retained pairs once; no second multi-hour replay or
independent reconstruction is required for this DEV screen. Copy final artifacts
to Mini for retention; do not put private game data or checkpoints in Git.

From the isolated executing checkout's `server/`, with the exact paths substituted:

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
python -B scripts/cwv_shortlist_screen.py \
  --arm learned --checkpoint /root/cwv-runABC-mlp-points-best.pt \
  --worlds 32 --alternatives 4 --selection-worlds 30 --report-worlds 300 \
  --selection-allocation adaptive --baseline flat-shortlist \
  --encoding mlp-static --reuse-successors --batch-size 128 \
  --clusters 260 --workers 16 --seed0 91260904 \
  --trump-ranks 2,3,4,5,6,7,8,9,10,J,Q,K,A \
  --cost-order-from /root/cwv-ranks13-20260906.YtvILo/ranks13-paired \
  --out NEW_ADAPTIVE_ROOT_OUTPUT
```

Checkpoint SHA256:
`3f00500c5bf207e51d50ccd59a7b78c4f917b0a8adf3f39b31e660f81baa84ec`.
Pin the actual executing head/command/environment in the launch record. Source
PASS plus Jerry's standing bounded-experiment authority and verified host handoff
unblock this named DEV screen, not production deployment or a broad scaling queue.

## What comes after

Interpret this result before designing selective depth. If allocation helps,
independent confirmation and an optional random-allocation/measured-cost control
can ask why. If it does not, examine whether pruning occurred and whether a better
checkpoint changes candidate quality before increasing compute. Selective depth
is a different treatment and stays out of this first source/run packet.

## Source validation before review

The focused shortlist/screen/S0/sampler suite passes **56 tests**, with one
existing skip and two explicitly excluded artifact-dependent sampler tests,
in both pure Python (unset `SHENGJI_FAST`) and compiled mode. The excluded
tests need absent `rl_data/highn_corpus_all.jsonl`; they are not counted as
passing. No production engine or allocator source changes are part of this PR.

The new consumer witness reads the CLI's persisted config, constructs both
real W32 bots, samples their W32 rankings, performs adaptive versus uniform
selection and the real independent R300 report, then inspects the screen's
saved decision trace. Neural ranking scores and terminal rollout returns are
synthetic; it is a wiring test, not model-strength or runtime evidence. It
checks allocations `[64,64,7,7,7]` versus `[30,30,30,30,30]`, 150 selection
rollouts including the one adaptive dummy, 600 report rollouts, unchanged
source state, report-RNG isolation and no stale allocation on a forced move.
An anchored mutation disabling `make_side`'s adaptive assignment turns this
test red; restoring the assignment returns all six new tests to green.
The same file tests incompatible recipes and refusal to resume a uniform
shard as adaptive. This replaces a helper-only allocator probe.

CI then found an existing double-shortlist consumer regression: an unconditional
assignment of the new root flag disabled that bot's selection-stage hook. Before
any launch, the factory was repaired to leave double-shortlist's constructor-owned
flag unchanged. The existing real-decision test is included in the focused set;
all 20 adaptive/screen/double-screen tests pass in both pure and compiled mode.
This preserves the parked arm's behavior without combining it with adaptive-root
allocation or changing the proposed experiment.

## Completed screen — September 6

**No demonstrated incremental strength gain.** All 260 deals / 520 mirrored
rounds completed with no reported problems. Adaptive minus uniform flat W32
was **+0.00577 signed levels per round**, deal-clustered 95% bootstrap interval
**[−0.05774, +0.07308]**. This is inconclusive, not equivalence or a new win.
The actual opponent was flat W32, not production MC; do not add this estimate
to the earlier W32-versus-production result.

| Quantity | Observed result |
|---|---:|
| Adaptive round win rate | 50.5769%, clustered interval [47.8846%, 53.4615%] |
| Adaptive / flat decision wall | 0.96663x |
| Adaptive / flat decision CPU | 0.96662x |
| Adaptive / flat total full rollouts | 1.00117x |
| Completed pairs | 260 / 260 |
| Whole-job elapsed | 2,108.6 seconds (35m09s), 16 one-thread workers |
| Rank coverage | 20 deals / 40 mirrored rounds at each of 13 ranks |
| Actual suit coverage, rounds | C 92, D 124, H 126, S 128, NT 50 |

The roughly 3.3% lower decision wall is **not decision-preserving optimization
evidence**: the policies reach different trajectories and candidate populations.
Measured arm/flat shortlist time was 13,017.93 / 13,600.40 seconds, versus
16,056.99 / 16,611.29 seconds for all decisions. Ranking therefore still accounts
for about 81–82% of decision time. Both teams together accumulated 32,659.45 CPU
seconds, about 15.49 decision-CPU cores over the job wall; this excludes other
worker/parent overhead. The run did not need a repeated capacity census or an
engine/model reconstruction pass.

There were 49 positive, 50 negative and 161 zero paired level sums. **Zero paired
outcomes do not imply unchanged decisions**; both mirrors remain in all 260
bootstrap clusters. The 1,000-replicate bootstrap seeds are retained in the
summary. This was the already-opened broader-rank DEV population, not a fresh
confirmation or a post-outcome population expansion.

### Did the intervention actually happen?

Yes. A read-only reduction of all 260 retained shards (1,040 trace groups,
17,798 decisions per side) gives:

| Decision-trace quantity | Adaptive | Uniform flat |
|---|---:|---:|
| Contested decisions with an allocation/report | 14,868 | 14,855 |
| Decisions with pruning | 7,492 (50.39% of contested) | 0 |
| Unequal candidate sample counts | 7,419 | 0 |
| Report accepted challenger | 4,857 (32.67% of contested) | 4,697 (31.62%) |
| Report retained incumbent | 10,011 | 10,158 |
| Missing/incomplete contested reports | 0 | 0 |
| Allocation underfill / attempt-cap hits | 0 / 0 | 0 / 0 |
| Explicit dummy selection rollouts | 8,116 across 5,334 decisions | 0 |

Adaptive survivor counts were 2: 5,125; 3: 3,557; 4: 2,503; 5: 3,683.
The 73 pruned decisions with equal final sample counts are possible when pruning
happens at the end of the budget; pruning is not identical to actual reallocation.
Every adaptive allocation was recorded as `deterministic_adaptive`, and every
baseline allocation as `uniform`. Forced decisions (2,930 / 2,943) correctly have
no stale allocation/report. Generic trace fields such as `counts` and `leaf_tricks`
are null; the populated `selection_allocation`, `cwv_shortlist` and top-level
`reason` fields were used, not those placeholders.

This rules out a silently disabled treatment as the explanation for the null.
It does **not** establish that the extra 160 challenger overrides were correct:
the sides reach different states. Nor does a null here show that all adaptive or
selective-depth strategies fail. It limits this allocator/checkpoint/DEV recipe.

Existing successor reuse produced 229,696,304 hits / 17,601,072 completions for
the adaptive side and 229,609,264 / 21,361,296 for flat. These are already-banked
savings, not a new prospective optimization. Their difference also demonstrates
why the 3.3% observed timing difference is not an isolated engineering A/B.

### Source and retention

- Executing source: `07e7ff94b630d809d757ad2715778d80e1236d56`.
- Source PASS: [PR #278 review](https://github.com/jerryyyu/shengji/pull/278#issuecomment-5561639276).
- Exact launch: [PR #278 record](https://github.com/jerryyyu/shengji/pull/278#issuecomment-5561705753).
- Original root: `shengji-cloud:/root/cwv-adaptive-root-run-20260906.ijXCaw/`.
- Retained Mini copy: `~/shengji-archive/2026-09-06/adaptive-root-final.3ga88X/`.
- Summary SHA256: `fd1ad46b5f16c35f4c4207d01fcc3e637291012227e50d62cae6070e75337094`.
- Config SHA256: `17b81ff742159ebed3d793cf671afcb8948af5ce86bebb67d293ca274b22e60a`.

Both locations contain all 260 pair shards; config/summary hashes agree at first
archive consumption. Full traces, failures (none reported), timings, launch
recipe and every result are preserved, not only favorable deals. The original
cloud evidence was not deleted. The service was verified inactive with MainPID 0,
Result success and exit status 0 before Strength was handed back to Claude for
F2. No follow-up arm was automatically launched.

**Reference stays optimized flat W32/K4/N30/R300.** Adaptive allocation did not
show a reason to replace it here. Selective depth remains a separate untested
mechanism; do not escalate worlds, population or confidence settings merely to
chase this screen's sign. No production default or deployment changes.
