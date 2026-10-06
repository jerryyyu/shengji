"""Matched play-only LLM comparisons, using the canonical engine round driver."""
from __future__ import annotations

import copy
from collections import Counter
from dataclasses import asdict
import time

from shengji.ai.env import play_prepared_round
from shengji.engine.cards import make_deck
from shengji.engine.legal import IllegalPlay
from .benchmark_policy import SeatPlannerPolicy
from .benchmark_failure_protocol import ToolBudgetExceeded
from .game import signed_level_utility


_CARD_CODES = frozenset(make_deck())


def _native_action_rejection(cards, hand, exc):
    """Recognize narrow native input errors after an actual engine rejection."""
    if (type(hand) not in (tuple, list) or not 1 <= len(hand) <= 25
            or any(type(c) is not str or c not in _CARD_CODES for c in hand)
            or any(n > 2 for n in Counter(hand).values())):
        return False
    if type(cards) is not list or any(type(c) is not str for c in cards):
        return False
    if type(exc) is KeyError:
        return (len(exc.args) == 1 and isinstance(exc.args[0], str)
                and exc.args[0] in cards and exc.args[0] not in _CARD_CODES)
    return (type(exc) is ValueError and exc.args == ("play too large",)
            and len(cards) > len(hand))


def play_mirror(prepared_game, *, flip, information, planner_factory,
                baseline_factory, seed, before_decision=lambda: None,
                invalid_action_feedback=False, classify_final_action_failures=False):
    """Compare one partnership to baseline, retaining a partial trace on failure.

    The caller prepares setup once and supplies the same root for every mirror
    and model. Factories make fresh seat-local instances; no model shares a
    partnership memory. before_decision enforces the caller's run budget.
    """
    if type(flip) is not int or flip not in (0, 1):
        raise ValueError("mirror must be 0 or 1")
    if type(invalid_action_feedback) is not bool:
        raise ValueError("invalid_action_feedback must be bool")
    if type(classify_final_action_failures) is not bool:
        raise ValueError("classify_final_action_failures must be bool")
    game = copy.deepcopy(prepared_game)
    events, planners, policies, planner_bots = [], [], [], []
    for seat in range(4):
        baseline = baseline_factory(seat, seed)
        if seat % 2 == flip:
            planner = planner_factory(seat)
            planners.append(planner)
            bot = SeatPlannerPolicy(seat=seat, information=information,
                                    planner=planner, setup_policy=baseline, seed=seed,
                                    invalid_action_feedback=invalid_action_feedback,
                                    classify_final_action_failures=classify_final_action_failures)
            planner_bots.append(bot)
        else:
            bot = baseline
        policies.append(_RecordedPolicy(bot, seat, before_decision, events))
    started = time.monotonic()
    record = {"flip": flip, "information": information, "seed": seed,
              "complete": False, "events": events,
              "invalid_action_feedback": invalid_action_feedback}
    if classify_final_action_failures:
        record["classify_final_action_failures"] = True

    def on_play_error(seat, attempted_cards, exc):
        if seat % 2 == flip and (isinstance(exc, IllegalPlay) or
                _native_action_rejection(attempted_cards, policies[seat].pre_play_hand, exc)):
            record["failure"] = {
                "schema": "benchmark-action-failure-v1",
                "category": "model_illegal_action", "stage": "engine_play",
                "seat": seat, "attempted_cards": list(attempted_cards),
                "event_index": len(events) - 1}
    try:
        log = play_prepared_round(game, policies, record=True,
                                  on_play_error=on_play_error if classify_final_action_failures else None)
        record.update(complete=True, result=asdict(log),
                      signed_levels=signed_level_utility(
                          log.attacker_points, banker_seat=log.banker,
                          perspective_seat=flip))
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        if (type(exc) is ToolBudgetExceeded and invalid_action_feedback
                and classify_final_action_failures):
            record['failure'] = dict(exc.failure, completed_play_events=len(events))
        for bot in planner_bots:
            if bot.rollout_diagnostic is not None:
                # Diagnostic only: deliberately NOT an accepted `failure`
                # disposition. Terminal validation still blocks this mirror.
                record["rollout_diagnostic"] = dict(bot.rollout_diagnostic,
                                                    completed_play_events=len(events))
                if bot.rollout_request_binding is not None:
                    record["rollout_request_binding"] = dict(
                        bot.rollout_request_binding, completed_play_events=len(events))
    record["wall_seconds"] = time.monotonic() - started
    record["calls"] = [call for planner in planners for call in getattr(planner, "calls", ())]
    record["rollout_usage"] = {
        key: sum(bot.rollout_usage[key] for bot in planner_bots)
        for key in ("requested_batches", "attempted_evaluations",
                    "completed_evaluations", "completed_world_rollouts")}
    if invalid_action_feedback:
        record["final_action_feedback"] = [
            dict(feedback)
            for bot in planner_bots
            for feedback in bot.final_action_feedback]
        counts = {
            key: sum(bot.final_action_feedback_counts[key] for bot in planner_bots)
            for key in ("decisions_with_rejections", "rejected_attempts",
                        "corrected_decisions", "exhausted_decisions")}
        # A provider/budget/internal fault after rejection is not successful
        # correction and is not exhaustion of the model's correction allowance.
        counts["interrupted_decisions"] = (counts["decisions_with_rejections"]
                                            - counts["corrected_decisions"]
                                            - counts["exhausted_decisions"])
        record["final_action_feedback_counts"] = counts
    return record


class _RecordedPolicy:
    def __init__(self, bot, seat, before_decision, events):
        self.bot, self.seat = bot, seat
        self.before_decision, self.events = before_decision, events
        self.pre_play_hand = None

    def decide_play(self, rnd, seat):
        self.before_decision()
        started = time.monotonic()
        cards = self.bot.decide_play(rnd, seat)
        self.pre_play_hand = tuple(rnd.hands[seat])
        self.events.append({"seat": seat, "attempted_cards": list(cards),
                            "wall_seconds": time.monotonic() - started})
        return cards
