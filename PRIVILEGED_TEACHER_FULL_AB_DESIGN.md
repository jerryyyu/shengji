# Privileged Teacher Full-Play A/B — information-value screen

Status: DEV diagnostic design. This document grants no scientific execution,
strength, gameplay, promotion, deployment, merge or training authority.

## Question

PT1 found almost no exact-search headroom in natural three- and four-card
endgames even though the exact teacher frequently changed the selected action.
That result does not answer whether complete hidden information helps when it
can influence an entire round. This screen asks the cheapest preceding
question:

> From the first ordinary-play decision after burying through round end, can
> the current production search turn the true hidden world into higher paired
> signed-level return than the same search using public information?

No learned teacher is included. A learned or search-improved `C` is admitted
only after this screen measures the baseline information gap and diagnoses how
the current policy uses it.

## Arms

Every arm starts from byte-equivalent post-bury `Round` state and uses the same
per-seat policy seeds, production ballot, `N=30`, `R=300`, LCB rule and rollout
policy.

1. **A — public production.** All four seats use unmodified
   `mc-s0-report-lcb` and its constraint-consistent public sampler.
2. **A0 — repeated public world.** The treatment partnership uses the same
   production policy, but the first ordinary public-compatible sampled world
   at each decision is repeated for every candidate and report rollout in that
   decision. Opponents remain arm-A production. This controls for collapsing a
   distribution to one world without revealing the true one.
3. **B — repeated true world.** The treatment partnership uses the same
   production policy and work budget, but every determinization is the exact
   current hidden world, including the buried kitty. Opponents remain arm-A
   production.

The causal contrasts are `B-A0` (correct-world information), `A0-A`
(single-world collapse) and `B-A` (total operational oracle ceiling). They may
not be substituted for one another.

## Population and mirroring

The first bounded DEV run uses 26 independent post-bury roots:

```text
13 trump ranks x 2 fixed banker-seat representatives x 1 replicate
```

Each root is generated once by ordinary production declaration and bury
policies. It then produces five complete round continuations: A once, plus A0
and B with the banker partnership treated, and A0 and B with the attacker
partnership treated. This yields 52 role-mirrored comparison records and 130
complete played rounds.

Round seeds and all policy streams are SHA-256-derived from a private 256-bit
run key plus the named DEV namespace, coordinate and seat. The key is a
mode-0600, single-link external input; only its SHA-256 commitment is
published. Thus the result binds one deterministic population without making
its hidden deals reconstructible from the public report. The population is
disjoint from PT0/PT1 and BELIEF test namespaces. No coordinate may be
selected, repeated, dropped or retried based on an action, score, point total
or contrast.

## Outputs

Each record publishes only the coordinate, root identity hashes, terminal
attacker points, signed-level utilities, contrasts and aggregate work counts.
It never publishes hands, burial, deck order or raw RNG state. Progress is
published after every root as completed roots, total roots, basis points,
elapsed wall time and ETA.

The DEV diagnostic reports:

- mean and positive/zero/negative counts for all three contrasts;
- role and rank slices;
- whole-round search, rollout, sampler-attempt and accepted-world work;
- elapsed wall time (host-level capacity receipts account CPU separately); and
- whether every root and both treatment roles completed.

Every contested decision must publish a complete production decision record:
30 selection worlds per candidate, the full independent 300-world paired
report fold, exact total rollouts, and reconciled sampler counters. Any short
search, zero-world fallback, incomplete report fold, missing contested-search
dose, or aggregate mismatch refuses the whole DEV result rather than sealing a
weaker arm as COMPLETE.

This first run is descriptive and cannot make a strength claim. Its purpose is
to measure effect size, variance, dose economics and capacity before any fresh
held-out paired design.

## Interpretation and next step

- `B > A` with a useful effect: today's search can use hidden information;
  BELIEF has a plausible gameplay consumer.
- `B ~= A` but a later compute-only C0 improves: search/continuation quality,
  rather than information availability, is the binding constraint.
- `A0` differs materially from A: interpret B only relative to A0 until the
  single-world-collapse effect is understood.
- B changes trajectories without return gain: diagnose ballot and continuation
  value before training a model.

Only after reading this run may a separate C0 DEV ladder test 2x/4x search,
wider ballots, stronger rollouts or an exact PT1 tail. A learned full-state
teacher remains later work.

## Isolation and review

Mini is the only host for this DEV run. R4, R5, their roots, runtime identities,
registries, populations and review markers are forbidden inputs. One source
review should cover the complete runner and its tests; no repeated rehearsal is
required. Any later held-out scientific screen requires one consolidated
source-and-freeze review.

The runner binds the exact clean Git head, Mini hostname, compiled native
binary hash and private-seed commitment into the report before execution.
