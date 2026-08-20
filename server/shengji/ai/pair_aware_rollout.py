"""Bounded public-information pair awareness for MC continuations.

The live MC root already uses :class:`SmartBot`, so its ballot can recognize
that a low pair has become unbeatable after higher pairs are exhausted.  Its
continuations still use :class:`HeuristicBot`, which forgets that public
history.  That mismatch can make search undervalue a setup play that draws the
remaining high pairs and leaves a low pair to cash on a later lead.

This experiment changes only rollout leads.  It never reads hidden hands: a
fresh :class:`Memory` is derived from the public trick history and the acting
rollout player's own hand.  Treatment and matched null perform identical
analysis.  On a narrow trigger, treatment leads the promoted pair and null
keeps the historical heuristic lead.
"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache

from ..engine.cards import points
from ..engine.legal import suit_cards
from ..engine.round import Round
from .heuristic import PLAIN_SUITS, HeuristicBot
from .memory import Memory


PAIR_AWARE_COUNTER_FIELDS = (
    "lead_calls",
    "single_baseline_leads",
    "pair_candidates_checked",
    "promoted_boss_pairs",
    "ruff_safe_promoted_pairs",
    "opportunities",
    "triggers",
    "changes",
    "matched_noops",
    "attacker_triggers",
    "defender_triggers",
    "point_pair_triggers",
)

PAIR_AWARE_POLICIES = {
    "base": "mc-s0-report-lcb",
    "treatment": "mc-s0-report-lcb-pair-aware-rollout",
    "matched_null": "mc-s0-report-lcb-pair-aware-rollout-null",
}


def empty_pair_aware_telemetry(mode: str = "off") -> dict[str, object]:
    return {
        "schema": "pair-aware-rollout-telemetry-v1",
        "mode": mode,
        "deterministic": True,
        "public_information_only": True,
        "exact_work_complete": True,
        **{name: 0 for name in PAIR_AWARE_COUNTER_FIELDS},
    }


class PairAwareRolloutPolicy(HeuristicBot):
    """Historical continuation plus one promoted-low-pair lead rule.

    A candidate must satisfy every condition below:

    * the historical continuation would lead a single, so tractors, throws,
      and its own pair choices are never displaced;
    * it is a plain-suit pair below that suit's natural top rank;
    * public card counting proves no higher pair remains outside this hand;
    * public void information does not expose it to a possible ruff.

    The last two conditions distinguish a *promoted* low pair from a generic
    pairs-first heuristic.  The rule can therefore recognize the payoff of an
    earlier bait/exhaustion sequence without using determinized hidden hands.
    """

    def __init__(self, *, apply_treatment: bool):
        self.apply_treatment = bool(apply_treatment)
        self._pair_aware_totals = Counter(
            {name: 0 for name in PAIR_AWARE_COUNTER_FIELDS})

    @property
    def mode(self) -> str:
        return "treatment" if self.apply_treatment else "matched_null"

    def pair_aware_snapshot(self) -> dict[str, int]:
        return {
            name: int(self._pair_aware_totals[name])
            for name in PAIR_AWARE_COUNTER_FIELDS
        }

    def pair_aware_telemetry(self) -> dict[str, object]:
        counters = self.pair_aware_snapshot()
        self._validate(counters)
        return {
            "schema": "pair-aware-rollout-telemetry-v1",
            "mode": self.mode,
            "deterministic": True,
            "public_information_only": True,
            "exact_work_complete": True,
            **counters,
        }

    def pair_aware_delta(self, before: dict[str, int]) -> dict[str, object]:
        if set(before) != set(PAIR_AWARE_COUNTER_FIELDS):
            raise AssertionError("pair-aware snapshot field population drift")
        after = self.pair_aware_snapshot()
        delta = {name: after[name] - int(before[name]) for name in after}
        self._validate(delta)
        return {
            "schema": "pair-aware-rollout-decision-v1",
            "mode": self.mode,
            "deterministic": True,
            "public_information_only": True,
            "exact_work_complete": True,
            "before": dict(before),
            "after": after,
            "delta": delta,
        }

    def _validate(self, counters: dict[str, int]) -> None:
        if set(counters) != set(PAIR_AWARE_COUNTER_FIELDS):
            raise AssertionError("pair-aware counter field population drift")
        if any(isinstance(value, bool) or not isinstance(value, int)
               or value < 0 for value in counters.values()):
            raise AssertionError("pair-aware counters must be non-negative ints")
        if counters["single_baseline_leads"] > counters["lead_calls"]:
            raise AssertionError("pair-aware single leads exceed all leads")
        if counters["promoted_boss_pairs"] > \
                counters["pair_candidates_checked"]:
            raise AssertionError("promoted pairs exceed checked pairs")
        if counters["ruff_safe_promoted_pairs"] > \
                counters["promoted_boss_pairs"]:
            raise AssertionError("ruff-safe pairs exceed promoted pairs")
        if counters["triggers"] != counters["opportunities"]:
            raise AssertionError("pair-aware opportunity paths do not reconcile")
        if counters["triggers"] != (
                counters["attacker_triggers"]
                + counters["defender_triggers"]):
            raise AssertionError("pair-aware role counters do not reconcile")
        if counters["point_pair_triggers"] > counters["triggers"]:
            raise AssertionError("point-pair triggers exceed all triggers")
        expected_changes = counters["triggers"] if self.apply_treatment else 0
        expected_noops = 0 if self.apply_treatment else counters["triggers"]
        if counters["changes"] != expected_changes:
            raise AssertionError("pair-aware treatment dose does not reconcile")
        if counters["matched_noops"] != expected_noops:
            raise AssertionError("pair-aware null dose does not reconcile")

    def _lead(self, rnd: Round, seat: int) -> list[str]:
        baseline = super()._lead(rnd, seat)
        totals = self._pair_aware_totals
        totals["lead_calls"] += 1
        if len(baseline) != 1:
            return baseline
        totals["single_baseline_leads"] += 1

        o = rnd.ordering
        assert o is not None
        mem = Memory(
            rnd, seat, own_kitty=getattr(self, "BANKER_KITTY", True))
        opponents = [other for other in range(4)
                     if other % 2 != seat % 2]
        hand_counts = Counter(rnd.hands[seat])
        candidates: list[str] = []
        for suit in PLAIN_SUITS:
            for code, copies in sorted(hand_counts.items()):
                if copies < 2 or o.eff_suit(code) != suit:
                    continue
                totals["pair_candidates_checked"] += 1
                # Natural top pairs were already strong before any baiting or
                # exhaustion.  The experiment is specifically about a lower
                # pair promoted by public card history.
                if o.level(code) >= len(o.plain_ranks) - 1:
                    continue
                if not mem.pair_is_boss(code):
                    continue
                totals["promoted_boss_pairs"] += 1
                if mem.ruff_risk(suit, opponents):
                    continue
                totals["ruff_safe_promoted_pairs"] += 1
                candidates.append(code)

        if not candidates:
            return baseline
        proposed = max(
            candidates,
            key=lambda code: (2 * points(code), o.level(code), code),
        )
        if sorted(baseline) == [proposed, proposed]:
            raise AssertionError("single baseline unexpectedly equals pair")

        totals["opportunities"] += 1
        totals["triggers"] += 1
        if points(proposed):
            totals["point_pair_triggers"] += 1
        role = "attacker_triggers" if rnd.is_attacker(seat) \
            else "defender_triggers"
        totals[role] += 1
        if self.apply_treatment:
            totals["changes"] += 1
            return [proposed, proposed]
        totals["matched_noops"] += 1
        return baseline


@lru_cache(maxsize=1)
def _experiment_bot_class(base_cls):
    class PairAwareExperimentBot(base_cls):
        def __init__(self, seed: int | None = None, *, apply_treatment: bool):
            base_cls.__init__(self, seed=seed)
            self.rollout_policy = PairAwareRolloutPolicy(
                apply_treatment=apply_treatment)

        def decide_play(self, rnd: Round, seat: int) -> list[str]:
            before = self.rollout_policy.pair_aware_snapshot()
            played = base_cls.decide_play(self, rnd, seat)
            record = self.last_decision_record
            if record is not None:
                record["pair_aware_rollout_telemetry"] = \
                    self.rollout_policy.pair_aware_delta(before)
            return played

        def pair_aware_telemetry(self) -> dict[str, object]:
            return self.rollout_policy.pair_aware_telemetry()

    PairAwareExperimentBot.__name__ = "PairAwareMCS0ReportLCB"
    PairAwareExperimentBot.__qualname__ = "PairAwareMCS0ReportLCB"
    return PairAwareExperimentBot


def make_pair_aware_bot(*, treatment: bool, seed: int | None = None):
    """Construct the exact champion with only this rollout seam changed."""
    from .registry import make_bot

    base_policy = PAIR_AWARE_POLICIES["base"]
    base = make_bot(base_policy, seed=seed)
    if type(base.rollout_policy) is not HeuristicBot:
        raise RuntimeError(
            f"pair-aware base {base_policy!r} has a non-heuristic rollout")
    if any(getattr(base, field, False) for field in
           ("MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME")):
        raise RuntimeError(
            f"pair-aware base {base_policy!r} enables another S3 feature")
    cls = _experiment_bot_class(type(base))
    bot = cls(seed=seed, apply_treatment=treatment)
    bot.policy_name = PAIR_AWARE_POLICIES[
        "treatment" if treatment else "matched_null"]
    bot.pair_aware_base_policy = base_policy
    return bot
