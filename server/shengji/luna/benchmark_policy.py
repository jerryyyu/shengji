"""Seat-private planner adapter for the existing headless round runner.

The planner receives JSON data, not a Round or a bound engine method. Declare
and bury remain the explicitly supplied common setup policy. This is a play
comparison adapter, not a transport sandbox or a rollout-tool implementation.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json

from shengji.engine.legal import IllegalPlay, validate_follow, validate_lead
from .benchmark_observation import observation
from .canonical import canonical_json_bytes
from .benchmark_rollouts import DecisionRollouts
from .game import (MAX_ROLLOUT_CALLS_PER_DECISION, MAX_NEW_EVALUATIONS_PER_CALL,
                   WideHeuristicBallotBot)


MAX_FINAL_ACTION_CORRECTIONS = 2


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
        self.final_action_feedback = []
        # Lifetime totals for this seat-policy instance, including partial failures.
        # World counts cover returned successful evaluations, not internal work
        # completed before an evaluator raises midway through its world loop.
        self.rollout_diagnostic = None
        self.rollout_request_binding = None
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
        self.rollout_diagnostic = None
        self.rollout_request_binding = None
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
        if self.invalid_action_feedback:
            packet.update(final_action_corrections_remaining=MAX_FINAL_ACTION_CORRECTIONS,
                          final_action_errors=[])
        tool = None
        request_index = 0
        correction_index = 0
        while True:
            while True:
                packet["rollout_calls_remaining"] = (
                    MAX_ROLLOUT_CALLS_PER_DECISION - request_index)
                # Detach mutable values and exercise the actual JSON transport boundary.
                packet_bytes = canonical_json_bytes(packet)
                reply = self.planner(json.loads(packet_bytes))
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
                for evaluation_index, evaluation in enumerate(reply["evaluations"]):
                    if (type(evaluation) is not dict
                            or set(evaluation) != {"cards", "continuation"}):
                        raise ValueError("invalid planner rollout evaluation")
                    self.rollout_usage["attempted_evaluations"] += 1
                    try:
                        result = tool.evaluate(**evaluation)
                    except Exception:
                        if tool.last_failure is not None:
                            self.rollout_diagnostic = {
                                "schema": "benchmark-rollout-diagnostic-v1",
                                **tool.last_failure, "seat": seat,
                                "request_index": request_index,
                                "evaluation_index": evaluation_index,
                                "cards": list(evaluation["cards"]),
                                "continuation": evaluation["continuation"]}
                            # Diagnostic evidence only, not a failure disposition.
                            # These bind canonical structured JSON, NOT raw provider
                            # output or a prompt file. Preserve the evaluator error
                            # even if a synthetic planner returns non-JSON values.
                            try:
                                reply_bytes = canonical_json_bytes(reply)
                            except (TypeError, ValueError, RecursionError):
                                pass
                            else:
                                self.rollout_request_binding = {
                                    "schema": "benchmark-rollout-request-binding-v1",
                                    "seat": seat, "request_index": request_index,
                                    "evaluation_index": evaluation_index,
                                    "observation_sha256": visible["observation_sha256"],
                                    "packet_sha256": hashlib.sha256(packet_bytes).hexdigest(),
                                    "reply_sha256": hashlib.sha256(reply_bytes).hexdigest()}
                        raise
                    if result.get("status") != "invalid":
                        self.rollout_usage["completed_evaluations"] += 1
                        self.rollout_usage["completed_world_rollouts"] += result["worlds"]
                    results.append(result)
                packet["rollout_results"].extend(results)
                packet["memory"] = reply["memory"]
                request_index += 1

            if type(reply) is not dict or set(reply) != {"cards", "memory"}:
                raise ValueError("planner reply requires cards and memory")
            cards, memory = reply["cards"], reply["memory"]
            if (type(cards) is not list
                    or any(type(card) is not str for card in cards)
                    or type(memory) is not str):
                raise ValueError("invalid planner cards or memory")

            if not self.invalid_action_feedback:
                if not self.classify_final_action_failures and (
                        not cards or Counter(cards) - Counter(rnd.hands[seat])):
                    raise ValueError("invalid planner cards or memory")
                # The normal engine enforces follow rules and resolves throws. Never
                # replace a refused response with a stronger policy without recording it.
                self._memory = memory
                return list(cards)

            try:
                if plays:
                    validate_follow(cards, rnd.hands[seat], plays[0]["cards"],
                                    rnd.ordering)
                else:
                    validate_lead(cards, rnd.hands[seat], [], rnd.ordering)
            except IllegalPlay as exc:
                feedback = {"cards": list(cards), "error": "illegal_action",
                            "message": str(exc)}
                self.final_action_feedback.append({
                    "seat": seat,
                    "observation_sha256": visible["observation_sha256"],
                    "attempted_cards": list(cards),
                    "correction_index": correction_index,
                    "error": feedback["error"],
                    "message": feedback["message"],
                })
                if correction_index >= MAX_FINAL_ACTION_CORRECTIONS:
                    if self.classify_final_action_failures:
                        # Submit the actual exhausted attempt to the engine.
                        # Only its rejection may create an engine_play failure;
                        # correction attempts above were never played.
                        self._memory = memory
                        return list(cards)
                    raise
                packet["final_action_errors"].append(feedback)
                correction_index += 1
                packet["final_action_corrections_remaining"] = (
                    MAX_FINAL_ACTION_CORRECTIONS - correction_index)
                packet["memory"] = memory
                # The retry is another final-action response, but it shares the
                # same decision-local observation, rollout results and tool.
                continue

            self._memory = memory
            return list(cards)
