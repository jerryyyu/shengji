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

## Implementation notes (claude/cwv-puct, `shengji/ai/cwv_puct.py`)
- `CWVPuctBot` (registry `mc-cwvpuct-<ckpt8>-s<S>`, control `mc-cwvpuct-prior-<ckpt8>-s<S>`
  via `registry.register_cwv_puct_policies`). Constructor knobs: `CWV_SIMULATIONS` (S),
  `CWV_WORLD_POOL` (W, default 32, drawn round-robin), `CWV_BATCH` (K, default 16),
  `CWV_C_PUCT` (1.5), `CWV_VIRTUAL_LOSS` (1.0), `CWV_PRIOR` (`uniform` | `head`),
  Dirichlet alpha/epsilon (off).  The world pool is the only world mode built (the
  "fresh sample per simulation" option of the design is not implemented).
- Prior head = `shengji.train.train_v0` checkpoint (`PublicPriorHead`), softmaxed over the
  node's ballot for the seat to act, using `rl.encode.encode_obs` of the world clone (public
  information + that seat's hand in the world).  Priors are cached per (node, action); a
  world whose ballot adds actions to a node queues a prior request served in the next
  batched step (newcomers take the node's mean prior until then).
- A node's ballot per world is cached (`Node.world_ballots`): the ballot generator was
  two thirds of the descent's wall under the head prior.
- Virtual loss: a pending path counts one extra visit on each node, priced `vloss` worse
  to the seat selecting there; released at backup.  Leaf value = root team's signed level;
  opponent nodes select with the negated objective.
- Per decision the record carries simulations, positions, forward passes, max and mean
  leaf depth, terminal leaves, root visits / Q / prior, and the `search` identity.
- `scripts/cwv_duel.py --tree` calibrates S (grid 64/256/1024/4096) against production's
  wall on outcome-blind deals and runs the PUCT arm, its control, production's x3/x10 arms
  and the reference; the calibration binding carries W, K, c_puct, prior mode and the prior
  checkpoint sha and refuses a mismatch.
- Witnesses: `tests/test_cwv_puct.py` (selection formula, back-up, legality mask, batched
  == per-leaf scoring, virtual-loss release, argmax visits, identity binding, zero-signal).

## The joint-package policy prior and the finish-trick leaf boundary (#436 step 1)

Every PUCT read on record lost, and none of them varied the two inputs that have since
changed: the prior was SmartBot-level (the #213 public head, or the value net's own one-ply
softmax) and the leaf was read mid-trick, a boundary the outcome head was never trained on.
The gen-5 heads change both (the SMV3 policy head is +0.21 vs the production head in paired
duels; the outcome head is the served value since release 36), so the retry design on #436
puts them into the SAME tree, one variable per read.  This step is the code; no screen is
armed by it.

- **`prior="package"` (`JointPackagePriorHead`).** The joint NumPy serving package
  (`smv3out-<sha8>.npz`: value head + 54-card policy head, the release-36 file) read through
  `train.cwv_prior_admission.load_prior_checked` as kind `joint-numpy`, with the SHA256
  **pinned** by the caller and a mismatch refused, exactly as the served prior admission and
  pv-search bind it.  A ballot is priced by `cwv_prior_admission.prior_scores`: one
  `policy_prior.flat_input(root_tensors(root_clone(...)))` row per sampled world, the
  package's `policy_log_odds`, and per action the SUM of its cards' log-odds (a pair counts
  its card twice).  That function is the served admission's `_prior_scores` (which now
  delegates to it), so the tree's prior is production's prior by construction, not by a
  re-derivation: the parity witness asserts bitwise equality of the root prior with
  `softmax(_prior_scores(...).mean(axis=0) / T)`.
  - Root: scores averaged over the sampled world pool (pv-search's `.mean(axis=0)`
    preference), softmaxed over the ballot at `prior_temperature` (default 1; the name
    carries `-pprior` or `-pprior-T<T>`).  The true hidden hands are never encoded
    (`probabilities(rnd, ...)` refuses; the pool is the only input).
  - Below the root: the acting seat's node is priced in the CURRENT world (the clone's own
    hands), batched across nodes in one forward through the `encode` /
    `batch_from_encoded` hooks `prior="head"` already uses; priors are cached per node as
    before.
- **`leaf_finish_trick` (`-ftl`, net leaf only).** The scored position is not the reached
  leaf but its afterstate boundary: a private copy in which production's heuristic finishes
  the CURRENT trick and nothing more (`cwv_policy.finish_current_trick` with the default
  finisher -- the `afterstate(..., finish_trick=True)` path pv-search serves and the outcome
  head was trained on).  The tree's leaf, its node, its ballot and its trace stay as
  reached; `trace["boundary"]` carries the scored copy.  A playout leaf already plays
  through the trick, so the flag is refused there.  Default `False`: the leaves themselves
  are scored, the identity carries no key and the record is byte-identical to before (the
  existing 31 witnesses run unchanged; a determinism witness compares the default against
  an explicit `False`).
- **Names.** `mc-cwvpuct-<ckpt8>-s<S>-pprior[-T<T>][-ftl]` when the package serves both the
  value leaf and the prior (the #436 arm); `-prior-<prior8>` is inserted after `<ckpt8>`
  when the prior package is another file.  The control stays the uniform prior
  (`mc-cwvpuct-prior-<ckpt8>-s<S>[-ftl]`).  `cwv_duel.py --tree --prior package
  --prior-checkpoint PKG.npz --prior-sha256 SHA [--leaf-finish-trick]` binds both into the
  calibration (`prior_checkpoint_sha256` = the pin; `prior_temperature`;
  `leaf_finish_trick` only when on).  Screen-only: no env or fly.toml registration.
- **Witnesses:** `tests/test_cwv_puct_package_prior.py` (parity with `_prior_scores` on a
  synthetic joint package, torch-free; sha mismatch refuses; the boundary moves only within
  the trick and the default path is unchanged; the registry name and the duel binding
  round-trip; an end-to-end decision on one package in both roles).
