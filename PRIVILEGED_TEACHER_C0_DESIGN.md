# Privileged Teacher C0 — full-play consumer diagnostic

Status: open-DEV mechanism design. This document grants no scientific,
strength, gameplay, training, promotion, deployment or merge authority.

## Why this precedes another belief run

BELIEF and its gameplay consumer answer different questions. A calibrated
posterior can identify which opponent is likely to hold an ace, pair, trump or
point card. A policy must still put the safer action on its ballot and assign
that action a better continuation value. PT-Full measured the ceiling of the
current consumer: replacing every sampled world with the exact true world did
not beat public production (`B-A = -3/52` signed levels), even though the true
world repaired the severe single-world-collapse control (`B-A0 = +44/52`).

C0 therefore asks:

> With the same exact hidden world, which smallest policy-side change lets the
> bot convert that information into stronger full-round play?

This is a prerequisite to treating a positive BELIEF result as gameplay-ready.
It is not a substitute for measuring whether BELIEF predicts hidden hands.

## Frozen parent and population reuse

C0 reuses the 26 open-DEV roots from the sealed PT-Full report rather than
generating or selecting another population. The external SHA-256 and internal
report SHA-256 of that report, its source Git, seed commitment, native binary
and all 26 root hashes are inputs. The same mode-0600 seed secret reconstructs
each root; execution refuses before playing if any reconstructed root hash
differs from both role records in the parent.

This reuse is legitimate because the roots are already open DEV. It saves the
public A, repeated-world A0 and exact-production B arms from being replayed.
It cannot support a strength claim or a held-out confirmation.

## Arms

The parent supplies **A** (public production) and **B** (exact world with the
unchanged production policy). C0 adds three treatment-partnership arms. In all
three, opponents remain exact `mc-s0-report-lcb` public production.

1. **C0-P — exact deterministic production ballot.** Use the true world, the
   production candidate source and one deterministic rollout per candidate.
   Remove the redundant 30+300 repetitions of the identical true world, use
   signed level outcome rather than raw points, set the override margin to
   zero and preserve production's tractor lock. `C0-P - B` isolates the
   noisy/fallback/objective decision rule from candidate sourcing.
2. **C0-H — widened exact search, heuristic continuation.** Starting from
   C0-P, unlock tractor leads and retain the current candidate source plus all
   legal pairs, strategically distinct lead singles, bounded risky throws,
   trump leads and up to 64 legal follow candidates. Continue with the current
   deterministic HeuristicBot. `C0-H - C0-P` isolates ballot coverage.
3. **C0-S — widened exact search, SmartBot continuation.** Identical to C0-H
   except the named public-style continuation is SmartBot. `C0-S - C0-H`
   isolates continuation quality without changing hidden information, ballot
   or objective.

One exact world means repeated rollouts are byte-identical; spending 330 draws
per contested decision would add no information. Every contested C0 decision
must instead prove exactly one accepted world, exactly one rollout per emitted
candidate, zero report work and no fallback. This is an efficiency correction,
not a claim of work parity with A or B.

## Bare-point sentinel and mechanism telemetry

The player-reported bare-10 failure is a named sentinel, not a hard-coded
policy rule. For every treatment decision C0 records aggregate, hidden-free
counts for:

- contested decisions and candidate population;
- selected action differing from candidate zero;
- selected action outside the production ballot;
- lead decisions where a point-bearing incumbent is replaced by a zero-point
  action (`bare_point_avoidance`);
- the reverse direction (`bare_point_introduction`); and
- positive/zero/negative exact rollout gap versus candidate zero.

The sentinel is deliberately evaluated on final signed-level return. If an H10
is doomed later and leading it now does not change the round, C0 should not be
credited merely for making the locally attractive-looking move.

## Outputs and decisions

Each of the 52 mirrored role records contains the parent A/B terminal outcomes,
the three C0 terminal outcomes, their signed-level contrasts, work receipts and
aggregate mechanism telemetry. It publishes root hashes but no hands, burial,
deck order, seed, policy RNG state or per-decision cards.

The first run is a mechanism ladder:

- if no C0 arm improves on B and A, the current rollout family is not a viable
  belief consumer; next work is bounded-depth partnership search, not a larger
  belief model;
- if C0-P improves, objective/fallback logic was binding;
- if C0-H adds value, ballot coverage was binding;
- if C0-S adds value, continuation memory/judgment was binding; and
- a bare-point avoidance count without positive full-round contrast is a UX
  change, not strength evidence.

Select at most one C0 recipe from this DEV ladder. A selected recipe must then
face public production on **128 fresh independent roots**, balanced over all 13
trump ranks and both treatment roles, with paired common setup/policy streams
and root-clustered uncertainty. The fixed confirmation reports 64 and 128-root
looks but makes no early selection from outcomes. A public-information
extra-compute control is required if the selected recipe uses more distinct
search work than production.

## Isolation, review and stopping

C0 runs only on Mini and reads only the sealed PT-Full report plus its external
seed secret. R4 and R5 source, evidence roots, models, registries, markers and
hosts are forbidden inputs. One consolidated source review covers this design,
runner, exact-work verifier, parent/root binding, privacy walk and tests. No
rehearsal loop is required: the first execution is open DEV and must publish
progress after every completed root.

The lane stops after the DEV read unless at least one arm has positive mean
signed-level contrast versus both A and B and the mechanism telemetry proves a
nonzero causal dose. Passing that screen authorizes only a fresh confirmation
design; it does not authorize training, belief integration or deployment.
