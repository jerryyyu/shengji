"""Determinized Monte Carlo bot.

For every play decision:
 1. Enumerate a small, diverse set of legal candidate plays.
 2. Sample N "determinizations": full deals of the unseen cards to the other
    players (and hidden kitty), consistent with public information — hand
    sizes, observed voids, and the card count. The banker's own knowledge of
    the buried kitty is used when this bot IS the banker (that's private but
    legitimately its own information).
 3. Roll each (candidate, determinization) to the end of the round with the
    fast heuristic policy for all four seats, scoring attacker points
    (sign-flipped for the banker team).
 4. Play the candidate with the best average score.

Declaration and burying are inherited from SmartBot.
"""

from __future__ import annotations

import copy
import random
from collections import Counter

from ..engine.cards import TRUMP
from ..engine.combos import decompose
from ..engine.legal import IllegalPlay, suit_cards, uniform_suit, validate_follow
from ..engine.round import Round, Trick, TrickPlay
from .heuristic import PLAIN_SUITS, HeuristicBot
from .memory import Memory
from .smart import SmartBot


class _BuryLoose(SmartBot):
    """Bury variant: points in the kitty are nearly free."""
    def _bury_points_mult(self, trump_count: int, has_big_joker: bool) -> float:
        return 1.0


class _BuryStrict(SmartBot):
    """Bury variant: never bury points."""
    def _bury_points_mult(self, trump_count: int, has_big_joker: bool) -> float:
        return 8.0


class _BuryNoVoid(SmartBot):
    """Bury variant: ignore void-creation, keep balanced suits."""
    BURY_VOID = False


class MCBot(SmartBot):
    N_DETERMINIZATIONS = 10
    MAX_CANDIDATES = 8
    SAMPLE_RETRIES = 15
    MARGIN = 5.0  # points/round a candidate must beat SmartBot's pick by;
    #               keeps the heuristic prior unless the search is confident.
    #               0 = pure argmax.
    LEVEL_OBJECTIVE = False  # score rollouts by level-change brackets (the
    #                          real payoff: 79 vs 80 points is a cliff), not
    #                          raw points. Scaled so MARGIN keeps meaning.
    MC_BURY = False          # search the banker's bury over sampled worlds
    N_BURY_WORLDS = 8

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.rollout_policy = HeuristicBot()

    # ------------------------------------------------------------------- play
    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        assert rnd.trick is not None and rnd.ordering is not None
        candidates = self._candidates(rnd, seat)
        if len(candidates) <= 1:
            return candidates[0]
        mem = Memory(rnd, seat)
        i_attack = rnd.is_attacker(seat)
        totals = [0.0] * len(candidates)
        n_worlds = 0
        for _ in range(self.N_DETERMINIZATIONS):
            sampled = self._sample_hands(rnd, seat, mem)
            if sampled is None:
                continue
            n_worlds += 1
            hands, buried = sampled
            for i, cand in enumerate(candidates):
                val = self._score(self._rollout(rnd, seat, hands, buried, cand))
                totals[i] += val if i_attack else -val
        if n_worlds == 0:
            return candidates[0]
        best = max(range(len(candidates)), key=lambda i: totals[i])
        # candidates[0] is SmartBot's own choice: prefer it unless the search
        # clears the confidence margin (rollouts are noisiest early on).
        if best != 0 and (totals[best] - totals[0]) / n_worlds < self.MARGIN:
            return candidates[0]
        return candidates[best]

    def _score(self, attacker_pts: float) -> float:
        """Rollout value from the attackers' perspective.

        With LEVEL_OBJECTIVE, points map to the scoring brackets that decide
        the round (0 / <40 / <80 / 80+ / 120+ / ...) plus a half-bracket for
        seizing or keeping the deal, scaled x40 so MARGIN stays comparable;
        a small points term breaks ties within a bracket."""
        p = attacker_pts
        if not self.LEVEL_OBJECTIVE:
            return float(p)
        if p >= 80:
            bracket, deal = min(3, int(p - 80) // 40), 0.5
        elif p == 0:
            bracket, deal = -3, -0.5
        else:
            bracket, deal = -(1 + int(79 - p) // 40), -0.5
        return 40.0 * (bracket + deal) + 0.2 * p

    # ------------------------------------------------------------------- bury
    def decide_bury(self, rnd: Round, seat: int) -> list[str]:
        base = super().decide_bury(rnd, seat)
        if not self.MC_BURY:
            return base
        cands: list[list[str]] = [base]
        for variant in (_BuryLoose(), _BuryStrict(), _BuryNoVoid()):
            c = variant.decide_bury(rnd, seat)
            if not any(sorted(c) == sorted(x) for x in cands):
                cands.append(c)
        if len(cands) == 1:
            return base
        mem = Memory(rnd, seat)
        totals = [0.0] * len(cands)
        n_worlds = 0
        for _ in range(self.N_BURY_WORLDS):
            sampled = self._sample_hands(rnd, seat, mem)
            if sampled is None:
                continue
            n_worlds += 1
            hands, _ = sampled
            for i, cand in enumerate(cands):
                # banker's perspective: minimize the attackers' value
                totals[i] -= self._score(
                    self._rollout_from_bury(rnd, seat, hands, cand))
        if n_worlds == 0:
            return base
        best = max(range(len(cands)), key=lambda i: totals[i])
        if best != 0 and (totals[best] - totals[0]) / n_worlds < self.MARGIN:
            return base
        return cands[best]

    def _rollout_from_bury(self, rnd: Round, seat: int,
                           sampled: dict[int, list[str]],
                           bury_cards: list[str]) -> float:
        clone: Round = copy.copy(rnd)
        clone.hands = [list(sampled.get(s, rnd.hands[s])) for s in range(4)]
        clone.hands[seat] = list(rnd.hands[seat])
        clone.buried = []
        clone.trick = None
        clone.last_trick = None
        clone.history = []
        clone.message = None
        clone.bury(seat, list(bury_cards))
        policy = self.rollout_policy
        while clone.phase == "play":
            s = clone.turn
            assert s is not None
            clone.play(s, policy.decide_play(clone, s))
        return float(clone.attacker_points)

    # ------------------------------------------------------------- candidates
    def _candidates(self, rnd: Round, seat: int) -> list[list[str]]:
        o = rnd.ordering
        assert o is not None and rnd.trick is not None
        hand = rnd.hands[seat]
        cands: list[list[str]] = []

        def add(play: list[str] | None) -> None:
            if not play:
                return
            key = tuple(sorted(play))
            if key in {tuple(sorted(c)) for c in cands}:
                return
            if rnd.trick.plays:
                try:
                    validate_follow(play, hand, rnd.trick.plays[0].cards, o)
                except IllegalPlay:
                    return
            cands.append(play)

        if not rnd.trick.plays:
            add(self._lead(rnd, seat))  # SmartBot's pick (throws included)
            for s in PLAIN_SUITS:
                cards = suit_cards(hand, s, o)
                if not cards:
                    continue
                comps = decompose(cards, o).components
                paired = [c for c in comps if c.pair_len]
                if paired:
                    add(max(paired, key=lambda c: (c.pair_len, c.top)).cards)
                # top single (the ace lead) must always be on the ballot
                add([max(cards, key=o.level)])
                add([self._lowest(cards, o, avoid_points=True)])
            trumps = suit_cards(hand, TRUMP, o)
            if trumps:
                add([self._lowest(trumps, o, avoid_points=True)])
        else:
            add(self._follow(rnd, seat))  # SmartBot's pick
            lead = rnd.trick.plays[0].cards
            add(self._forced_follow(hand, lead, o, prefer_points=False))
            add(self._forced_follow(hand, lead, o, prefer_points=True))
            win_seat, inc_suit, inc_top = self._current_winner(rnd)
            add(self._cheapest_winning(hand, lead, inc_suit, inc_top, o))
        return cands[:self.MAX_CANDIDATES]

    # ------------------------------------------------------------- sampling
    def _sample_hands(self, rnd: Round, seat: int, mem: Memory):
        """Deal unseen cards to the other three seats (+ hidden kitty when we
        aren't the banker), respecting hand sizes and observed voids.
        Returns (hands, buried) or None if sampling failed."""
        o = rnd.ordering
        assert o is not None
        pool = list(mem.unseen.elements())
        if seat == rnd.banker:
            burial = Counter(rnd.buried)
            pool = list((Counter(pool) - burial).elements())
            buried = list(rnd.buried)
            kitty_slots = 0
        else:
            buried = []
            kitty_slots = len(rnd.buried)

        others = [s for s in range(4) if s != seat]
        sizes = {s: len(rnd.hands[s]) for s in others}
        for attempt in range(self.SAMPLE_RETRIES):
            respect_voids = attempt < self.SAMPLE_RETRIES - 1
            self.rng.shuffle(pool)
            hands: dict[int, list[str]] = {s: [] for s in others}
            kitty: list[str] = []
            ok = True
            for c in pool:
                eff = o.eff_suit(c)
                slots = [s for s in others
                         if len(hands[s]) < sizes[s]
                         and not (respect_voids and eff in mem.voids[s])]
                if slots:
                    hands[self.rng.choice(slots)].append(c)
                elif len(kitty) < kitty_slots:
                    kitty.append(c)
                else:
                    ok = False
                    break
            if ok and all(len(hands[s]) == sizes[s] for s in others) \
                    and len(kitty) == kitty_slots:
                return hands, (buried or kitty)
        return None

    # -------------------------------------------------------------- rollout
    def _rollout(self, rnd: Round, seat: int, sampled: dict[int, list[str]],
                 buried: list[str], candidate: list[str]) -> float:
        clone: Round = copy.copy(rnd)
        clone.hands = [list(sampled.get(s, rnd.hands[s])) for s in range(4)]
        clone.hands[seat] = list(rnd.hands[seat])
        clone.buried = list(buried)
        assert rnd.trick is not None
        clone.trick = Trick(
            leader=rnd.trick.leader,
            plays=[TrickPlay(p.seat, list(p.cards)) for p in rnd.trick.plays])
        clone.history = list(rnd.history)
        clone.last_trick = rnd.last_trick
        clone.message = None
        clone.play(seat, list(candidate))
        policy = self.rollout_policy
        while clone.phase == "play":
            s = clone.turn
            assert s is not None
            clone.play(s, policy.decide_play(clone, s))
        return float(clone.attacker_points)


class MCSmartRoll(MCBot):
    """MCBot with SmartBot (memory-aware) rollouts — ~5x slower/decision."""

    def __init__(self, seed: int | None = None):
        super().__init__(seed)
        self.rollout_policy = SmartBot()
