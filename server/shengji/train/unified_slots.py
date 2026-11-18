"""The unified sequence model in a slot of the served search.  Nothing here registers a policy:
`unified_serving` does, and only when the environment names a unified package.

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
        def __deepcopy__(self, memo):
            # Weights are immutable; decision caches belong to one speculative bot.
            out = copy.copy(self)
            memo[id(self)] = out
            out.shared = {}
            return out

        def logits(self, inp, enc=None):
            u = self.unified
            w = self.w
            if enc is None:
                enc = u.trunk.encode_history(inp)
            q, g = u.card_states(inp, enc)
            self.shared.clear()
            self.shared.update(q=q, g=g, seat=int(inp["seat"]), plays=len(inp["tok_int"]))
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
    if getattr(self, "unified_frame", None) is None:
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


# ---- the value slot and the reply prior from the per-world readout (`train.unified_readout`)

VALUE_TOKEN = "uvalue"
REPLY_TOKEN = "ureply"


class LeafFrame:
    """One play decision as the readout's frame: the actor, the trick it decides in, and (lazily) the
    decision's projected card states and context."""

    def __init__(self, bot, rnd, seat: int):
        self.bot, self.rnd, self.seat = bot, rnd, int(seat)
        self.tricks = len(rnd.history)
        self.pos = len(rnd.trick.plays) if rnd.trick is not None else 0
        self._cache = None

    def cache(self, model):
        """The readout's per-decision cache: from the card states the shared belief forward of this
        decision kept (same model), else from the model's own trunk forward."""
        if self._cache is None:
            bot, rnd, seat = self.bot, self.rnd, self.seat
            slot = getattr(getattr(bot, "belief_model", None), "shared", None)
            if slot and slot.get("rnd") is rnd and slot.get("seat") == seat and slot.get("plays") == _plays_so_far(rnd) \
                    and getattr(bot.belief_model, "unified", None) is model:
                q, g = slot["q"], slot["g"]
                bot.unified_trunk_shared += 1
            else:
                from ..ai.belief_numpy import decision_inputs
                refusals = bot._refusals.observe(rnd) if getattr(bot, "refusal_constraints", False) else ()
                inp = decision_inputs(rnd, seat, refusals)
                q, g = model.card_states(inp, model.trunk.encode_history(inp))
                bot.unified_trunk_forwards += 1
            self._cache = model.decision_cache(q, g)
        return self._cache


def _leaf_entries(frame: LeafFrame, leaf):
    """``(flat plane indices (plane * 54 + card, one per card), (plays since the decision, plays in the
    trick, its points, its winner, the seat to act))`` of ``leaf``, or ``None`` when it is not a state
    of the frame's own trick after the decision."""
    from ..engine.cards import points
    from ..rl.encode import CARD_INDEX
    from .belief_history import _winner_so_far
    if leaf.phase != "play":
        return None
    tricks = len(leaf.history)
    if tricks == frame.tricks and leaf.trick is not None:
        trick = leaf.trick
    elif tricks == frame.tricks + 1 and (leaf.trick is None or not leaf.trick.plays):
        trick = leaf.history[-1]
    else:
        return None
    plays = trick.plays
    n_trick = len(plays)
    n_delta = n_trick - frame.pos
    if not 1 <= n_delta <= 4 or n_trick > 4:
        return None
    seat = frame.seat
    hands = leaf.hands
    idx = [CARD_INDEX[card] for card in hands[seat]]
    for rel in (1, 2, 3):
        base = rel * N_CARDS
        idx += [base + CARD_INDEX[card] for card in hands[(seat + rel) % 4]]
    idx += [4 * N_CARDS + CARD_INDEX[card] for card in leaf.buried]
    total = 0
    for i, tp in enumerate(plays):
        if i >= frame.pos:
            base = (5 + (tp.seat - seat) % 4) * N_CARDS
            idx += [base + CARD_INDEX[card] for card in tp.cards]
        for card in tp.cards:
            total += points(card)
    winner = (_winner_so_far(trick, leaf.ordering) - seat) % 4
    nxt = winner if n_trick == 4 else (plays[-1].seat + 1 - seat) % 4
    return idx, (n_delta, n_trick, total, winner, nxt)


def leaf_features_batch(frame: LeafFrame, leaves):
    """``(covered indices into leaves, (n, 9, 54) planes, (n, 12) scalars)`` of the leaves the frame
    covers, as `unified_readout.leaf_batch` builds them."""
    from ..ai.unified_readout_numpy import N_PLANES, leaf_scalars
    width = N_PLANES * N_CARDS
    mine, flat, meta = [], [], []
    for i, leaf in enumerate(leaves):
        entry = _leaf_entries(frame, leaf)
        if entry is None:
            continue
        base = len(mine) * width
        flat += [base + k for k in entry[0]]
        mine.append(i)
        meta.append(entry[1])
    if not mine:
        return mine, np.zeros((0, N_PLANES, N_CARDS), np.float32), np.zeros((0, 12), np.float32)
    planes = np.bincount(np.asarray(flat, np.int64), minlength=len(mine) * width).astype(np.float32)
    m = np.asarray(meta, np.int64)
    return mine, planes.reshape(len(mine), N_PLANES, N_CARDS), leaf_scalars(m[:, 0], m[:, 1], m[:, 2], m[:, 3], m[:, 4])


def leaf_features(frame: LeafFrame, leaf):
    """``((9, 54) planes, (12,) scalars)`` of one leaf, or ``None`` (`leaf_features_batch`)."""
    mine, planes, scalars = leaf_features_batch(frame, [leaf])
    return (planes[0], scalars[0]) if mine else None


def _framed_search(self, rnd, seat, anchor, started, check_budget=None):
    self.unified_frame = LeafFrame(self, rnd, seat)
    try:
        return type(self)._search(self, rnd, seat, anchor, started, check_budget)
    finally:
        self.unified_frame = None


def _install_frame(bot, keep_prefix: bool = False):
    if "unified_frame" not in vars(bot):
        if not callable(getattr(type(bot), "_search", None)):
            raise UnifiedSlotError("the bot has no play search to frame")
        bot.unified_frame = None
        bot.unified_trunk_shared = 0
        bot.unified_trunk_forwards = 0
        bot._search = types.MethodType(_framed_search, bot)
    # the leaves must reach the evaluator as states: the prefix encoder hands it rows instead, unless
    # `readout_score_leaves` stands in for ``pv_encode_prefix.score_leaves`` (``keep_prefix``)
    if not keep_prefix and getattr(bot, "encode_prefix_cache", False):
        bot.encode_prefix_cache = False


def readout_evaluator(evaluator, bot, model):
    """``evaluator`` (the served value evaluator) as one that scores a framed decision's same-trick
    leaves with ``model``'s readout and hands every other position to the served evaluator."""
    import copy
    base = type(evaluator)

    class ReadoutEvaluator(base):
        def score_many(self, positions, seats, **kw):
            frame = self.unified_bot.unified_frame
            mine, planes, scalars = ([], None, None) if frame is None else leaf_features_batch(frame, positions)
            covered = set(mine)
            rest = [i for i in range(len(positions)) if i not in covered]
            if frame is not None:
                # a framed decision's non-terminal positions the readout does not cover
                self.unified_bot.unified_value_other += sum(positions[i].phase != "round_end" for i in rest)
            if not mine:
                self.unified_bot.unified_value_served += len(rest)
                return base.score_many(self, positions, seats, **kw)
            values = np.empty(len(positions), dtype=np.float64)
            if rest:
                values[rest] = base.score_many(self, [positions[i] for i in rest], [seats[i] for i in rest], **kw)
            m = self.unified_model
            probs = m.leaf_value_probs(frame.cache(m), planes, scalars)
            sign = np.asarray([1.0 if (int(seats[i]) - frame.seat) % 2 == 0 else -1.0 for i in mine])
            values[mine] = sign * (probs @ self.support)
            self.positions += len(mine)
            self.model_rows += len(mine)
            self.unified_bot.unified_value_rows += len(mine)
            self.unified_bot.unified_value_served += len(rest)
            return values

    out = copy.copy(evaluator)
    out.__class__ = ReadoutEvaluator
    out.unified_bot = bot
    out.unified_model = model
    return out


def readout_score_leaves(served_score_leaves):
    """``served_score_leaves`` (``pv_encode_prefix.score_leaves``) for every evaluator except a
    `readout_evaluator`, which scores the leaves as states (its own ``score``)."""
    def score_leaves(evaluator, leaves, seat, *args, **kw):
        if getattr(evaluator, "unified_model", None) is None:
            return served_score_leaves(evaluator, leaves, seat, *args, **kw)
        return evaluator.score(leaves, seat)
    return score_leaves


def install_value_readout(bot, model, keep_prefix: bool = False):
    """Replace ``bot``'s value slot on play decisions with ``model``'s readout (the leaves of the
    decision's own trick; terminal leaves, bury and declare values stay the served evaluator's);
    returns ``bot``."""
    sha = getattr(model, "package_sha256", None)
    if not sha or not callable(getattr(model, "leaf_value_probs", None)):
        raise UnifiedSlotError("the model is not a hashed unified readout package")
    if getattr(bot, "unified_value_model", None) is not None:
        raise UnifiedSlotError("a unified value readout is already installed")
    if not callable(getattr(getattr(bot, "evaluator", None), "score_many", None)):
        raise UnifiedSlotError("the bot has no served value evaluator to replace")
    _install_frame(bot, keep_prefix)
    bot.unified_value_model = model
    bot.unified_value_rows = 0
    bot.unified_value_served = 0
    bot.unified_value_other = 0
    bot.evaluator = readout_evaluator(bot.evaluator, bot, model)
    bot.policy_name = f"{getattr(bot, 'policy_name', None) or type(bot).__name__}-{VALUE_TOKEN}{sha[:8]}"
    return bot


def install_reply_readout(bot, model, keep_prefix: bool = False):
    """Mark ``bot`` to take its greedy-finish reply prior from ``model``'s readout
    (`readout_reply_ply` must stand in for ``pv_tree_search.greedy_reply_ply``); returns ``bot``."""
    sha = getattr(model, "package_sha256", None)
    if not sha or not callable(getattr(model, "leaf_reply_logits", None)):
        raise UnifiedSlotError("the model is not a hashed unified readout package")
    if getattr(bot, "unified_reply_model", None) is not None:
        raise UnifiedSlotError("a unified reply readout is already installed")
    _install_frame(bot, keep_prefix)
    bot.unified_reply_model = model
    bot.unified_reply_rows = 0
    bot.unified_reply_served = 0
    bot.policy_name = f"{getattr(bot, 'policy_name', None) or type(bot).__name__}-{REPLY_TOKEN}{sha[:8]}"
    return bot


def readout_reply_ply(served_ply):
    """``served_ply`` (``pv_tree_search.greedy_reply_ply``) for every bot, except that a bot marked by
    `install_reply_readout` ranks each clone's follows by the readout's reply log-odds inside a framed
    decision.  A bot without the mark runs ``served_ply`` with its own arguments."""
    def ply(bot, active, gate, cache, stats, keep, version, legal_fn, values_fn, rows_fn=None, *args, **kw):
        model = getattr(bot, "unified_reply_model", None)
        frame = getattr(bot, "unified_frame", None)
        if model is None:
            return served_ply(bot, active, gate, cache, stats, keep, version, legal_fn, values_fn, rows_fn, *args, **kw)
        mine, planes, scalars = ([], None, None) if frame is None else leaf_features_batch(frame, active)
        if len(mine) != len(active):
            bot.unified_reply_served += len(active)
            return served_ply(bot, active, gate, cache, stats, keep, version, legal_fn, values_fn, rows_fn, *args, **kw)
        index_of = {id(clone): i for i, clone in enumerate(active)}
        pending = []

        def listing(clone, seat, cache_):
            out = legal_fn(clone, seat, cache_)
            if len(out[0]) != 1:
                pending.append(index_of[id(clone)])
            return out

        def rows(clones, seat):
            return np.zeros((len(clones), 1), np.float32)

        at = [0]

        def predict(chunk):
            take = pending[at[0]:at[0] + len(chunk)]
            at[0] += len(chunk)
            if len(take) != len(chunk):
                raise UnifiedSlotError("the reply rows and the listed clones disagree")
            bot.unified_reply_rows += len(take)
            return model.leaf_reply_logits(frame.cache(model), planes[take], scalars[take])
        served_predict = bot.predict
        bot.predict = predict
        try:
            return served_ply(bot, active, gate, cache, stats, keep, version, listing, values_fn, rows, *args, **kw)
        finally:
            bot.predict = served_predict
    return ply
