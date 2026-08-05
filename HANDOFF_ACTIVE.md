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

## PROPOSED v3 — item 4 continuation robustness (HOLD; revised per 15:55)

Not launched. The v2 gate was on the WRONG quantity; corrected below.

**The gate now sits on RAW disagreement.** v2 put the 0.05 bound on
control-subtracted EXCESS disagreement. Codex's counterexample kills that: 20%
raw disagreement minus an 18% incumbent-resample rate passes a 5% excess bound
while ONE ACTION IN FIVE still changes when only the continuation changes. The
question is raw shared-world action stability, so:

- **PRIMARY gate:** upper 95% bound of RAW disagreement vs the incumbent
  < 0.05, for every portfolio member.
- **SECONDARY, attribution only:** excess over an incumbent-resample control at
  the same world count, to say how much of any instability is continuation
  rather than Monte Carlo noise. It no longer gates anything.

**Three specifications v2 left undefined:**

- **Independent oracle-selection fold.** The regret reference must be chosen on
  its OWN fold, never on the report worlds. Selecting the best action on report
  worlds restores the same-world maximum bias that invalidated the original
  high-N labels. Folds: `proposal` (selection), `oracle` (reference selection),
  `report` (scoring), mutually disjoint — the existing `draw_folds` machinery
  already provides exactly this.
- **Exact report-world count:** 12 report worlds per state, matching the
  registered pilot budget, declared before any run.
- **CI procedure:** per-state disagreement indicator, one state = one cluster =
  one deal; mean over states; 95% interval from the state-level clustered
  standard error, reported as an upper bound for the gate.

**Unchanged from v2:** portfolio (heuristic, SmartBot, smart-trumpdrain,
smart-feedtrump); deployed `choose_action` semantics with ties resolved by that
rule; fresh frozen primary from UNSELECTED DEV-split deals with DEV-512 only as
a labelled post-hoc secondary; CALIB and REPORT sealed.

**Still my recommendation to REJECT rather than run.** Its best outcome tightens
the interpretation of results we already hold without moving the RL-beats-MC
goal. I have specified it properly so the decision is on merit, not on an
under-specified design.

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
