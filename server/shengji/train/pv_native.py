"""Compiled hot paths of the served search, behind latency switches.

``SHENGJI_PV_LEGAL_NATIVE=1`` (OFF by default; no name, payload or decision
reads it) builds the ``lgf`` greedy finish's follow listings
(`pv_tree_search.legal_replies_compact`) with the compiled
`_pv_fast.subset_listing`: the actions of
``islice(harvest.legal.iter_follow_actions(hand, lead, ordering), cap)`` in
the same order, stored as `pv_tree_search.CompactReplies` stores them, without
a Python tuple per action.  The follow case (in-suit, short, void) is
`harvest.legal._follow_case`'s own; the in-suit rows are kept by the same
``validate_follow`` (the module attribute at call time, so the compiled engine
validator when ``SHENGJI_FAST`` routed it) refusing with the same
``IllegalPlay``.  Without the compiled module every call returns None and the
caller takes the Python reference.

``SHENGJI_PV_WORLD_FAST=1`` (OFF by default; no name or payload reads it)
speeds up the belief-proposed world draw: the proposal's copy loop
(`train.belief_seq.sample_worlds`) runs as the compiled `_pv_fast.belief_draw`
on the same generator, called at the same points (`belief_sample_worlds`), and
the history-legal draw completes each world against the decision's played
cards and deck counted once (`world_completion`) instead of once per world.
The worlds, the generator's state and every refusal are the reference's.
"""
from __future__ import annotations

from collections import Counter

from ..ai.mcbot import MCBot
from ..harvest import legal as harvest_legal
from . import belief_seq

try:
    from . import _pv_fast
except ImportError:      # not built: every caller keeps its Python reference
    _pv_fast = None

HAVE_NATIVE = _pv_fast is not None

#: the reference functions the listing kernel stands for, as imported: a
#: listing call declines (the caller's Python listing runs) once either is
#: replaced
_REFERENCE_MULTISET_SUBSETS = harvest_legal.multiset_subsets
_REFERENCE_ITER_FOLLOW = harvest_legal.iter_follow_actions
#: the reference function objects the world switch stands for, as imported;
#: only the identical objects take the fast paths
_REFERENCE_BELIEF_DRAW = belief_seq.sample_worlds
_REFERENCE_COMPLETION = MCBot._complete_determinized_hands

class ReferenceSnapshot:
    """The Python references a fast path stands for, frozen at import: each
    function object, its code, defaults and globals dict, and every global its
    code (nested code included) reads, by identity, with a copy of each
    container's content.  `intact` is True only while every one of them is
    the very object captured, holding the content captured; a fast path that
    cannot establish that declines and the reference runs."""

    _CONTAINERS = (dict, list, set, frozenset, tuple, bytearray)

    def __init__(self, *functions):
        import numpy as np
        self._np = np
        self.entries = []
        for fn in functions:
            raw = getattr(fn, "__func__", fn)
            namespace = raw.__globals__
            self.entries.append((raw, raw.__code__, raw.__defaults__, raw.__kwdefaults__,
                                 namespace, self._frozen(raw.__defaults__),
                                 self._frozen(raw.__kwdefaults__),
                                 [(name, namespace[name], self._frozen(namespace[name]))
                                  for name in sorted(self._names(raw.__code__))
                                  if name in namespace]))

    @staticmethod
    def _names(code):
        names = set(code.co_names)
        for const in code.co_consts:
            if hasattr(const, "co_names"):
                names |= ReferenceSnapshot._names(const)
        return names

    def _frozen(self, value):
        if isinstance(value, self._np.ndarray):
            return value.copy()
        if isinstance(value, self._CONTAINERS):
            import copy
            try:
                return copy.deepcopy(value)
            except Exception:
                return None
        return None

    def _same(self, value, frozen):
        if frozen is None:
            return True
        if isinstance(frozen, self._np.ndarray):
            return (isinstance(value, self._np.ndarray) and value.dtype == frozen.dtype
                    and value.shape == frozen.shape and bool((value == frozen).all()))
        try:
            return type(value) is type(frozen) and bool(value == frozen)
        except Exception:
            return False

    def intact(self, *functions) -> bool:
        """Every captured reference unchanged, and ``functions`` (the objects
        the caller is about to treat as the references) are those objects."""
        try:
            captured = [entry[0] for entry in self.entries]
            if any(not any(getattr(fn, "__func__", fn) is c for c in captured)
                   for fn in functions):
                return False
            for (fn, code, defaults, kwdefaults, namespace, frozen_defaults, frozen_kw,
                 bindings) in self.entries:
                if (fn.__code__ is not code or fn.__defaults__ is not defaults
                        or fn.__kwdefaults__ is not kwdefaults or fn.__globals__ is not namespace
                        or not self._same(defaults, frozen_defaults)
                        or not self._same(kwdefaults, frozen_kw)):
                    return False
                for name, value, frozen in bindings:
                    if namespace.get(name, _MISSING) is not value or not self._same(value, frozen):
                        return False
            return True
        except Exception:
            return False


_MISSING = object()

_LISTING_REFERENCES = ReferenceSnapshot(harvest_legal.multiset_subsets,
                                        harvest_legal.iter_follow_actions)
_DRAW_REFERENCES = ReferenceSnapshot(belief_seq.sample_worlds)
_COMPLETION_REFERENCES = ReferenceSnapshot(MCBot._complete_determinized_hands)

_TABLES = None


def _tables():
    """``(card index, global sort rank, index -> card)``: the listing's card
    numbering (`policy_prior.CARD_INDEX`, as `CompactReplies`) and the string
    order ``sorted`` gives the codes."""
    global _TABLES
    if _TABLES is None:
        from .policy_prior import CARD_INDEX
        rank = {code: i for i, code in enumerate(sorted(CARD_INDEX))}
        names = [None] * len(CARD_INDEX)
        for code, index in CARD_INDEX.items():
            names[index] = code
        _TABLES = (dict(CARD_INDEX), rank, names)
    return _TABLES


def listing_intact() -> bool:
    """The listing kernel's references (`harvest.legal`'s enumeration and the
    card numbering `CompactReplies` reads) are the ones captured: checked once
    per greedy finish by the caller, which otherwise keeps the Python listing."""
    from . import policy_prior
    tables = _tables()
    return (_pv_fast is not None and _LISTING_REFERENCES.intact(
                harvest_legal.multiset_subsets, harvest_legal.iter_follow_actions)
            and policy_prior.CARD_INDEX == tables[0])


def follow_listing(hand, lead, ordering, cap):
    """``(cards, offsets)`` (int8 card indices, int32 row offsets) of the
    first ``cap`` actions of ``iter_follow_actions(hand, lead, ordering)``
    (every action when ``cap`` is None), or None without the compiled
    module.  Raises what the reference raises on the same inputs."""
    if (_pv_fast is None or harvest_legal.multiset_subsets is not _REFERENCE_MULTISET_SUBSETS
            or harvest_legal.iter_follow_actions is not _REFERENCE_ITER_FOLLOW):
        return None
    case, h_suit, off, n = harvest_legal._follow_case(hand, lead, ordering)
    card_index, rank, names = _tables()
    limit = (1 << 30) if cap is None else int(cap)
    if case == "in-suit":
        counts = Counter(h_suit)
        codes = sorted(counts)
        validate = (harvest_legal.validate_follow, harvest_legal.IllegalPlay, hand, lead,
                    ordering, names)
        return _pv_fast.subset_listing(codes, [counts[c] for c in codes], n, limit, card_index,
                                       rank, None, validate)
    counts = Counter(off)
    codes = sorted(counts)
    return _pv_fast.subset_listing(codes, [counts[c] for c in codes], n - len(h_suit), limit,
                                   card_index, rank, list(h_suit), None)


def is_reference_belief_draw(draw) -> bool:
    """``draw`` is the `belief_seq.sample_worlds` function object this module
    imported, by identity, with its code, defaults and the globals it reads
    unchanged: any other object, whatever its code or name, keeps its own draw."""
    return draw is _REFERENCE_BELIEF_DRAW and _DRAW_REFERENCES.intact(draw)


def belief_sample_worlds(P, n_c, M, sizes, W, rng):
    """`belief_seq.sample_worlds(P, n_c, M, sizes, W, rng)`: its prologue
    here, its copy loop compiled; None (the generator untouched) without the
    compiled module or for arrays the kernel does not take."""
    import numpy as np
    from .belief_seq import N_CARDS, N_RECV, BeliefSeqError
    if _pv_fast is None:
        return None
    P = np.asarray(P)
    M = np.asarray(M)
    sizes = np.asarray(sizes)
    n_c = np.asarray(n_c)
    if (P.dtype != np.float64 or P.shape != (N_CARDS, N_RECV) or M.dtype != np.bool_
            or M.shape != (N_CARDS, N_RECV) or sizes.shape != (N_RECV,)
            or n_c.shape != (N_CARDS,) or type(W) is not int or W < 0):
        return None
    if not np.isfinite(P).all() or (P < 0).any():
        raise BeliefSeqError("world probabilities must be finite and nonnegative")
    copies = np.repeat(np.arange(N_CARDS), n_c.astype(np.int64))
    copies = copies[rng.permutation(len(copies))]
    types = (M[copies] * (1 << np.arange(N_RECV))).sum(-1)
    tc = np.bincount(types, minlength=16).astype(np.int64)
    return _pv_fast.belief_draw(np.ascontiguousarray(P), np.ascontiguousarray(M).view(np.uint8),
                                np.ascontiguousarray(copies, dtype=np.int64),
                                np.ascontiguousarray(types, dtype=np.int64), tc,
                                np.ascontiguousarray(sizes, dtype=np.int64), W, rng,
                                BeliefSeqError)


def world_completion(bot, rnd, seat):
    """``bot._complete_determinized_hands`` for draws at ``(rnd, seat)``, the
    cards already played and the deck counted once: the same hands, the same
    refusals with the same messages.  None when ``bot`` overrides the method
    (the caller keeps it): the method ``bot`` resolves, on its class or on
    the instance, must be the `MCBot` function this module imported, bound to
    ``bot``."""
    from collections import Counter as _Counter
    from ..ai.mcbot import DeterminizationContractError
    method = getattr(bot, "_complete_determinized_hands", None)
    if (getattr(method, "__func__", None) is not _REFERENCE_COMPLETION
            or getattr(method, "__self__", None) is not bot
            or not _COMPLETION_REFERENCES.intact(method)):
        return None
    expected = {other for other in range(4) if other != seat}
    played = []
    for trick in rnd.history:
        for play in trick.plays:
            played.extend(play.cards)
    if rnd.trick is not None:
        for play in rnd.trick.plays:
            played.extend(play.cards)
    seen = _Counter(played)
    deck = _Counter(rnd.deck)
    own = sorted(rnd.hands[seat])
    lengths = {other: len(rnd.hands[other]) for other in expected}

    def complete(rnd_, seat_, sampled, *, buried):
        if rnd_ is not rnd or seat_ != seat:
            return bot._complete_determinized_hands(rnd_, seat_, sampled, buried=buried)
        if set(sampled) != expected:
            raise DeterminizationContractError(
                f"sampled hand keys {sorted(sampled)} != opponents "
                f"{sorted(expected)}")
        for other in expected:
            if len(sampled[other]) != lengths[other]:
                raise DeterminizationContractError(
                    f"sampled seat {other} has {len(sampled[other])} cards, "
                    f"expected {lengths[other]}")
        hands = [list(own) if current == seat else sorted(sampled[current])
                 for current in range(4)]
        observed = _Counter(seen)
        observed.update(buried)
        for hand in hands:
            observed.update(hand)
        # both counters hold positive counts only (counted, never subtracted),
        # where Counter equality is dict equality
        if dict.__ne__(observed, deck):
            missing = deck - observed
            extra = observed - deck
            raise DeterminizationContractError(
                "sampled world violates card conservation: "
                f"missing={dict(sorted(missing.items()))}, "
                f"extra={dict(sorted(extra.items()))}")
        return hands
    return complete


__all__ = ["HAVE_NATIVE", "ReferenceSnapshot", "belief_sample_worlds", "follow_listing",
           "listing_intact", "is_reference_belief_draw",
           "world_completion"]
