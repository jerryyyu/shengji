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

## PROPOSED v2 — item 4 continuation robustness (HOLD; revised per 14:49)

Not launched. Four errors in v1 are corrected below rather than argued.

**Correction 1 — I repeated the superiority/equivalence error.** I wrote that
the strength form was "largely answered against us" because `mc-smartroll` tied
twice. Those are FAILED SUPERIORITY tests; they are not equivalence evidence.
The right statement is that no continuation has been shown stronger, not that
continuation strength is known not to matter.

**Correction 2 — a common continuation is not a confounder.** I claimed DEV's
SELECT NONE and the N=60 null were "confounded" by an unregistered continuation.
Wrong: a continuation held common across arms DEFINES the conditional estimand.
Instability would show limited TRANSPORT or an interaction — it would not
invalidate either contrast. The revised claim is scoped accordingly.

**Correction 3 — plain argmax is the wrong decision rule** for a claim about
shipped MC. The measured decision must apply deployed semantics: `MARGIN` /
`LEAD_MARGIN`, `POINT_SHY_EPS`, and candidate-0 protection, via
`choose_action`. Plain argmax measures a policy nobody runs.

**Correction 4 — this cannot strengthen N=30/N=60.** A 12-world, lead-only
assay says nothing about a full-game dose result. That needs a separate
continuation-by-dose design, which I am NOT proposing here.

### Registered claim, scoped

Does the DEPLOYED lead decision change when only the continuation policy
changes, holding worlds fixed? Nothing more.

### Preregistration

- **Portfolio** (behaviourally divergent, not strength-ordered): incumbent
  `HeuristicBot`, `SmartBot`, `smart-trumpdrain`, `smart-feedtrump`.
- **States — fresh frozen primary.** The DEV split holds 4,354 deals and
  DEV-512 consumed 512, so freeze a new-salt 512-state set from DEV-split deals
  NOT selected into v6. That is genuinely fresh, keeps CALIB and REPORT sealed,
  and reuses the proven freezer. **DEV-512 is a POST-HOC SECONDARY audit only**,
  labelled as such.
- **Worlds:** shared across continuations within a state; proposal worlds for
  selection, DISJOINT report worlds for scoring.
- **Decision rule:** `choose_action` with deployed `MARGIN`/`POINT_SHY_EPS`/
  candidate-0. **Tie rule:** ties are resolved BY the deployed rule; agreement
  is measured on the final chosen action, never on a raw value ordering.
- **Primary:** continuation-attributable excess disagreement = (disagreement of
  continuation c vs incumbent) minus (disagreement of an INCUMBENT-RESAMPLE
  control at the same world count). One state = one cluster = one deal;
  aggregate at state level; 95% CI clustered by state.
- **Equivalence bound, numeric and preregistered:** claim stability only if the
  UPPER 95% bound of excess disagreement is **below 0.05** for every portfolio
  member. Above 0.05 -> report limited transport, not invalidation. A point
  estimate near zero with a wide interval is NOT stability — that is the
  N=60 mistake and I will not repeat it.
- **Regret:** under a NAMED continuation-specific reference — for continuation
  c, the best action under c — evaluated on the disjoint report worlds.
- **Cost, including the controls I omitted in v1:** 4 continuations + 1
  incumbent-resample control = 5 selection passes, plus report passes, over
  ~512 states x ~7 candidates x 12 worlds. SmartBot-family rollouts are ~5x
  slower, so budget the run by wall clock rather than by world count.

### Open for you

Whether a fresh freeze from unused DEV-split deals is acceptable as the
confirmatory primary, or whether this should wait entirely. I am not launching,
and I am not freezing anything, until this is registered or rejected.

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
