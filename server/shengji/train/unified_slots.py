"""DEV: the unified sequence model in a slot of the served search.  Nothing here is registered or served.

The served search has three learned parts: the belief model its sampler draws worlds from, the
policy prior that ranks the root's legal plays for admission (and shortlists replies inside the
greedy trick finish), and the value network that scores every (candidate, world) leaf.  The unified
model (``ai.unified_numpy``: the belief trunk plus heads) can stand in for them one slot at a time
with the search unchanged:

* belief slot -- the trunk with its belief output IS a ``BeliefNumpy``; exported as a served-shape
  belief package it goes in through ``SHENGJI_PV_BELIEF_CKPT`` and needs no code;
* root prior slot -- `install_root_prior` below: the root's ``scores`` come from the policy head on
  the actor's own information (one trunk forward, no sampled world) instead of the prior package on
  every sampled world.  The reply shortlist inside the greedy finish keeps the served prior (it
  scores other seats in hypothetical worlds; a per-world trunk forward is a separate cost question).

`install_root_prior` changes one bound method of one bot instance and appends ``-uprior<sha8>`` to
its name; a bot it was not called on is untouched, and no served module imports this one.  An
error in the model raises inside the search, which plays its anchor and records the fallback as for
any search error.
"""
from __future__ import annotations

import types

import numpy as np

TOKEN = "uprior"
N_CARDS = 54


class UnifiedSlotError(ValueError):
    pass


def root_prior_preferences(model, rnd, seat: int, actions, refusals=()) -> np.ndarray:
    """``(A,)``: each play's mean card log-odds under the policy head, from the actor's own
    information.  The head is trained as a softmax over the cards in hand, so its log-odds carry a
    free per-decision offset; the mean over a play's cards is invariant to how many cards it has."""
    from ..ai.belief_numpy import decision_inputs
    from ..rl.encode import CARD_INDEX
    logits = np.asarray(model.policy_logits(decision_inputs(rnd, seat, refusals)), dtype=np.float64)
    if logits.shape != (N_CARDS,) or not np.isfinite(logits).all():
        raise UnifiedSlotError("the policy head requires 54 finite card log-odds")
    out = np.empty(len(actions), dtype=np.float64)
    for i, action in enumerate(actions):
        if not action:
            raise UnifiedSlotError("an empty play")
        out[i] = sum(logits[CARD_INDEX[card]] for card in action) / len(action)
    return out


def _unified_scores(self, rnd, seat, actions, worlds):
    """The served ``scores`` contract (worlds x plays), every row the same own-information score."""
    refusals = self._refusals.observe(rnd) if getattr(self, "refusal_constraints", False) else ()
    row = root_prior_preferences(self.unified_prior_model, rnd, seat, actions, refusals)
    self.unified_prior_calls += 1
    return np.tile(row, (len(worlds), 1))


def install_root_prior(bot, model):
    """Replace ``bot``'s root prior with ``model``'s policy head; returns ``bot``."""
    sha = getattr(model, "package_sha256", None)
    if not sha:
        raise UnifiedSlotError("the model has no package sha256 (load it with load_unified_numpy)")
    if not callable(getattr(bot, "scores", None)) or not hasattr(bot, "_refusals"):
        raise UnifiedSlotError("the bot has no served root prior to replace")
    if getattr(bot, "unified_prior_model", None) is not None:
        raise UnifiedSlotError("a unified root prior is already installed")
    bot.unified_prior_model = model
    bot.unified_prior_calls = 0
    bot.scores = types.MethodType(_unified_scores, bot)
    bot.policy_name = f"{bot.policy_name}-{TOKEN}{sha[:8]}"
    return bot
