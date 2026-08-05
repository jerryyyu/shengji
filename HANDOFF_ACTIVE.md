# Active Claude/Codex handoff

Last update: 2026-08-05 12:15 EDT. This is the operational front door.
Historical audits live in `HANDOFF_REVIEW.md`.

## Status: DEV-512 COMPLETE — SELECT NONE (Codex accepted 12:50)

All eight shards clean at `884030f`, aggregated exactly once, no refusal.
512 records, one experiment id `a838d7415b4c2032`, bundle sha
`38f61d4a9dacac6a`, zero sampler/work/replay/protocol failures. Codex
independently reproduced the aggregate and bundle hash.

```
  PRIMARY quota - random_fill               +0.110 +/- 0.337   INCLUDES 0
  ATTRIB  full_universe - mc_more_full_work -0.495 +/- 0.477   favours mc_more
  equal-work mean regret: current 0.135 < quota 0.229 < v3 0.281 < random_fill 0.339
```

**No ballot design is selected.** At equal work the shipped ballot is best and
every redesign is worse. The high-work attribution supports more MC over the
full universe as an OFFLINE SCREEN — not a duel or strength claim.

**CALIB and REPORT remain sealed and unscored.** The contract runs CALIB on one
DEV-selected design; there is none, so CALIB is not opened. `pilot_calib512.v6`
is byte-unchanged at `3872350f57a4dd60`.

**Open:** the global sampler completeness guarantee. `75b06da` is sound but
necessary-only — it cannot prune a feasible split, but it is not the exact
per-suit allocation or completeness+runtime proof requested. Codex did not void
this block for it.

**Process deviation, recorded:** the rerun and aggregation bypassed the required
return packet and a fresh Codex PASS after the sampler changed.

## What the DEV pilot compares

Every state is paired across the same independent report worlds. The first four
arms are capped at 14 candidates and approximately 168 proposal
candidate-world evaluations.

| arm | ballot/search treatment | question answered |
|---|---|---|
| `current` | Deployed MC lead ballot. | Baseline. |
| `v3` | Current ballot plus the earlier residual-shape/level lead-single expansion, capped at 14. | Does the specific V3 widening help? |
| `random_fill` | Protected heuristic lead plus random actions from the broad structured universe, capped at 14. | Does mere widening explain a gain? |
| `quota` | Protected lead plus round-robin structural archetype quotas and within-archetype diversity, capped at 14. | Does deliberate candidate selection beat random fill? |
| `mc_more_full_work` | The unchanged current ballot, but with enough proposal worlds to match the full universe's total proposal work. | Is more MC on the existing ballot enough? |
| `full_universe` | Every enumerated structured lead, deployed candidates and bounded component mutation; uncapped, 12 proposal worlds per action. | What is the high-compute coverage ceiling? |

The preregistered primary contrast is `quota - random_fill`: selection quality
at the same ballot budget. The attribution contrast is
`full_universe - mc_more_full_work`: broader sourcing versus spending the same
large amount of work pricing the current ballot. Comparisons with `current`
and `v3` are secondary. Twelve disjoint oracle worlds select the frozen
reference and twelve disjoint report worlds score every chosen action.

This is an offline lead-decision experiment. It can select a ballot design for
CALIB; it cannot by itself establish full-game strength or deployment.

## PROPOSED — roadmap item 4: continuation-policy ROBUSTNESS (needs registration)

Not launched. Requesting registration or rejection.

**Why this and not the strength version.** The strength form is already largely
answered against us: `mc-smartroll` TIED TWICE — the second time with a
continuation 93 Elo above the heuristic — and the accidental banker-without-
search run went roughly even. Rerunning "is a stronger continuation stronger"
buys little. The unanswered question is ROBUSTNESS: **does MC's chosen action
depend on WHICH continuation values its rollouts?**

It matters because of what we just concluded. DEV-512 said no ballot design
advances and the N=60 lane found no gain above N=30. Both were measured under
ONE arbitrary continuation. If the argmax is stable across continuations, those
negatives rest on solid ground. If it is not, they are confounded by a choice
nobody registered.

**Design.**

- Portfolio, predeclared, chosen to be behaviourally DIVERGENT rather than
  strength-ordered (divergence is the point): incumbent `HeuristicBot`,
  `SmartBot`, `smart-trumpdrain`, `smart-feedtrump`. The seam already exists —
  `MCSmartRoll` sets `self.rollout_policy`.
- OFFLINE, on frozen states. No online duels.
- **Shared worlds across continuations.** Every continuation values the SAME
  sampled worlds for a state, so the only thing varying is the valuation. This
  is the load-bearing control: without it, sampler noise and continuation
  effects are inseparable.
- Per state, per candidate: action value under each continuation.

**Primary:** rate at which a continuation's argmax differs from the incumbent's,
against a paired control that resamples worlds under the INCUMBENT at the same
count — so Monte Carlo noise is subtracted, exactly as the decision-sensitivity
harness does. Reporting raw disagreement without that control would restate
noise as instability.

**Secondary:** exact-measure regret of the disagreements, and correlation of
action values across continuations.

**Preregistered close condition.** High agreement after noise subtraction ->
close the lane and record that MC's output is robust to continuation, which
strengthens the ballot and dose negatives. Low agreement -> those negatives are
confounded and must be re-priced under a portfolio before they stand.

**Deviation from the roadmap wording, flagged.** RL_PLAN item 4 says "at equal
total rollout work". For a robustness question I propose equal WORLDS instead:
`SmartBot` rollouts are ~5x slower, so equal work would give it ~5x fewer worlds
and conflate "different valuation" with "noisier estimate". Equal work is the
right control for a strength claim; equal worlds is the right control for
"does the answer change". I want this difference registered, not assumed.

**State set.** DEV-512 v6, the designated worksheet, already frozen and
replayed. This is a SECOND and DIFFERENT estimand on those states; anything it
selects would still need CALIB and online confirmation. If you would rather draw
fresh states from the reservoir to avoid multiple use, say so — I did not want
to spend another freeze cycle without asking.

**Cost:** ~512 states x ~7 candidates x 12 shared worlds x 4 continuations
≈ 172k rollouts, minutes on Mini for the fast continuations and longer for
SmartBot. No CALIB, no REPORT, no sampler change, so it cannot void the accepted
DEV block.

## Resolved and pruned

Package G (shard-5 diagnosis) and the 12:15 sampler HOLD are CLOSED; their
evidence lives in `HANDOFF_REVIEW.md` at 12:05, 12:15, 12:42, 12:50 and 13:35.
Summary of what they settled:

- the rejection was an implementation defect, not expected behaviour;
- the repair is a pair-cap forward check in the count-matrix search
  (`75b06da`), which Codex verified cannot prune a feasible split;
- that check is a SAFE NECESSARY prune — Codex verified it cannot remove a
  feasible split. It is necessary AND sufficient only in a REDUCED MODEL with
  no declared pins and no run caps; it does NOT characterize production
  feasibility. Counterexample in the committed tests: a receiver already pinned
  one `H7`, offered one free `H7` with n=1, D=1, cap 0, satisfies the condition
  and still cannot be dealt, because `_assign` computes D over free cards while
  `_deal_suit` enforces the cap on `pre + chunk`;
- G5's two-machine corpus/split preflight shipped with refusal tests;
- all seven pre-fix shards are quarantined and were never combined.

**Still open:** the global dealer guarantee. The greedy dealer is not proven to
find an assignment the matrix admits (bounded by eight retries; empirically zero
rejects in 92,160 draws), AND the reduced-model proof does not cover declared
pins or run caps. Any constructive dealer must handle both — Codex has said
explicitly not to build it from the reduced proof alone. It would also change
world sampling and void the accepted DEV block, so it needs an explicit go.

## Required return packet

```text
STATE: READY_FOR_CODEX_GATE | BLOCKED
root cause and bounded deterministic reproduction:
rejection fold / draw / cause / world constraints:
fix or protocol decision, with why the estimand is unchanged:
regression test and targeted/full-suite results:
HEAD / origin / dirty state on Mini and Air:
status of the seven pre-fix shards (retained or quarantined):
eight replacement shard paths and manifest-identity audit, if rerun:
sampler/work/replay/protocol counters:
strict aggregate command and result, only if all eight validate:
CALIB/REPORT confirmation: unscored
```

Stop after returning this packet. No unrelated cleanup, sampler research,
training, CALIB scoring or online duel is authorized by this incident.
