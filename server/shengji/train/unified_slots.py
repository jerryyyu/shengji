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

`install_shared_forward` fills both slots from ONE trunk forward per decision: the bot's belief
model becomes a `SharedTrunkBelief` (the same weights; its ``logits`` keep the card states the trunk
just computed) and the root prior reads those states through the policy head instead of running the
trunk again.  The belief logits and the prior scores are the bytes the two separate forwards give.

`install_root_prior` changes one bound method of one bot instance and appends ``-uprior<sha8>`` to
its name (`install_shared_forward`: two bound methods and the instance's belief model, ``-ushare<sha8>``); a bot it was not called on is untouched, and no served module imports this one.  An
error in the model raises inside the search, which plays its anchor and records the fallback as for
any search error.
"""
from __future__ import annotations

import types

import numpy as np

TOKEN = "uprior"
SHARED_TOKEN = "ushare"
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
    bot.policy_name = f"{getattr(bot, 'policy_name', None) or type(bot).__name__}-{TOKEN}{sha[:8]}"
    return bot


def policy_from_states(model, q: np.ndarray) -> np.ndarray:
    """``UnifiedNumpy.policy_logits`` from card states already computed (the same operations)."""
    from ..ai.unified_numpy import _gelu, _ln
    h = model.h
    x = _ln(q, h["p_head.0.weight"], h["p_head.0.bias"])
    x = _gelu(x @ h["p_head.1.weight"].T + h["p_head.1.bias"])
    return (x @ h["p_head.3.weight"].T + h["p_head.3.bias"])[:, 0]


def _preferences(logits, actions) -> np.ndarray:
    from ..rl.encode import CARD_INDEX
    logits = np.asarray(logits, dtype=np.float64)
    if logits.shape != (N_CARDS,) or not np.isfinite(logits).all():
        raise UnifiedSlotError("the policy head requires 54 finite card log-odds")
    out = np.empty(len(actions), dtype=np.float64)
    for i, action in enumerate(actions):
        if not action:
            raise UnifiedSlotError("an empty play")
        out[i] = sum(logits[CARD_INDEX[card]] for card in action) / len(action)
    return out


def _plays_so_far(rnd) -> int:
    trick = rnd.trick
    return sum(len(t.plays) for t in rnd.history) + (len(trick.plays) if trick is not None else 0)


def shared_trunk_belief(belief_model, model):
    """``belief_model`` (a served ``BeliefNumpy``) as a `SharedTrunkBelief` over ``model``'s trunk.
    Refuses unless every trunk array of the two is equal: the belief the search draws from must be
    the belief package's."""
    from ..ai.belief_numpy import BeliefNumpy
    from ..ai.unified_numpy import _ln

    class SharedTrunkBelief(BeliefNumpy):
        def logits(self, inp, enc=None):
            u = self.unified
            w = self.w
            if enc is None:
                enc = u.trunk.encode_history(inp)
            q, g = u.card_states(inp, enc)
            self.shared.clear()
            self.shared.update(q=q, seat=int(inp["seat"]), plays=len(inp["tok_int"]))
            out = (g @ w["x_logits.weight"].T + w["x_logits.bias"]).reshape(N_CARDS, 4)
            o = _ln(q, w["out.0.weight"], w["out.0.bias"])
            return out + o @ w["out.1.weight"].T + w["out.1.bias"]

    if type(belief_model) is not BeliefNumpy:
        raise UnifiedSlotError("the bot's belief model is not a served BeliefNumpy")
    tw = model.trunk.w
    if belief_model.config != model.trunk.config or belief_model.dtype != model.dtype or set(belief_model.w) != set(tw) \
            or any(not np.array_equal(belief_model.w[k], tw[k]) for k in tw):
        raise UnifiedSlotError("the belief package's trunk is not the unified model's trunk")
    import copy
    shared = copy.copy(belief_model)
    shared.__class__ = SharedTrunkBelief
    shared.unified = model
    #: the last forward's card states, consumed by the root prior of the same decision
    shared.shared = {}
    return shared


def _shared_belief_worlds(self, rnd, seat, mem, refusals, check_budget):
    slot = self.belief_model.shared
    slot.clear()
    out = type(self)._belief_worlds(self, rnd, seat, mem, refusals, check_budget)
    if slot:
        slot["rnd"] = rnd
    return out


def _shared_scores(self, rnd, seat, actions, worlds):
    """`_unified_scores` from the card states the belief proposal of this decision computed; when
    there are none for this exact state (no proposal ran), the trunk runs as in `_unified_scores`."""
    slot = self.belief_model.shared
    model = self.unified_prior_model
    if slot.get("rnd") is rnd and slot.get("seat") == int(seat) and slot.get("plays") == _plays_so_far(rnd):
        row = _preferences(policy_from_states(model, slot["q"]), actions)
        self.unified_shared_hits += 1
    else:
        refusals = self._refusals.observe(rnd) if getattr(self, "refusal_constraints", False) else ()
        row = root_prior_preferences(model, rnd, seat, actions, refusals)
        self.unified_shared_misses += 1
    slot.clear()
    self.unified_prior_calls += 1
    return np.tile(row, (len(worlds), 1))


def install_shared_forward(bot, model):
    """Fill ``bot``'s belief and root-prior slots from one trunk forward of ``model`` per decision
    (the bot's belief package must carry ``model``'s trunk); returns ``bot``."""
    sha = getattr(model, "package_sha256", None)
    if not sha:
        raise UnifiedSlotError("the model has no package sha256 (load it with load_unified_numpy)")
    if not callable(getattr(bot, "scores", None)) or not hasattr(bot, "_refusals") \
            or not callable(getattr(type(bot), "_belief_worlds", None)):
        raise UnifiedSlotError("the bot has no served root prior and belief proposal to replace")
    if getattr(bot, "unified_prior_model", None) is not None:
        raise UnifiedSlotError("a unified root prior is already installed")
    if getattr(bot, "belief_model", None) is None:
        raise UnifiedSlotError("the bot has no belief package bound")
    bot.belief_model = shared_trunk_belief(bot.belief_model, model)
    bot.unified_prior_model = model
    bot.unified_prior_calls = 0
    bot.unified_shared_hits = 0
    bot.unified_shared_misses = 0
    bot._belief_worlds = types.MethodType(_shared_belief_worlds, bot)
    bot.scores = types.MethodType(_shared_scores, bot)
    bot.policy_name = f"{getattr(bot, 'policy_name', None) or type(bot).__name__}-{SHARED_TOKEN}{sha[:8]}"
    return bot
