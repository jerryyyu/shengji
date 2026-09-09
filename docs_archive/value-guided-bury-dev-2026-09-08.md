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

Still required before shipping: explicit recipe/checkpoint registration and
manifest identity, compatibility with full-legal play-score capture, a bounded
serving fallback and target-host latency checks, plus the selected recipe's
representative-rank/no-trump evidence. No production default changes here.
