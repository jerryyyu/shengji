"""Matched play-only LLM comparisons, using the canonical engine round driver."""
from __future__ import annotations

import copy
from dataclasses import asdict
import time

from shengji.ai.env import play_prepared_round
from .benchmark_policy import SeatPlannerPolicy
from .game import signed_level_utility


def decision_telemetry(bot, attribute):
    """Copy operational metadata only; never expose private search state."""
    record = getattr(bot, attribute, None)
    if not isinstance(record, dict):
        return None
    return {key: copy.deepcopy(record[key]) for key in
            ("schema", "reason", "error_class", "work_complete", "budget_seconds")
            if key in record}


def fallback_summary(events):
    """Count attempted baseline decisions, including failed mirrors and missing records."""
    selected = [e for e in events if e.get("side") == "baseline"]
    missing, fallbacks, reasons = 0, 0, {}
    for event in selected:
        record = event.get("policy_record")
        if not isinstance(record, dict) or not record.get("schema"):
            missing += 1
        elif "fallback" in record["schema"]:
            fallbacks += 1
            reason = record.get("reason", "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1
    return {"attempted_decisions": len(selected), "fallbacks": fallbacks,
            "missing_records": missing, "reasons": reasons,
            "fallback_fraction": fallbacks / len(selected) if selected else None,
            "warning": bool(fallbacks or missing)}


class RecordedSetupPolicy:
    """Preserve the setup policy while recording every actual bury invocation."""
    def __init__(self, bot, events):
        self.bot, self.events = bot, events

    def __getattr__(self, name):
        return getattr(self.bot, name)

    def decide_bury(self, rnd, seat):
        before = getattr(self.bot, "last_bury_record", None)
        try:
            return self.bot.decide_bury(rnd, seat)
        finally:
            record = decision_telemetry(self.bot, "last_bury_record")
            if getattr(self.bot, "last_bury_record", None) is before:
                record = None  # do not count stale telemetry from an earlier call
            self.events.append({"seat": seat, "side": "baseline", "policy_record": record})


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
        policies.append(_RecordedPolicy(bot, seat, before_decision, events,
                                       side="planner" if seat % 2 == flip else "baseline"))
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
    record["baseline_play"] = fallback_summary(events)
    record["calls"] = [call for planner in planners for call in getattr(planner, "calls", ())]
    return record


class _RecordedPolicy:
    def __init__(self, bot, seat, before_decision, events, side="baseline"):
        self.bot, self.seat = bot, seat
        self.before_decision, self.events = before_decision, events
        self.side = side

    def decide_play(self, rnd, seat):
        self.before_decision()
        started = time.monotonic()
        before = getattr(self.bot, "last_decision_record", None)
        event = {"seat": seat, "side": self.side}
        try:
            cards = self.bot.decide_play(rnd, seat)
            event["attempted_cards"] = list(cards)
            return cards
        except Exception as exc:
            event["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            event["wall_seconds"] = time.monotonic() - started
            if self.side == "baseline":
                event["policy_record"] = decision_telemetry(self.bot, "last_decision_record")
                if getattr(self.bot, "last_decision_record", None) is before:
                    event["policy_record"] = None
            self.events.append(event)
