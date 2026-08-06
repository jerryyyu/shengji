# Ballot Generation Plan

## Objective

Build the strongest verified Shengji bot. Deployment latency is not an
optimization target; record compute so experiments are attributable and the
production cost is understood, but prefer a slower policy when it is proven
stronger.

The current `MCBot` is generate-then-evaluate: `_candidates()` constructs and
truncates a small list, then MC rollouts price only that list. Search cannot
discover an action that generation omitted. The replacement must separate
legal action generation, strategic proposal, candidate selection, and final
evaluation.

## Outcome — 2026-08-05

The registered lead-ballot experiment completed its DEV stage and selected
**NONE**. Across 512 frozen states, quota minus random-fill was
`+0.110 +/- 0.337`; at equal work the shipped ballot had the lowest mean regret,
and the resolved high-work contrast favoured putting extra MC on the incumbent
ballot over brute-force full-universe expansion. CALIB and REPORT remain sealed
because no DEV design earned advancement.

This is what the 512 states were for: reject an obvious ballot-design win
cheaply before spending on full games. They were never training data and cannot
prove online strength. At the observed variance, 2,048 comparable rows would
still have a primary half-width near 0.169; resolving a 0.10 offline regret
effect would need roughly 5,800. Do **not** append to inspected DEV, open CALIB
without a selected design, or cycle more proposal arms through the worksheet.

The result rejects these registered selectors, not every possible action-search
idea. Ballot-related strength work now moves to three different estimands:

1. confidence-aware/adaptive allocation on the incumbent ballot;
2. a new deep counterfactual teacher/challenge asset outside all evaluation
   splits; and
3. structured bury search, where the once-per-round action set can afford a
   much wider proposal budget.

Fresh paired full games—not a larger DEV worksheet—remain the promotion gate.

```text
reachable state
    -> lazy canonical legal actions
    -> protected actions + archetype/diversity proposal
    -> optional proposal-world search
    -> fixed selected ballot
    -> disjoint common-world MC evaluation
    -> action
```

Do not train a model until the non-learned ballot contract is stable.

## Using the completed high-N corpus

`rl_data/highn_corpus.jsonl` is valuable primarily as a **rebuildable state
reservoir**. Its 20,000 rows rebuild exactly under the current engine and its
stored current-MC candidates replay exactly. It must not be treated as a
finished oracle for the new ballot:

- it contains only the old capped `_candidates()` actions, so it has no value
  label for an action the new proposer discovers;
- generation used the old sampler's unconstrained final retry and did not
  record void fallbacks; `pair_void` was not enforced;
- the apparent best, gap, and `significant` flag were selected and measured on
  the same 240 worlds, with no multiple-comparison correction;
- labels are expected raw round points under `HeuristicBot` continuation, not
  a scoring-bracket distribution or expected signed level utility;
- four states were saved from each of 5,000 deals and collection stopped after
  the fourth sample: median ply is 6, 90% are at ply 15 or earlier, and only 48
  rows are later than ply 31.

Use it as follows:

1. Freeze deal-grouped train/calibration/report assignments before fitting
   anything. Keep all four rows from a seed together and store the split file.
2. Use the development deals for static current/quota/random ballot coverage,
   determinism, and candidate-distribution analysis.
3. Select a small stratified lead subset, at most one state per deal, and add a
   newly generated late-game supplement. Re-evaluate the union of current and
   newly proposed actions with strict sampling, pair-void enforcement, and
   disjoint proposal/oracle-selection/report worlds. Store per-world returns or
   covariance plus bracket outcomes; means alone are insufficient.
4. Use untouched existing labels for representation and calibration
   diagnostics only. A predeclared policy choice can be compared with another
   predeclared choice on report rows because the selected-maximum term cancels;
   do not train or report on `best`/`significant` rows alone.
5. If an absolute action-value model is tested, call its contract
   `Q^Heuristic(s,a)` and evaluate it as a root scorer first. Existing rows do
   not by themselves justify a generic state-value/leaf model.

Do not rerun 37 million evaluations. Re-label only the small stratified union
needed to decide whether the new proposer finds valuable off-ballot actions.

## P0 correctness and measurement gates

**Status 2026-08-05.** The bounded action and pilot-measurement portions below
are implemented and the DEV experiment is complete: card-code multiset identity, permutation-invariant pure/fast
decomposition, complete tied-code tractors, shape-preserving component
replacement, independent fold streams, exact work accounting, retained
per-world vectors/brackets, and fail-closed aggregation. The clean v6 asset and
all eight scoring shards passed; SELECT NONE is final for this design.

Complete these before an online strength claim or a large corpus run:

1. Make `scripts/evaluate.py` test the paired arm-minus-control contrast, not
   only arm-minus-reference with a control veto. Remove confirmation bypasses;
   require non-null checkpoint digests for every learned policy; fail on zero
   sampled worlds and every strict-sampling rejection/fallback.
2. Make strict suit-void sampling a tested invariant and consume/test
   `pair_void`. The current `strict_rejects >= 0` assertion is tautological.
3. Define attempted-play identity as a sorted card-code multiset. Do **not**
   collapse different card codes merely because `Ordering.level()` ties them:
   playing `S7` rather than `D7` can preserve a different pair in the
   successor hand. Two physical copies of the same code may collapse.
4. Resolve the engine's order-dependent decomposition of tied-level trump
   pairs. Either make lead/throw semantics permutation-invariant, or represent
   the player's explicit decomposition in the action. A ballot must not dedupe
   two lists as the same multiset while the engine can interpret their list
   order differently.
5. Freeze a baseline commit, ballot version, state corpus, seed ranges, and
   evaluator version. Existing V3 results are a rejection of that naive arm,
   not baseline evidence for the new architecture.

## Code architecture

Add a small, independently testable ballot package; keep it in Python until
the contract is correct.

- `CanonicalAction`: immutable sorted code tuple plus a stable digest.
- `ActionProposal`: action, archetype, source/reason, and cheap public-state
  features. Proposal metadata must not affect engine semantics.
- `LegalActionSource`: lazy iterators; the engine remains the final legality
  oracle.
- `BallotSelector`: protected actions, archetype quotas, diversity, stable
  order-independent tie handling.
- `ProposalSearch`: optional search on proposal-only belief worlds.
- `BallotTrace`: ballot version/digest, state hash, RNG stream IDs, generated
  and retained counts by archetype, work, scores, rejection reasons, and the
  final action.
- `BallotSpec`: one versioned configuration passed by MC, teacher generation,
  training, and play. Replace interacting class flags with this contract so a
  train/play ballot mismatch cannot happen silently again.

Use separately derived RNG streams for proposal, belief sampling, rollout
continuation, and evaluator seeds. Derivation must not advance another stream.

## Phase 1: evaluation-free lead proposer

Leads are first because deployed MC misses 93/601 human leads, while follows
miss 30/1511, and the naive V3 arm already showed that wider generation alone
is insufficient.

Generate lazily, per effective suit:

- every distinct card-code singleton;
- every available pair;
- every tractor window and length;
- the SmartBot action and existing safe/near-boss throws;
- bounded component-throw mutations: add, remove, or replace one component
  from a canonical same-suit decomposition.

Protect SmartBot's action. Select the remaining slots with archetype quotas
and feature diversity, not generator order. Initial lead archetypes:

- low/high/middle single;
- point/non-point single;
- pair and tractor by strength/length;
- trump drain and side-suit lead;
- create-void versus preserve-length;
- preserve versus break a pair/tractor in the residual hand;
- safe, near-boss, and speculative component throw.

Within an archetype, select deterministic feature extremes and then
farthest-point diversity. Do not use rollouts or v11 in this first arm. Use the
same selected count as its random-fill control. Keep current MC unchanged as a
baseline.

### Phase 1 tests

- Every emitted action is held by the player and is a legal attempted lead.
- Every current deployed candidate is contained in the broad proposal union.
- Brute-force agreement on small hands; no duplicate canonical actions.
- Shuffling generator input does not change the selected ballot.
- Results are identical across `PYTHONHASHSEED` values.
- Tied-level but different-code actions survive when their successor hands
  differ.
- Calling the proposer does not change the subsequent belief worlds.
- Candidate list/cache objects are never aliased or mutated.
- Exact quota, protected-action, and total-work accounting.

## Phase 2: frozen-state offline gate

Build a small versioned corpus, balanced across banker/attacker, early/late
round, trump/side-suit, ordinary/throw decisions, and enriched for current
off-ballot human leads. Include ordinary self-play states so the test is not
optimized only for human disagreement.

Use three disjoint belief-world folds:

1. **Proposal fold:** used only by arms that search for proposals.
2. **Oracle-selection fold:** selects a reference action from the union of all
   arms plus a much wider mutation set.
3. **Report fold:** estimates every arm's chosen action and the frozen
   reference action on unseen common worlds.

Report, clustered by source game/deal:

- legality, determinism, and ballot size by archetype;
- human-action coverage as a diagnostic only;
- current-ballot best-action recall on the frozen reference;
- paired report-fold value and regret versus the frozen reference;
- choice stability across independent world batches;
- generated/selected candidates, rollouts, wall time, and fallbacks.

The quota arm earns Phase 3 only if it improves report-fold paired value or
regret over current MC with a preregistered interval, while all correctness
gates stay green. Merely recovering more human actions is not a promotion.

## Phase 3: rollout-guided proposal

Only after the evaluation-free arm establishes the pipeline, add search to
candidate creation.

1. Start from the protected/quota ballot and a wider pool of component/card
   mutations.
2. On a small set of strict **proposal worlds**, give the wider pool a cheap
   initial budget. Prefer a few full-round heuristic continuations initially;
   a 2-4-trick truncation introduces an unvalidated leaf function and should be
   a separate later ablation.
3. Retain per-world winners, lower-confidence-bound winners, and archetype
   representatives. Never let noisy global top-k remove all candidates of an
   archetype.
4. Freeze that ballot, discard the proposal worlds, and evaluate survivors on
   fresh common worlds. Candidate 0 remains protected and the existing margin
   rule remains an explicit ablation.
5. If the broad pool is large, use successive halving within archetypes rather
   than a fixed prefix. Log every allocation decision.

The first comparison matrix is:

| Arm | Proposal | Final evaluation |
|---|---|---|
| deployed MC | current ballot | current budget |
| MC-more | current ballot | all extra proposal compute moved into more worlds |
| random-fill | same broad pool/count as treatment, random selector | matched total work |
| quota | evaluation-free archetype selector | matched total work |
| rollout-proposal | quota + proposal-world search | disjoint worlds, matched total work |

`MC-more` is essential: if simply spending the extra simulations on the old
ballot is equally strong, use the simpler bot. Equal-work arms establish why an
idea works; because strength is the product objective, a winning arm may then
be scaled beyond that budget and compared against an equally scaled baseline.

## Phase 4: online strength gate

Preregister the metric, effect bar, seed clusters, stopping rule, work band,
and controls before launch. Use a small screen only to select one design; use
fresh seeds and a power calculation from observed paired variance for the
confirmation.

Promotion requires:

- positive paired signed level utility against the strongest current or
  compute-matched MC baseline, with the preregistered interval clearing zero;
- a paired arm-minus-control result attributable to structured proposal;
- zero illegal actions, zero zero-world searches, and zero forbidden sampler
  fallback;
- exact artifacts and replay on a clean, hashed tree;
- a final mirrored full-game level-progression check.

Do not pool the selection screen into confirmation.

## Phase 5: extend surfaces in evidence order

1. **Follows:** lazy legal multiset generation, then quotas for win,
   cheap-win, feed, dump points, ruff, create void, preserve/break structure.
   Replace the current lexicographic prefix.
2. **Bury:** generate structured void-creation, point retention, trump
   preservation, pair/tractor preservation, and mixed mutations. This is once
   per round, so a much wider proposal budget is affordable.
3. **Declare/wait:** explicitly enumerate legal declarations and waiting; use
   round-value rollouts. The action set is small.
4. **Rollout interiors:** only if root improvements plateau. Root candidates
   are currently evaluated against narrow heuristic continuations; test a
   small mixture of continuation personalities before recursive full search.

Each surface must pass its own static/offline gate before an online duel.

## Phase 6: learned proposal, after the ballot freezes

Regenerate dense teacher data on the new `BallotSpec`, with strict belief
worlds and independent selection/report folds. Train a pairwise proposal or
prior model to allocate search, but retain MC as the final evaluator. Existing
v11pair must not score newly widened actions: its training ballot does not
cover them.

Compare the learned proposer against quota, random, and MC-more controls. RL
enters the champion path only if the resulting hybrid proves stronger than the
best non-learned search, not because it is faster.

## Immediate bounded work

1. Preserve DEV-512/CALIB-512/REPORT exactly; the registered lead-ballot lane is
   closed at SELECT NONE.
2. Implement confidence-gated, common-world adaptive allocation on the current
   ballot with fixed candidate-world work and uniform/random controls.
3. Build the new teacher-v1 asset outside every evaluation split; its 64-state
   replay/schema preflight may automatically launch the registered 2,048-state
   pilot, but not a 10k/50k expansion.
4. Enumerate and price 20–50 structured bury candidates as a separate surface;
   the historical four-variant `MC_BURY` tie did not test this proposal space.
5. Promote only after fresh paired full games beat compiled `mc-strong` N=30.
