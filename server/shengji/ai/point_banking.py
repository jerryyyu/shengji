"""Bounded point-banking treatment for Monte Carlo rollout continuations.

This module deliberately does *not* change :class:`HeuristicBot` or the root
MC ballot.  It is an experiment-only continuation policy: the matched null
runs the same analysis and counters but returns the historical cheap winner,
while the treatment may bank a point card in one narrow, secure situation.

The sign is intentionally left to a strength screen.  Spending a point card
can sacrifice future control, so the rule requires a higher winning reserve
and declines every non-last-seat opportunity.
"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache

from ..engine.cards import points
from ..engine.legal import IllegalPlay, beats, validate_follow
from ..engine.round import Round
from .heuristic import HeuristicBot


POINT_BANKING_COUNTER_FIELDS = (
    "follow_calls",
    "single_follow_calls",
    "candidate_checks",
    "legal_winning_actions",
    "opportunities",
    "triggers",
    "changes",
    "matched_noops",
    "attacker_triggers",
    "defender_triggers",
    "point_gain",
    "decline_partner_winning",
    "decline_baseline_not_winning",
    "decline_not_last",
    "decline_no_higher_reserve",
)

POINT_BANKING_POLICIES = {
    "base": "mc-s0-report-lcb",
    "treatment": "mc-s0-report-lcb-point-banking",
    "matched_null": "mc-s0-report-lcb-point-banking-null",
}


def empty_point_banking_telemetry(mode: str = "off") -> dict[str, object]:
    """Return the canonical zero-dose record for feature-off policies."""
    return {
        "schema": "point-banking-rollout-telemetry-v1",
        "mode": mode,
        "deterministic": True,
        "exact_work_complete": True,
        **{name: 0 for name in POINT_BANKING_COUNTER_FIELDS},
    }


class PointBankingRolloutPolicy(HeuristicBot):
    """Historical rollout policy plus a narrowly gated point-card winner.

    The treatment and null share this exact class.  ``apply_treatment`` is the
    only difference: both enumerate and assess the same winning actions, while
    the null keeps ``HeuristicBot._follow``'s answer.  There is no RNG here;
    replay is fully determined by the root MC RNG state already logged.
    """

    def __init__(self, *, apply_treatment: bool):
        self.apply_treatment = bool(apply_treatment)
        self._point_banking_totals = Counter(
            {name: 0 for name in POINT_BANKING_COUNTER_FIELDS})

    @property
    def mode(self) -> str:
        return "treatment" if self.apply_treatment else "matched_null"

    def point_banking_snapshot(self) -> dict[str, int]:
        return {
            name: int(self._point_banking_totals[name])
            for name in POINT_BANKING_COUNTER_FIELDS
        }

    def point_banking_telemetry(self) -> dict[str, object]:
        counters = self.point_banking_snapshot()
        self._validate(counters)
        return {
            "schema": "point-banking-rollout-telemetry-v1",
            "mode": self.mode,
            "deterministic": True,
            "exact_work_complete": True,
            **counters,
        }

    def point_banking_delta(self, before: dict[str, int]) -> dict[str, object]:
        if set(before) != set(POINT_BANKING_COUNTER_FIELDS):
            raise AssertionError("point-banking snapshot field population drift")
        after = self.point_banking_snapshot()
        delta = {name: after[name] - int(before[name]) for name in after}
        self._validate(delta)
        return {
            "schema": "point-banking-rollout-decision-v1",
            "mode": self.mode,
            "deterministic": True,
            "exact_work_complete": True,
            "before": dict(before),
            "after": after,
            "delta": delta,
        }

    def _validate(self, counters: dict[str, int]) -> None:
        if set(counters) != set(POINT_BANKING_COUNTER_FIELDS):
            raise AssertionError("point-banking counter field population drift")
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0
               for v in counters.values()):
            raise AssertionError("point-banking counters must be non-negative ints")
        if counters["triggers"] != (
                counters["attacker_triggers"] + counters["defender_triggers"]):
            raise AssertionError("point-banking role counters do not reconcile")
        expected_changes = counters["triggers"] if self.apply_treatment else 0
        expected_noops = 0 if self.apply_treatment else counters["triggers"]
        if counters["changes"] != expected_changes:
            raise AssertionError("point-banking treatment dose does not reconcile")
        if counters["matched_noops"] != expected_noops:
            raise AssertionError("point-banking null dose does not reconcile")
        if counters["triggers"] > counters["opportunities"]:
            raise AssertionError("point-banking triggers exceed opportunities")
        if counters["single_follow_calls"] > counters["follow_calls"]:
            raise AssertionError("point-banking single calls exceed follows")
        if counters["legal_winning_actions"] > counters["candidate_checks"]:
            raise AssertionError("point-banking winners exceed checked actions")
        if counters["opportunities"] != (
                counters["triggers"] + counters["decline_not_last"]
                + counters["decline_no_higher_reserve"]):
            raise AssertionError("point-banking opportunity paths do not reconcile")
        if counters["point_gain"] < 5 * counters["triggers"]:
            raise AssertionError("point-banking trigger has impossible point gain")

    def _follow(self, rnd: Round, seat: int) -> list[str]:
        baseline = super()._follow(rnd, seat)
        totals = self._point_banking_totals
        totals["follow_calls"] += 1

        o = rnd.ordering
        trick = rnd.trick
        assert o is not None and trick is not None and trick.plays
        lead = trick.plays[0].cards
        if len(lead) != 1:
            return baseline
        totals["single_follow_calls"] += 1

        winner, inc_suit, inc_top = self._current_winner(rnd)
        if winner % 2 == seat % 2:
            totals["decline_partner_winning"] += 1
            return baseline

        # Preserve the historical contest/no-contest decision.  The S4
        # question is which winner to use *after* the baseline has elected to
        # win, not whether a rollout player should spend trump on the trick.
        baseline_won, _ = beats(baseline, lead, inc_suit, inc_top, o)
        if not baseline_won:
            totals["decline_baseline_not_winning"] += 1
            return baseline

        # Enumerate distinct legal single-card winners.  This is the matched
        # work unit: treatment and null execute the same validation and beats
        # calls, including on states where the gate declines.
        winners: list[str] = []
        for card in sorted(set(rnd.hands[seat])):
            totals["candidate_checks"] += 1
            try:
                validate_follow([card], rnd.hands[seat], lead, o)
            except IllegalPlay:
                continue
            won, _ = beats([card], lead, inc_suit, inc_top, o)
            if won:
                winners.append(card)
        totals["legal_winning_actions"] += len(winners)
        if len(winners) < 2:
            return baseline

        baseline_points = sum(points(card) for card in baseline)
        point_winners = [card for card in winners
                         if points(card) > baseline_points]
        if not point_winners:
            return baseline
        totals["opportunities"] += 1

        # A non-last mover has not actually secured the points; a later player
        # may overtake.  Refuse rather than letting the treatment smuggle an
        # unmodelled risk assumption into every rollout.
        if len(trick.plays) != 3:
            totals["decline_not_last"] += 1
            return baseline

        # Maximise secured points, then spend the cheapest such card.  Require
        # a still-higher winning card in reserve: this is the bounded strategic
        # cost that distinguishes the treatment from "play K whenever seen".
        proposed = min(point_winners,
                       key=lambda card: (-points(card), o.level(card), card))
        has_higher_reserve = any(
            card != proposed and o.eff_suit(card) == o.eff_suit(proposed)
            and o.level(card) > o.level(proposed)
            for card in winners
        )
        if not has_higher_reserve:
            totals["decline_no_higher_reserve"] += 1
            return baseline

        if sorted([proposed]) == sorted(baseline):
            # Defensive: point_winners is strictly above baseline_points, so a
            # matching action means the baseline stopped being a single-card
            # winner and this experimental rule's assumptions drifted.
            raise AssertionError("point-banking trigger did not change action")

        gain = points(proposed) - baseline_points
        if gain <= 0:
            raise AssertionError("point-banking trigger has no positive point gain")
        totals["triggers"] += 1
        totals["point_gain"] += gain
        role = "attacker_triggers" if rnd.is_attacker(seat) \
            else "defender_triggers"
        totals[role] += 1
        if self.apply_treatment:
            totals["changes"] += 1
            return [proposed]
        totals["matched_noops"] += 1
        return baseline


@lru_cache(maxsize=1)
def _experiment_bot_class(base_cls):
    """Build one wrapper without editing sealed MCBot/registry source bytes.

    Several terminal evidence receipts intentionally hash those shared files.
    An experiment added directly to either module would invalidate historical
    replay even while production behavior stayed off.  The wrapper inherits
    the exact named base and adds telemetry only to its own decision records.
    """
    class PointBankingExperimentBot(base_cls):
        def __init__(self, seed: int | None = None, *, apply_treatment: bool):
            base_cls.__init__(self, seed=seed)
            self.rollout_policy = PointBankingRolloutPolicy(
                apply_treatment=apply_treatment)

        def decide_play(self, rnd: Round, seat: int) -> list[str]:
            before = self.rollout_policy.point_banking_snapshot()
            played = base_cls.decide_play(self, rnd, seat)
            record = self.last_decision_record
            if record is not None:
                record["rollout_policy_telemetry"] = \
                    self.rollout_policy.point_banking_delta(before)
            return played

        def point_banking_telemetry(self) -> dict[str, object]:
            return self.rollout_policy.point_banking_telemetry()

    PointBankingExperimentBot.__name__ = "S4PointBankingMCS0ReportLCB"
    PointBankingExperimentBot.__qualname__ = \
        "S4PointBankingMCS0ReportLCB"
    return PointBankingExperimentBot


def make_point_banking_bot(*, treatment: bool,
                           seed: int | None = None):
    """Construct the exact champion with only the S4 rollout seam changed."""
    from .registry import make_bot

    base_policy = POINT_BANKING_POLICIES["base"]
    base = make_bot(base_policy, seed=seed)
    if type(base.rollout_policy) is not HeuristicBot:
        raise RuntimeError(
            f"S4 base policy {base_policy!r} has a non-heuristic rollout")
    if any(getattr(base, field, False) for field in
           ("MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME")):
        raise RuntimeError(
            f"S4 base policy {base_policy!r} enables another S3 feature")
    cls = _experiment_bot_class(type(base))
    bot = cls(seed=seed, apply_treatment=treatment)
    bot.policy_name = POINT_BANKING_POLICIES[
        "treatment" if treatment else "matched_null"]
    bot.point_banking_base_policy = base_policy
    return bot
