"""The served bury inside the value declaration's worlds (OFF BY DEFAULT;
``SHENGJI_PV_VALUE_DECLARE_SERVED_BURY=1``, name token ``vdsb``; #707 S15(2)).

The value declaration (`value_declare`, release 44's ``vd``) scores each
declare outcome on sampled complete deals; in each deal the world's banker
buries with the HEURISTIC bury (`value_declare.declare_outcome_position`).
Since release 45 the bot does not bury that way: it buries with the wide
value-only chooser (`bury_wide_value`, ``bwv``).  With this rule on the
declare world's banker buries with that chooser instead, so the value of a
declaration is the value of the bury the bot would actually make.

The chooser in a declare world is the served one, at a reduced width (the
cost: below).  It sees only what a banker sees there -- the 33-card hand
after the kitty and the public declaration, never the declare world's other
hands -- and:

1. its incumbent is the bot's heuristic bury (the served incumbent);
2. its candidates are the served enumeration (`bury_wide_value.
   wide_bury_candidates`: the structured ballot, then the incumbent's swaps,
   with the bot's own ``bury_wide_swaps``) cut to ``k``;
3. it samples ``model_worlds`` completions of the other hands from the
   banker's view through the served bury's own model sampler (a fresh
   ``mc-s0-report-lcb`` helper on the served bury's ``model`` seed: no RNG
   the bot owns moves) and scores every candidate with the value head from
   the banker's seat, on the served leaf (the heuristic first trick, or the
   policy head's under ``lpft``, `PVSearchBuryBot._leaf_first_trick`);
4. the argmax of the mean (lowest index on a tie) is buried.

The declare world's own position is then built and scored exactly as before
(`declare_outcome_position` with this bury in place of the heuristic's).

Cost.  The served chooser is ``k = 64`` candidates on 32 worlds, about 0.37 s
a bury on the cloud screen host; the declaration needs one bury per (world,
outcome), 64 x up to 5, so the served width would cost minutes per decision.
The rule therefore (a) runs the served chooser at ``k`` x ``model_worlds``
(`K_DEFAULT` x `MODEL_WORLDS_DEFAULT` = 16 x 8) and (b) re-scores only TWO
outcomes, the heuristic's and the best alternative of the ordinary
(heuristic-bury) pass, on the first `WORLDS_DEFAULT` (16) worlds of the
ordinary pass's stream.  On each of those worlds both outcomes are scored
twice, with the heuristic bury and with the served chooser's, and each
outcome's mean is the control-variate estimate ``ordinary-pass mean +
(served-bury mean - heuristic-bury mean)`` over the 16 paired worlds; the
rule's margin compares those two.  The ordinary pass only nominates the
challenger.  A decision whose ordinary pass found a single outcome needs no
second pass.

Measured (release 45's package smv3out-491ee4bf, compiled engine, one
thread, Mac Mini; 36 bury-phase declare worlds, each judged on 128
independent banker-view worlds): the heuristic bury is 0.127 signed levels
below the served chooser's pick; 16 x 8 is 0.016 below it (88% of the gap
recovered), 32 x 16 0.006, 16 x 4 0.040.  One chooser call is ~14 ms at
16 x 8 against ~190 ms at the served 64 x 32.  Per evaluated declare chance
(204 chances of seeded deals): ordinary pass 0.029 s mean; with the rule
0.495 s mean, p90 0.513 s, max 0.544 s, inside the 3 s serving budget.
The bury figures are agreement with the value head's own judgement, not
playing strength; strength needs a screen.

Nothing here chooses a declaration, serves or registers anything; the
wiring, budget and record are `pv_search_policy.PVSearchBot.decide_declare`.
"""
from __future__ import annotations

import numpy as np

from ..ai.registry import make_bot
from .bury_wide_value import wide_bury_candidates
from .cwv_bury import score_bury_candidates
from .cwv_bury_policy import BuryPolicyError, CWVBuryMixin, _seed, _worlds

#: the name token (declare-rule slot, after ``vdef``)
TOKEN = "vdsb"
#: the chooser's width in a declare world (served: 64)
K_DEFAULT = 16
#: the chooser's banker-view worlds in a declare world (served: 32)
MODEL_WORLDS_DEFAULT = 8
#: the declare worlds the second pass scores (the ordinary pass: 64)
WORLDS_DEFAULT = 16
#: the outcomes the second pass re-scores: the heuristic's and one challenger
OUTCOMES = 2
#: the bury this world model names (`value_declare.MODEL`'s bury segment)
MODEL_BURY = "served-wide-value-bury"


def served_bury(bot, world, banker: int, *, k: int, model_worlds: int,
                check_budget=None) -> list[str]:
    """The served wide value-only chooser's bury for ``banker`` on the
    bury-phase round ``world`` (module docstring, steps 1-4).  Reads only the
    banker's view of ``world``; sets no attribute of ``bot``."""
    if getattr(world, "phase", None) != "bury" or getattr(world, "banker", None) != banker:
        raise BuryPolicyError("served declare bury requires the banker in bury phase")
    options = {} if check_budget is None else {"check_budget": check_budget}
    # the served incumbent: the play bot's own heuristic bury (the mixin's `super`)
    incumbent = list(super(CWVBuryMixin, bot).decide_bury(world, banker))
    candidates, _counts = wide_bury_candidates(
        world, banker, bot._bury_candidates(world, incumbent), k, bot.bury_wide_swaps)
    if check_budget is not None:
        check_budget()
    model_bot = make_bot("mc-s0-report-lcb", seed=_seed("model", bot.seed))
    worlds, _attempts = _worlds(model_bot, world, banker, model_worlds, "model", **options)
    leaf = bot._leaf_first_trick(model_bot.rollout_policy, check_budget)
    first_trick = ({"first_trick_policy": model_bot.rollout_policy} if leaf is None
                   else {"first_trick_batch": leaf.play_first_tricks})
    values = score_bury_candidates(world, candidates, worlds, bot.evaluator,
                                   **first_trick, **options)
    if not np.isfinite(values).all():
        raise BuryPolicyError("served declare bury values must be finite")
    means = np.mean(values, axis=0)
    picked = min(range(len(candidates)), key=lambda i: (-float(means[i]), i))
    return list(candidates[picked])


__all__ = ["TOKEN", "K_DEFAULT", "MODEL_WORLDS_DEFAULT", "WORLDS_DEFAULT", "OUTCOMES",
           "MODEL_BURY", "served_bury"]
