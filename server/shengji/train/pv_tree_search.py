"""The OPTIONAL paired lookahead tree on the served pv-search bot ("PUCT v2").

Why (the diagnosis of the first PUCT bot `ai.cwv_puct`): that tree valued
each root candidate from about six single-world visits in DIFFERENT worlds, on
the old MC ballot, and played the most-visited action.  This one is built on
the served search instead and never decides on unpaired noise:

Stage A -- mechanics (identity by construction).
  1. The root ballot is exactly the served admission (whatever rules are on).
  2. The PV pass prices every admitted candidate on the same W sampled worlds
     through serving's own loop (`PVSearchBot._score_leaves`, capturing
     ``v0[w, a]``; the means are serving's accumulator ``sums / W``, the same
     floats).
  3. The PV decision ``b`` is serving's `_select` on those means -- argmax plus
     every selection rule that is on.  With ``sims == 0``, with fewer than two
     contenders, on a budget skip or on a tree error, ``b`` is played: the
     decision, the tie-break record and the sampler stream are the mode-off
     bot's.

Stage B -- the tree.
  * Contenders T: ``b`` (always) plus the admitted candidates whose v0 mean is
    within ``eps`` of the best mean, best first, at most ``max_contenders``
    (4).  Fewer than two -> no tree.
  * The S simulations are spent on T only and PAIRED BY WORLD: worlds are
    visited in the fixed order 0, 1, 2, ... and in every visited world EVERY
    contender gets one lookahead, so the visited set is V = the first
    ``min(W, S // |T|)`` sampled worlds (S is rounded down to a multiple of
    |T|).
  * One lookahead of (a, w): apply ``a`` in world w (`cwv_policy.afterstate`,
    the clone serving's leaf starts from), play the CONTINUATION (``cont``,
    below), and read the value head at the trick boundary reached, from the
    ROOT seat's team through the served evaluator (a terminal position takes
    its exact value there, never the model).
  * Continuation modes (``PVTreeConfig.cont``, ``SHENGJI_PV_TREE_CONT``):
      - ``trick`` (default): the remaining seats of the CURRENT trick follow
        with the package policy's top legal follow; nothing is led.  Serving's
        own leaf finishes the same trick with the HEURISTIC, so here ``d`` is
        "policy-finished minus heuristic-finished" on the same world.  When
        the root seat is last to play there is nothing to look ahead: the tree
        is skipped (``tree_skipped == "last-seat"``, d = 0).
      - ``trick-next-heuristic``: as ``trick``, then the next trick is led by
        production's heuristic (`cwv_policy.default_finisher`, the heuristic
        that gives serving its anchor and finishes its leaves) and followed by
        the policy.
      - ``policy`` (kept for comparison): as ``trick``, then the next trick is
        led by the policy's best SINGLE-COMPONENT lead (a single, a pair or a
        tractor; never a multi-component throw), ranked by the MEAN card
        log-odds (length-normalised; ties by enumeration order), and followed
        by the policy.
      - ``trick-greedy``: the current trick only, like ``trick``, but each
        remaining seat replies by ONE-STEP VALUE GREED inside the sampled
        world.  Its candidates are the policy's top ``reply_candidates`` (4)
        legal follows plus production's heuristic follow when that is not
        among them; each candidate is applied, the rest of the trick is
        finished by production's heuristic (`finish_current_trick`), and the
        value head is read at that trick boundary from THAT seat's team; the
        seat plays its highest-valued candidate (ties: policy order, the
        heuristic's last).  Seats reply in turn order, so the last seat's
        candidates are valued directly at the boundary.  The root candidate's
        lookahead value is the value head at the resulting boundary from the
        ROOT seat's team.  This is PERFECT-INFORMATION play inside a
        determinised world -- every replying seat sees all four hands through
        the value head -- so strategy fusion is possible; the significance
        gate and the tactical fixtures are what guard against it.  Skipped,
        like ``trick``, when the root seat plays last.
    In the other modes a FOLLOW is always the policy's top legal follow: the card log-odds of the
    acting seat's own row in that world
    (``flat_input(root_tensors(clone, seat))``, the admission's scoring path)
    summed over the action's cards (the length is fixed by the lead), over the
    capped legal enumeration, ties to the first in enumeration order.  A seat
    with one legal action plays it without a model row; a seat short of the
    led suit has a closed form (`top_fill`), used only when it is provably the
    unique maximiser of the complete enumeration.
    The engine must ACCEPT every continuation action as submitted.  A lead it
    refuses and forces down (a heuristic throw another hand beats in that
    world) aborts the tree: the PV decision is played and the record says
    ``tree_skipped == "refused"``.
  * ``d[w, a] = lookahead(a, w) - v0[w, a]``; for a contender
    ``Q(a) = mean_W v0[., a] + mean_V d[., a]`` (the 64-world mean plus a
    paired depth correction); a non-contender keeps ``Q = mean v0`` and cannot
    be chosen by the tree.
  * The gate (v2).  The action selected under Q is ``a'`` = SERVING'S OWN
    SELECTION run on Q instead of on the v0 means: the same `_select` call --
    argmax, then every selection rule that is on (the points tie-break, the
    lead-prior rule), with the same worlds and priors -- so a tie-break serving
    applied to the PV decision is applied to the tree's choice as well.
    ``a' == b``: ``b`` is played.  ``a' != b``: the override must be justified
    by DEPTH evidence alone -- ``y_w = d[w, a'] - d[w, b]`` over the visited
    worlds, ``z = mean(y) / (sd(y) / sqrt(|V|))`` -- and happens only when
    ``|V| >= 2``, ``mean(y) > 0`` and ``z >= zmin`` (`depth_override`).  The v0
    gap between the two is never counted (the first gate counted it, and so
    reversed serving's tie-breaks).  If ``a'`` is not a contender there
    is no depth evidence for it and ``b`` stands.  A tree whose lookahead says
    nothing (d = 0) therefore never changes the move.  The gate is still
    POST-SELECTION -- ``a'`` is chosen after looking at Q -- so it is a noise
    filter, not a calibrated test.
  * Network calls are batched across (a, w): one policy forward per ply and
    one value pass, each in ``batch_size`` chunks.

Budget.  With a serving budget the tree starts only while the decision has
used at most ``budget_fraction`` of it, and abandons itself at any batch
boundary once ``budget_stop_fraction`` is reached; either way ``b`` (a complete
PV result) is played and the record says ``tree_skipped == "budget"``.  The
fallback of serving (anchor on expiry or error BEFORE the PV pass completes) is
unchanged.  An exception inside the tree never costs the PV decision: ``b`` is
played and the record carries ``tree_skipped == "error"`` and the class name.

Record (scalars only, so the screen trace filter keeps them; added to the
ordinary ``pv-search-decision-v1`` record on every decision while the mode is
on): ``tree_sims``, ``tree_applied``, ``tree_skipped`` (``""``, ``"sims0"``,
``"single"``, ``"last-seat"``, ``"budget"``, ``"refused"``, ``"error"``),
``tree_cont``, ``tree_skipped_budget``,
``tree_contenders``, ``tree_worlds``, ``tree_evaluations``,
``tree_pv_action`` / ``tree_selected_q_index`` / ``tree_action`` (admitted
positions: PV's, serving's selection on Q, the one played),
``tree_pv_tiebreak`` (the PV decision is not the argmax of the v0 means: a
selection rule chose it), ``tree_changed_action``, ``tree_override``,
``tree_override_blocked``, ``tree_depth_delta``, ``tree_depth_se``,
``tree_depth_z`` (None when not finite), ``tree_mean_abs_d``, ``tree_max_abs_d``,
``tree_d_nonzero`` (lookaheads whose value differs from v0 by more than 1e-6:
the continuation reached a different leaf than serving's), ``tree_policy_rows``,
``tree_forced_plays``, ``tree_multi_leads`` (lookahead leads of two or more
cards), ``tree_terminal_leaves``, ``tree_value_batches``, ``tree_seconds``,
and for ``trick-greedy`` ``tree_reply_plays`` (replies played),
``tree_reply_evaluations`` (reply candidates valued),
``tree_reply_differs_heuristic`` / ``tree_reply_differs_policy`` (replies that
are not the heuristic's follow / not the policy's top follow); and
two short numeric lists, ``tree_d_means`` (mean depth correction per contender)
and ``tree_contender_indices`` (corresponding admitted positions; both empty
without a completed lookahead). ``tree_pv_cards_json`` stores the PV candidate's
card codes as a JSON scalar so the screen retains the unplayed alternative.
These fields describe choices, not counterfactual utility or evidence of benefit.

Bury is untouched.  Nothing here is reachable unless a recipe sets
``PVSearchConfig.tree`` (``SHENGJI_PV_TREE_SIMS``).
"""
from __future__ import annotations

import json
import math
import time
from collections import Counter
from itertools import islice

import numpy as np

from ..ai.cwv_policy import afterstate, child_position, default_finisher, finish_current_trick
from ..engine import round as engine_round
from ..engine.round import Round, Trick, TrickPlay
from ..engine.combos import find_tractor_runs
from ..harvest.legal import (MAX_TRACTOR, _follow_case, _lead_groups, count_multiset_subsets,
                             iter_follow_actions)
from . import pv_native
from .pv_search_policy import PVSearchBot, PVSearchBuryBot, PVSearchPolicyError
from .pv_tree_config import PVTreeConfig

#: the references the fast clones stand for, frozen at import
#: (`pv_native.ReferenceSnapshot`): the fast twins run only while they are
#: intact and the names in use are those very objects
import copy as _copy_module  # noqa: E402
_CLONE_REFERENCES = pv_native.ReferenceSnapshot(afterstate, child_position, _copy_module.copy)


def clone_references_intact(*functions) -> bool:
    """`afterstate`, `child_position` and ``copy.copy`` as captured, and
    ``functions`` (the names the caller resolves) are those objects."""
    return (_copy_module.copy is _CLONE_REFERENCES.entries[2][0]
            and _CLONE_REFERENCES.intact(*functions))

#: the stop-fraction deadline is also checked every this-many clones inside a ply
TREE_BUDGET_STRIDE = 16
#: a closed-form policy choice is used only when its maximiser is unique by more
#: than this (log-odds); float rounding of an enumerated score is ~1e-13
TOP_TOLERANCE = 1e-9
#: per-decision record state of serving's selection rules (`policy_value_search`)
_SELECTION_STATE = ("_tiebreak", "_lead_tiebreak")
#: a lookahead value further than this from v0 counts as a different leaf
D_NONZERO = 1e-6


class PVTreeBudgetExceeded(PVSearchPolicyError):
    """The tree reached its share of the play budget (the PV decision stands)."""


class PVTreeContinuationRefused(PVSearchPolicyError):
    """The engine did not accept a continuation action as submitted."""


def contender_set(means, pv_index: int, eps: float, cap: int) -> list[int]:
    """Admitted positions of the contenders, ascending: ``pv_index`` (always)
    plus the candidates within ``eps`` of the best mean, best mean first (ties
    by admission order), ``cap`` in all."""
    means = np.asarray(means, dtype=np.float64)
    finite = np.isfinite(means)
    if not finite.any():
        return [int(pv_index)]
    best = means[finite].max()
    near = [int(i) for i in np.flatnonzero(finite & (means >= best - eps)) if int(i) != pv_index]
    near.sort(key=lambda i: (-means[i], i))
    return sorted([int(pv_index)] + near[:max(0, cap - 1)])


def depth_override(d, a: int, b: int, zmin: float) -> dict:
    """The override gate (module docstring): is the DEPTH evidence alone in
    favour of column ``a`` over column ``b``?  ``d`` is the ``(V, n)``
    depth-correction matrix; ``y_w = d[w, a] - d[w, b]`` over the V visited
    worlds, ``delta = mean(y)``, ``se = sd(y, ddof=1) / sqrt(V)``,
    ``z = delta / se``.  Override only with ``V >= 2``, ``delta > 0`` and
    ``z >= zmin``.  The v0 gap between the two candidates is never evidence.

    Returns ``delta``, ``se`` (``inf`` when V < 2), ``z`` and ``override``."""
    d = np.asarray(d, dtype=np.float64)
    y = d[:, a] - d[:, b]
    delta = float(y.mean())
    if len(y) < 2:
        return {"delta": delta, "se": math.inf, "z": 0.0, "override": False}
    se = float(y.std(ddof=1) / math.sqrt(len(y)))
    if se > 0:
        z = delta / se
    elif delta != 0:
        z = math.copysign(math.inf, delta)     # the same difference in every world
    else:
        z = 0.0
    return {"delta": delta, "se": se, "z": z, "override": bool(delta > 0 and z >= zmin)}


def _separated(values) -> bool:
    """True when every two of ``values`` differ by more than `TOP_TOLERANCE`."""
    ordered = sorted(values)
    return all(high - low > TOP_TOLERANCE for low, high in zip(ordered, ordered[1:]))


def single_component_leads(hand, ordering) -> list[list[str]]:
    """The legal leads of one component -- singles, pairs, tractors -- in
    `harvest.legal.iter_lead_actions`' own order (they are its first three
    sections, before any throw, so its cap never truncates them).  A single
    component always stands: the engine cannot refuse one."""
    groups = list(_lead_groups(list(hand), ordering))
    out, seen = [], set()

    def emit(key):
        if key not in seen:
            seen.add(key)
            out.append(list(key))
    for _, cards in groups:
        for code in sorted(set(cards)):
            emit((code,))
    for _, cards in groups:
        counts = Counter(cards)
        for code in sorted(counts):
            if counts[code] >= 2:
                emit((code, code))
    for _, cards in groups:
        for length in range(2, MAX_TRACTOR + 1):
            runs = find_tractor_runs(cards, ordering, length)
            if not runs:
                break
            for run in sorted(tuple(sorted(r)) for r in runs):
                emit(run)
    return out


def top_fill(base, off, need, row, cap):
    """The first-maximum legal FOLLOW of a seat short of (or void in) the led
    suit, in closed form, or None when the enumeration must decide.  Its legal
    follows are ``base`` (every card it holds of the led suit) plus any
    ``need``-sub-multiset of its other cards (`iter_follow_actions`), so the
    best one adds the ``need`` highest log-odds; unique when the distinct
    cards' log-odds are apart, and complete when the count is within ``cap``."""
    from .policy_prior import CARD_INDEX
    counts = Counter(off)
    if count_multiset_subsets(list(counts.values()), need) > cap:
        return None
    logit = {card: float(row[CARD_INDEX[card]]) for card in counts}
    if not _separated(logit.values()):
        return None
    ranked = sorted(off, key=lambda card: -logit[card])
    return sorted(list(base) + ranked[:need])


def _finite_or_none(value):
    return float(value) if math.isfinite(value) else None


# -- the greedy trick finish: shared by the tree's ``trick-greedy`` continuation
# and the served ``leaf_greedy_finish`` value leaf (`policy_value_search`) ------

#: the work counters one greedy finish accumulates (the tree's record names)
GREEDY_STATS = ("tree_policy_rows", "tree_forced_plays", "tree_value_batches", "tree_reply_plays",
                "tree_reply_evaluations", "tree_reply_differs_heuristic",
                "tree_reply_differs_policy")


def greedy_stats() -> dict:
    return {key: 0 for key in GREEDY_STATS}


def trick_open(clone, target: int) -> bool:
    """True while ``clone``'s current trick is unresolved: the round is in play
    and its history is shorter than ``target`` (the root's history plus one)."""
    return clone.phase == "play" and len(clone.history) < target


def legal_replies(bot, clone, seat, cache):
    """``(actions, scoring matrix)`` of the seat to act.  A follower: the
    capped legal enumeration the admission scores (`enumerate_legal`'s
    listing, ``bot.cap``) and the card multiplicities (score = summed
    log-odds).  A leader: the single-component leads and their multiplicities
    divided by the action length (score = mean log-odds).
    The legal set is a function of the seat's hand and the trick's lead under
    one trump ordering, so within a decision it is computed once per distinct
    (hand, lead) -- contenders share worlds, hence most hands."""
    from .policy_prior import CARD_INDEX, N_CARDS
    plays = clone.trick.plays
    key = (tuple(sorted(clone.hands[seat])), tuple(plays[0].cards) if plays else None)
    hit = None if cache is None else cache.get(key)
    if hit is None:
        if plays:
            # `enumerate_legal`'s own follow listing (its first ``cap`` actions),
            # without its second pass that only counts them
            legal = [list(a) for a in islice(
                iter_follow_actions(list(clone.hands[seat]), plays[0].cards, clone.ordering),
                bot.cap)]
        else:
            # a continuation LEAD (``cont == "policy"``): one component only
            legal = single_component_leads(clone.hands[seat], clone.ordering)
        if not legal:
            raise PVSearchPolicyError("lookahead reached a seat with no legal action")
        multiplicity = None
        if len(legal) > 1:
            multiplicity = np.zeros((len(legal), N_CARDS), dtype=np.float64)
            np.add.at(multiplicity,
                      ([i for i, action in enumerate(legal) for _ in action],
                       [CARD_INDEX[card] for action in legal for card in action]), 1.0)
            if not plays:
                # leads differ in length: rank by the MEAN card log-odds
                multiplicity /= multiplicity.sum(axis=1, keepdims=True)
        hit = (legal, multiplicity)
        if cache is not None:
            cache[key] = hit
    return hit


def _card_names():
    from .policy_prior import CARD_INDEX
    names = [None] * len(CARD_INDEX)
    for card, index in CARD_INDEX.items():
        names[index] = card
    return names


class CompactReplies:
    """`legal_replies`' listing stored as int8 card indices in listing order:
    ``len`` and ``[i]`` (a fresh card list, equal to the listing's ``i``-th
    action) read as the listing does.  A capped follow listing holds up to
    ``cap`` actions; as lists plus a dense float64 scoring matrix that is
    about 2 MB per distinct (hand, lead), against a few tens of kB here."""

    __slots__ = ("cards", "offsets", "leads")
    _names = None

    def __init__(self, legal, leads: bool):
        from .policy_prior import CARD_INDEX
        self.cards = np.fromiter((CARD_INDEX[card] for action in legal for card in action),
                                 dtype=np.int8)
        self.offsets = np.zeros(len(legal) + 1, dtype=np.int32)
        np.cumsum([len(action) for action in legal], out=self.offsets[1:])
        self.leads = leads

    @classmethod
    def from_arrays(cls, cards, offsets, leads: bool):
        """The listing whose int8 ``cards`` and int32 ``offsets`` are given
        (`pv_native.follow_listing`'s output: the arrays ``__init__`` builds)."""
        replies = cls.__new__(cls)
        replies.cards, replies.offsets, replies.leads = cards, offsets, leads
        return replies

    def __len__(self):
        return len(self.offsets) - 1

    def __getitem__(self, i):
        names = CompactReplies._names
        if names is None:
            names = CompactReplies._names = _card_names()
        return [names[j] for j in self.cards[self.offsets[i]:self.offsets[i + 1]].tolist()]

    def multiplicity(self) -> np.ndarray:
        """The matrix `legal_replies` builds for this listing, by the same
        operations (integer counts accumulated into float64 zeros; leads
        divided by their row sums), so its products are the same floats."""
        from .policy_prior import N_CARDS
        n = len(self)
        multiplicity = np.zeros((n, N_CARDS), dtype=np.float64)
        rows = np.repeat(np.arange(n), np.diff(self.offsets))
        np.add.at(multiplicity, (rows, self.cards.astype(np.intp)), 1.0)
        if self.leads:
            multiplicity /= multiplicity.sum(axis=1, keepdims=True)
        return multiplicity


_LISTING_REFERENCES = pv_native.ReferenceSnapshot(legal_replies, CompactReplies.__init__,
                                                  CompactReplies.multiplicity)


class _DenseSlot:
    """The one materialized scoring matrix of a ply: clones of one world that
    share a (hand, lead) are consecutive, so they reuse it."""

    __slots__ = ("owner", "dense")

    def __init__(self):
        self.owner = self.dense = None


class LazyScoring:
    """``scoring @ row`` for a `CompactReplies`: the dense matrix is built at
    the product and kept only in the ply's single `_DenseSlot`."""

    __slots__ = ("replies", "slot")

    def __init__(self, replies: CompactReplies, slot: _DenseSlot):
        self.replies, self.slot = replies, slot

    def __matmul__(self, row):
        slot = self.slot
        if slot.owner is not self:
            slot.owner, slot.dense = None, None
            slot.dense = self.replies.multiplicity()
            slot.owner = self
        return slot.dense @ row


def legal_replies_compact(bot, clone, seat, cache, slot, native=False):
    """`legal_replies` with the listing held as `CompactReplies` and the
    scoring as `LazyScoring`: the same actions in the same order, the same
    scores, without the per-key lists and dense matrix.  ``native`` builds a
    follow listing with `pv_native.follow_listing` (the same actions; the
    Python listing where the compiled module is absent)."""
    plays = clone.trick.plays
    key = (tuple(sorted(clone.hands[seat])), tuple(plays[0].cards) if plays else None)
    hit = cache.get(key)
    if hit is None:
        listing = None
        if native and plays:
            listing = pv_native.follow_listing(list(clone.hands[seat]), plays[0].cards, clone.ordering,
                                     bot.cap)
        if listing is not None:
            cards, offsets = listing
            if len(offsets) < 2:
                raise PVSearchPolicyError("lookahead reached a seat with no legal action")
            replies = CompactReplies.from_arrays(cards, offsets, leads=False)
            if len(replies) == 1:
                hit = ([replies[0]], None)
            else:
                hit = (replies, LazyScoring(replies, slot))
        else:
            legal, multiplicity = legal_replies(bot, clone, seat, None)
            if multiplicity is None:
                hit = (legal, None)
            else:
                replies = CompactReplies(legal, leads=not plays)
                hit = (replies, LazyScoring(replies, slot))
        cache[key] = hit
    return hit


_COPY_HOOKS = ("__copy__", "__reduce_ex__", "__reduce__", "__getstate__", "__setstate__",
               "__slots__", "__new__")


def _round_default_copy(rnd) -> bool:
    """True when ``copy.copy(rnd)`` is ``Round.__new__(Round)`` with ``rnd``'s
    ``__dict__``: an exact `Round` (whose only base is ``object``) with no
    copy hook on the class or the instance and no ``copyreg`` reducer.
    Checked on every call, against the objects themselves."""
    import copy
    import copyreg
    if type(rnd) is not Round or Round.__bases__ != (object,):
        return False
    names = Round.__dict__
    if any(hook in names for hook in _COPY_HOOKS):
        return False
    # copy.copy reads __reduce_ex__ / __reduce__ through the instance
    held = rnd.__dict__
    if "__reduce_ex__" in held or "__reduce__" in held:
        return False
    return Round not in copyreg.dispatch_table \
        and Round not in getattr(copy, "_copy_dispatch", {})


def shallow_round(rnd):
    """``copy.copy(rnd)``: under the default protocol (`_round_default_copy`)
    the same new object built without the reduce machinery, else
    ``copy.copy``."""
    if _round_default_copy(rnd):
        clone = object.__new__(Round)
        clone.__dict__.update(rnd.__dict__)
        return clone
    import copy
    return copy.copy(rnd)


def child_position_fast(clone, seat, cards):
    """`cwv_policy.child_position` with `shallow_round` for its ``copy.copy``:
    the same child, attribute for attribute."""
    child = shallow_round(clone)
    child.hands = [list(hand) for hand in clone.hands]
    child.buried = list(clone.buried)
    assert clone.trick is not None
    child.trick = Trick(
        leader=clone.trick.leader,
        plays=[TrickPlay(p.seat, list(p.cards)) for p in clone.trick.plays])
    child.trick.running_points = clone.trick.running_points
    child.trick.incumbent = clone.trick.incumbent
    child.history = list(clone.history)
    child.last_trick = clone.last_trick
    child.message = None
    child._trusted_rollout = True
    child._determinized_world = True
    child.play(seat, list(cards))
    return child


def afterstate_fast(rnd, seat, hands, buried, candidate):
    """`cwv_policy.afterstate` (no lead validation context, no finish) with
    `shallow_round` for its ``copy.copy``: the same clone, attribute for
    attribute."""
    clone = shallow_round(rnd)
    clone.hands = [list(hand) for hand in hands]
    clone.buried = list(buried)
    assert rnd.trick is not None
    clone.trick = Trick(
        leader=rnd.trick.leader,
        plays=[TrickPlay(p.seat, list(p.cards)) for p in rnd.trick.plays])
    clone.history = list(rnd.history)
    clone.last_trick = rnd.last_trick
    clone.message = None
    clone._trusted_rollout = True
    clone._determinized_world = True
    clone.play(seat, list(candidate))
    return clone


def seed_trick_caches(clone) -> None:
    """Give a trusted clone whose open trick carries no caches the incumbent
    and running points `Round.play` keeps inside the trusted rollout, as if
    every play of the trick had been made there: the lead's uniform suit and
    top level, folded over the later plays by ``beats`` exactly as
    `Round.play` and `Round._resolve_trick` fold them, and the trick's points.
    A trick whose lead has no uniform suit keeps no incumbent, as there.  The
    engine's functions are `engine.round`'s own (the compiled ones when
    ``SHENGJI_FAST`` routed them)."""
    trick = clone.trick
    if (getattr(clone, "_trusted_rollout", False) is not True or trick is None
            or not trick.plays or trick.incumbent is not None
            or trick.running_points is not None):
        return
    ordering = clone.ordering
    plays = trick.plays
    lead = plays[0].cards
    running = engine_round.total_points(lead)
    suit = engine_round.uniform_suit(lead, ordering)
    incumbent = None
    if suit is not None:
        incumbent = (plays[0].seat, suit, engine_round.decompose(lead, ordering).top_level())
    for play in plays[1:]:
        running += engine_round.total_points(play.cards)
        if incumbent is not None:
            won, top = engine_round.beats(play.cards, lead, incumbent[1], incumbent[2], ordering)
            if won:
                incumbent = (play.seat, ordering.eff_suit(play.cards[0]), top)
    trick.running_points = running
    trick.incumbent = incumbent


def team_values(bot, leaves, seat, gate=None, prefix=None):
    """Root-team (``seat``'s team) values of ``leaves``: ``(values, batches)``.
    With ``prefix`` (a `pv_encode_prefix.HistoryPrefix` of the decision root)
    each batch is encoded on it (`pv_encode_prefix.score_leaves`: the
    reference's tensors, rows, forward pass and counters)."""
    if prefix is not None:
        from .pv_encode_prefix import score_leaves
    values = np.empty(len(leaves), dtype=np.float64)
    batches = 0
    for start in range(0, len(leaves), bot.batch_size):
        if gate is not None:
            gate()
        chunk = leaves[start:start + bot.batch_size]
        scores = bot.evaluator.score(chunk, seat) if prefix is None \
            else score_leaves(bot.evaluator, chunk, seat, prefix)
        scores = np.asarray(scores, dtype=np.float64)
        if scores.shape != (len(chunk),) or not np.isfinite(scores).all():
            raise ValueError("value evaluator requires one finite root-team score per leaf")
        values[start:start + len(chunk)] = scores
        batches += 1
    return values, batches


def greedy_reply_ply(bot, active, gate, cache, stats, keep, version, legal_fn, values_fn,
                     rows_fn=None, guard=None, child_fn=child_position):
    """One reply ply of the greedy finish: every clone in ``active`` has the
    SAME seat to act (turn order inside one trick is fixed); that seat plays
    its highest-valued candidate in each clone (module docstring: the policy's
    top-``keep`` follows plus the heuristic's, each heuristic-finished and
    valued from the replying seat's team, under ``gate``).  ``version`` is the
    policy rows' encoder version; ``legal_fn`` / ``values_fn`` are
    `legal_replies` / `team_values` or the tree's hooks.  ``rows_fn(clones,
    seat)``, when given, builds the policy rows of the non-forced clones in
    one call (`pv_encode_prefix.reply_rows`: the same rows).  ``guard``, when
    given, is called before every clone's listing and child expansion (the
    served finish's deadline; it raises to stop the ply).  ``child_fn`` builds
    each (clone, candidate) child (`child_position` or `child_position_fast`)."""
    from .policy_prior import N_CARDS, flat_input, root_tensors
    seat = active[0].turn
    if any(clone.turn != seat for clone in active):
        raise PVSearchPolicyError("greedy ply: the clones disagree on the seat to act")
    heuristic = default_finisher()
    plans = [None] * len(active)       # (candidates in policy order [+ heuristic], heuristic)
    rows, pending = [], []
    for index, clone in enumerate(active):
        if gate is not None and index and index % TREE_BUDGET_STRIDE == 0:
            gate()
        if guard is not None:
            guard()
        legal, scoring = legal_fn(clone, seat, cache)
        if len(legal) == 1:
            plans[index] = ([list(legal[0])], list(legal[0]))
            continue
        if rows_fn is None:
            rows.append(flat_input(root_tensors(clone, seat, version), version))
        pending.append((index, legal, scoring))
    if rows_fn is not None and pending:
        rows = rows_fn([active[index] for index, _, _ in pending], seat)
    for start in range(0, len(rows), bot.batch_size):
        if gate is not None:
            gate()
        chunk = np.stack(rows[start:start + bot.batch_size]).astype(np.float32)
        logits = np.asarray(bot.predict(chunk), dtype=np.float64)
        if logits.shape != (len(chunk), N_CARDS) or not np.isfinite(logits).all():
            raise ValueError("policy requires finite rows x 54 log-odds")
        for row, (index, legal, scoring) in zip(logits, pending[start:start + bot.batch_size]):
            # the policy's top-R follows; a stable sort keeps enumeration order on ties
            order = np.argsort(-(scoring @ row), kind="stable")[:keep]
            candidates = [list(legal[int(i)]) for i in order]
            follow = sorted(heuristic.decide_play(active[index], seat))
            if follow not in candidates:
                candidates.append(follow)
            plans[index] = (candidates, follow)
    stats["tree_policy_rows"] += len(rows)
    stats["tree_forced_plays"] += len(active) - len(rows)
    # every (clone, candidate): apply it, let the heuristic finish the trick,
    # read the value head from the ACTING seat's team
    leaves, owners = [], []
    for index, (candidates, _follow) in enumerate(plans):
        if len(candidates) == 1:
            continue
        if gate is not None and index and index % TREE_BUDGET_STRIDE == 0:
            gate()
        if guard is not None:
            guard()
        for k, candidate in enumerate(candidates):
            child = child_fn(active[index], seat, candidate)
            finish_current_trick(child)
            leaves.append(child)
            owners.append((index, k))
    best = [0] * len(active)
    if leaves:
        values, batches = values_fn(leaves, seat, gate)
        stats["tree_value_batches"] += batches
        stats["tree_reply_evaluations"] += len(leaves)
        top = {}
        for (index, k), value in zip(owners, values):
            if index not in top or value > top[index]:     # first maximum: policy order
                top[index], best[index] = value, k
    for index, clone in enumerate(active):
        candidates, follow = plans[index]
        choice = candidates[best[index]]
        stats["tree_reply_plays"] += 1
        stats["tree_reply_differs_heuristic"] += choice != follow
        stats["tree_reply_differs_policy"] += choice != candidates[0]
        clone.play(seat, choice)


def greedy_finish_current_trick(bot, clones, target, gate, keep, version, stats=None,
                                compact=False, prefix=None, guard=None, native=False,
                                fast_clone=False) -> dict:
    """Finish the CURRENT trick of every clone in ``clones`` (all at the same
    ply) by greedy reply plies, never further; returns the `greedy_stats`
    (accumulated into ``stats`` when given).  ``bot`` supplies the policy
    (``predict``, rows encoded at ``version``), the value head (``evaluator``),
    ``batch_size`` and ``cap``; ``gate`` is the deadline callback (None:
    unbudgeted).

    ``compact`` holds the reply listings as `legal_replies_compact` does and
    keeps them for one ply only (a key is the acting seat's hand, so no later
    ply of the trick can hit it); the plies, their batches and every value are
    the same.  ``native`` (with ``compact``) builds the follow listings with
    `pv_native.follow_listing`: the same listings.  ``fast_clone`` builds the
    reply children with `child_position_fast`: the same children.  ``prefix`` encodes the reply valuations (`team_values`) and the
    reply policy rows (`pv_encode_prefix.reply_rows`) on the decision root's
    history.  ``guard`` (the served finish's deadline) is called before each
    ply, each value batch and every clone of a ply; it raises to stop."""
    stats = greedy_stats() if stats is None else stats
    cache = {}
    rows_fn = None
    if prefix is not None:
        from .pv_encode_prefix import reply_rows

        def rows_fn(clones_, seat):
            return reply_rows(clones_, seat, version, prefix)
    # the native listing stands for this module's Python listing: decided
    # once per finish, from the references as they are now
    native = bool(native and compact and _LISTING_REFERENCES.intact(legal_replies)
                  and pv_native.listing_intact())
    if compact:
        def legal_fn(clone, seat, cache_):
            return legal_replies_compact(bot, clone, seat, cache_, slot, native)
    else:
        def legal_fn(clone, seat, cache_):
            return legal_replies(bot, clone, seat, cache_)
    ply_gate = gate
    if guard is not None:
        # the deadline is checked wherever the budget is, and before the budget
        def ply_gate():
            guard()
            if gate is not None:
                gate()
    child_fn = (child_position_fast if fast_clone and clone_references_intact(child_position)
                else child_position)
    active = [c for c in clones if trick_open(c, target)]
    while active:
        if ply_gate is not None:
            ply_gate()
        if compact:
            cache, slot = {}, _DenseSlot()
        greedy_reply_ply(bot, active, ply_gate, cache, stats, keep, version, legal_fn,
                         lambda leaves, seat, gate_=None: team_values(bot, leaves, seat, gate_,
                                                                      prefix),
                         rows_fn, guard, child_fn)
        active = [c for c in active if trick_open(c, target)]
    return stats


class PVTreeMixin:
    """The tree on top of the served decision; composes with `PVSearchBot` and
    `PVSearchBuryBot` (first in the MRO).  It overrides only `_value_means`
    (to keep the per-world matrix serving's own loop already produces),
    `_select` (the tree, after serving's selection) and `_search` (the record
    fields)."""

    _tree_started = None
    _tree_v0 = None
    _tree_fields = None
    _tree_last_d = None
    _tree_points = None

    @property
    def tree_config(self) -> PVTreeConfig:
        tree = self.config.tree
        if not isinstance(tree, PVTreeConfig):
            raise PVSearchPolicyError("the tree bot needs PVSearchConfig.tree")
        return tree

    # -- Stage A: the PV pass, with the matrix kept -----------------------------

    def _value_means(self, rnd, seat, actions, worlds, check_budget=None):
        matrix = np.full((len(worlds), len(actions)), np.nan, dtype=np.float64)
        # serving's loop and accumulator; ``capture`` is additive (`_score_leaves`)
        sums, batches = self._score_leaves(rnd, seat, actions, worlds, check_budget,
                                           capture=matrix)
        self._tree_v0 = matrix
        return sums / len(worlds), batches

    def _search(self, rnd, seat, anchor, started, check_budget=None):
        self.tree_config
        self._tree_started, self._tree_v0, self._tree_fields = started, None, None
        self._tree_points = {}
        try:
            action = super()._search(rnd, seat, anchor, started, check_budget)
        finally:
            self._tree_v0 = self._tree_points = None
        record = self.last_decision_record
        if isinstance(record, dict) and self._tree_fields is not None:
            record.update(self._tree_fields)
        return action

    # -- Stage B ------------------------------------------------------------------

    def _blank_fields(self, pv_winner):
        return {"tree_sims": int(self.tree_config.sims), "tree_applied": False,
                "tree_skipped": "", "tree_cont": self.tree_config.cont,
                "tree_skipped_budget": False,
                "tree_contenders": 0, "tree_worlds": 0, "tree_evaluations": 0,
                "tree_pv_action": int(pv_winner), "tree_selected_q_index": int(pv_winner),
                "tree_pv_tiebreak": False,
                "tree_action": int(pv_winner), "tree_changed_action": False,
                "tree_override": False, "tree_override_blocked": False,
                "tree_depth_delta": 0.0, "tree_depth_se": 0.0, "tree_depth_z": 0.0,
                "tree_mean_abs_d": 0.0, "tree_max_abs_d": 0.0, "tree_d_nonzero": 0,
                "tree_d_means": [], "tree_contender_indices": [],
                "tree_policy_rows": 0, "tree_forced_plays": 0,
                "tree_multi_leads": 0, "tree_reply_plays": 0, "tree_reply_evaluations": 0,
                "tree_reply_differs_heuristic": 0, "tree_reply_differs_policy": 0,
                "tree_terminal_leaves": 0, "tree_value_batches": 0, "tree_seconds": 0.0}

    def _select(self, rnd, seat, admitted, means, worlds=None, check_budget=None, **kwargs):
        # the PV decision, exactly serving's (argmax + every selection rule that is on)
        pv_winner = super()._select(rnd, seat, admitted, means, worlds=worlds,
                                    check_budget=check_budget, **kwargs)
        fields = self._blank_fields(pv_winner)
        self._tree_fields = fields
        tree_started = time.perf_counter()
        winner = pv_winner
        self._tree_last_d = None
        # the selection rules' own record fields describe the PV decision; the
        # second selection (on Q) must not replace them
        kept = {name: getattr(self, name) for name in _SELECTION_STATE if hasattr(self, name)}
        tiebreak = int(pv_winner) != int(np.argmax(means))
        try:
            winner = self._tree_decide(rnd, seat, admitted, means, worlds, pv_winner, fields,
                                       kwargs)
        except PVTreeBudgetExceeded:
            winner = pv_winner
            fields.update(self._blank_fields(pv_winner), tree_skipped="budget",
                          tree_skipped_budget=True)
        except PVTreeContinuationRefused:
            winner = pv_winner
            fields.update(self._blank_fields(pv_winner), tree_skipped="refused")
        except Exception as exc:   # the PV decision is complete; never lose it to the tree
            winner = pv_winner
            fields.update(self._blank_fields(pv_winner), tree_skipped="error",
                          tree_error=type(exc).__name__)
        finally:
            for name, value in kept.items():
                setattr(self, name, value)
        fields["tree_pv_tiebreak"] = bool(tiebreak)
        # A JSON scalar survives the screen's bounded trace filter, unlike a
        # card list. Retain the unplayed PV alternative without the full ballot.
        fields["tree_pv_cards_json"] = json.dumps(list(admitted[pv_winner]),
                                                  separators=(",", ":"))
        fields["tree_seconds"] = time.perf_counter() - tree_started
        return winner

    def _trick_points(self, rnd, seat, hands, buried, action, world_index):
        """Serving's tie-break points, remembered within a decision: the second
        selection (on Q) asks for the same (candidate, world) leaves again."""
        cache = self._tree_points
        if cache is None:
            return super()._trick_points(rnd, seat, hands, buried, action, world_index)
        key = (tuple(action), world_index)
        if key not in cache:
            cache[key] = super()._trick_points(rnd, seat, hands, buried, action, world_index)
        return cache[key]

    def _tree_gate(self):
        """The tree's own deadline callback (None without a serving budget)."""
        budget = self.serving_budget_seconds
        if budget is None or self._tree_started is None:
            return None
        stop = self._tree_started + self.tree_config.budget_stop_fraction * budget

        def gate():
            if time.perf_counter() >= stop:
                raise PVTreeBudgetExceeded("pv-tree budget share reached")
        return gate

    def _tree_decide(self, rnd, seat, admitted, means, worlds, pv_winner, fields, select_kwargs):
        cfg = self.tree_config
        means = np.asarray(means, dtype=np.float64)
        if cfg.sims == 0:
            fields["tree_skipped"] = "sims0"
            return pv_winner
        contenders = contender_set(means, pv_winner, cfg.eps, cfg.max_contenders)
        fields["tree_contenders"] = len(contenders)
        if len(contenders) < 2:
            fields["tree_skipped"] = "single"
            return pv_winner
        if cfg.cont in ("trick", "trick-greedy") and len(rnd.trick.plays) == 3:
            # the root seat's play completes the trick: nothing to look ahead, d = 0
            fields["tree_skipped"] = "last-seat"
            return pv_winner
        visited = min(len(worlds), cfg.sims // len(contenders))
        if visited < 1:
            fields["tree_skipped"] = "sims0"
            return pv_winner
        v0 = self._tree_v0
        if worlds is None or v0 is None or v0.shape != (len(worlds), len(admitted)) \
                or not np.isfinite(v0).all():
            raise PVSearchPolicyError("the tree needs the PV pass's complete value matrix")
        budget = self.serving_budget_seconds
        if budget is not None and \
                time.perf_counter() - self._tree_started > cfg.budget_fraction * budget:
            raise PVTreeBudgetExceeded("the PV pass used the tree's share of the budget")
        gate = self._tree_gate()
        deep, stats = self._tree_lookahead(rnd, seat, [admitted[i] for i in contenders],
                                           worlds[:visited], gate)
        if gate is not None:
            gate()   # nothing computed past the tree's deadline is used
        d = deep - v0[:visited][:, contenders]
        self._tree_last_d = d     # diagnostic only (probes); never read by the bot
        q = means.copy()
        q[contenders] = means[contenders] + d.mean(axis=0)
        fields.update(tree_applied=True, tree_worlds=int(visited),
                      tree_evaluations=int(visited * len(contenders)),
                      tree_mean_abs_d=float(np.abs(d).mean()),
                      tree_max_abs_d=float(np.abs(d).max()),
                      tree_d_nonzero=int((np.abs(d) > D_NONZERO).sum()),
                      tree_d_means=[float(v) for v in d.mean(axis=0)],
                      tree_contender_indices=list(contenders), **stats)
        # serving's own selection, on Q: the same call that chose the PV decision,
        # under the tree's deadline (expiry leaves the PV decision in place)
        selected = int(super()._select(rnd, seat, admitted, q, worlds=worlds, check_budget=gate,
                                       **select_kwargs))
        fields["tree_selected_q_index"] = selected
        winner = pv_winner
        if selected != pv_winner:
            override = False
            if selected in contenders:     # else: no depth evidence for it
                test = depth_override(d, contenders.index(selected),
                                      contenders.index(pv_winner), cfg.zmin)
                fields.update(tree_depth_delta=test["delta"],
                              tree_depth_se=_finite_or_none(test["se"]),
                              tree_depth_z=_finite_or_none(test["z"]))
                override = test["override"]
            fields.update(tree_override=override, tree_override_blocked=not override)
            if override:
                winner = selected
        fields.update(tree_action=int(winner), tree_changed_action=winner != pv_winner)
        return winner

    # -- the lookahead ------------------------------------------------------------

    def _tree_legal(self, clone, seat, cache):
        """`legal_replies` (the instance method is the hook a diagnostic may
        replace; the lookahead and the greedy ply call it through ``self``)."""
        return legal_replies(self, clone, seat, cache)

    def _tree_top_action(self, clone, seat, row, cache=None):
        """The policy's action for ``seat`` under the card log-odds ``row``: the
        first maximum of the score over `_tree_legal`'s listing.  For a seat
        short of the led suit the closed form (`top_fill`) returns that same
        action without enumerating when it is provably unique."""
        plays = clone.trick.plays
        action = None
        if plays:
            case, base, off, n = _follow_case(list(clone.hands[seat]), plays[0].cards,
                                              clone.ordering)
            if case != "in-suit":
                action = top_fill(base, off, n - len(base), row, self.cap)
        if action is None:
            legal, scoring = self._tree_legal(clone, seat, cache)
            # argmax returns the first maximum = enumeration order on a tie
            action = legal[0] if scoring is None else legal[int(np.argmax(scoring @ row))]
        return list(action)

    def _tree_forced(self, clone, seat, cache):
        """The seat's only legal action, or None when it has a choice."""
        hand = clone.hands[seat]
        plays = clone.trick.plays
        case = None
        if plays:
            case, base, off, n = _follow_case(list(hand), plays[0].cards, clone.ordering)
        if plays and case != "in-suit":
            need = n - len(base)
            if count_multiset_subsets(list(Counter(off).values()), need) != 1:
                return None
            return sorted(base + off[:need])   # one distinct fill: all of it, or one code
        legal, _ = self._tree_legal(clone, seat, cache)
        return list(legal[0]) if len(legal) == 1 else None

    def _tree_policy_choices(self, clones, gate=None, cache=None):
        """The package policy's top-scoring legal action for the seat to act in
        each clone (its own world): ``(actions, model_rows)``.  One forward per
        ``batch_size`` rows; a seat with a single legal action needs no row."""
        from .policy_prior import N_CARDS, flat_input, root_tensors
        choices = [None] * len(clones)
        rows, pending = [], []
        for index, clone in enumerate(clones):
            if gate is not None and index and index % TREE_BUDGET_STRIDE == 0:
                gate()
            seat = clone.turn
            forced = self._tree_forced(clone, seat, cache)
            if forced is not None:
                choices[index] = forced
                continue
            rows.append(flat_input(root_tensors(clone, seat, self.version), self.version))
            pending.append(index)
        for start in range(0, len(rows), self.batch_size):
            if gate is not None:
                gate()
            chunk = np.stack(rows[start:start + self.batch_size]).astype(np.float32)
            logits = np.asarray(self.predict(chunk), dtype=np.float64)
            if logits.shape != (len(chunk), N_CARDS) or not np.isfinite(logits).all():
                raise ValueError("policy requires finite rows x 54 log-odds")
            for offset, (row, index) in enumerate(zip(logits, pending[start:start + self.batch_size])):
                if gate is not None and offset and offset % TREE_BUDGET_STRIDE == 0:
                    gate()
                clone = clones[index]
                choices[index] = self._tree_top_action(clone, clone.turn, row, cache)
        return choices, len(rows)

    def _tree_values(self, leaves, seat, gate=None):
        """`team_values` (the hook a diagnostic may replace)."""
        return team_values(self, leaves, seat, gate)

    def _tree_greedy_ply(self, active, gate, cache, stats):
        """One reply ply of ``trick-greedy`` (`greedy_reply_ply` with the tree's
        R, through this instance's `_tree_legal` and `_tree_values` hooks)."""
        greedy_reply_ply(self, active, gate, cache, stats, self.tree_config.reply_candidates,
                         self.version, self._tree_legal, self._tree_values)

    def _tree_lookahead_greedy(self, rnd, seat, actions, worlds, gate=None):
        """`_tree_lookahead` for ``cont == "trick-greedy"``."""
        target = len(rnd.history) + 1
        clones = [afterstate(rnd, seat, hands, buried, action, finish_trick=False)
                  for hands, buried in worlds for action in actions]
        stats = {"tree_multi_leads": 0, "tree_terminal_leaves": 0, **greedy_stats()}
        cache = {}

        active = [c for c in clones if trick_open(c, target)]
        while active:
            if gate is not None:
                gate()
            self._tree_greedy_ply(active, gate, cache, stats)
            active = [c for c in active if trick_open(c, target)]
        values, batches = self._tree_values(clones, seat, gate)
        stats["tree_value_batches"] += batches
        stats["tree_terminal_leaves"] = sum(c.phase == "round_end" for c in clones)
        return values.reshape(len(worlds), len(actions)), {k: int(v) for k, v in stats.items()}

    def _tree_lookahead(self, rnd, seat, actions, worlds, gate=None):
        """``(values, stats)``: ``values[w, a]`` is the root-team value of
        contender ``a`` in visited world ``w`` after the continuation
        (``cont``, module docstring).  Every contender is evaluated in every
        given world.  Raises `PVTreeContinuationRefused` when the engine does
        not accept a continuation lead as submitted."""
        cont = self.tree_config.cont
        if cont == "trick-greedy":
            return self._tree_lookahead_greedy(rnd, seat, actions, worlds, gate)
        target = len(rnd.history) + (1 if cont == "trick" else 2)
        clones = [afterstate(rnd, seat, hands, buried, action, finish_trick=False)
                  for hands, buried in worlds for action in actions]
        heuristic = default_finisher() if cont == "trick-next-heuristic" else None

        def open_(clone):
            return clone.phase == "play" and len(clone.history) < target

        policy_rows = forced = multi_leads = 0
        cache = {}
        active = [c for c in clones if open_(c)]
        while active:
            if gate is not None:
                gate()
            choices = [None] * len(active)
            asked = []
            for index, clone in enumerate(active):
                if heuristic is not None and not clone.trick.plays:
                    # the next trick's lead, by production's heuristic, from the
                    # leader's own seat in this world
                    choices[index] = list(heuristic.decide_play(clone, clone.turn))
                else:
                    asked.append(index)
            picked, rows = self._tree_policy_choices([active[i] for i in asked], gate, cache)
            for index, action in zip(asked, picked):
                choices[index] = action
            policy_rows += rows
            forced += len(asked) - rows
            for clone, action in zip(active, choices):
                trick = clone.trick
                lead = not trick.plays
                clone.play(clone.turn, action)
                if lead:
                    multi_leads += len(action) > 1
                    if sorted(trick.plays[0].cards) != sorted(action):
                        raise PVTreeContinuationRefused(
                            f"the engine forced {trick.plays[0].cards} for the lead {action}")
            active = [c for c in active if open_(c)]
        values = np.empty(len(clones), dtype=np.float64)
        batches = 0
        for start in range(0, len(clones), self.batch_size):
            if gate is not None:
                gate()
            chunk = clones[start:start + self.batch_size]
            scores = np.asarray(self.evaluator.score(chunk, seat), dtype=np.float64)
            if scores.shape != (len(chunk),) or not np.isfinite(scores).all():
                raise ValueError("value evaluator requires one finite root-team score per leaf")
            values[start:start + len(chunk)] = scores
            batches += 1
        stats = {"tree_policy_rows": int(policy_rows), "tree_forced_plays": int(forced),
                 "tree_multi_leads": int(multi_leads),
                 "tree_terminal_leaves": sum(c.phase == "round_end" for c in clones),
                 "tree_value_batches": int(batches)}
        return values.reshape(len(worlds), len(actions)), stats


class PVTreeSearchBot(PVTreeMixin, PVSearchBot):
    """`PVSearchBot` with the paired lookahead tree."""


class PVTreeSearchBuryBot(PVTreeMixin, PVSearchBuryBot):
    """`PVSearchBuryBot` with the paired lookahead tree (bury unchanged)."""


def tree_bot_class(expected, bot_factory=None):
    """The class `make_pv_search_bot` builds when the recipe carries a tree."""
    if bot_factory is not None:
        raise PVSearchPolicyError("the tree mode does not compose with a bot_factory")
    if expected is PVSearchBuryBot:
        return PVTreeSearchBuryBot
    if expected is PVSearchBot:
        return PVTreeSearchBot
    raise PVSearchPolicyError(f"no tree class for {expected.__name__}")
