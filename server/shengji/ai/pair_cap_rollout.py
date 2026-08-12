"""Experimental team-aware extension to public pair-aware continuations.

The reviewed v1 rollout promotes a low pair only when public counting proves
that no higher pair remains anywhere outside the acting hand.  This extension
adds one strictly broader, still-public case: neither *opponent* can still form
a pair in the suit, even if higher cards may remain with the actor's partner.

It leaves v1 untouched and keeps the same ruff-risk decline.  Treatment plays
the promoted pair; matched null performs identical public analysis and keeps
the historical continuation.
"""
from __future__ import annotations

from collections import Counter

from ..engine.cards import points
from .heuristic import PLAIN_SUITS, HeuristicBot
from .memory import Memory
from .pair_aware_rollout import PairAwareRolloutPolicy, make_pair_aware_bot


PAIR_CAP_COUNTER_FIELDS = (
    "candidates_checked",
    "opponent_pair_cap_proofs",
    "ruff_safe_proofs",
    "opportunities",
    "triggers",
    "changes",
    "matched_noops",
    "attacker_triggers",
    "defender_triggers",
    "point_pair_triggers",
)

PAIR_CAP_POLICIES = {
    "base": "mc-s0-report-lcb",
    "treatment": "mc-s0-report-lcb-pair-cap-rollout-v2",
    "matched_null": "mc-s0-report-lcb-pair-cap-rollout-v2-null",
}


class OpponentPairCapRolloutPolicy(PairAwareRolloutPolicy):
    """v1 pair-aware rollout plus a public opponent-pair-cap proof."""

    def __init__(self, *, apply_treatment: bool):
        super().__init__(apply_treatment=apply_treatment)
        self._pair_cap_totals = Counter(
            {name: 0 for name in PAIR_CAP_COUNTER_FIELDS})

    def pair_cap_snapshot(self) -> dict[str, int]:
        return {name: int(self._pair_cap_totals[name])
                for name in PAIR_CAP_COUNTER_FIELDS}

    def pair_cap_telemetry(self) -> dict[str, object]:
        values = self.pair_cap_snapshot()
        if any(value < 0 for value in values.values()):
            raise AssertionError("pair-cap telemetry has a negative counter")
        if values["ruff_safe_proofs"] > values["opponent_pair_cap_proofs"] \
                or values["opponent_pair_cap_proofs"] > \
                values["candidates_checked"]:
            raise AssertionError("pair-cap proof accounting does not reconcile")
        if values["triggers"] != values["opportunities"]:
            raise AssertionError("pair-cap trigger accounting does not reconcile")
        if values["triggers"] != (
                values["attacker_triggers"] + values["defender_triggers"]):
            raise AssertionError("pair-cap role accounting does not reconcile")
        if values["point_pair_triggers"] > values["triggers"]:
            raise AssertionError("pair-cap point triggers exceed all triggers")
        expected_changes = values["triggers"] if self.apply_treatment else 0
        expected_noops = 0 if self.apply_treatment else values["triggers"]
        if values["changes"] != expected_changes \
                or values["matched_noops"] != expected_noops:
            raise AssertionError("pair-cap treatment/null dose does not reconcile")
        return {
            "schema": "opponent-pair-cap-rollout-telemetry-v1",
            "mode": self.mode,
            "deterministic": True,
            "public_information_only": True,
            "exact_work_complete": True,
            **values,
        }

    def _lead(self, rnd, seat: int) -> list[str]:
        # Preserve v1 exactly when its stricter global-boss proof fires.
        baseline = HeuristicBot._lead(self, rnd, seat)
        v1_before = self._pair_aware_totals["triggers"]
        v1_play = super()._lead(rnd, seat)
        if self._pair_aware_totals["triggers"] != v1_before:
            return v1_play
        if len(baseline) != 1:
            return v1_play

        ordering = rnd.ordering
        assert ordering is not None
        memory = Memory(
            rnd, seat, own_kitty=getattr(self, "BANKER_KITTY", True))
        opponents = [other for other in range(4)
                     if other % 2 != seat % 2]
        hand_counts = Counter(rnd.hands[seat])
        candidates = []
        extra = self._pair_cap_totals
        for suit in PLAIN_SUITS:
            for code, copies in sorted(hand_counts.items()):
                if copies < 2 or ordering.eff_suit(code) != suit:
                    continue
                if ordering.level(code) >= len(ordering.plain_ranks) - 1:
                    continue
                # v1 already handled globally boss pairs above.  This lane is
                # the strictly incremental partner-may-hold-the-threat case.
                if memory.pair_is_boss(code):
                    continue
                extra["candidates_checked"] += 1
                if not all(memory.max_pairs(other, suit) == 0
                           for other in opponents):
                    continue
                extra["opponent_pair_cap_proofs"] += 1
                if memory.ruff_risk(suit, opponents):
                    continue
                extra["ruff_safe_proofs"] += 1
                candidates.append(code)

        if not candidates:
            return v1_play
        proposed = max(
            candidates,
            key=lambda code: (2 * points(code), ordering.level(code), code),
        )
        if sorted(v1_play) == [proposed, proposed]:
            raise AssertionError("pair-cap extension did not add a new action")

        extra["opportunities"] += 1
        extra["triggers"] += 1
        role = "attacker_triggers" if rnd.is_attacker(seat) \
            else "defender_triggers"
        extra[role] += 1
        if points(proposed):
            extra["point_pair_triggers"] += 1

        # Fold the incremental trigger into v1's canonical aggregate telemetry
        # so whole-round accounting sees every changed continuation.  Extra
        # counters retain the mechanism attribution.
        base = self._pair_aware_totals
        base["opportunities"] += 1
        base["triggers"] += 1
        base[role] += 1
        if points(proposed):
            base["point_pair_triggers"] += 1
        if self.apply_treatment:
            extra["changes"] += 1
            base["changes"] += 1
            self._validate(base)
            self.pair_cap_telemetry()
            return [proposed, proposed]
        extra["matched_noops"] += 1
        base["matched_noops"] += 1
        self._validate(base)
        self.pair_cap_telemetry()
        return v1_play


def make_pair_cap_bot(*, treatment: bool, seed: int | None = None):
    """Construct the reviewed v1 root with only its rollout policy extended."""
    bot = make_pair_aware_bot(treatment=treatment, seed=seed)
    bot.rollout_policy = OpponentPairCapRolloutPolicy(
        apply_treatment=treatment)
    bot.policy_name = PAIR_CAP_POLICIES[
        "treatment" if treatment else "matched_null"]
    bot.pair_cap_rollout_base_policy = PAIR_CAP_POLICIES["base"]
    return bot
