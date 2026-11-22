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

from ..ai.heuristic import HeuristicBot

TOKEN = "uprior"
SHARED_TOKEN = "ushare"
N_CARDS = 54
_STANDARD_DECIDE_PLAY = HeuristicBot.decide_play


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
#: under ``UNIFIED_FAST`` the most value rows one readout forward scores: a reply ply's leaves are
#: featurised ahead in the search's own ``batch_size`` chunks (its budget gate before each) and their
#: new rows scored this many leaves at a time (`ReadoutEvaluator.readout_ahead`)
READOUT_BATCH = 512


class LeafFrame:
    """One play decision as the readout's frame: the actor, the trick it decides in, and (lazily) the
    decision's projected card states and context."""

    def __init__(self, bot, rnd, seat: int):
        self.bot, self.rnd, self.seat = bot, rnd, int(seat)
        self.tricks = len(rnd.history)
        self.pos = len(rnd.trick.plays) if rnd.trick is not None else 0
        self._cache = None
        #: the fast readout (`UNIFIED_FAST`): the fused stem and the rows this decision already scored
        self.fast = bool(getattr(bot, "unified_fast", False))
        self._fused = None
        self.value_memo: dict = {}
        self.reply_memo: dict = {}
        #: the reply ply's value chunks scored ahead, in the order `team_values` asks for them
        self.ahead: list | None = None

    @classmethod
    def at_states(cls, bot, rnd, seat: int, model, q: np.ndarray, g: np.ndarray):
        """A frame of ``seat`` at ``rnd`` whose cache is ``model``'s on card states ``q``, ``g`` the
        caller already computed for that information set (a re-rooted leaf, `pv_reroot`): no trunk
        forward of its own, and the bot's refusal ledger is never read."""
        frame = cls(bot, rnd, seat)
        frame._cache = model.decision_cache(q, g)
        return frame

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

    def fused(self, model):
        """``model.fused_stem`` of this decision's cache, computed once."""
        if self._fused is None:
            self._fused = model.fused_stem(self.cache(model))
        return self._fused


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


_FAST_TABLES = None


def _fast_tables():
    """``(per-plane card -> flat index maps, card -> points, engine.combos, engine.legal)``, built once.
    The engine modules are held as modules, so their functions are looked up per call as
    ``belief_history._winner_so_far``'s imports look them up (the compiled ones once routed)."""
    global _FAST_TABLES
    if _FAST_TABLES is None:
        from ..ai.unified_readout_numpy import N_PLANES
        from ..engine import cards, combos, legal
        from ..rl.encode import CARD_INDEX
        planes = tuple({card: plane * N_CARDS + i for card, i in CARD_INDEX.items()} for plane in range(N_PLANES))
        _FAST_TABLES = (planes, {card: cards.points(card) for card in CARD_INDEX}, combos, legal)
    return _FAST_TABLES


def _winner_fast(trick, ordering, combos, legal, *, with_level=False):
    """``belief_history._winner_so_far`` with its modules passed in (the same loop)."""
    if not trick.plays:
        return None
    lead = trick.plays[0].cards
    inc_suit = legal.uniform_suit(lead, ordering)
    if inc_suit is None:
        return (trick.plays[0].seat, None, None) if with_level else trick.plays[0].seat
    inc_top = combos.decompose(lead, ordering).top_level()
    winner = trick.plays[0].seat
    for tp in trick.plays[1:]:
        won, top = legal.beats(tp.cards, lead, inc_suit, inc_top, ordering)
        if won:
            winner, inc_top = tp.seat, top
            inc_suit = ordering.eff_suit(tp.cards[0])
    return (winner, inc_suit, inc_top) if with_level else winner


def _leaf_entries_fast(frame: LeafFrame, leaf, tables):
    """`_leaf_entries` from `_fast_tables` (the same indices in the same order, the same scalars)."""
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
    planes, pts, combos, legal = tables
    seat = frame.seat
    hands = leaf.hands
    idx = list(map(planes[0].__getitem__, hands[seat]))
    idx += map(planes[1].__getitem__, hands[(seat + 1) % 4])
    idx += map(planes[2].__getitem__, hands[(seat + 2) % 4])
    idx += map(planes[3].__getitem__, hands[(seat + 3) % 4])
    idx += map(planes[4].__getitem__, leaf.buried)
    total = 0
    pos = frame.pos
    for i, tp in enumerate(plays):
        if i >= pos:
            idx += map(planes[5 + (tp.seat - seat) % 4].__getitem__, tp.cards)
        total += sum(map(pts.__getitem__, tp.cards))
    winner = (_winner_fast(trick, leaf.ordering, combos, legal) - seat) % 4
    nxt = winner if n_trick == 4 else (plays[-1].seat + 1 - seat) % 4
    return idx, (n_delta, n_trick, total, winner, nxt)


def _native_leaf_counts():
    """The compiled `_pv_fast.leaf_counts`, or None: it runs only while the compiled engine is active
    and the extension is built, so the pure engine always takes the Python counts."""
    from ..engine import fast
    from . import pv_native
    if not fast.is_active() or pv_native._pv_fast is None:
        return None
    return getattr(pv_native._pv_fast, "leaf_counts", None)


def _leaf_counts_python(frame: LeafFrame, leaves, tables, width):
    """``(covered indices, (n, width) counts, (n, 5) int64 meta)`` from `_leaf_entries_fast`."""
    mine, flat, meta = [], [], []
    for i, leaf in enumerate(leaves):
        entry = _leaf_entries_fast(frame, leaf, tables)
        if entry is None:
            continue
        base = len(mine) * width
        flat += [base + k for k in entry[0]]
        mine.append(i)
        meta.append(entry[1])
    if not mine:
        return mine, None, None
    counts = np.bincount(np.asarray(flat, np.int64), minlength=len(mine) * width).reshape(len(mine), width)
    return mine, counts, np.asarray(meta, np.int64)


def leaf_features_fast(frame: LeafFrame, leaves, native=True):
    """``(covered indices, (n, 9 * 54) uint8 planes, (n, 12) scalars, n row keys)``: `leaf_features_batch`'s
    rows with the planes flat, and each row's bytes as its memo key (equal rows, equal keys).  The counts
    come from the compiled `_pv_fast.leaf_counts` where `_native_leaf_counts` offers it (and ``native``),
    else from `_leaf_entries_fast`; both give the same rows, keys and order. Count planes stay compact
    through memo lookup; the fused forward converts only rows it actually scores to the model dtype."""
    from ..ai.unified_readout_numpy import N_PLANES, N_SCALARS
    tables = _fast_tables()
    width = N_PLANES * N_CARDS
    kernel = _native_leaf_counts() if native else None
    if kernel is not None:
        planes, pts, combos, legal = tables
        mine, counts, m = kernel(frame.seat, frame.tricks, frame.pos, leaves, width, planes, pts,
                                 _winner_fast, combos, legal)
    else:
        mine, counts, m = _leaf_counts_python(frame, leaves, tables, width)
    if not mine:
        return mine, np.zeros((0, width), np.uint8), np.zeros((0, N_SCALARS), np.float32), []
    return _feature_rows(mine, counts, m)


def _feature_rows(mine, counts, m):
    from ..ai.unified_readout_numpy import leaf_scalars
    scalars = leaf_scalars(m[:, 0], m[:, 1], m[:, 2], m[:, 3], m[:, 4])
    counts = np.asarray(counts, dtype=np.uint8)
    raw = np.ascontiguousarray(np.concatenate([counts, scalars.view(np.uint8)], 1))
    keys = raw.view(np.dtype((np.void, raw.shape[1]))).ravel().tolist()
    return mine, counts, scalars, keys


def memo_rows(memo: dict, keys, compute):
    """The rows of ``keys`` (one per key, in order), computing ``compute(first positions)`` only for the
    keys ``memo`` lacks (each distinct key once) and storing them; ``memo`` maps key -> row."""
    todo: dict = {}
    for i, key in enumerate(keys):
        if key not in memo and key not in todo:
            todo[key] = i
    if todo:
        rows = compute(np.fromiter(todo.values(), np.int64, len(todo)))
        for key, row in zip(todo, rows):
            memo[key] = row
    return [memo[key] for key in keys], len(keys) - len(todo)


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
            if frame is not None and frame.fast:
                return self._score_many_fast(frame, positions, seats, **kw)
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

        def readout_ahead(self, frame, leaves, chunk, gate=None, features=None):
            """`leaf_features_fast` of ``leaves`` in ``chunk``-leaf slices (``gate`` before each, as
            `team_values` calls it), with every `READOUT_BATCH` leaves' rows the value memo lacks
            scored in one forward into it.  Per slice ``[leaves, mine, planes, scalars, keys, new]``:
            ``new`` counts the keys first scored for that slice, as `memo_rows` would have."""
            m = self.unified_model
            memo = frame.value_memo
            features = leaf_features_fast if features is None else features
            window = max(chunk, READOUT_BATCH // chunk * chunk)
            out = []
            for first in range(0, len(leaves), window):
                parts, todo = [], {}
                for start in range(first, min(first + window, len(leaves)), chunk):
                    if gate is not None:
                        gate()
                    part = leaves[start:start + chunk]
                    mine, planes, scalars, keys = features(frame, part)
                    new = 0
                    for i, key in enumerate(keys):
                        if key not in memo and key not in todo:
                            todo[key] = (len(parts), i)
                            new += 1
                    parts.append([part, mine, planes, scalars, keys, new])
                if todo:
                    planes = np.stack([parts[p][2][i] for p, i in todo.values()])
                    scalars = np.stack([parts[p][3][i] for p, i in todo.values()])
                    rows = m.leaf_value_probs_fused(frame.fused(m), planes, scalars) @ self.support
                    for key, row in zip(todo, rows):
                        memo[key] = row
                out.extend(parts)
            return out

        def _score_many_fast(self, frame, positions, seats, **kw):
            """`score_many` with `leaf_features_fast`, the fused stem and the decision's value memo
            (the slice `readout_ahead` scored for these positions, when it did)."""
            bot = self.unified_bot
            ahead = frame.ahead
            if ahead and len(ahead[0][0]) == len(positions) and all(a is b for a, b in zip(ahead[0][0], positions)):
                _, mine, planes, scalars, keys, new = ahead.pop(0)
            else:
                mine, planes, scalars, keys = leaf_features_fast(frame, positions)
                new = None
            covered = set(mine)
            rest = [i for i in range(len(positions)) if i not in covered]
            bot.unified_value_other += sum(positions[i].phase != "round_end" for i in rest)
            if not mine:
                bot.unified_value_served += len(rest)
                return base.score_many(self, positions, seats, **kw)
            values = np.empty(len(positions), dtype=np.float64)
            if rest:
                values[rest] = base.score_many(self, [positions[i] for i in rest], [seats[i] for i in rest], **kw)
            values[mine] = self._covered_values(frame, planes, scalars, keys, new, [seats[i] for i in mine])
            bot.unified_value_served += len(rest)
            return values

        def _covered_values(self, frame, planes, scalars, keys, new, seats):
            bot, m = self.unified_bot, self.unified_model
            if new is None:
                fused = frame.fused(m)
                expected, hits = memo_rows(frame.value_memo, keys,
                                           lambda rows: m.leaf_value_probs_fused(fused, planes[rows], scalars[rows]) @ self.support)
            else:
                expected, hits = [frame.value_memo[key] for key in keys], len(keys) - new
            sign = np.asarray([1.0 if (int(seat) - frame.seat) % 2 == 0 else -1.0 for seat in seats])
            self.positions += len(keys)
            self.model_rows += len(keys)
            bot.unified_value_rows += len(keys)
            bot.unified_value_memo += hits
            return sign * np.asarray(expected, np.float64)

    out = copy.copy(evaluator)
    out.__class__ = ReadoutEvaluator
    from ..ai.cwv_policy import CompleteWorldEvaluator
    out._fourth_score_methods = (CompleteWorldEvaluator.score, ReadoutEvaluator.score_many,
                                 ReadoutEvaluator._score_many_fast, ReadoutEvaluator.readout_ahead)
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
    score_leaves.readout_dispatch = score_leaves
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
    bot.unified_value_memo = 0
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
    bot.unified_reply_memo = 0
    bot.policy_name = f"{getattr(bot, 'policy_name', None) or type(bot).__name__}-{REPLY_TOKEN}{sha[:8]}"
    return bot


def _values_ahead(bot, frame, values_fn):
    """``values_fn`` (`team_values`) with the fast readout's value rows of its leaves scored ahead
    in `READOUT_BATCH`-row forwards (`ReadoutEvaluator.readout_ahead`): the same rows and memo
    counts, each value up to the float rounding a forward's batch shape decides."""
    ahead = getattr(bot.evaluator, "readout_ahead", None)
    if ahead is None:
        return values_fn

    def values(leaves, seat, gate=None):
        frame.ahead = ahead(frame, leaves, bot.batch_size, gate)
        try:
            return values_fn(leaves, seat, gate)
        finally:
            frame.ahead = None
    return values


def _direct_reply_features(frame, items):
    """Build the completed-trick rows from the indexed moves and their parent count planes."""
    from . import pv_tree_search as search
    kernel = getattr(search._reply_fast, "pack_reply_rows", None)
    if kernel is not None:
        counts, meta = kernel(items, 4 - frame.pos)
        return _feature_rows(list(range(len(items))), counts, meta)
    counts = np.stack([parent for parent, *_ in items]).astype(np.uint8, copy=False)
    meta = np.empty((len(items), 5), np.int64)
    for i, (_, hand_slots, points, winner) in enumerate(items):
        for slot in hand_slots:
            counts[i, slot] -= 1
            counts[i, slot + 5 * N_CARDS] += 1
        meta[i] = (4 - frame.pos, 4, points, winner, winner)
    return _feature_rows(list(range(len(items))), counts, meta)


def _projected_reply_features(frame, items):
    """Join projected rows and materialized leaves in the original candidate order."""
    projected = [i for i, item in enumerate(items) if type(item) is tuple]
    if len(projected) == len(items):
        return _direct_reply_features(frame, items)
    if not projected:
        return leaf_features_fast(frame, items)
    materialized = [i for i, item in enumerate(items) if type(item) is not tuple]
    _, direct_planes, direct_scalars, direct_keys = _direct_reply_features(
        frame, [items[i] for i in projected])
    mine, leaf_planes, leaf_scalars, leaf_keys = leaf_features_fast(frame, [items[i] for i in materialized])
    covered = projected + [materialized[i] for i in mine]
    order = np.argsort(covered)
    keys = direct_keys + leaf_keys
    return ([covered[i] for i in order], np.concatenate((direct_planes, leaf_planes))[order],
            np.concatenate((direct_scalars, leaf_scalars))[order], [keys[i] for i in order])


def _projectable_reply_clone(clone, pos, search, fast):
    trick = clone.trick
    if (getattr(clone, "_trusted_rollout", False) is not True or type(trick) is not search.Trick
            or type(trick.plays) is not list or len(trick.plays) != pos
            or type(clone.ordering) is not fast.Ordering
            or type(clone.turn) is not int or type(trick.leader) is not int
            or not 0 <= trick.leader < 4 or clone.turn != (trick.leader + pos) % 4
            or type(clone.banker) is not int or not 0 <= clone.banker < 4
            or type(clone.attacker_points) is not int
            or type(clone.hands) is not list or len(clone.hands) != 4
            or any(type(hand) is not list or len(hand) > search.engine_round.HAND_SIZE
                   for hand in clone.hands)):
        return False
    first = trick.plays[0]
    if type(first) is not search.TrickPlay or type(first.cards) is not list:
        return False
    width = len(first.cards)
    if not width or any(len(clone.hands[(trick.leader + i) % 4]) <= width for i in range(pos, 4)):
        return False
    inc, points = trick.incumbent, trick.running_points
    return (type(inc) is tuple and len(inc) == 3 and type(inc[0]) is int and 0 <= inc[0] < 4
            and type(inc[1]) is str and inc[1] in ("S", "H", "D", "C", "T")
            and type(inc[2]) is int and -1 <= inc[2] <= 15
            and type(points) is int and 0 <= points <= 200
            and all(type(play) is search.TrickPlay and play.seat == (trick.leader + i) % 4
                    and type(play.cards) is list and len(play.cards) == width
                    for i, play in enumerate(trick.plays)))


def _projected_reply_callbacks(bot, frame, active, planes, index_of, values_fn, args, kw):
    """Rank covered continuations by their card moves when the standard finish permits it."""
    from functools import partial
    from ..engine import fast
    from . import pv_encode_prefix, pv_tree_search as search
    if (not active or active[0].trick is None or planes.dtype != np.uint8 or not planes.flags.c_contiguous
            or not isinstance(values_fn, partial) or values_fn.func is not search._STANDARD_TEAM_VALUES
            or values_fn.args != (bot,) or kw.get("children_fn") is not search._STANDARD_REPLY_CHILDREN
            or len(args) != 2 or args[1] is not search.child_position_fast
            or not fast.is_active() or search.Round.play is not fast._fast.round_play):
        return None
    # The canonical builder is supplied only while its clone and finisher references are intact.
    evaluator = bot.evaluator
    methods = tuple(getattr(getattr(evaluator, name, None), "__func__", None)
                    for name in ("score", "score_many", "_score_many_fast", "readout_ahead"))
    if methods != getattr(evaluator, "_fourth_score_methods", None):
        return None
    if values_fn.keywords.get("prefix") is not None:
        score = pv_encode_prefix.score_leaves
        if getattr(score, "readout_dispatch", None) is not score:
            return None
    plane_maps, pts, combos, legal = _fast_tables()
    pos = len(active[0].trick.plays)
    if not 1 <= pos <= 3:
        return None
    if pos < 3:
        project = getattr(search._reply_fast, "project_replies", None)
        if (project is None or legal.beats is not fast._fast.beats
                or combos.decompose is not fast._fast.decompose
                or legal.uniform_suit is not fast._fast.uniform_suit
                or HeuristicBot._follow is not fast._fast.heuristic_follow
                or HeuristicBot._forced_follow is not fast._forced_follow_fast
                or _STANDARD_DECIDE_PLAY.__globals__.get("validate_follow") is not fast._fast.validate_follow):
            return None
        finisher = search.default_finisher()
        if type(finisher) is not HeuristicBot or vars(finisher) or HeuristicBot.decide_play is not _STANDARD_DECIDE_PLAY:
            return None
        decide = finisher.decide_play
    eligible = set()
    for clone in active:
        trick = clone.trick
        if (trick is None or len(trick.plays) != pos or len(clone.history) != frame.tricks
                or trick.incumbent is None or trick.running_points is None
                or not search._round_default_copy(clone) or "play" in vars(clone)):
            continue
        if pos == 3:
            if len(clone.hands[clone.turn]) > len(trick.plays[0].cards):
                eligible.add(id(clone))
        elif _projectable_reply_clone(clone, pos, search, fast):
            eligible.add(id(clone))
    if not eligible or (pos == 3 and len(eligible) != len(active)):
        return None

    def children(clone, seat, candidates):
        if id(clone) not in eligible:
            return search._STANDARD_REPLY_CHILDREN(clone, seat, candidates)
        trick = clone.trick
        lead = trick.plays[0].cards
        # The compiled follow can call the Python shape picker for throws.
        if pos < 3 and len(lead) > 1 and len(combos.decompose(lead, clone.ordering).components) != 1:
            return search._STANDARD_REPLY_CHILDREN(clone, seat, candidates)
        actual = _winner_fast(trick, clone.ordering, combos, legal, with_level=True)
        prior_points = sum(pts[c] for play in trick.plays for c in play.cards)
        parent = planes[index_of[id(clone)]]
        if pos < 3:
            if actual[1] is None:
                return search._STANDARD_REPLY_CHILDREN(clone, seat, candidates)
            result = project(clone, seat, candidates, frame.seat, parent, plane_maps, pts,
                             actual, prior_points, decide, legal.beats, search.TrickPlay, memo_heuristic=True)
            if result is None:
                return search._STANDARD_REPLY_CHILDREN(clone, seat, candidates)
            return result
        incumbent, suit, top = actual
        rel = (seat - frame.seat) % 4
        lookup = plane_maps[rel].__getitem__
        result = []
        for cards in candidates:
            won = suit is not None and legal.beats(cards, lead, suit, top, clone.ordering)[0]
            winner = rel if won else (incumbent - frame.seat) % 4
            points = prior_points + sum(map(pts.__getitem__, cards))
            result.append((parent, tuple(map(lookup, cards)), points, winner))
        return result

    def values(items, seat, gate=None):
        evaluator = bot.evaluator
        features = _direct_reply_features if pos == 3 else _projected_reply_features
        rows = evaluator.readout_ahead(frame, items, bot.batch_size, gate, features)
        if any(len(part) != len(mine) for part, mine, *_ in rows):
            frame.ahead = rows
            try:
                return values_fn(items, seat, gate)
            finally:
                frame.ahead = None
        ahead = iter(rows)

        def score(part, seat):
            _, _, counts, scalars, keys, new = next(ahead)
            return evaluator._covered_values(frame, counts, scalars, keys, new, [seat] * len(part))

        return search.value_batches(items, seat, bot.batch_size, gate, score)

    return children, values


def readout_reply_ply(served_ply):
    """``served_ply`` (``pv_tree_search.greedy_reply_ply``) for every bot, except that a bot marked by
    `install_reply_readout` ranks each clone's follows by the readout's reply log-odds inside a framed
    decision.  A bot without the mark runs ``served_ply`` with its own arguments."""
    def ply(bot, active, gate, cache, stats, keep, version, legal_fn, values_fn, rows_fn=None, *args, **kw):
        model = getattr(bot, "unified_reply_model", None)
        frame = getattr(bot, "unified_frame", None)
        if model is None:
            return served_ply(bot, active, gate, cache, stats, keep, version, legal_fn, values_fn, rows_fn, *args, **kw)
        fast = frame is not None and frame.fast
        keys = None
        if fast:
            mine, planes, scalars, keys = leaf_features_fast(frame, active)
        else:
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
            if fast:
                at_rows = np.asarray(take, np.int64)
                fused = frame.fused(model)
                rows, hits = memo_rows(frame.reply_memo, [keys[i] for i in take],
                                       lambda sub: model.leaf_reply_logits_fused(fused, planes[at_rows[sub]],
                                                                                 scalars[at_rows[sub]]))
                bot.unified_reply_memo += hits
                return np.stack(rows) if rows else np.zeros((0, N_CARDS), np.float32)
            return model.leaf_reply_logits(frame.cache(model), planes[take], scalars[take])
        served_predict = bot.predict
        if fast:
            callbacks = _projected_reply_callbacks(bot, frame, active, planes, index_of, values_fn, args, kw)
            if callbacks is None:
                values_fn = _values_ahead(bot, frame, values_fn)
            else:
                kw["children_fn"], values_fn = callbacks
        bot.predict = predict
        try:
            return served_ply(bot, active, gate, cache, stats, keep, version, listing, values_fn, rows, *args, **kw)
        finally:
            bot.predict = served_predict
    return ply
