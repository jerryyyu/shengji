"""DEV policy admission followed by sampled-world value choice, without MC.

This is a policy change, not a decision-preserving optimization. The value
contract matches CWV shortlist: apply the candidate, heuristically finish the
current trick, and evaluate from the root team's perspective.

Optional admission rules (#676 A/C, #677 strategy 1; BOTH OFF BY DEFAULT, and
with both off the admitted indices are exactly the ranked prefix they always
were):

* ``admission_diversity`` -- after the anchor, the K-1 policy slots are filled
  in preference order but near-duplicate throws are capped: at most
  ``max_per_structure`` actions per structural key ``(effective suit, card
  count, multiset of component shapes)`` and no action whose card multiset
  shares all-but-one cards with an already-admitted action of the same size.
  If the caps leave slots empty, the capped actions back-fill in preference
  order, so K is filled whenever the legal set allows.  The survey's KHPX
  decision (7 of 8 slots on one diamond combination) is the case.
* ``admit_forced_single`` -- for every admitted multi-component lead (a throw
  the engine may refuse), the component the engine would force is computed in
  every sampled world (`harvest.legal.forced_lead`: the verdict depends on the
  other three hands, so it is world-dependent); the component forced most often
  is admitted too when it is forced in at least ``forced_min_fraction`` of the
  worlds and is not already admitted, at most ``FORCED_EXTRA_SLOTS`` extra
  slots.  The search then prices the realised fallback next to the throw
  (71% of refused throws had never admitted the forced card, #676).

Optional admission WIDTH rule (#676 C; OFF BY DEFAULT, and while off K is
``candidates`` on every decision exactly as before):

* ``adaptive_k`` -- when the acting seat is LEADING (no play yet in the current
  trick) and the scored legal set holds at least one multi-card action (a
  pair, tractor or throw), the admission takes
  ``max(candidates, candidates_lead_multi)`` slots (default 16 against
  production's 8); on a single-only lead and on every follow K is unchanged.
  The rule never SHRINKS the ballot: a recipe whose ``candidates`` already
  meets the width (K=32..512) admits ``candidates`` as before, and with the
  rule off ``candidates_lead_multi`` is unused and never constrains
  ``candidates`` (every K in 1..512 constructs exactly as before the rule).  The anchor keeps slot 0 and the extra slots
  are the next-best by the same policy preference, so the widened ballot is a
  strict superset of the K=8 ballot in the same order (`admission_diversity`,
  when on, applies its caps within the widened K).  The width is decided
  INSIDE `_admit`, FIRST -- before the diversity caps and before the forced
  components of `admit_forced_single` are appended -- so the final ballot is
  at most ``K + FORCED_EXTRA_SLOTS`` (K the decided width) and a wrapper that
  captures the ballot at the admission boundary (the harvest mixin) sees the
  widened, final one.  Evidence (#676 category 2): an exploration draw
  out-valued all 8 shortlisted candidates in 12.4% of multi-card leads
  against 2.1% of single leads, 1.3% of multi-card follows and 0.07% of
  single follows.  Cost: the value pass is K x W leaves, so a widened
  decision does twice the value work; `_value_means` flushes in
  ``batch_size`` batches and the served `_score_leaves` checks the serving
  budget around every flush, so the extra batches sit inside the cooperative
  deadline.  The record carries ``adaptive_k_applied`` and ``k_used`` (the
  width before any forced extras).

Optional selection rule (#676 E, #677 strategy 2; OFF BY DEFAULT, and while off
`_select` is the plain ``argmax`` it always was):

* ``tiebreak_points`` -- after the value means over the admitted candidates,
  the near-set is every candidate within ``tiebreak_epsilon`` of the best mean.
  UNITS: the served evaluator's score is the expected SIGNED LEVEL for the
  root team (its support is ``rl.value_afterstate.category_signed_level``:
  half-integer levels, one level = 40 points), so the default epsilon 0.02 is
  0.02 of a level, the #676 figure (43% of the 846 last-position point dumps
  in 2,000 self-play rounds sat within 0.02 of a zero-point alternative; 4.5%
  of decisions had every candidate within 0.005; #677's HK over H7 was a
  0.000806 preference).  When the near-set has at least two members, each
  member's leaf is rebuilt (`_leaf`: `afterstate(..., finish_trick=True)`,
  the same heuristic finisher the value head scored) in every sampled world
  and the resolved trick's points are read off the leaf (the engine's own
  ``Trick.points``, signed + when the trick's winner is on the root team and
  - when it is not; the last trick's kitty bonus is left to the value head).
  The finisher's
  follows depend on the world's hidden hands, so the criterion is the sum over
  the sampled worlds.  The member with the most root-team points wins; on an
  exact points tie the original argmax stands (then admission order).  The
  record carries ``tiebreak_applied`` (the selection moved off the argmax),
  ``tiebreak_near_set`` (admitted positions, ascending) and
  ``tiebreak_points`` (the mean signed points per member, in that order; empty
  when the near-set had one member and nothing was rebuilt).  Nothing runs
  when the near-set is a singleton; no model is consulted.  The rebuild runs
  under the serving deadline: ``check_budget`` is called before every member
  and every ``TIEBREAK_BUDGET_STRIDE`` worlds inside the loop and once more
  after the rebuild completes (before its points are used), and when it
  fires the tie-break ABANDONS ITSELF and the argmax (a complete value-pass
  result, published within budget) is played -- never the anchor fallback --
  with ``tiebreak_applied`` False and ``tiebreak_abandoned`` ``"budget"``.

Optional LEAD selection rule (#676 online lead review, board A8; OFF BY DEFAULT,
and while off `_select` is exactly what it was):

* ``lead_tiebreak_prior`` -- ONLY when the acting seat is LEADING (`leading`:
  no play yet in the current trick).  The near-set is every admitted candidate
  whose value mean is finite and within ``lead_tiebreak_epsilon`` of the best
  mean (inclusive).  UNITS: the same as ``tiebreak_epsilon`` -- the value
  head's expected SIGNED LEVEL (one level = 40 points); the default is the
  same constant, 0.02 of a level (about 0.8 points).  Among the near-set the
  candidate with the highest POLICY PRIOR score is played: the admission's own
  ranking score, i.e. the world-averaged sum of the action's card log-odds
  (``preferences``; no new model call, nothing rebuilt).  A candidate with a
  non-finite prior (a masked exploration draw) is never preferred.  The
  heuristic anchor (slot 0) has no special status.  On an exact prior tie the
  original argmax stands, then admission order.  Evidence: about 60% of the
  low-single leads reviewed in production were value near-ties (< 0.02), where
  the argmax is effectively arbitrary while the policy has a preference.
  PRECEDENCE with ``tiebreak_points`` when both are on -- the rule is
  ADDITIVE on top of the points rule, never a replacement.  The points rule
  runs FIRST, exactly as it does alone (it does act on leads: it prices the
  trick the heuristic finisher completes), and its record is unchanged.  Any
  selection it CHANGES is kept: the prior rule stands aside
  (``lead_tiebreak_applied`` False, ``lead_tiebreak_superseded``
  ``"tiebreak_points"``).  The prior decides only on a lead where the points
  rule leaves the original argmax in place (a singleton near-set, the argmax
  banks the most points or ties for them, or the rebuild abandoned itself on
  the serving budget).  On a FOLLOW this rule does nothing.  So with both on,
  every decision the points rule moves is played exactly as without this rule.
  The record carries scalars only: ``lead_tiebreak_leading``,
  ``lead_tiebreak_applied`` (this rule moved the selection off the argmax),
  ``lead_tiebreak_near_count``, ``lead_tiebreak_from_index`` /
  ``lead_tiebreak_to_index`` (admitted positions: the argmax, this rule's
  choice), ``lead_tiebreak_from`` / ``lead_tiebreak_to`` (their cards),
  ``lead_tiebreak_value_gap`` (the value mean given up, >= 0) and, only when
  the points rule's change was kept, ``lead_tiebreak_superseded``.

Optional PLAYED-ACTION rule (OXPS round 1, release 38; OFF BY DEFAULT, and while
off the played action is the selected candidate exactly as before):

* ``doomed_throw_swap`` -- after the selection (every selection rule above
  included), when the acting seat is LEADING and the selected action is a
  multi-card lead that the engine REFUSES in EVERY sampled world with the SAME
  forced component (`harvest.legal.forced_lead`, the engine's own
  ``validate_lead`` on that world's hands), that forced component is played
  instead of the throw.  The value is unchanged under the search's own model:
  the throw's leaf in each world (`_leaf` -> `afterstate` -> ``Round.play``)
  already IS the forced component played, because a rollout clone posts no
  failed-throw notice and the encoder reads none, so the two leaves are the same
  state.  The throw was therefore a free alias of its forced card, and it won
  only by first-argmax order over equal values; played for real it also posts a
  public notice that shows the thrown cards (and, under the refusal sampler
  rule, constrains the other bots' worlds).  The swap removes only that.  A
  throw that stands in some world, or that is forced to different components in
  different worlds, is played unchanged (its exposure is not priced here).
  Nothing in the admission, the value pass or the selection changes, no model
  is called, and ``selected_index`` / ``value_means`` keep describing the
  search; the record adds scalars only: ``doomed_throw_swap_applied``,
  ``doomed_throw_swap_from`` / ``doomed_throw_swap_to`` (cards; ``to`` equals
  ``from`` when nothing was swapped), ``doomed_throw_swap_worlds`` and
  ``doomed_throw_swap_refused_worlds`` (sampled worlds and how many refused the
  throw; 0 when the selected action was not a multi-card lead) and
  ``doomed_throw_swap_forced_variants`` (distinct forced components seen).  The
  check runs under the serving deadline (strided like the forced-component
  rule); on expiry it abandons itself and the selected action is played, with
  ``doomed_throw_swap_abandoned`` ``"budget"``.

Optional ADMISSION exclusion (#676 online lead review, ranked fix 3 "LJ-into-
unseen-BJ guard", board #707 S4 formerly A9; OFF BY DEFAULT, and while off the
admitted indices, slot 0 and the record are exactly what they were):

* ``small_joker_guard`` -- when the acting seat is LEADING, holds a small joker
  (``LJ``) and at least ``SMALL_JOKER_GUARD_MIN_OTHER_TRUMPS`` (3) other trumps
  (the trumps in its hand minus the one led small joker), and at least one big
  joker (``BJ``) is OUTSTANDING, the single-``LJ`` lead is dropped from the
  admission: it never enters the K policy slots, it is never slot 0 (a
  heuristic or ``lead_anchor`` slot 0 that is the single ``LJ`` is replaced by
  the best remaining policy-ranked action), and it is never a forced extra.
  The policy back-fills the slot from its own ranking, so K is unchanged.
  "Outstanding" uses only what the seat knows: the deck's big jokers minus
  those in its own hand, those played in any resolved trick or the current one,
  and (banker only) those in its own buried kitty -- never another seat's hand.
  Multi-card leads that contain an ``LJ`` (``LJ LJ``, a throw) and every
  follow are untouched.  Evidence (#676, Claude's online lead review): LJ
  leads won only 6/12 tricks in production and all six losses were to the big
  joker; self-play won 73% of 67.  No model is called and nothing is rebuilt.
  The record carries scalars only: ``small_joker_guard_active`` (the condition
  held and a single-``LJ`` lead was in the scored set, i.e. it was excluded),
  ``small_joker_guard_big_jokers_out``, ``small_joker_guard_other_trumps`` and
  ``small_joker_guard_anchor_replaced`` (slot 0 was the single ``LJ``).  The
  budget fallback still plays the heuristic anchor (the rule does not reach it).
"""
from __future__ import annotations

import time
from collections import Counter

import numpy as np

from ..ai.cwv_policy import afterstate
from ..ai.heuristic import HeuristicBot
from ..engine.cards import BJ, LJ, TRUMP, make_deck
from ..engine.combos import decompose
from ..harvest.legal import enumerate_legal, forced_lead
from .policy_world_search import PolicyWorldBot

#: `admit_forced_single` may grow the shortlist by at most this many slots (K+2).
FORCED_EXTRA_SLOTS = 2
#: the cooperative budget is checked before every admitted throw and after
#: every this-many sampled worlds inside the throw-resolution loop
FORCED_BUDGET_STRIDE = 16
ADMISSION_DEFAULTS = dict(admission_diversity=False, max_per_structure=2,
                          admit_forced_single=False, forced_min_fraction=0.25)
#: `tiebreak_points`: epsilon in the value head's units (signed levels, see the
#: module docstring); 0.02 of a level is #676's near-tie figure.
TIEBREAK_DEFAULTS = dict(tiebreak_points=False, tiebreak_epsilon=0.02)
#: the cooperative budget is checked before every near-set member and after
#: every this-many sampled worlds inside the tie-break's leaf rebuild
TIEBREAK_BUDGET_STRIDE = FORCED_BUDGET_STRIDE

#: `lead_tiebreak_prior`: the optional lead near-tie rule (module docstring); its
#: epsilon is on the SAME scale as ``tiebreak_epsilon`` (signed levels) and
#: defaults to the same constant.
LEAD_TIEBREAK_DEFAULTS = dict(lead_tiebreak_prior=False,
                              lead_tiebreak_epsilon=TIEBREAK_DEFAULTS["tiebreak_epsilon"])

#: `adaptive_k`: the admission width on a lead whose legal set holds a
#: multi-card action (module docstring); 16 = twice production's K=8.
ADAPTIVE_K_DEFAULTS = dict(adaptive_k=False, candidates_lead_multi=16)

#: `lead_anchor`: the optional slot-0 rule on low-single leads (module docstring)
LEAD_ANCHOR_DEFAULTS = dict(lead_anchor=False)

#: `doomed_throw_swap`: the optional played-action rule (module docstring)
DOOMED_THROW_DEFAULTS = dict(doomed_throw_swap=False)
#: the cooperative budget is checked after every this-many sampled worlds
#: inside the swap's throw-resolution loop
DOOMED_THROW_BUDGET_STRIDE = FORCED_BUDGET_STRIDE

#: `small_joker_guard`: the optional single-LJ lead exclusion (module docstring)
SMALL_JOKER_GUARD_DEFAULTS = dict(small_joker_guard=False)
#: the guard needs this many trumps in hand besides the led small joker
SMALL_JOKER_GUARD_MIN_OTHER_TRUMPS = 3
_DECK = tuple(sorted(set(make_deck())))
_BIG_JOKERS_IN_DECK = make_deck().count(BJ)


def _cards_text(cards):
    """A scalar for the decision record (the screen trace writer drops lists)."""
    return " ".join(cards)


def _is_top_live(rnd, seat, card):
    """True when no live card of ``card``'s effective suit outranks it.  Live =
    not played in a resolved trick or the current one, and not in the seat's
    own kitty (only the banker knows it); the seat's own hand is live, so a
    held higher card makes ``card`` not the top."""
    ordering = rnd.ordering
    suit, level = ordering.eff_suit(card), ordering.level(card)
    gone = Counter()
    tricks = list(rnd.history) + ([rnd.trick] if rnd.trick is not None else [])
    for trick in tricks:
        for play in trick.plays:
            gone.update(play.cards)
    if rnd.banker == seat and rnd.buried:
        gone.update(rnd.buried)
    return not any(ordering.eff_suit(c) == suit and ordering.level(c) > level
                   and gone[c] < 2 for c in _DECK)


def big_jokers_outstanding(rnd, seat):
    """Big jokers ``seat`` cannot account for from public play and its own
    holdings: the deck's copies minus those in its hand, those played in a
    resolved trick or the current one, and (banker only) its own buried kitty.
    Never reads another seat's hand."""
    gone = rnd.hands[seat].count(BJ)
    tricks = list(rnd.history) + ([rnd.trick] if rnd.trick is not None else [])
    for trick in tricks:
        for play in trick.plays:
            gone += list(play.cards).count(BJ)
    if rnd.banker == seat and rnd.buried:
        gone += list(rnd.buried).count(BJ)
    return max(0, _BIG_JOKERS_IN_DECK - gone)


def leading(rnd):
    """True when the acting seat opens the current trick: a trick is open and
    holds no play yet (the complement is exactly `_forced_extras`' follow test)."""
    return rnd.trick is not None and not rnd.trick.plays


def structure_key(rnd, action):
    """``(suit class, card count, component shapes)`` for `admission_diversity`.

    The suit class is the effective suit (plain suit letter or the trump
    token) when the action is one effective suit, else ``"mixed"`` (a void
    follow dumping across suits).  Shapes are the sorted pair-lengths of the
    components of each effective-suit group (0 single, 1 pair, k tractor of k
    pairs) tagged with their suit, so ``[D7,D7,D9]`` and ``[D4,D4,DQ]`` share
    a key while ``[D7,D7,D9,D9]`` (a tractor) and ``[D7,D9]`` do not.
    """
    ordering = rnd.ordering
    groups = {}
    for card in action:
        groups.setdefault(ordering.eff_suit(card), []).append(card)
    shapes = []
    for suit, cards in groups.items():
        for component in decompose(cards, ordering).components:
            shapes.append((suit, component.pair_len))
    suit_class = next(iter(groups)) if len(groups) == 1 else "mixed"
    return (suit_class, len(action), tuple(sorted(shapes)))


def _near_duplicate(counts, size, admitted_counts):
    """True when ``counts`` (a card multiset of ``size`` >= 2 cards) shares all
    but at most one card with an admitted multiset of the same size."""
    if size < 2:
        return False
    for other_size, other in admitted_counts:
        if other_size != size:
            continue
        shared = sum(min(n, other.get(card, 0)) for card, n in counts.items())
        if shared >= size - 1:
            return True
    return False


def _budget_exceeded():
    """The serving wrapper's deadline exception (lazy: that module imports this
    one).  The harness has no deadline, so nothing else is ever caught."""
    from .pv_search_policy import PVSearchBudgetExceeded
    return PVSearchBudgetExceeded


class PolicyValueBot(PolicyWorldBot):
    # class-level OFF defaults for the later optional rule, so a bare instance
    # built without __init__ (`eval.fixed_tape_policy.release38_admission`
    # allocates one and sets only the release-38 fields) admits exactly as before
    small_joker_guard = SMALL_JOKER_GUARD_DEFAULTS["small_joker_guard"]
    _small_joker = None

    def __init__(self, predict, *, evaluator, candidates=8, batch_size=128,
                 admission_diversity=ADMISSION_DEFAULTS["admission_diversity"],
                 max_per_structure=ADMISSION_DEFAULTS["max_per_structure"],
                 admit_forced_single=ADMISSION_DEFAULTS["admit_forced_single"],
                 forced_min_fraction=ADMISSION_DEFAULTS["forced_min_fraction"],
                 tiebreak_points=TIEBREAK_DEFAULTS["tiebreak_points"],
                 tiebreak_epsilon=TIEBREAK_DEFAULTS["tiebreak_epsilon"],
                 adaptive_k=ADAPTIVE_K_DEFAULTS["adaptive_k"],
                 candidates_lead_multi=ADAPTIVE_K_DEFAULTS["candidates_lead_multi"],
                 lead_anchor=LEAD_ANCHOR_DEFAULTS["lead_anchor"],
                 lead_tiebreak_prior=LEAD_TIEBREAK_DEFAULTS["lead_tiebreak_prior"],
                 lead_tiebreak_epsilon=LEAD_TIEBREAK_DEFAULTS["lead_tiebreak_epsilon"],
                 doomed_throw_swap=DOOMED_THROW_DEFAULTS["doomed_throw_swap"],
                 small_joker_guard=SMALL_JOKER_GUARD_DEFAULTS["small_joker_guard"],
                 **kwargs):
        super().__init__(predict, **kwargs)
        if evaluator is None:
            raise ValueError('value evaluator required')
        for name, value in (('candidates', candidates), ('batch_size', batch_size)):
            if type(value) is not int or not 1 <= value <= 512:
                raise ValueError(f'{name} must be an integer in [1,512]')
        for name, value in (('admission_diversity', admission_diversity),
                            ('admit_forced_single', admit_forced_single)):
            if type(value) is not bool:
                raise ValueError(f'{name} must be a bool')
        if type(max_per_structure) is not int or max_per_structure < 1:
            raise ValueError('max_per_structure must be a positive integer')
        if type(forced_min_fraction) not in (int, float) or not 0 < forced_min_fraction <= 1:
            raise ValueError('forced_min_fraction must be in (0,1]')
        self.evaluator = evaluator
        self.candidates = candidates
        self.batch_size = batch_size
        self.admission_diversity = admission_diversity
        self.max_per_structure = max_per_structure
        self.admit_forced_single = admit_forced_single
        self.forced_min_fraction = float(forced_min_fraction)
        self._admission_context = (None, None)
        self._diversity_skipped, self._forced_added, self._forced_detail = [], [], []
        if type(tiebreak_points) is not bool:
            raise ValueError('tiebreak_points must be a bool')
        if type(tiebreak_epsilon) not in (int, float) or not np.isfinite(tiebreak_epsilon) \
                or tiebreak_epsilon < 0:
            raise ValueError('tiebreak_epsilon must be a finite non-negative number')
        self.tiebreak_points = tiebreak_points
        self.tiebreak_epsilon = float(tiebreak_epsilon)
        self._tiebreak = None
        if type(adaptive_k) is not bool:
            raise ValueError('adaptive_k must be a bool')
        # Range-checked on its own, NEVER against ``candidates``: with the rule
        # off the width is unused, so every K main accepted (1..512) must still
        # construct (#687 HOLD: K32..512 refused against the default 16).  With
        # the rule on, a width below ``candidates`` is not a narrowing either:
        # `_admission_k` takes max(candidates, candidates_lead_multi).
        if type(candidates_lead_multi) is not int or not 1 <= candidates_lead_multi <= 512:
            raise ValueError('candidates_lead_multi must be an integer in [1,512]')
        self.adaptive_k = adaptive_k
        self.candidates_lead_multi = candidates_lead_multi
        self._adaptive = {'adaptive_k_applied': False, 'k_used': int(candidates)}
        if type(lead_anchor) is not bool:
            raise ValueError('lead_anchor must be a bool')
        self.lead_anchor = lead_anchor
        self._lead_anchor = None
        if type(lead_tiebreak_prior) is not bool:
            raise ValueError('lead_tiebreak_prior must be a bool')
        if type(lead_tiebreak_epsilon) not in (int, float) \
                or not np.isfinite(lead_tiebreak_epsilon) or lead_tiebreak_epsilon < 0:
            raise ValueError('lead_tiebreak_epsilon must be a finite non-negative number')
        self.lead_tiebreak_prior = lead_tiebreak_prior
        self.lead_tiebreak_epsilon = float(lead_tiebreak_epsilon)
        self._lead_tiebreak = None
        if type(doomed_throw_swap) is not bool:
            raise ValueError('doomed_throw_swap must be a bool')
        self.doomed_throw_swap = doomed_throw_swap
        self._doomed_throw = None
        if type(small_joker_guard) is not bool:
            raise ValueError('small_joker_guard must be a bool')
        self.small_joker_guard = small_joker_guard
        self._small_joker = None

    def _leaf(self, rnd, seat, hands, buried, action, world_index):
        return afterstate(rnd, seat, hands, buried, action, finish_trick=True)

    def _value_means(self, rnd, seat, actions, worlds):
        sums = np.zeros(len(actions), dtype=np.float64)
        pending, indices = [], []
        batches = 0

        def flush():
            nonlocal batches
            if not pending:
                return
            scores = np.asarray(self.evaluator.score(pending, seat), dtype=np.float64)
            if scores.shape != (len(pending),) or not np.isfinite(scores).all():
                raise ValueError('value evaluator requires one finite root-team score per leaf')
            np.add.at(sums, indices, scores)
            batches += 1
            pending.clear()
            indices.clear()

        for world_index, (hands, buried) in enumerate(worlds):
            for index, action in enumerate(actions):
                pending.append(self._leaf(rnd, seat, hands, buried, action, world_index))
                indices.append(index)
                if len(pending) == self.batch_size:
                    flush()
        flush()
        return sums / len(worlds), batches

    def _select(self, rnd, seat, admitted, means, worlds=None, check_budget=None,
                priors=None):
        """The admitted position to play.  ``priors`` are the admitted
        candidates' policy preference scores (the admission's ranking scores),
        needed only by ``lead_tiebreak_prior``."""
        winner = int(np.argmax(means))  # anchor retained on an exact value tie
        chosen = winner
        if self.tiebreak_points:
            chosen = self._select_by_points(rnd, seat, admitted, means, worlds, winner,
                                            check_budget)
        if self.lead_tiebreak_prior:
            # PRECEDENCE: the points rule ran first, unchanged; a selection it
            # moved is kept, the prior decides only where it left the argmax
            chosen = self._select_by_prior(rnd, admitted, means, priors, winner, chosen)
        return chosen

    # -- selection: the optional lead near-tie break by the policy prior -------

    def _select_by_prior(self, rnd, admitted, means, priors, argmax, held=None):
        """The module docstring's ``lead_tiebreak_prior`` rule; sets
        ``self._lead_tiebreak`` (the record fields) on every decision.
        ``held`` is the selection so far (the points rule's, when that rule is
        on; else the argmax): when it already differs from ``argmax`` it is
        returned untouched."""
        held = argmax if held is None else held
        is_lead = leading(rnd)
        winner, near = argmax, []
        means = np.asarray(means, dtype=np.float64)
        superseded = is_lead and held != argmax
        if is_lead:
            if priors is None:
                raise ValueError('lead_tiebreak_prior needs the admitted policy priors')
            priors = np.asarray(priors, dtype=np.float64)
            if priors.shape != means.shape:
                raise ValueError('lead_tiebreak_prior needs one prior per admitted candidate')
            if np.isfinite(means[argmax]):
                near = [int(i) for i in np.flatnonzero(
                    np.isfinite(means) & (means >= means[argmax] - self.lead_tiebreak_epsilon))]
            rated = [i for i in near if np.isfinite(priors[i])]
            if len(near) >= 2 and rated and not superseded:
                # highest prior first; the argmax breaks an exact tie, then admission order
                winner = min(rated, key=lambda i: (-priors[i], i != argmax, i))
        self._lead_tiebreak = {
            'lead_tiebreak_leading': bool(is_lead),
            'lead_tiebreak_applied': winner != argmax,
            'lead_tiebreak_near_count': len(near),
            'lead_tiebreak_from_index': int(argmax),
            'lead_tiebreak_to_index': int(winner),
            'lead_tiebreak_from': _cards_text(admitted[argmax]),
            'lead_tiebreak_to': _cards_text(admitted[winner]),
            'lead_tiebreak_value_gap': float(means[argmax] - means[winner]) if winner != argmax else 0.0,
        }
        if superseded:
            self._lead_tiebreak['lead_tiebreak_superseded'] = 'tiebreak_points'
        return winner if held == argmax else held

    def _lead_tiebreak_record(self):
        if not self.lead_tiebreak_prior or self._lead_tiebreak is None:
            return {}
        return dict(self._lead_tiebreak)

    # -- the played action: the optional doomed-throw swap ----------------------

    def _swap_doomed_throw(self, rnd, seat, action, worlds, check_budget=None):
        """The cards to play for the selected ``action`` (module docstring's
        ``doomed_throw_swap``): its forced component when the engine refuses it
        in every one of ``worlds`` with one forced component, else ``action``.
        Sets ``self._doomed_throw`` (the record fields) whenever the rule is on.
        On the serving deadline the check abandons itself and ``action`` stands
        (the value pass and the selection were complete)."""
        self._doomed_throw = None
        action = list(action)
        if not self.doomed_throw_swap:
            return action
        record = {'doomed_throw_swap_applied': False,
                  'doomed_throw_swap_from': _cards_text(action),
                  'doomed_throw_swap_to': _cards_text(action),
                  'doomed_throw_swap_worlds': len(worlds) if worlds is not None else 0,
                  'doomed_throw_swap_refused_worlds': 0,
                  'doomed_throw_swap_forced_variants': 0}
        self._doomed_throw = record
        if not worlds or not leading(rnd) or len(action) < 2:
            return action
        refused, variants = 0, set()
        try:
            for world_index, (hands, _) in enumerate(worlds):
                if check_budget is not None and world_index \
                        and world_index % DOOMED_THROW_BUDGET_STRIDE == 0:
                    check_budget()
                forced = forced_lead(rnd, seat, action, hands)
                if forced is not None:
                    refused += 1
                    variants.add(tuple(forced))
            # nothing computed past the deadline may be published
            if check_budget is not None:
                check_budget()
        except _budget_exceeded() as exc:
            record['doomed_throw_swap_abandoned'] = 'budget'
            record['doomed_throw_swap_abandon_error'] = type(exc).__name__
            return action
        record['doomed_throw_swap_refused_worlds'] = refused
        record['doomed_throw_swap_forced_variants'] = len(variants)
        if refused != len(worlds) or len(variants) != 1:
            return action
        forced = list(next(iter(variants)))
        record['doomed_throw_swap_applied'] = True
        record['doomed_throw_swap_to'] = _cards_text(forced)
        return forced

    def _doomed_throw_record(self):
        if not self.doomed_throw_swap or self._doomed_throw is None:
            return {}
        return dict(self._doomed_throw)

    # -- selection: the optional epsilon tie-break by trick points -------------

    def _trick_points(self, rnd, seat, hands, buried, action, world_index):
        """The points of ``action``'s trick as the engine resolves it under the
        SAME leaf the value head scored (`_leaf`), signed for the root team:
        + when the trick's winner is the root team, - when it is the other."""
        leaf = self._leaf(rnd, seat, hands, buried, action, world_index)
        trick = leaf.last_trick
        if len(leaf.history) != len(rnd.history) + 1 or trick is None or trick.winner is None:
            raise RuntimeError('tie-break leaf did not resolve exactly the current trick')
        ours = rnd.is_attacker(trick.winner) == rnd.is_attacker(seat)
        return int(trick.points) if ours else -int(trick.points)

    def _select_by_points(self, rnd, seat, admitted, means, worlds, argmax, check_budget=None):
        """The module docstring's rule.  ``worlds`` are the sampled worlds the
        means were taken over; the near-set's leaves are rebuilt in each, under
        ``check_budget`` (the serving deadline): on expiry the rebuild stops and
        ``argmax`` is returned, the record saying so."""
        if worlds is None:
            raise ValueError('tiebreak_points needs the sampled worlds')
        means = np.asarray(means, dtype=np.float64)
        near = [int(i) for i in np.flatnonzero(means >= means[argmax] - self.tiebreak_epsilon)]
        self._tiebreak = {'tiebreak_applied': False, 'tiebreak_near_set': near,
                          'tiebreak_points': []}
        if len(near) < 2:
            return argmax
        sums = {i: 0 for i in near}
        try:
            for i in near:
                if check_budget is not None:
                    check_budget()
                for world_index, (hands, buried) in enumerate(worlds):
                    if check_budget is not None and world_index \
                            and world_index % TIEBREAK_BUDGET_STRIDE == 0:
                        check_budget()
                    sums[i] += self._trick_points(rnd, seat, hands, buried, admitted[i], world_index)
            # final post-rebuild check: the strided checks above miss expiry
            # inside the last <= TIEBREAK_BUDGET_STRIDE-world chunk, and nothing
            # computed past the deadline may be published
            if check_budget is not None:
                check_budget()
        except _budget_exceeded() as exc:
            # the value pass was complete and within budget; only the optional
            # refinement is past it, so the argmax stands and nothing falls back
            self._tiebreak['tiebreak_abandoned'] = 'budget'
            self._tiebreak['tiebreak_abandon_error'] = type(exc).__name__
            return argmax
        # most points first; the argmax breaks an exact tie, then admission order
        winner = min(near, key=lambda i: (-sums[i], i != argmax, i))
        self._tiebreak['tiebreak_points'] = [sums[i] / len(worlds) for i in near]
        self._tiebreak['tiebreak_applied'] = winner != argmax
        return winner

    def _tiebreak_record(self):
        if not self.tiebreak_points:
            return {}
        return dict(self._tiebreak)

    # -- admission ------------------------------------------------------------

    def _admission_k(self, rnd, actions, preferences):
        """``(K, applied)`` for this decision: ``candidates``, or with
        ``adaptive_k`` on a lead whose scored set holds a multi-card action,
        ``max(candidates, candidates_lead_multi)`` (module docstring).  The
        rule only ever WIDENS: when ``candidates`` already meets or exceeds
        ``candidates_lead_multi`` (e.g. a fixed K=32 recipe with the default
        16) the ballot stays ``candidates`` wide and ``applied`` is False, so
        ``applied`` means exactly "this decision admitted more than
        ``candidates``".  An entry with a non-finite preference is not
        production's (the harvest mixin masks a forced-in exploration draw to
        -inf) and never decides the width."""
        if not self.adaptive_k or not leading(rnd):
            return self.candidates, False
        multi = any(len(action) >= 2 and np.isfinite(preferences[i])
                    for i, action in enumerate(actions))
        if not multi:
            return self.candidates, False
        k = max(self.candidates, self.candidates_lead_multi)
        return k, k > self.candidates

    def _admit(self, rnd, seat, actions, preferences, anchor_index):
        """Indices (into ``actions``) the value head prices -- THE FINAL scored
        ballot: the anchor first, then the policy's best scores, K in all
        (``self.candidates``, or the widened width of `_admission_k` under
        ``adaptive_k``, decided first), then (``admit_forced_single``) the forced components, at most
        `FORCED_EXTRA_SLOTS`.  With ``admission_diversity`` the structural caps
        apply (module docstring); the capped indices that stayed out are kept in
        ``self._diversity_skipped``, the forced extras in ``self._forced_added``.

        Everything that reaches the value head is decided HERE, so a wrapper that
        captures the ballot at the admission boundary (the trajectory mixin's
        production ballot, a hook override's ``super()._admit``) sees exactly what
        is priced.  The signature is the hook contract (five positionals); the
        sampled worlds and the serving deadline callback the forced-component rule
        needs arrive through ``self._admission_context``, set by the caller for
        the duration of the call (`_admission`).
        """
        worlds, check_budget = self._admission_context
        ranked = sorted(range(len(actions)), key=lambda i: (-preferences[i], i))
        guarded = set()
        if self.small_joker_guard:
            guarded = self._small_joker_guarded(rnd, seat, actions)
            if guarded:
                ranked = [i for i in ranked if i not in guarded]
        if self.lead_anchor:
            anchor_index = self._lead_anchor_index(rnd, seat, actions, preferences,
                                                   anchor_index, ranked)
        if anchor_index in guarded:
            anchor_index = self._small_joker_anchor(actions, preferences, anchor_index, ranked)
        k, applied = self._admission_k(rnd, actions, preferences)
        self._adaptive = {'adaptive_k_applied': applied, 'k_used': int(k)}
        self._diversity_skipped = []
        self._forced_added, self._forced_detail = [], []
        if not self.admission_diversity:
            chosen = [anchor_index]
            chosen.extend(i for i in ranked if i != anchor_index)
            chosen = chosen[:k]
        else:
            chosen = self._admit_diverse(rnd, actions, ranked, anchor_index, k)
        if self.admit_forced_single:
            if worlds is None:
                raise ValueError('admit_forced_single needs the sampled worlds at admission')
            extras, detail = self._forced_extras(rnd, seat, actions, chosen, worlds,
                                                 check_budget=check_budget)
            if guarded:
                extras = [i for i in extras if i not in guarded]
            self._forced_added, self._forced_detail = extras, detail
            chosen = list(chosen) + extras
        return chosen

    # -- admission: the optional single small-joker lead exclusion -------------

    def _small_joker_guarded(self, rnd, seat, actions):
        """The indices (into ``actions``) of the single-``LJ`` lead when the
        module docstring's ``small_joker_guard`` condition holds, else the empty
        set.  Sets ``self._small_joker`` (the record fields) on every decision."""
        hand = rnd.hands[seat]
        trumps = sum(1 for c in hand if rnd.ordering.eff_suit(c) == TRUMP)
        other = trumps - 1 if LJ in hand else trumps
        out = big_jokers_outstanding(rnd, seat)
        singles = {i for i, action in enumerate(actions) if list(action) == [LJ]}
        active = bool(leading(rnd) and LJ in hand and out > 0
                      and other >= SMALL_JOKER_GUARD_MIN_OTHER_TRUMPS
                      and singles and len(singles) < len(actions))
        self._small_joker = {
            "small_joker_guard_active": active,
            "small_joker_guard_big_jokers_out": int(out),
            "small_joker_guard_other_trumps": int(other),
            "small_joker_guard_anchor_replaced": False,
        }
        return singles if active else set()

    def _small_joker_anchor(self, actions, preferences, anchor_index, ranked):
        """Slot 0 when it is the guarded single ``LJ``: the best remaining
        policy-ranked action (``ranked`` already excludes the guarded lead)."""
        finite = [i for i in ranked if np.isfinite(preferences[i])]
        target = finite[0] if finite else ranked[0]
        self._small_joker["small_joker_guard_anchor_replaced"] = True
        self._small_joker["small_joker_guard_anchor_to"] = _cards_text(actions[target])
        return target

    def _small_joker_record(self):
        if not self.small_joker_guard or self._small_joker is None:
            return {}
        return dict(self._small_joker)

    def _lead_anchor_index(self, rnd, seat, actions, preferences, anchor_index, ranked):
        """Slot 0 under ``lead_anchor`` (module docstring): the heuristic's index,
        or its replacement on a low-single lead.  ``ranked`` is the admission's
        own preference order, reused (no new model call).  Sets
        ``self._lead_anchor`` (the record fields, the effective anchor's cards)."""
        anchor = list(actions[anchor_index])
        target, source = anchor_index, "heuristic"
        ordering = rnd.ordering
        if leading(rnd) and len(anchor) == 1 and ordering.eff_suit(anchor[0]) != TRUMP \
                and not _is_top_live(rnd, seat, anchor[0]):
            best = None
            for i, action in enumerate(actions):
                if len(action) < 2 or not np.isfinite(preferences[i]):
                    continue
                suits = {ordering.eff_suit(c) for c in action}
                if len(suits) != 1 or TRUMP in suits:
                    continue
                components = decompose(list(action), ordering).components
                if len(components) != 1 or components[0].pair_len < 1:
                    continue
                key = (components[0].top, len(action), -i)
                if best is None or key > best[0]:
                    best = (key, i)
            if best is not None:
                target, source = best[1], "pair"
            elif ranked and np.isfinite(preferences[ranked[0]]):
                target, source = ranked[0], "policy"
        self._lead_anchor = {
            "lead_anchor_applied": target != anchor_index,
            "lead_anchor_from": _cards_text(anchor),
            "lead_anchor_to": _cards_text(actions[target]),
            "lead_anchor_source": source if target != anchor_index else "heuristic",
        }
        return target

    def _effective_anchor_key(self, anchor_key):
        """The cards key slot 0 must hold: the heuristic anchor's, or (rule on)
        the one `_lead_anchor_index` chose for this decision, or (guard on) the
        replacement of a guarded single small joker."""
        if self.small_joker_guard and self._small_joker is not None \
                and self._small_joker["small_joker_guard_anchor_replaced"]:
            return tuple(sorted(self._small_joker["small_joker_guard_anchor_to"].split(" ")))
        if self.lead_anchor and self._lead_anchor is not None:
            return tuple(sorted(self._lead_anchor["lead_anchor_to"].split(" ")))
        return anchor_key

    def _admit_diverse(self, rnd, actions, ranked, anchor_index, k=None):
        k = self.candidates if k is None else k
        chosen = [anchor_index]
        per_structure = Counter([structure_key(rnd, actions[anchor_index])])
        admitted_counts = [(len(actions[anchor_index]), Counter(actions[anchor_index]))]
        skipped = []
        for i in ranked:
            if len(chosen) >= k:
                break
            if i == anchor_index:
                continue
            action = actions[i]
            key = structure_key(rnd, action)
            counts = Counter(action)
            if per_structure[key] >= self.max_per_structure \
                    or _near_duplicate(counts, len(action), admitted_counts):
                skipped.append(i)
                continue
            chosen.append(i)
            per_structure[key] += 1
            admitted_counts.append((len(action), counts))
        # back-fill from the capped actions, best preference first, so K is
        # filled whenever the legal set allows
        backfill = skipped[:max(0, k - len(chosen))]
        chosen.extend(backfill)
        self._diversity_skipped = skipped[len(backfill):]
        return chosen

    def _forced_extras(self, rnd, seat, actions, chosen, worlds, check_budget=None):
        """Indices of the forced components to admit next to the admitted throws
        (``admit_forced_single``) and their detail records.  Empty on a follow,
        and whenever the rule is off.  ``check_budget`` (the serving deadline)
        runs before every admitted throw and every `FORCED_BUDGET_STRIDE` worlds
        inside the resolution loop, so the work between two checks is bounded
        by one stride of engine validations, never by throws x worlds."""
        if not self.admit_forced_single or not leading(rnd):
            return [], []
        index_of = {tuple(a): i for i, a in enumerate(actions)}
        admitted = set(chosen)
        extras, detail = [], []
        for throw_index in chosen:
            if len(extras) >= FORCED_EXTRA_SLOTS:
                break
            action = actions[throw_index]
            if len(action) < 2 or len(decompose(list(action), rnd.ordering).components) < 2:
                continue
            if check_budget is not None:
                check_budget()
            tally = Counter()
            for world_index, (hands, _) in enumerate(worlds):
                if check_budget is not None and world_index and world_index % FORCED_BUDGET_STRIDE == 0:
                    check_budget()
                forced = forced_lead(rnd, seat, action, hands)
                if forced is not None:
                    tally[tuple(forced)] += 1
            if not tally:
                continue
            # most worlds first; ties by the forced component's enumeration order
            # (an unlisted component -- the capped listing withheld it -- sorts last
            # and is never admitted, only recorded)
            forced, count = min(tally.items(),
                                key=lambda kv: (-kv[1], index_of.get(kv[0], len(actions))))
            fraction = count / len(worlds)
            entry = {"throw_index": int(throw_index), "forced": list(forced),
                     "index": index_of.get(forced), "worlds_forced": int(count),
                     "fraction": fraction, "admitted": False}
            index = entry["index"]
            if index is not None and fraction >= self.forced_min_fraction \
                    and index not in admitted:
                extras.append(index)
                admitted.add(index)
                entry["admitted"] = True
            detail.append(entry)
        return extras, detail

    def _admission(self, rnd, seat, actions, preferences, anchor_index, worlds,
                   check_budget=None):
        """`_admit` with the per-decision context (worlds, deadline) in place."""
        self._admission_context = (worlds, check_budget)
        self._lead_anchor = None
        self._small_joker = None
        try:
            return [int(i) for i in self._admit(rnd, seat, actions, preferences, anchor_index)]
        finally:
            self._admission_context = (None, None)

    def _admission_record(self):
        """The rule fields of the decision record; EMPTY with both rules off."""
        record = {}
        if self.admission_diversity:
            record["diversity_skipped"] = [int(i) for i in self._diversity_skipped]
        if self.admit_forced_single:
            record["forced_single_added"] = [int(i) for i in self._forced_added]
            record["forced_single_detail"] = list(self._forced_detail)
        if self.adaptive_k:
            record.update(self._adaptive)
        if self.lead_anchor and self._lead_anchor is not None:
            record.update(self._lead_anchor)
        record.update(self._small_joker_record())
        return record

    def decide_play(self, rnd, seat):
        self.last_decision_record = None
        self.last_world_diversity = None
        started = time.perf_counter()
        anchor = HeuristicBot().decide_play(rnd, seat)
        legal = enumerate_legal(rnd, seat, cap=self.cap, must_include=[anchor])
        actions = list(legal.actions)
        worlds, attempts = self._worlds(rnd, seat)
        diversity = self.last_world_diversity
        preferences = self.scores(rnd, seat, actions, worlds).mean(axis=0)
        # The anchor occupies one slot. Ties follow enumeration order. Compare
        # card multisets because the heuristic need not return canonical order.
        anchor_key = tuple(sorted(anchor))
        anchor_index = next(i for i, a in enumerate(actions)
                            if tuple(sorted(a)) == anchor_key)
        chosen = self._admission(rnd, seat, actions, preferences, anchor_index, worlds)
        admitted = [actions[i] for i in chosen]
        means, batches = self._value_means(rnd, seat, admitted, worlds)
        winner = self._select(rnd, seat, admitted, means, worlds=worlds,
                              priors=[float(preferences[i]) for i in chosen])
        played = self._swap_doomed_throw(rnd, seat, admitted[winner], worlds)
        self.last_decision_record = {
            'schema': 'policy-admit-value-mean-v1', 'worlds': len(worlds),
            'sample_attempts': attempts, 'actions': len(actions), 'cap': self.cap,
            'world_diversity': diversity,
            'legal_count': legal.count, 'legal_complete': legal.complete,
            'admitted_indices': chosen, 'value_means': means.tolist(),
            'selected_index': chosen[winner], 'value_batches': batches,
            'value_evaluations': len(worlds) * len(admitted),
            'seconds': time.perf_counter() - started,
            **self._admission_record(),
            **self._tiebreak_record(),
            **self._lead_tiebreak_record(),
            **self._doomed_throw_record(),
        }
        return played
