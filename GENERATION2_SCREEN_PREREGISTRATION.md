# Generation-2 screen: pre-registration

**Written 2026-09-17 11:1x ET, while generation 2 is at epoch 5 of 20 and its weights do not
yet exist.** That timing is the whole point of this document. It fixes the arms, the deals, both
outcome scales and every decision rule *before* any generation-2 number can be looked at.

Related: #421 (the loop and its gating rule), #487 (the tie-rate finding), #425.

## Why this exists

Two things happened in the last day that make an ordinary screen insufficient.

1. **Generation-1 was a null** against production on levels, by two designs that disagreed in sign
   (+0.0136 and −0.0131). The gating rule on #421 predicted that at 7.9% new-teacher corpus share,
   and generation 2 at **20.5%** is the first run the rule permits.
2. **A post-hoc look at the attacker-points scale on generation-1's already-analysed deals produced
   +0.5106 [+0.031, +0.990], which excludes zero.** That is a garden-of-forking-paths result and was
   explicitly refused as evidence. The only thing that can turn it into evidence is a scale declared
   in advance on data that does not yet exist. This document is that declaration.

This project has been burned once by quoting a zero-excluding interval that later failed to confirm
(release 28's +0.0239 on a shared control). The discipline below is the response to that.

## Arms

| role | recipe |
|---|---|
| **arm** | generation 2 (`JS2-M1-policy-w0.2-gen2`) as ONE package: value net + its own policy head as the admission prior |
| **control** | the production recipe, JS-M1 `a5248cc5` as one package, `JS-M1-joint1k-out` |

Both at **threshold 1,000 / top 256, hybrid bury, capped `--decision-deadline 300`**, both against the
fixed yardstick `mc-s0-report-lcb`, both in the same lane on the same host. The contrast is the
difference of the two arms on shared seeds, as always.

Generation 2 is **parameter-matched** with JS-M1 and generation-1 (653,532 parameters, verified) and
**NOT compute-matched** — more rows per epoch, and the trainer's own patience decides how many epochs
are kept. Any comparison must say so.

## Deals — fixed now

Five fresh windows of 520 clusters: **16760910, 16860910, 16960910, 17060910, 17160910**.

Verified disjoint from every window spent to date on the Mini, `shengji-perf` and `shengji-cloud`
(used blocks run 13260910–13660910, 13760910–15160910, 15260910–15660910, 15760910–16660910). Each
window spans 520 consecutive seeds and the spacing is 100,000, so overlap is impossible by
construction.

If a window has to be replaced for an operational reason, the replacement is the next unused
multiple of 100,000 and the substitution is recorded here **before** that window is read.

## Outcome scales — both declared, one decides

**PRIMARY, and the only promotion criterion: signed level utility per round.**
Pooled DerSimonian-Laird across the five windows, as `vol_re.py` computes it. MDE80 ≈ 0.032.

**SECONDARY, declared in advance: signed attacker points per round.**
`+attacker_points` when the arm is the attacker, `−attacker_points` when it is the banker, summed over
a cluster's two mirrors exactly as levels are. Expected MDE80 ≈ 0.7 points on the same five windows,
from the two sealed contrasts measured on 09-17.

Levels remain the criterion because levels are the objective. Points are a finer ruler for the same
quantity — measured at 31.6 and 39.0 points per level across two independent contrasts — but nobody
has established what a points gain is worth in levels, so nothing is promoted on points alone.

## Decisions, fixed in advance

1. **Triage.** Five windows first. Extend to ten only if the **level** point estimate exceeds
   **+0.015**. The points scale does not trigger an extension.
2. **Promotion.** Nothing is proposed for deploy on this screen alone. A deploy request requires the
   level-scale interval to exclude zero on fresh deals *and* Jerry's go, as always.
3. **The generation-1 points hypothesis.** The specific claim under test is that generation *n*
   beats its predecessor on the points scale where the level scale cannot resolve it. It is
   **supported** only if generation 2's points interval excludes zero **in the positive direction**.
   Any other outcome — a null, or an interval excluding zero negatively — is recorded as the
   hypothesis failing to confirm, and the generation-1 post-hoc result stays refused permanently.
4. **Sign agreement is a reportable check, not a filter.** If the two scales disagree in sign on
   generation 2, that is reported prominently as evidence against the points scale being a finer
   ruler for the same quantity, and #487's proposal is weakened accordingly.
5. **Tie fractions on both scales are reported** whatever the result.

## What would falsify what

| outcome | reading |
|---|---|
| level interval excludes zero, positive | the loop works at 20.5% share; the first real generation gain |
| both nulls, scales agree in sign | the **first informative null** (#421 rule 4): the question becomes whether the teacher must be *stronger*, not merely more sampled |
| levels null, points positive and excluding zero | the generation-1 hypothesis confirms; points becomes a candidate criterion and needs a points-to-levels conversion before anything is promoted on it |
| scales disagree in sign | #487's core claim is damaged; investigate before trusting either scale further |

## What this document does not cover

It does not pre-register the offline reads (fixed external holdouts, head recall against prior v3).
Those are diagnostics, not decisions, and rule 3 on #421 already says the in-play paired contrast
decides. It also does not fix the wall-cost comparison, which is descriptive.

Readout tooling: `scratchpad/vol_re.py` (levels) and `scratchpad/points_vs_levels.py` (both scales,
self-tested against `vol_re.py`'s per-window output). Readouts are archived under
`~/shengji-archive/2026-09-13/readouts/` with SHA256SUMS.
