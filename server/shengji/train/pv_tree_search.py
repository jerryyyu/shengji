"""The OPTIONAL paired lookahead tree on the served pv-search bot ("PUCT v2").

Why (#436, the diagnosis of the first PUCT bot `ai.cwv_puct`): that tree valued
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
  * The tree's candidate ``a*`` is the argmax of Q over T (an exact tie keeps
    ``b``, then admission order).  When ``a* != b`` the PAIRED difference
    ``delta = mean_W(x) + mean_V(y)`` with ``x = v0[., a*] - v0[., b]`` and
    ``y = d[., a*] - d[., b]`` is computed with its standard error
    ``se = sqrt(Var(x)/W + Var(y)/|V| + 2 Cov(x[V], y)/W)`` (sample moments;
    the covariance term is there because the depth corrections are measured on
    worlds that also enter the 64-world mean; with V = W it is
    ``sqrt(Var(x + y)/W)``), and ``b`` is overridden only when
    ``delta > zmin * se``; with fewer than two visited worlds (or W < 2), or a
    negative variance estimate, ``se`` is infinite and ``b`` stands.  The gate
    is POST-SELECTION -- ``a*`` is the best of up to four contenders -- so it
    is a filter against noise, not a calibrated test.  ``zmin == 0`` is the plain argmax of Q
    (``delta > 0``).  The serving selection rules (the points tie-break, ...)
    act on the PV decision ``b`` only; they are not re-run on Q.
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
``tree_pv_action`` / ``tree_q_action`` / ``tree_action`` (admitted positions:
PV's, the argmax of Q, the one played), ``tree_changed_action``,
``tree_override``, ``tree_override_blocked``, ``tree_delta``, ``tree_se``,
``tree_z`` (None when not finite), ``tree_mean_abs_d``, ``tree_max_abs_d``,
``tree_d_nonzero`` (lookaheads whose value differs from v0 by more than 1e-6:
the continuation reached a different leaf than serving's), ``tree_policy_rows``,
``tree_forced_plays``, ``tree_multi_leads`` (lookahead leads of two or more
cards), ``tree_terminal_leaves``, ``tree_value_batches``, ``tree_seconds``,
and for ``trick-greedy`` ``tree_reply_plays`` (replies played),
``tree_reply_evaluations`` (reply candidates valued),
``tree_reply_differs_heuristic`` / ``tree_reply_differs_policy`` (replies that
are not the heuristic's follow / not the policy's top follow); and
one short numeric list, ``tree_d_means`` (the mean depth correction per
contender, in admission order; kept whole by the trace filter).

Bury is untouched.  Nothing here is reachable unless a recipe sets
``PVSearchConfig.tree`` (``SHENGJI_PV_TREE_SIMS``).
"""
from __future__ import annotations

import math
import time
from collections import Counter
from itertools import islice

import numpy as np

from ..ai.cwv_policy import afterstate, child_position, default_finisher, finish_current_trick
from ..engine.combos import find_tractor_runs
from ..harvest.legal import (MAX_TRACTOR, _follow_case, _lead_groups, count_multiset_subsets,
                             iter_follow_actions)
from .pv_search_policy import PVSearchBot, PVSearchBuryBot, PVSearchPolicyError
from .pv_tree_config import PVTreeConfig

#: the stop-fraction deadline is also checked every this-many clones inside a ply
TREE_BUDGET_STRIDE = 16
#: a closed-form policy choice is used only when its maximiser is unique by more
#: than this (log-odds); float rounding of an enumerated score is ~1e-13
TOP_TOLERANCE = 1e-9
#: a negative variance estimate smaller than this in magnitude is rounding (-> 0)
VARIANCE_ROUNDING = 1e-12
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


def paired_override(v0, d, a: int, b: int, zmin: float) -> dict:
    """The significance gate (module docstring).  ``v0`` is the ``(W, n)`` PV
    matrix over the contender columns; ``d`` is the ``(V, n)`` depth-correction
    matrix over the same columns, measured on the FIRST ``V`` of those ``W``
    worlds; ``a`` / ``b`` are column indices.

    With ``x_w = v0[w, a] - v0[w, b]`` (all W worlds) and
    ``y_w = d[w, a] - d[w, b]`` (the V visited worlds):
    ``delta = mean_W(x) + mean_V(y)`` and, because ``y`` is measured on worlds
    that also enter ``mean_W(x)``,
    ``var(delta) = Var(x)/W + Var(y)/V + 2 Cov(x[:V], y)/W``
    (sample variances and covariance, ddof 1).  With ``V == W`` this is
    ``Var(x + y)/W``.  The standard error is infinite (no override unless
    ``zmin == 0``) when ``W < 2`` or ``V < 2``, or when the estimate comes out
    negative by more than rounding (possible for ``V < W``).

    Returns ``delta``, ``se``, ``z`` and ``override``."""
    v0 = np.asarray(v0, dtype=np.float64)
    d = np.asarray(d, dtype=np.float64)
    x = v0[:, a] - v0[:, b]
    y = d[:, a] - d[:, b]
    worlds, visited = len(x), len(y)
    if visited > worlds:
        raise ValueError("the depth corrections cover more worlds than the PV pass")
    delta = float(x.mean() + y.mean())
    if worlds < 2 or visited < 2:
        se = math.inf
    else:
        head = x[:visited]
        covariance = float(((head - head.mean()) * (y - y.mean())).sum() / (visited - 1))
        variance = float(x.var(ddof=1) / worlds + y.var(ddof=1) / visited
                         + 2.0 * covariance / worlds)
        if variance >= 0.0:
            se = math.sqrt(variance)
        elif variance > -VARIANCE_ROUNDING:
            se = 0.0
        else:
            se = math.inf
    if zmin == 0:
        override = delta > 0
    elif not math.isfinite(se):
        override = False
    else:
        override = delta > zmin * se
    if se > 0 and math.isfinite(se):
        z = delta / se
    elif se == 0 and delta != 0:
        z = math.copysign(math.inf, delta)
    else:
        z = 0.0
    return {"delta": delta, "se": se, "z": z, "override": bool(override)}


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
        try:
            action = super()._search(rnd, seat, anchor, started, check_budget)
        finally:
            self._tree_v0 = None
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
                "tree_pv_action": int(pv_winner), "tree_q_action": int(pv_winner),
                "tree_action": int(pv_winner), "tree_changed_action": False,
                "tree_override": False, "tree_override_blocked": False,
                "tree_delta": 0.0, "tree_se": 0.0, "tree_z": 0.0,
                "tree_mean_abs_d": 0.0, "tree_max_abs_d": 0.0, "tree_d_nonzero": 0,
                "tree_d_means": [], "tree_policy_rows": 0, "tree_forced_plays": 0,
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
        try:
            winner = self._tree_decide(rnd, seat, admitted, means, worlds, pv_winner, fields)
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
        fields["tree_seconds"] = time.perf_counter() - tree_started
        return winner

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

    def _tree_decide(self, rnd, seat, admitted, means, worlds, pv_winner, fields):
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
        # argmax of Q over the contenders; an exact tie keeps the PV decision
        best = min(contenders, key=lambda i: (-q[i], i != pv_winner, i))
        fields.update(tree_applied=True, tree_worlds=int(visited),
                      tree_evaluations=int(visited * len(contenders)),
                      tree_q_action=int(best),
                      tree_mean_abs_d=float(np.abs(d).mean()),
                      tree_max_abs_d=float(np.abs(d).max()),
                      tree_d_nonzero=int((np.abs(d) > D_NONZERO).sum()),
                      tree_d_means=[float(v) for v in d.mean(axis=0)], **stats)
        winner = pv_winner
        if best != pv_winner:
            test = paired_override(v0[:, contenders], d, contenders.index(best),
                                   contenders.index(pv_winner), cfg.zmin)
            fields.update(tree_delta=test["delta"], tree_se=_finite_or_none(test["se"]),
                          tree_z=_finite_or_none(test["z"]),
                          tree_override=test["override"],
                          tree_override_blocked=not test["override"])
            if test["override"]:
                winner = best
        fields.update(tree_action=int(winner), tree_changed_action=winner != pv_winner)
        return winner

    # -- the lookahead ------------------------------------------------------------

    def _tree_legal(self, clone, seat, cache):
        """``(actions, scoring matrix)`` of the seat to act.  A follower: the
        capped legal enumeration the admission scores (`enumerate_legal`'s
        listing, ``self.cap``) and the card multiplicities (score = summed
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
                    self.cap)]
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
        """Root-team (``seat``'s team) values of ``leaves``: ``(values, batches)``."""
        values = np.empty(len(leaves), dtype=np.float64)
        batches = 0
        for start in range(0, len(leaves), self.batch_size):
            if gate is not None:
                gate()
            chunk = leaves[start:start + self.batch_size]
            scores = np.asarray(self.evaluator.score(chunk, seat), dtype=np.float64)
            if scores.shape != (len(chunk),) or not np.isfinite(scores).all():
                raise ValueError("value evaluator requires one finite root-team score per leaf")
            values[start:start + len(chunk)] = scores
            batches += 1
        return values, batches

    def _tree_greedy_ply(self, active, gate, cache, stats):
        """One reply ply of ``trick-greedy``: every clone in ``active`` has the
        SAME seat to act (turn order inside one trick is fixed); that seat plays
        its highest-valued candidate in each clone (module docstring)."""
        from .policy_prior import N_CARDS, flat_input, root_tensors
        seat = active[0].turn
        if any(clone.turn != seat for clone in active):
            raise PVSearchPolicyError("greedy ply: the clones disagree on the seat to act")
        heuristic = default_finisher()
        keep = self.tree_config.reply_candidates
        plans = [None] * len(active)       # (candidates in policy order [+ heuristic], heuristic)
        rows, pending = [], []
        for index, clone in enumerate(active):
            if gate is not None and index and index % TREE_BUDGET_STRIDE == 0:
                gate()
            legal, scoring = self._tree_legal(clone, seat, cache)
            if len(legal) == 1:
                plans[index] = ([list(legal[0])], list(legal[0]))
                continue
            rows.append(flat_input(root_tensors(clone, seat, self.version), self.version))
            pending.append((index, legal, scoring))
        for start in range(0, len(rows), self.batch_size):
            if gate is not None:
                gate()
            chunk = np.stack(rows[start:start + self.batch_size]).astype(np.float32)
            logits = np.asarray(self.predict(chunk), dtype=np.float64)
            if logits.shape != (len(chunk), N_CARDS) or not np.isfinite(logits).all():
                raise ValueError("policy requires finite rows x 54 log-odds")
            for row, (index, legal, scoring) in zip(logits, pending[start:start + self.batch_size]):
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
            for k, candidate in enumerate(candidates):
                child = child_position(active[index], seat, candidate)
                finish_current_trick(child)
                leaves.append(child)
                owners.append((index, k))
        best = [0] * len(active)
        if leaves:
            values, batches = self._tree_values(leaves, seat, gate)
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

    def _tree_lookahead_greedy(self, rnd, seat, actions, worlds, gate=None):
        """`_tree_lookahead` for ``cont == "trick-greedy"``."""
        target = len(rnd.history) + 1
        clones = [afterstate(rnd, seat, hands, buried, action, finish_trick=False)
                  for hands, buried in worlds for action in actions]
        stats = {"tree_policy_rows": 0, "tree_forced_plays": 0, "tree_multi_leads": 0,
                 "tree_terminal_leaves": 0, "tree_value_batches": 0, "tree_reply_plays": 0,
                 "tree_reply_evaluations": 0, "tree_reply_differs_heuristic": 0,
                 "tree_reply_differs_policy": 0}
        cache = {}

        def open_(clone):
            return clone.phase == "play" and len(clone.history) < target

        active = [c for c in clones if open_(c)]
        while active:
            if gate is not None:
                gate()
            self._tree_greedy_ply(active, gate, cache, stats)
            active = [c for c in active if open_(c)]
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
