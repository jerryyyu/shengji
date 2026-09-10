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
