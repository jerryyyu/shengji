# PUCT over sampled worlds with the complete-world evaluator (step 2b design)

Second PR, same worktree, built after the one-ply bot (2a) is reviewed. The one-ply bot prices
each ballot action by averaging the complete-world value over W sampled worlds one ply deep
(plus the current trick). The tree spends the same evaluator budget on MORE positions per
decision: deeper continuations of the promising actions, fewer of the hopeless ones. Nothing
else changes — same ballot at the root, same sampler, same evaluator, same perspective.

## Tree
- **Information-set tree keyed by the public action sequence from the root.** A node is the
  sequence of engine-accepted plays since the root decision (root = empty sequence). The
  hidden hands are NOT part of the key: one node aggregates statistics over every world in
  which that public sequence occurred. Node statistics: `N`, `W_sum`, `Q = W_sum / N` (root
  seat's team perspective, signed level), children keyed by the accepted play, and a prior `P`.
- **Actions at a node.** Root: production's ballot (`MCBot._candidates`, canonicalised) so the
  move set is exactly the one-ply bot's and production's. Below the root the acting seat can be
  any of the four; its candidate set is the same generator run on the sampled world (its hand is
  known in that world). Because different worlds can enumerate different sets at the same public
  node, the child map is the union; a child that is illegal in the current world is masked for
  that simulation (a standard determinized-tree device).
- **Prior.** `P(a)` = the public prior head trained on the search's final move (the #213 public
  pipeline's policy head — `lc-8000/best.pt` or its successor — which cannot see the world and is
  therefore the same for every simulation through a node); **control = uniform prior**, which
  isolates "the tree" from "the prior". The prior is cached per node. Dirichlet noise at the
  root (`alpha`, `epsilon`) is an option, off by default; temperature 0.

## One simulation
1. **World.** Draw a complete world: either a fresh sample from production's sampler (the
   default; every simulation is a new determinization) or the next of a fixed pool of W worlds
   sampled once at the root (`--world-pool W`; lower variance across candidates, the pairing the
   one-ply bot relies on). Worlds are canonicalised exactly as `_rollout` canonicalises them.
2. **Descent.** From the root, choose `argmax_a Q(s,a) + c_puct * P(a) * sqrt(N(s)) / (1 + N(s,a))`
   among children legal in this world, applying each move in the cloned world (engine truth,
   `_trusted_rollout`), until a node with an unexpanded child or a terminal state is reached.
   `Q` of an unvisited child = the parent's `Q` (first-play urgency), `Q` is always the ROOT
   seat's team value (no sign flips at opponent nodes: the opponent moves chosen by PUCT then
   maximise the root's value, which is wrong for adversarial seats). **Opponent and partner
   nodes therefore select with the negated/adjusted objective**: partner nodes maximise `Q`,
   opponent nodes minimise it (`-Q` in the PUCT term). Trick-finishing is not needed: the tree
   descends through the trick.
3. **Expansion + leaf.** Expand the reached node's action set in this world, pick the child by
   prior, apply it, and hand the reached complete position to the evaluator from the root
   seat's perspective. Terminal positions take `terminal_distribution` exactly.
4. **Backup.** Add the leaf value to `W_sum` of every node on the path, increment `N`.

## Batching (the reason the evaluator is batched)
K simulations per step are descended together with **virtual loss** (each pending path adds
`-vloss` to its nodes' `W_sum` and +1 to `N`, removed at backup), their K leaves are stacked
and scored in ONE `CompleteWorldEvaluator.score` call, then backed up. K = 32–128 keeps the
forward pass efficient; positions per second is reported (target: the evaluator's ~7–8k/s on
the Mini for the MLP; the descent is pure Python on the fast engine).

## Budget, move, records
- **Budget = simulations per decision**, calibrated to production's wall time by the same
  outcome-blind calibration (`cwv_duel.py calibrate --tree`): measure wall per decision at
  simulation counts {64, 256, 1024, 4096}, fit, freeze the budget ladder (1x/3x/10x). Positions
  per decision = simulations (one leaf each) plus the root's ballot at depth 1.
- **Move = argmax visits at the root** (temperature 0); ties by `Q`, then ballot order.
- **Record** per decision (production's shape where possible): simulations, positions
  evaluated, batch wall/CPU, worlds drawn or pool size, depth reached (max and mean leaf
  depth), root visit counts and `Q` per ballot action, prior, `c_puct`, virtual loss, played
  index, reason.

## Controls and witnesses (planned)
- Controls: uniform prior (same budget, same tree) and the one-ply bot at the same positions
  budget (does depth buy anything the flat average does not?).
- Witnesses: (i) with one simulation per candidate and depth 1 the tree's root `Q` equals the
  one-ply bot's means on the same worlds (RED when perspective flips at opponent nodes);
  (ii) virtual loss removed exactly at backup (RED when a pending path leaks into `Q`);
  (iii) argmax visits, not `Q` (RED when a rarely-visited high-`Q` child wins);
  (iv) budget from wall time only, ladder monotone (shared with 2a's witness).
