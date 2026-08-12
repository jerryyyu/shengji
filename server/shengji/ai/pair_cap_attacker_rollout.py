"""Attacker-only gate for the experimental opponent-pair-cap rollout.

The broad pair-cap extension produced two helpful changed roots and one
harmful reversion in its frozen high-N audit.  The harmful root was the only
one whose incremental continuation dose was exclusively on defender leads;
both helpful roots contained attacker-lead dose.  This module encodes that
small, falsifiable follow-up without changing either frozen parent policy.

The reviewed v1 pair-aware policy remains active in both roles.  Only the
strictly incremental opponent-pair-cap extension is declined for defenders.
"""
from __future__ import annotations

from .pair_aware_rollout import PairAwareRolloutPolicy, make_pair_aware_bot
from .pair_cap_rollout import OpponentPairCapRolloutPolicy


PAIR_CAP_ATTACKER_POLICIES = {
    "base": "mc-s0-report-lcb",
    "treatment": "mc-s0-report-lcb-pair-cap-attacker-rollout-v3",
    "matched_null": "mc-s0-report-lcb-pair-cap-attacker-rollout-v3-null",
}


class AttackerOnlyOpponentPairCapRolloutPolicy(
        OpponentPairCapRolloutPolicy):
    """Apply v1 everywhere and the incremental v2 rule only to attackers."""

    def _lead(self, rnd, seat: int) -> list[str]:
        if not rnd.is_attacker(seat):
            # Deliberately bypass OpponentPairCapRolloutPolicy._lead while
            # retaining the reviewed v1 public boss-pair rule and telemetry.
            return PairAwareRolloutPolicy._lead(self, rnd, seat)
        return super()._lead(rnd, seat)


def make_pair_cap_attacker_bot(*, treatment: bool,
                               seed: int | None = None):
    """Construct the champion with the attacker-only continuation gate."""
    bot = make_pair_aware_bot(treatment=treatment, seed=seed)
    bot.rollout_policy = AttackerOnlyOpponentPairCapRolloutPolicy(
        apply_treatment=treatment)
    bot.policy_name = PAIR_CAP_ATTACKER_POLICIES[
        "treatment" if treatment else "matched_null"]
    bot.pair_cap_attacker_base_policy = PAIR_CAP_ATTACKER_POLICIES["base"]
    return bot
