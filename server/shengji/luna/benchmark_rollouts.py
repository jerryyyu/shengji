"""Trusted decision-local rollout tool; reuses the existing Luna continuations.

Only aggregate results may cross the planner boundary. Actor-only worlds are
drawn once from public constraints and reused across action comparisons; no
conditioning on the real opponents' cards or real non-banker burial is allowed.
"""
from __future__ import annotations

import copy

from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.engine.legal import validate_follow, validate_lead

from .benchmark_observation import observation
from .game import _continuation, signed_level_utility


class DecisionRollouts:
    def __init__(self, rnd, seat, *, information, seed, worlds=8, max_evaluations=32):
        observation(rnd, seat, information=information)  # enforce acting seat/mode
        if type(worlds) is not int or not 1 <= worlds <= 32:
            raise ValueError("rollout worlds must be 1..32")
        if type(max_evaluations) is not int or not 1 <= max_evaluations <= 32:
            raise ValueError("rollout evaluations must be 1..32")
        self._rnd = copy.deepcopy(rnd)
        self._seat = seat
        self._remaining = max_evaluations
        self._worlds = []
        if information == "perfect":
            self._worlds.append(({s: list(rnd.hands[s]) for s in range(4) if s != seat},
                                 list(rnd.buried)))
        else:
            sampler = MCBot(seed=seed)
            mem = Memory(rnd, seat)
            for _ in range(worlds * 8):
                sampled = sampler._sample_hands(rnd, seat, mem)
                if sampled is None:
                    continue
                hands, buried = sampled
                # Legacy sampler can relax voids on its final retry. Never
                # admit those worlds into this public-information tool.
                if any(rnd.ordering.eff_suit(card) in mem.voids[s]
                       for s, hand in hands.items() for card in hand):
                    continue
                self._worlds.append((hands, buried))
                if len(self._worlds) == worlds:
                    break
            if len(self._worlds) != worlds:
                raise ValueError("public rollout world population underfilled")

    def evaluate(self, cards, *, continuation="heuristic-all"):
        rnd, seat = self._rnd, self._seat
        if self._remaining <= 0:
            raise ValueError("decision rollout budget exhausted")
        if type(cards) is not list or any(type(c) is not str for c in cards):
            raise ValueError("rollout cards must be a list of card codes")
        # Validate follows before entering MCBot's trusted rollout fast path.
        # Lead structure is checked without consulting the real hidden hands;
        # throw reduction occurs independently inside each sampled world.
        if rnd.trick.plays:
            validate_follow(cards, rnd.hands[seat], rnd.trick.plays[0].cards, rnd.ordering)
        else:
            validate_lead(cards, rnd.hands[seat], [], rnd.ordering)
        policy, exact = _continuation(continuation, seat % 2)
        self._remaining -= 1
        evaluator = MCBot(seed=0)
        evaluator.rollout_policy, evaluator.EXACT_ENDGAME = policy, exact
        points = []
        for hands, buried in self._worlds:
            world = copy.copy(rnd)
            world.hands = evaluator._complete_determinized_hands(rnd, seat, hands, buried=buried)
            world.buried = list(buried)
            points.append(evaluator._rollout(
                world, seat, hands, buried, cards,
                exact_session=evaluator._new_exact_world_session(world, buried)))
        utilities = [signed_level_utility(int(p), banker_seat=rnd.banker,
                                          perspective_seat=seat) for p in points]
        return {"cards": list(cards), "continuation": continuation,
                "worlds": len(points), "mean_attacker_points": sum(points) / len(points),
                "mean_signed_levels": sum(utilities) / len(utilities)}
