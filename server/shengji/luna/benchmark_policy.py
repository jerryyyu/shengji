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
    def __init__(self, *, seat, information, planner, setup_policy, seed=0, worlds=8,
                 invalid_action_feedback=False, classify_final_action_failures=False):
        if type(invalid_action_feedback) is not bool:
            raise ValueError("invalid_action_feedback must be bool")
        self.invalid_action_feedback = invalid_action_feedback
        if type(classify_final_action_failures) is not bool:
            raise ValueError("classify_final_action_failures must be bool")
        self.classify_final_action_failures = classify_final_action_failures
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
        # Lifetime totals for this seat-policy instance, including partial failures.
        # World counts cover returned successful evaluations, not internal work
        # completed before an evaluator raises midway through its world loop.
        self.rollout_usage = {"requested_batches": 0, "attempted_evaluations": 0,
                              "completed_evaluations": 0, "completed_world_rollouts": 0}

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
        trick = visible["current_trick"]
        plays = trick["plays"] if trick else []
        # Redundant public guidance, outside the observation digest so the
        # existing shared-world sampling seeds do not change.
        lead = plays[0] if plays else None
        packet = {"observation": visible, "memory": self._memory,
                  "play_requirement": {
                      "is_leading": lead is None,
                      "lead_seat": None if lead is None else lead["seat"],
                      "lead_cards": [] if lead is None else list(lead["cards"]),
                      "required_card_count": None if lead is None else len(lead["cards"])},
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
            self.rollout_usage["requested_batches"] += 1
            if tool is None:
                # Seeds depend only on explicit experiment seed and visible state.
                tool = DecisionRollouts(
                    rnd, seat, information=self.information, worlds=self.worlds,
                    seed=self.seed + int(visible["observation_sha256"][:16], 16),
                    invalid_action_feedback=self.invalid_action_feedback)
            results = []
            for evaluation in reply["evaluations"]:
                if type(evaluation) is not dict or set(evaluation) != {"cards", "continuation"}:
                    raise ValueError("invalid planner rollout evaluation")
                self.rollout_usage["attempted_evaluations"] += 1
                result = tool.evaluate(**evaluation)
                if result.get("status") != "invalid":
                    self.rollout_usage["completed_evaluations"] += 1
                    self.rollout_usage["completed_world_rollouts"] += result["worlds"]
                results.append(result)
            packet["rollout_results"].extend(results)
            packet["memory"] = reply["memory"]
        if type(reply) is not dict or set(reply) != {"cards", "memory"}:
            raise ValueError("planner reply requires cards and memory")
        cards, memory = reply["cards"], reply["memory"]
        if (type(cards) is not list
                or any(type(card) is not str for card in cards)
                or type(memory) is not str):
            raise ValueError("invalid planner cards or memory")
        if not self.classify_final_action_failures and (
                not cards or Counter(cards) - Counter(rnd.hands[seat])):
            raise ValueError("invalid planner cards or memory")
        # The normal engine enforces follow rules and resolves throws. Never
        # replace a refused response with a stronger policy without recording it.
        self._memory = memory
        return list(cards)
