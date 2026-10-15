"""The policy head playing the value leaf's first trick (OFF BY DEFAULT).

``SHENGJI_PV_LEAF_POLICY_FIRST_TRICK=1`` (wiring, name token ``lpft``, recipe
digest and the record keys: `pv_search_policy`).  The value head needs a card
on the table (the frozen afterstate encoder rejects a position with no played
card), so both value leaves of the served bot -- the bury scoring of
`cwv_bury.score_bury_candidates` inside `cwv_bury_policy.CWVBuryMixin`'s
hybrid/value arms, and `value_declare.declare_outcome_position` -- complete
exactly the first trick before the head scores the position.  Served, that
trick is the HEURISTIC's (`HeuristicBot.decide_play` at every seat).  With the
rule on it is the POLICY HEAD's: at each of the four seats, the argmax of the
same package's policy prior (`pv_search_policy.NumpyPriorPredict`, the
admission's scorer) over the seat's COMPLETE legal set in that determinized
world.  One cheap policy call per seat and world: no value call, no world
sampling, no search.

The score of an action is the admission's (`cwv_prior_admission.action_scores`:
the sum of its cards' log-odds, a pair counting its card twice), and the legal
set's structure (`harvest.legal`, the enumeration the served admission ranks)
makes the argmax over the WHOLE set computable without enumerating it:

* a LEAD is any non-empty sub-multiset of one effective suit (`_lead_groups`:
  singles, pairs, tractors and throws alike), so the best lead of a suit is
  every card of the suit with POSITIVE log-odds (both copies of a pair when
  its card is positive) or, when none is, its single highest-log-odds card;
  the lead is the best suit's (a strictly higher score replaces: suit order,
  then the lower card index, settles a tie).  A multi-component lead is a
  throw the world's engine may force to a component, as it would at the table;
* a FOLLOW with enough cards of the led suit (`_follow_case` ``in-suit``) is
  one of the led-size subsets of them the engine's own `validate_follow`
  accepts (`iter_follow_actions`): these are enumerated, in enumeration order,
  up to `FOLLOW_CAP` (4000, the served admission's cap) and scored exactly as
  the admission scores them (first max on a tie); an enumeration that reaches
  the cap is incomplete and the seat falls back;
* a FOLLOW short of or void in the led suit plays every card it holds of the
  suit plus any off-suit fill of the remaining size (`iter_follow_actions`
  yields every fill), so the fill is the top-scoring off-suit cards (the lower
  card index on a tie).

The seat's input row is the served root encoding (`policy_prior.root_tensors`,
which handles the opening lead's empty history) of the leaf position itself --
a complete determinized world, so the row is what the served bot would encode
at that seat with those hands.

Fallback: a seat whose policy call fails (an exception in the encoding, the
predictor, the legal structure or the choice; a predictor row that is not
finite 54-wide log-odds) or whose follow enumeration is incomplete is played
by the HEURISTIC (``fallback.decide_play``), and `PolicyFirstTrick.fallbacks`
counts those seats; `policy_plays` counts the seats the policy played.  The
serving deadline (``check_budget``) is never swallowed: it runs OUTSIDE the
guarded calls, at every expensive-work boundary -- before each play's row
encoding, again after the encoding and BEFORE the predictor dispatch (an
expiry during encoding begins no model call), and once more after the trick's
last play, BEFORE the consumer's value inference (an expiry on the fourth
policy batch begins no value batch) -- so an expiry propagates to the stage's
own fallback (the bury's heuristic incumbent, the declare's heuristic choice)
without starting another model call.

`play_first_tricks` plays the trick on a BATCH of positions, play by play
(the lead at every position, one predictor call over the batch, then the
second plays, ...), so the predictor runs four times per batch instead of four
times per position; the per-position results are what the sequential
`PolicyFirstTrick.decide_play` would give (each row is its own position's
encoding).  `cwv_bury.score_bury_candidates` and
`pv_search_policy.PVSearchBot._value_declare_means` call it on each value
batch before the evaluator scores it.
"""
from __future__ import annotations

import numpy as np

from ..harvest.legal import _follow_case, _lead_groups, iter_follow_actions

#: the in-suit follow enumeration bound (the served admission's cap); reaching
#: it means the set is incomplete and the seat falls back
FOLLOW_CAP = 4000
#: the plays of one trick
TRICK_PLAYS = 4


def best_lead(hand, ordering, log_odds, card_index):
    """The argmax lead (module docstring): ``(score, cards)``, or None for an
    empty hand."""
    best = None
    for _suit, cards in _lead_groups(hand, ordering):
        scored = [(float(log_odds[card_index[c]]), card_index[c], c) for c in cards]
        positive = [(s, c) for s, _i, c in scored if s > 0.0]
        if positive:
            score, action = sum(s for s, _ in positive), [c for _, c in positive]
        else:
            score, _index, card = max(scored, key=lambda t: (t[0], -t[1]))
            action = [card]
        if best is None or score > best[0]:
            best = (score, sorted(action))
    return best


def best_follow(hand, lead, ordering, log_odds, card_index, cap=FOLLOW_CAP):
    """The argmax follow (module docstring): the cards, or None when the
    in-suit enumeration is incomplete at ``cap``."""
    case, h_suit, off, n = _follow_case(list(hand), list(lead), ordering)
    if case == "in-suit":
        actions = []
        for key in iter_follow_actions(list(hand), list(lead), ordering):
            if len(actions) >= cap:
                return None
            actions.append(list(key))
        if not actions:
            return None
        from .cwv_prior_admission import action_scores
        scores = action_scores(np.asarray(log_odds, dtype=np.float64)[None, :], actions)[0]
        return list(actions[int(np.argmax(scores))])   # first max: the lowest index on a tie
    need = n - len(h_suit)
    ranked = sorted(off, key=lambda c: (-float(log_odds[card_index[c]]), card_index[c]))
    return sorted(list(h_suit) + ranked[:need])


class PolicyFirstTrick:
    """The policy head's first-trick player (module docstring).

    ``predict``: the package's ``(rows, 54)`` log-odds callable; ``version``:
    its encoder version; ``fallback``: the heuristic (``decide_play(rnd, seat)``);
    ``check_budget``: the serving deadline, or None.  Counters: ``policy_plays``,
    ``fallbacks``, ``batches`` (predictor calls).
    """

    def __init__(self, predict, version: int, fallback, *, check_budget=None):
        self.predict = predict
        self.version = int(version)
        self.fallback = fallback
        self.check_budget = check_budget
        self.policy_plays = 0
        self.fallbacks = 0
        self.batches = 0

    # -- the per-seat pieces ---------------------------------------------------

    def _row(self, rnd, seat):
        """The seat's policy input row, or None when it cannot be encoded."""
        from .policy_prior import flat_input, root_tensors   # torch-free, lazy as serving's
        try:
            return flat_input(root_tensors(rnd, seat, self.version), self.version)
        except Exception:
            return None

    def _log_odds(self, rows):
        """The predictor over the stacked rows, or None when it fails or returns
        anything but finite ``(len(rows), 54)`` log-odds."""
        from .policy_prior import N_CARDS
        try:
            log_odds = np.asarray(self.predict(np.stack(rows).astype(np.float32)), dtype=np.float64)
        except Exception:
            return None
        if log_odds.shape != (len(rows), N_CARDS) or not np.isfinite(log_odds).all():
            return None
        return log_odds

    @staticmethod
    def _choose(rnd, seat, log_odds_row):
        """The argmax action for ``seat`` (module docstring), or None."""
        from .policy_prior import CARD_INDEX
        try:
            hand = rnd.hands[seat]
            if not rnd.trick.plays:
                best = best_lead(hand, rnd.ordering, log_odds_row, CARD_INDEX)
                return None if best is None else best[1]
            return best_follow(hand, rnd.trick.plays[0].cards, rnd.ordering, log_odds_row,
                               CARD_INDEX)
        except Exception:
            return None

    def _play(self, position, seat, log_odds_row):
        action = None if log_odds_row is None else self._choose(position, seat, log_odds_row)
        if action is None:
            self.fallbacks += 1
            action = self.fallback.decide_play(position, seat)
        else:
            self.policy_plays += 1
        return action

    # -- one position at a time -------------------------------------------------

    def decide_play(self, rnd, seat):
        """The policy argmax for ``seat`` at ``rnd``, else the fallback's play."""
        if self.check_budget is not None:
            self.check_budget()
        row = self._row(rnd, seat)
        if self.check_budget is not None:
            self.check_budget()   # an expiry during encoding starts no predictor call
        log_odds = None if row is None else self._log_odds([row])
        if log_odds is not None:
            self.batches += 1
        return self._play(rnd, seat, None if log_odds is None else log_odds[0])

    # -- a batch of positions ---------------------------------------------------

    def play_first_tricks(self, positions):
        """Complete the first trick at every position (each with the trick's
        leader to act), play by play across the batch (module docstring).
        Mutates the positions; returns None."""
        for _ in range(TRICK_PLAYS):
            if self.check_budget is not None:
                self.check_budget()
            rows = [self._row(position, position.turn) for position in positions]
            if self.check_budget is not None:
                self.check_budget()   # an expiry during encoding starts no predictor call
            encoded = [row for row in rows if row is not None]
            log_odds = self._log_odds(encoded) if encoded else None
            if log_odds is not None:
                self.batches += 1
            cursor = 0
            for position, row in zip(positions, rows):
                seat = position.turn
                log_odds_row = None
                if row is not None:
                    if log_odds is not None:
                        log_odds_row = log_odds[cursor]
                    cursor += 1
                position.play(seat, self._play(position, seat, log_odds_row))
        if self.check_budget is not None:
            self.check_budget()   # an expiry on the last play starts no value batch


__all__ = ["FOLLOW_CAP", "TRICK_PLAYS", "PolicyFirstTrick", "best_lead", "best_follow"]
