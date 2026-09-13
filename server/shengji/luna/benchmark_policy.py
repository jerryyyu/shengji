"""Seat-private planner adapter for the existing headless round runner.

The planner receives JSON data, not a Round or a bound engine method. Declare
and bury remain the explicitly supplied common setup policy. This is a play
comparison adapter, not a transport sandbox or a rollout-tool implementation.
"""
from __future__ import annotations

from collections import Counter
import json

from .benchmark_observation import observation
from .canonical import canonical_json_bytes
from .benchmark_rollouts import DecisionRollouts
from .game import (MAX_ROLLOUT_CALLS_PER_DECISION, MAX_NEW_EVALUATIONS_PER_CALL,
                   WideHeuristicBallotBot)


class SeatPlannerPolicy:
    def __init__(self, *, seat, information, planner, setup_policy, seed=0, worlds=8):
        if type(seat) is not int or seat not in range(4):
            raise ValueError("benchmark seat must be 0..3")
        if information not in ("actor-only", "perfect"):
            raise ValueError("unknown benchmark information mode")
        self.seat = seat
        self.information = information
        self.planner = planner
        self.setup_policy = setup_policy
        self.seed, self.worlds = seed, worlds
        self._round = None
        self._memory = ""

    def _check_seat(self, seat):
        if type(seat) is not int or seat != self.seat:
            raise ValueError("planner cannot serve a different seat")

    def decide_declare(self, rnd, seat, final=False):
        self._check_seat(seat)
        return self.setup_policy.decide_declare(rnd, seat, final=final)

    def decide_bury(self, rnd, seat):
        self._check_seat(seat)
        return self.setup_policy.decide_bury(rnd, seat)

    def decide_play(self, rnd, seat):
        self._check_seat(seat)
        visible = observation(rnd, seat, information=self.information)
        if rnd is not self._round:
            self._round, self._memory = rnd, ""
        # Reuse the existing teacher's bounded candidate generator as an aid.
        # Do not invoke its true-world decision/search path. Proposals outside
        # this ballot remain possible and are validated by the normal engine.
        candidates = WideHeuristicBallotBot(seed=self.seed)._candidates(rnd, seat)
        packet = {"observation": visible, "memory": self._memory,
                  "suggested_actions": [sorted(cards) for cards in candidates],
                  "rollout_results": []}
        tool = None
        for request_index in range(MAX_ROLLOUT_CALLS_PER_DECISION + 1):
            packet["rollout_calls_remaining"] = MAX_ROLLOUT_CALLS_PER_DECISION - request_index
            # Detach mutable values and exercise the actual JSON transport boundary.
            reply = self.planner(json.loads(canonical_json_bytes(packet)))
            if type(reply) is not dict or "evaluations" not in reply:
                break
            if (set(reply) != {"evaluations", "memory"}
                    or type(reply["memory"]) is not str
                    or type(reply["evaluations"]) is not list
                    or not 1 <= len(reply["evaluations"]) <= MAX_NEW_EVALUATIONS_PER_CALL):
                raise ValueError("invalid planner rollout request")
            if request_index == MAX_ROLLOUT_CALLS_PER_DECISION:
                raise ValueError("planner rollout call budget exhausted")
            if tool is None:
                # Seeds depend only on explicit experiment seed and visible state.
                tool = DecisionRollouts(
                    rnd, seat, information=self.information, worlds=self.worlds,
                    seed=self.seed + int(visible["observation_sha256"][:16], 16))
            results = []
            for evaluation in reply["evaluations"]:
                if type(evaluation) is not dict or set(evaluation) != {"cards", "continuation"}:
                    raise ValueError("invalid planner rollout evaluation")
                results.append(tool.evaluate(**evaluation))
            packet["rollout_results"].extend(results)
            packet["memory"] = reply["memory"]
        if type(reply) is not dict or set(reply) != {"cards", "memory"}:
            raise ValueError("planner reply requires cards and memory")
        cards, memory = reply["cards"], reply["memory"]
        if (type(cards) is not list or not cards
                or any(type(card) is not str for card in cards)
                or Counter(cards) - Counter(rnd.hands[seat])
                or type(memory) is not str):
            raise ValueError("invalid planner cards or memory")
        # The normal engine enforces follow rules and resolves throws. Never
        # replace a refused response with a stronger policy without recording it.
        self._memory = memory
        return list(cards)
