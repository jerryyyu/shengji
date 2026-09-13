"""Matched play-only LLM comparisons, using the canonical engine round driver."""
from __future__ import annotations

import copy
from dataclasses import asdict
import time

from shengji.ai.env import play_prepared_round
from .benchmark_policy import SeatPlannerPolicy
from .game import signed_level_utility


def play_mirror(prepared_game, *, flip, information, planner_factory,
                baseline_factory, seed, before_decision=lambda: None):
    """Compare one partnership to baseline, retaining a partial trace on failure.

    The caller prepares setup once and supplies the same root for every mirror
    and model. Factories make fresh seat-local instances; no model shares a
    partnership memory. before_decision enforces the caller's run budget.
    """
    if type(flip) is not int or flip not in (0, 1):
        raise ValueError("mirror must be 0 or 1")
    game = copy.deepcopy(prepared_game)
    events, planners, policies = [], [], []
    for seat in range(4):
        baseline = baseline_factory(seat, seed)
        if seat % 2 == flip:
            planner = planner_factory(seat)
            planners.append(planner)
            bot = SeatPlannerPolicy(seat=seat, information=information,
                                    planner=planner, setup_policy=baseline, seed=seed)
        else:
            bot = baseline
        policies.append(_RecordedPolicy(bot, seat, before_decision, events))
    started = time.monotonic()
    record = {"flip": flip, "information": information, "seed": seed,
              "complete": False, "events": events}
    try:
        log = play_prepared_round(game, policies, record=True)
        record.update(complete=True, result=asdict(log),
                      signed_levels=signed_level_utility(
                          log.attacker_points, banker_seat=log.banker,
                          perspective_seat=flip))
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["wall_seconds"] = time.monotonic() - started
    record["calls"] = [call for planner in planners for call in getattr(planner, "calls", ())]
    return record


class _RecordedPolicy:
    def __init__(self, bot, seat, before_decision, events):
        self.bot, self.seat = bot, seat
        self.before_decision, self.events = before_decision, events

    def decide_play(self, rnd, seat):
        self.before_decision()
        started = time.monotonic()
        cards = self.bot.decide_play(rnd, seat)
        self.events.append({"seat": seat, "attempted_cards": list(cards),
                            "wall_seconds": time.monotonic() - started})
        return cards
