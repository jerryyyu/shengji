# Value-guided bury: first DEV diagnostic

Production is unchanged. This branch is an unregistered experiment, not a
deployment candidate. The selected model is the Torch source of the current
Fly model: `3cd277160322b30e9a61d5d83cb7fb6bceac6887ab1e899b98a42f15b259d600`.

## What we learned before gameplay

The frozen value encoder rejects immediate post-bury states: there is no
played-card history. We did not weaken it or invent a history row. The model
arm instead applies each candidate to a sampled complete world, finishes one
trick with the existing heuristic rollout policy, then scores that leaf.

64 fresh natural rank-2 deals, including their natural suit/NT declarations,
were saved before scoring. Structured bury candidates always retain the exact
heuristic incumbent. Model ranking uses 32 shared worlds. MC selection uses
32 independent shared worlds; its evaluation uses a further 224 worlds that
selection never reads. MC keeps the existing point objective and incumbent
margin. All uncertainty below clusters by deal, not candidate/world.

| Bury chooser | Independent reference gain | 95% bootstrap interval | Changed /64 |
|---|---:|---:|---:|
| Model alone | +0.0315 | −0.0140 to +0.0765 | 61 |
| MC all structured candidates | +0.0843 | +0.0449 to +0.1271 | 27 |
| Model top four + incumbent, then MC | +0.0587 | +0.0294 to +0.0929 | 18 |

These are banker **model-support signed-level units under sampled-world
heuristic continuation**, not gameplay wins or optimal-play values. The model
alone buries 12.0 more points on average than the heuristic; MC/hybrid moderate
that to 4.7/3.7. This is a risk signal to investigate, not proof that burying
points is intrinsically bad. Within-deal model/reference correlation averages
0.274. MC-only remains a serious candidate; no evidence yet that model filtering
improves strength over MC-only.

433,408 reference rollouts cost 169.8 summed CPU seconds. The first timing state
took 1.40 seconds, and the remaining 63 completed in 23.85 seconds on eight Mini
workers. Each state is independently saved; there were no failed states.

Evidence: `/Users/jerryyu/shengji-archive/2026-09-08/bury-value-panel.ihd8VP/`
contains configuration, saved roots, all candidate/world matrices and summary.

## Fixed next comparison

256 **fresh** natural rank-2 deals (namespace
`cwv-bury-dev-20260909-panel-v1`, indices 64–319), each continued to round end
three ways: heuristic, MC-only, hybrid bury. Every seat uses the same W32
checkpoint/settings afterward: W32 ranking, 30 selection worlds, 300 report
worlds, four alternatives plus incumbent, successor reuse, static MLP encoding.
Play RNG seeds are identical across arms and separate from bury sampling.

This compares counterfactual continuations of the same banker situation, not
a mirrored opposing-team duel or multi-round match. Primary gameplay utility
uses the existing screen convention (signed levels, with a win/loss worth at
least one); banker win-rate, attacker points, kitty bonus, latency and work
are separate outputs. Its units are not the diagnostic's half-level support.

The count is a bounded exploratory budget, not a claim of power for a tiny
effect. Report the interval even if inconclusive; do not extend until positive.
First time one complete three-arm deal, preserving it within the same fixed
population. Then use eight safe Mini workers. Save each arm before the next,
retain successful arms across failures, and aggregate once. No duplicate
full reconstruction. Broader ranks, gameplay confirmation and deployment are
outside this first screen.

## Completed fixed gameplay screen

All **256 deals / 768 full-round continuations** completed. The resumed
six-worker Mini run took 3,304.2 seconds (55.1 minutes), in addition to the
retained 49.5-second timing deal. Summed round CPU was 5.386 core-hours.
No population extension, dropped arm, reported failure, short play search or
void fallback occurred. All 492 arm pairs with the same literal bury also had
identical subsequent attempted-play transcripts and attacker-point outcomes.

| Paired comparison | Banker utility gain / round | 95% interval | Banker win-rate gain |
|---|---:|---:|---:|
| MC − heuristic | +0.0430 | −0.0469 to +0.1367 | +1.56 pp |
| Hybrid − heuristic | +0.0469 | −0.0430 to +0.1367 | +1.95 pp |
| Hybrid − MC | +0.0039 | −0.0859 to +0.0898 | +0.39 pp |

All three strength comparisons are **inconclusive**, not equivalence findings.
The win-rate intervals also cross zero. These are nominal, deal-clustered 95%
intervals for exploratory comparisons, not a corrected confirmation gate.
Banker win rates were 57.42% heuristic, 58.98% MC, and 59.38% hybrid. The hybrid
changed 77 of 256 burials versus heuristic; MC changed 117. Hybrid and MC chose
different burials on 82 deals.

### Cost and kitty tradeoffs

| Measure | Heuristic | MC | Hybrid |
|---|---:|---:|---:|
| Mean bury latency | 0.000060 s | 0.304 s | 0.200 s |
| p95 bury latency | 0.000069 s | 0.385 s | 0.242 s |
| Full bury rollouts, total | 0 | 216,288 | 40,960 |
| Model leaf positions, total | 0 | 0 | 216,288 |
| Mean kitty bonus conceded to attackers | 0.234 points | 2.188 points | 1.367 points |
| Rounds with positive attacker kitty bonus | 4 | 18 | 13 |

Model filtering saved **81.1% of bury rollouts**, while adding one-trick model
evaluations, and its observed bury wall was **34.2% lower than MC-only**. Hybrid
spent about 0.137 s on its model stage and 0.062 s on bury rollouts. These are
shared-host measurements, with early overlap from Claude's low-priority
determinism check—not an isolated performance benchmark. Subsequent play
rollouts differed because burials changed trajectories; aggregate round costs
must not be described as a decision-preserving speedup.

Kitty leakage rose in both search arms. The final attacker-point differences
(which already include kitty bonuses) were −1.78 for MC and −1.95 for hybrid
versus heuristic, with intervals crossing zero. The increased kitty exposure
is therefore a real tradeoff in these sampled games, not proof that either arm
is worse overall or that adding an arbitrary kitty penalty would help.

Coverage: all deals were rank 2; natural declarations produced C=57, D=57,
H=77, S=50, NT=15. No claim about other ranks, multi-round matches, or humans.

### Decision

**Keep production heuristic bury. Stop this fixed experiment here.** The model
has some useful ranking signal and reduced the MC shortlist's cost, but this
screen does not establish a gameplay improvement or non-inferiority to MC.
Preserve the implementation and data; any future confirmation or new recipe
needs a separate decision, not an extension until the interval turns positive.

Evidence root:
`/Users/jerryyu/shengji-archive/2026-09-08/bury-w32-screen.FhhNJZ/`
contains exact configuration, command/log, 256 three-arm shards, 768 per-arm
records, `summary.json`, and the read-only `closeout.py`/`closeout.json` cost
analysis. No engine/model replay was performed for closeout.

- `summary.json` SHA256: `d4b58a980d4898a2330a7005a8f02523ea2a35ed023049845596bdc5d0be9018`
- `closeout.json` SHA256: `be377adae6f8776db54f76c6c0ddb56c91d3751b4c821b045c2e632f18492c0d`
- Run source: local `a98599ac309c71d73ed5a3a6baed75346ca7c0cb`, tree-identical
  to PR #323 source head `cf4de21820b33b43ff467eb42d109307ac208fe8`.

## Fixed extension authorized by Jerry — 2026-09-09

After seeing the first result, Jerry requested more samples with pooling and
set a new goal: **768 fresh deals, 1,024 total**. This is a separate, fixed
exploratory extension, not a continuation until significance. Keep all original
evidence unchanged; do not reinterpret the original stopping decision.

- Fresh range: the same natural rank-2 namespace, indices **320–1087**.
  Original gameplay indices 64–319 and diagnostic indices 0–63 are excluded.
- Exactly the same checkpoint, three bury recipes, W32 settings, RNG derivation,
  utility and per-deal pairing. The only runner change parameterizes the starting
  index and binds it in the existing configuration; default behavior remains 64.
- Separate output root; successful per-arm artifacts survive interruption. Use
  eight Mini workers if idle, single-threaded inference per worker. Initial
  estimate 2–3 hours; monitor completion percentage, ETA and failures, not outcomes
  to decide whether to continue.
- Publish original, fresh-only and pooled estimates for all three contrasts.
  Bootstrap complete paired deals, not worlds, candidates or three arms as
  independent samples. Pool by deal count, keeping old and fresh identities.
  Report nominal exploratory 95% intervals, no multiplicity-adjusted claim.
- Preserve latency and work separately by batch (host contention may differ),
  plus kitty bonuses and total outcomes; kitty bonus is already in final points.
- Do not pool the 64-root heuristic-reference diagnostic with gameplay. No
  recipe tuning, additional samples after this fixed endpoint, merge or deployment.

Halving the initial uncertainty is an approximate precision target, not a
guarantee of a positive finding or sufficient power for small effects. The
pooled analysis is explicitly exploratory because the initial outcomes were seen.

## Data-writer integration (September 9, separate from the live screen)

The old DEV bury record could not pass the real trajectory writer: it held a
list of candidate card lists where the writer required scored dictionaries.
New decisions retain the MC means already computed by the chooser. The adapter
exports only MC-scored candidates as the training ballot, with their actual
world counts and local played index. It preserves the complete proposal pool
and model rankings as separate `action_values.bury_search` metadata. Model
signed-level predictions are not substituted for MC's negative-score targets;
unsearched candidates receive no invented targets. Heuristic records have one
action, zero search worlds and a null mean. No new standard errors are claimed.

This is tested through real generated rounds, schema validation, atomic shard
publication/reopen and engine reconstruction of the bury state, not just an
adapter fixture. The factory and evaluator are test-supplied at reduced doses;
these tests do not establish a shipping factory, model accuracy or latency.
The live 512-deal experiment remains on its original source and is untouched.
Its older records are valid gameplay evidence, but cannot be retroactively
turned into MC value labels whose means were never saved.

The integration now also provides explicit `register_cwv_bury_policies`
factories and an opt-in `SHENGJI_CWV_BURY_ARM` environment setting. It reuses
the existing `SHENGJI_CWV_SHORTLIST_*` play recipe and checkpoint loader;
`SHENGJI_CWV_BURY_MAX_CANDIDATES`, `_MODEL_WORLDS`, `_SELECTION_WORLDS` and
`_ALTERNATIVES` control bury only. Both sets of parameters and the full model
SHA enter the named recipe and data manifest. The factory shares the immutable
evaluator, retains the exact play configuration/report budget, and uses the
original play RNG seed. No unqualified `mc-bury` name or default substitution.

The known bury wrapper supports full-legal play-score capture; unrelated
shortlist subclasses remain refused. A real tiny checkpoint, fresh subprocess
and spawned trajectory worker produce and reopen a complete round pair with
both evidence surfaces. Bury helper compute is reported separately in work
counters and runtime timing, without advancing or mislabeling play counters.
Thirty-eight focused integration/registry/capture tests pass in native mode.
These are contract tests, not new strength or target-host performance claims.

The optional serving recipe now takes `serving_budget_seconds` (environment:
`SHENGJI_CWV_BURY_SERVING_BUDGET_SECONDS`). It cooperatively checks expiry
between sampling attempts, model batches/candidates and full MC rollouts, then
unwinds synchronously to the prevalidated heuristic incumbent. Runtime search
errors use the same fallback; invalid callers/illegal incumbents still refuse.
No background thread is abandoned, no partial score matrix is published, and
play RNG is preserved. This is not a hard wall guarantee: queue wait and model
loading precede search, and an in-flight primitive must return before expiry
can be observed. Target-host tail latency must therefore be measured.

Serving-fallback recipes have a distinct bound identity and are refused as
scientific data teachers. The normal data/experiment recipe still fails on
errors (`fallback: raise`). Timing logs distinguish completed/fallback searches
and stale discarded turns; X-ray maps MC finalists correctly and reports
fallback without private error text or invented partial values. Tests reach
the actual off-loop serving snapshot, commit/discard and log consumers.

Still required before shipping: review, target-host latency/queue-tail checks,
and the selected recipe's representative-rank/no-trump evidence. No production
default, running experiment or deployed process changes here.

Serving integration validation:58 focused native bury/serving/X-ray tests pass.
A small real-checkpoint probe on four previously opened DEV roots used the
actual off-loop server path. Torch and compact NumPy matched both shortlisted
candidates and chosen bury on4/4 roots. NumPy compute time was232–291ms and
Torch179–275ms on the busy Mini; this is neither an isolated speed comparison
nor a target-Fly latency guarantee. The probe used a generous30s cooperative
budget solely to test the successful path, not to select a production budget.
Artifact: `/Users/jerryyu/shengji-archive/2026-09-09/bury-serving-probe.cNtfgV/`
(`probe.py`, `result.json`, executed-source delta `source.patch`).

## Fixed 512-deal scaling closeout (September 9)

All six arms completed: 3h10m09s runner wall, 25.27 summed core-hours. The
original source and per-arm artifacts are preserved at
`/Users/jerryyu/shengji-archive/2026-09-09/bury-scaling.6T8g9O/`;
`READOUT.md` and `complete-readout.json` contain all eight contrasts and risks.
Every utility interval crosses zero. Hybrid minus MC is +0.0156
[-0.0547,+0.0859]; this proves neither superiority nor equivalence.

Cap64 only adds proposals in 51/512 deals (mean actual pool 26.36 to 26.65),
changing six hybrid buries at MC32 and seven at MC128. Changed-deal means are
descriptive, not a replacement for the all-deal deployment estimand. Sparse
changes and bootstrap intervals cannot rule out unobserved rare effects.
The nominal doubled cap does not generate 64 distinct proposals.

Hybrid takes 227ms versus MC's 344ms mean bury wall on the busy Mini, with
81,920 full rollouts plus 431,808 model leaves versus MC's 431,808 full
rollouts. Do not call this a 5.27x total-work speedup. Cap64 alone is nearly
cost-neutral at 228ms; MC128 costs about 432ms for hybrid, without supported
strength gain. No broader scaling grid follows. Retain baseline hybrid as the
candidate by parsimony, not as a statistically established MC replacement.

Source/consumer PASS at PR323 head146be958 is closed and exact-head CI passed.
Production still uses heuristic bury; default data-teacher and production
shipping remain HOLD. All-rank functional Torch/NumPy checks passed 65/65
rank/suit fixtures, but those engineered roots are not strength evidence.

## One focused all-rank confirmation — plan before new outcomes

Question: does the earlier hybrid-versus-heuristic advantage generalize beyond
rank2 to an explicitly balanced established-banker population? This is one
fixed replication, not an extension until significance or a new recipe sweep.

- Exactly **1,040 fresh independent deals**, indices0–1039 in namespace
  `cwv-bury-allrank-confirm-20260909-v1`. Rank is `RANKS[index % 13]`;
  initial banker is `(index // 13) % 4`: 80 deals per rank, 20 per rank/seat.
  Construct the actual engine Round with that rank and known banker, then use
  unchanged production declaration decisions. Keep all deals: no suit/NT,
  candidate-count, model-score or outcome filtering. Report natural NT count.
- This is a balanced research population, **not an estimate of human game
  frequencies**, nor a complete multi-round match. Known banker models an
  established game, unlike the earlier opening-deal population. Both changes
  are population coverage, not changes to the tested decision policy.
- Three arms only: literal heuristic incumbent; full-pool MC32; baseline
  hybrid cap32/model32/incumbent+4/MC32. Identical W32 post-bury play and
  per-seat play seeds across arms. Pin source checkpoint
  `3cd277160322b30e9a61d5d83cb7fb6bceac6887ab1e899b98a42f15b259d600`.
  No checkpoint selection, candidate generation change or serving fallback.
- Primary comparison: hybrid minus heuristic signed banker utility. Estimate
  the equal-weight all-deal mean with 4,000 deterministic paired bootstrap
  replicates **within each fixed rank/initial-banker stratum**. Publish a
  two-sided nominal95% interval. A positive lower endpoint supports replication
  on this population; otherwise record it as unsupported/inconclusive. Never
  extend the count based on the result. All other contrasts, win rate, points,
  rank and NT breakdowns are descriptive/secondary, not alternative routes to
  a primary win. MC comparison is not an equivalence test.
- The earlier fresh768 hybrid-minus-heuristic CI suggests SE about0.025;
  scaling unchanged variance to1040 gives SE about0.021 and an approximate
  two-sided80%-power detectable difference near0.06. New ranks may have higher
  variance; this is a planning estimate, not guaranteed power. The replication
  is not sized to resolve the observed approximately0.016 hybrid-minus-MC gap.
- Publish actual coverage, paired kitty bonus/total attacker points, nonzero
  and80+ bonus frequencies, maximum bonus, model leaves/full rollouts, and
  bury-only/whole-round time separately. Kitty bonus is already in total points.
  Retain losing and fallback/error cases; no fabricated labels from partial MC.

### Execution and recovery

Expected Mini cost from completed real paths: about26 core-hours for3,120
rounds, approximately3.3h at8 single-threaded workers; plan3–5h for changed
rank complexity. Use a clean dedicated source tree and the existing atomic
per-arm/per-deal resume path. Complete one8-deal timing slice under this exact
fixed population, then reuse it in the full invocation—no throwaway rehearsal
or outcome-based dose selection. The slice checks legal completion, resources,
and model/runtime compatibility, not strength. Report percent/ETA on the
existing runner; report terminal errors and preserve all completed arms.

The DAG is root/declaration → three sequential counterfactual rounds per deal,
with eight independent deals in parallel → one saved-data summary. No retraining,
reference regeneration, duplicate full scoring or second expensive verifier.
If code repairs change semantics, reopen only compatible completed artifacts;
never combine source-incompatible rounds under one recipe. A resource failure
does not authorize erasing valid work or silently increasing the population.

### Separate ship decisions

Successful replication supports an **opt-in data-generation recommendation**,
subject to the already tested real writer, explicit recipe identity and honest
MC-finalist targets. It does not establish superiority over MC-only or optimal
labels. A null leaves default generation on heuristic; retain experimental
access and results rather than claiming a failed pipeline.

Production additionally needs the prepared actual-consumer compact-NumPy Linux
test at1CPU/512MiB, concurrency1, with cold-load/RSS, serial and queued-burst
latency, event-loop health, legal forced fallback, commit and logging evidence.
This bounded measurement is not a production p99 guarantee. Choose a disclosed
serving budget only after observing that non-strength probe. Any canary must
remain opt-in, record completion/expiry/error and stale-turn rates, and roll
back on illegal commit, play-RNG drift, OOM/crash or unacceptable queue delay.
Rollback disables bury only, retaining the existing W32 play model and logs.
**Jerry must explicitly approve deployment; no screen result deploys itself.**
