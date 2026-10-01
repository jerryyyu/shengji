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
  when the near-set is a singleton; no model is consulted.
"""
from __future__ import annotations

import time
from collections import Counter

import numpy as np

from ..ai.cwv_policy import afterstate
from ..ai.heuristic import HeuristicBot
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


class PolicyValueBot(PolicyWorldBot):
    def __init__(self, predict, *, evaluator, candidates=8, batch_size=128,
                 admission_diversity=ADMISSION_DEFAULTS["admission_diversity"],
                 max_per_structure=ADMISSION_DEFAULTS["max_per_structure"],
                 admit_forced_single=ADMISSION_DEFAULTS["admit_forced_single"],
                 forced_min_fraction=ADMISSION_DEFAULTS["forced_min_fraction"],
                 tiebreak_points=TIEBREAK_DEFAULTS["tiebreak_points"],
                 tiebreak_epsilon=TIEBREAK_DEFAULTS["tiebreak_epsilon"],
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

    def _select(self, rnd, seat, admitted, means, worlds=None):
        winner = int(np.argmax(means))  # anchor retained on an exact value tie
        if not self.tiebreak_points:
            return winner
        return self._select_by_points(rnd, seat, admitted, means, worlds, winner)

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

    def _select_by_points(self, rnd, seat, admitted, means, worlds, argmax):
        """The module docstring's rule.  ``worlds`` are the sampled worlds the
        means were taken over; the near-set's leaves are rebuilt in each."""
        if worlds is None:
            raise ValueError('tiebreak_points needs the sampled worlds')
        means = np.asarray(means, dtype=np.float64)
        near = [int(i) for i in np.flatnonzero(means >= means[argmax] - self.tiebreak_epsilon)]
        self._tiebreak = {'tiebreak_applied': False, 'tiebreak_near_set': near,
                          'tiebreak_points': []}
        if len(near) < 2:
            return argmax
        sums = {i: 0 for i in near}
        for world_index, (hands, buried) in enumerate(worlds):
            for i in near:
                sums[i] += self._trick_points(rnd, seat, hands, buried, admitted[i], world_index)
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

    def _admit(self, rnd, seat, actions, preferences, anchor_index):
        """Indices (into ``actions``) the value head prices -- THE FINAL scored
        ballot: the anchor first, then the policy's best scores, ``self.candidates``
        in all, then (``admit_forced_single``) the forced components, at most
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
        self._diversity_skipped = []
        self._forced_added, self._forced_detail = [], []
        if not self.admission_diversity:
            chosen = [anchor_index]
            chosen.extend(i for i in ranked if i != anchor_index)
            chosen = chosen[:self.candidates]
        else:
            chosen = self._admit_diverse(rnd, actions, ranked, anchor_index)
        if self.admit_forced_single:
            if worlds is None:
                raise ValueError('admit_forced_single needs the sampled worlds at admission')
            extras, detail = self._forced_extras(rnd, seat, actions, chosen, worlds,
                                                 check_budget=check_budget)
            self._forced_added, self._forced_detail = extras, detail
            chosen = list(chosen) + extras
        return chosen

    def _admit_diverse(self, rnd, actions, ranked, anchor_index):
        k = self.candidates
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
        if not self.admit_forced_single or rnd.trick is None or rnd.trick.plays:
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
        return record

    def decide_play(self, rnd, seat):
        self.last_decision_record = None
        started = time.perf_counter()
        anchor = HeuristicBot().decide_play(rnd, seat)
        legal = enumerate_legal(rnd, seat, cap=self.cap, must_include=[anchor])
        actions = list(legal.actions)
        worlds, attempts = self._worlds(rnd, seat)
        preferences = self.scores(rnd, seat, actions, worlds).mean(axis=0)
        # The anchor occupies one slot. Ties follow enumeration order. Compare
        # card multisets because the heuristic need not return canonical order.
        anchor_key = tuple(sorted(anchor))
        anchor_index = next(i for i, a in enumerate(actions)
                            if tuple(sorted(a)) == anchor_key)
        chosen = self._admission(rnd, seat, actions, preferences, anchor_index, worlds)
        admitted = [actions[i] for i in chosen]
        means, batches = self._value_means(rnd, seat, admitted, worlds)
        winner = self._select(rnd, seat, admitted, means, worlds=worlds)
        self.last_decision_record = {
            'schema': 'policy-admit-value-mean-v1', 'worlds': len(worlds),
            'sample_attempts': attempts, 'actions': len(actions), 'cap': self.cap,
            'legal_count': legal.count, 'legal_complete': legal.complete,
            'admitted_indices': chosen, 'value_means': means.tolist(),
            'selected_index': chosen[winner], 'value_batches': batches,
            'value_evaluations': len(worlds) * len(admitted),
            'seconds': time.perf_counter() - started,
            **self._admission_record(),
            **self._tiebreak_record(),
        }
        return list(admitted[winner])
