# Sampled declaration completion: first paired DEV experiment

PR #331 implements an actor-visible completion sampler and a bounded policy
screen. This is not a production change, a learned belief model, or an exact
Bayesian posterior. Existing W32 and hybrid-bury settings remain unchanged.

## Completed mechanics pilot

At public observation index 2, compare waiting and H2 using two common
selection completions and two independent report completions. All four tasks
completed in 362.8 seconds on Mini with four single-thread workers. Six unique
full bury/play continuations were computed; identical completed states reused
their result. One continuation took 294.3 seconds; the others took about
47–68 seconds. Do not project runtime from the fastest games.

Selection means: wait 0, H2 -1 signed levels. Selected wait equals baseline;
report deltas [0, 0]. This is mechanics evidence, not improved gameplay.

Artifact: `~/shengji-archive/2026-09-10/declare-completion-pilot-index2/`.
Pilot local source `35893999`, remote source `f6b468f9`, identical tree
`2be4b319a6c833f2964e8ce1a113c7f71fa3f7d5`.

## Fixed first paired screen

- 27 fresh actual deals, two per rank testing both focal teams, plus one true
  first round. Existing banker contexts span all four seats. The deterministic
  first population has four eligible deals; the other 23 are NOT dropped.
- Treatment changes at most one callback per round: the focal team's first
  legal declaration opportunity with at least 20 currently held cards. Every
  legal action and waiting are compared using two shared sampled completions.
  Exact ties retain the heuristic choice. No future cards are read.
- Future declaration callbacks use SmartBot, including after a treatment
  choice. Then all seats use full hybrid bury and W32 play, unbudgeted as in
  the research runner, not the Fly wall-budgeted variant.
- Baseline and treatment start from the same actual deal before dealing.
  Selection worlds, actual deals and actual continuation RNG have distinct
  domains. Actual evaluation shares play RNG across arms.
- Report paired signed levels (existing banker_utility convention, minimum
  one for a win), win indicators, kitty bonus/tail exposure, intervention
  frequency, measured work and runtime. Kitty bonus benefits attackers, so
  its sign is not uniformly favorable to the focal team.
- Uncertainty is a descriptive deal-level paired bootstrap over this sparse
  fixed context mix, not a powered confirmation or independent per-world
  sample count. Never select a policy using the actual report outcomes and
  claim those same outcomes as fresh confirmation.

This **one-intervention policy** deliberately does not claim to evaluate
searching at every callback. The pilot's long tail makes all-callback search
an expensive separate question. Use the first result to choose scale, repair,
or stop; positive performance is not required for a useful result.

## Execution and recovery

One worker owns one pair. Four workers on Mini, one numerical thread each;
no nested worker pool or competing cloud job. Persist each inner rollout,
completed selection and final pair. Reuse identical states across root actions
and arms. A failure preserves completed pairs and writes a partial readout;
resume the same source/configuration. No second full integrity replay.

`--max-new` bounds an operational chunk without changing the recipe. If the
27-deal run is chunked, keep the entire original population in the final
readout and record any incompleteness. Do not change parameters between chunks.

```sh
PYTHONPATH=server OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 SHENGJI_REQUIRE_VOIDS=1 \
  python -m shengji.train.declare_completion_paired \
  --checkpoint /path/to/selected-3cd27716-compact.npz \
  --out /fresh/declare-completion-paired27 --deals 27 --workers 4
```

22 focused tests cover physical conservation, reveal deadlines, hidden twins,
actual consumer isolation, future callback order, baseline equivalence,
selection/report separation, one-intervention wiring and CLI resume. A bounded
read-only review found no load-bearing defect in the paired runner. Production
adoption and any stronger-model/greater-world-count successor remain separate.

## Completed paired result: do not adopt this recipe

All 27/27 prespecified pairs finished on Mini in **676.9 seconds (11.3 min)**,
at remote source `9f1fc54e4b03c410ab5598e32cb646ad40ad6a5b`, byte-identical tree
`872aac9cbb6297b297f81dad807e44266375fab5` to local `59f7f518`.
No failures, retries, discarded pairs or follow-on reconstruction campaign.

| Metric | Heuristic | Sampled declaration | Paired difference |
|---|---:|---:|---:|
| Focal-team wins | 11/27 | 10/27 | -3.70 percentage points |
| Signed levels, sum | -7 | -9 | -0.07407 per round |
| Kitty bonus, sum | 10 | 10 | 0 |
| Kitty bonus >=80 | 0/27 | 0/27 | 0 |

Four deals (14.8%) had an eligible decision. Three retained the heuristic;
one changed. The descriptive paired bootstrap intervals were [-0.22222, 0]
levels/round and [-0.11111, 0] win-rate difference. They are dominated by one
changed deal: **not proof that sampled declaration search generally loses**,
and not evidence that more worlds or earlier intervention would succeed.

### The changed decision

Deal index21, rank10, banker seat2, focal attacker seat1. At dealt-card94,
seat1 held24 cards including BJ and both little jokers. Banker2 had previously
shown the H10 pair. Two sampled completions gave waiting mean0 versus little-
joker-pair declaration mean+1, so treatment switched hearts to no-trump.

On the independent actual deal, waiting scored95 attacker points (win,+1),
while the declaration scored75 (loss,-1). Kitty bonus was zero in both.
This is one observed selection-to-actual-outcome miss, not proof of a biased
estimator or a reason to tune specifically to this now-opened deal.

The other eligible cells were index1 (rank3,BJ pair), index5 (rank7,H7 pair),
and index16 (rank5,H5 pair). Index1 and16 had identical completed pre-bury
states across root actions in both sampled worlds: future fixed declarations
erased the timing difference. Index5 favored waiting by one sampled level.

### Cost and learning

- **40 unique full games**: 12 inner selection continuations plus28 actual
  evaluation games. There were54 actual arm records, but26 exact-state pairs
  reused the same completed result. Four of16 candidate/world comparisons
  likewise reused identical states. Never double-count cache-hit CPU records.
- Unique compute: 2,214.57 CPU-seconds (36.9 CPU-minutes), including594.38
  CPU-seconds selecting four declarations: about149 seconds per eligible
  decision. Baseline's27 actual games cost1,584.11 CPU-seconds; treatment play
  plus selection cost2,160.23, approximately1.36x that measured total.
- Workers initially used roughly100% CPU each and300–330MB RSS. Median
  unique actual-game wall was49.3s, maximum129.9s. The last pair took313s
  including its sequential inner comparisons, leaving a one-worker tail.
  Average-pair ETA underestimated that tail; it was active computation, not
  a hang or serial integrity pass.
- No recorded zero-world or short-search events across the40 games.
- A one-second stack sample found29/82 samples in NumPy's object ufunc/erf
  path and11/82 under matrix multiplication. `cwv_numpy._gelu_exact` uses
  `np.vectorize(math.erf)`. A compiled exact-formula kernel is a future
  optimization candidate; this sample is not a speedup benchmark. Keep
  numerical and decision parity checks, and do not change a live run.

**Recommendation for future data generation:** retain the current declaration
heuristic. Preserve the sampled-completion implementation and all trajectories
as DEV evidence, but do not ship or scale this two-world, one-intervention
recipe unchanged. Any successor should first address scarce meaningful
decision exposure, noisy two-world estimates and expensive full-game scoring.
Earlier/all-callback search, greater sample counts or a learned continuation
score would be separately named experiments; none is proved by this screen.

Results: `~/shengji-archive/2026-09-10/declare-completion-paired27/` contains
`config.json`, all27 `cluster-*.json`, all4 `selection-*.json`,40 unique
`rollouts/*.json`, `summary.json` and the additive `readout.json`. The readout
script `~/shengji-archive/2026-09-10/declare-completion-readout.py` only reads
retained records; it never replays models/games. Statistical sampler profile:
`/private/tmp/declare-completion-worker417.sample.txt`.
