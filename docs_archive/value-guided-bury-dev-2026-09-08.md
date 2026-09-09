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
