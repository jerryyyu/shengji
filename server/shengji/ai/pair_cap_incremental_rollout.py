"""Incremental attacker-gated pair-cap continuation experiment.

The reviewed attacker gate answers a useful action-semantics question, but its
original ``treatment=False`` arm disables both the reviewed v1 pair-aware rule
and the incremental attacker-only extension.  That is a champion-matched null,
not a parent-matched control, so it cannot say whether the extension improves
on v1.

This module makes that estimand explicit without editing either frozen parent:
both arms execute a v1 treatment policy and an attacker-gated v3 treatment
policy on every rollout lead.  The treatment returns v3's action; the matched
parent returns v1's action.  Component work and public-information analysis are
therefore identical.  A future whole-game controller must still run the literal
live champion as a separate absolute-strength arm.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache

from ..engine.cards import points
from ..engine.round import Round
from .heuristic import HeuristicBot
from .pair_aware_rollout import PairAwareRolloutPolicy
from .pair_cap_attacker_rollout import (
    AttackerOnlyOpponentPairCapRolloutPolicy,
)


PAIR_CAP_INCREMENTAL_COUNTER_FIELDS = (
    "lead_calls",
    "v1_v3_action_differences",
    "opportunities",
    "triggers",
    "changes",
    "matched_parent_noops",
    "attacker_triggers",
    "defender_triggers",
    "point_pair_triggers",
)

PAIR_CAP_INCREMENTAL_POLICIES = {
    "base": "mc-s0-report-lcb",
    "treatment": "mc-s0-report-lcb-pair-cap-attacker-incremental",
    "matched_parent": "mc-s0-report-lcb-pair-aware-parent-null",
    "literal_champion": "mc-s0-report-lcb",
}


def _subtract(after: dict[str, int], before: dict[str, int]) -> dict[str, int]:
    if set(after) != set(before):
        raise AssertionError("pair-cap incremental snapshot fields drifted")
    return {name: int(after[name]) - int(before[name]) for name in after}


class PairCapAttackerIncrementalRolloutPolicy(HeuristicBot):
    """Compare attacker-gated v3 directly with reviewed pair-aware v1.

    The nested policies always run in treatment mode so the two counterfactual
    actions are materialized under exactly the same public state.  Only this
    outer policy's ``apply_incremental`` flag controls the action returned to
    the rollout.
    """

    def __init__(self, *, apply_incremental: bool):
        self.apply_incremental = bool(apply_incremental)
        self._v1 = PairAwareRolloutPolicy(apply_treatment=True)
        self._v3 = AttackerOnlyOpponentPairCapRolloutPolicy(
            apply_treatment=True)
        self._incremental_totals = Counter({
            name: 0 for name in PAIR_CAP_INCREMENTAL_COUNTER_FIELDS
        })

    @property
    def mode(self) -> str:
        return "treatment" if self.apply_incremental else "matched_parent"

    def pair_cap_incremental_snapshot(self) -> dict[str, dict[str, int]]:
        return {
            "outer": {
                name: int(self._incremental_totals[name])
                for name in PAIR_CAP_INCREMENTAL_COUNTER_FIELDS
            },
            "v1_pair_aware": self._v1.pair_aware_snapshot(),
            "v3_pair_aware": self._v3.pair_aware_snapshot(),
            "v3_pair_cap": self._v3.pair_cap_snapshot(),
        }

    def _validate(self, snapshot: dict[str, dict[str, int]]) -> None:
        if set(snapshot) != {
                "outer", "v1_pair_aware", "v3_pair_aware", "v3_pair_cap"}:
            raise AssertionError("pair-cap incremental component population drift")
        outer = snapshot["outer"]
        v1 = snapshot["v1_pair_aware"]
        v3 = snapshot["v3_pair_aware"]
        cap = snapshot["v3_pair_cap"]
        if set(outer) != set(PAIR_CAP_INCREMENTAL_COUNTER_FIELDS):
            raise AssertionError("pair-cap incremental outer fields drifted")
        for section in snapshot.values():
            if any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in section.values()):
                raise AssertionError(
                    "pair-cap incremental counters must be non-negative ints")
        if outer["lead_calls"] != v1["lead_calls"] \
                or outer["lead_calls"] != v3["lead_calls"]:
            raise AssertionError("pair-cap incremental lead work diverged")
        if outer["triggers"] != outer["opportunities"] \
                or outer["triggers"] != outer["v1_v3_action_differences"]:
            raise AssertionError("pair-cap incremental trigger paths diverged")
        if outer["triggers"] != cap["triggers"]:
            raise AssertionError("pair-cap incremental component dose diverged")
        if outer["triggers"] != (
                outer["attacker_triggers"] + outer["defender_triggers"]):
            raise AssertionError("pair-cap incremental roles do not reconcile")
        if outer["defender_triggers"] != 0 \
                or cap["defender_triggers"] != 0:
            raise AssertionError("attacker-gated pair-cap fired for a defender")
        if outer["attacker_triggers"] != cap["attacker_triggers"] \
                or outer["point_pair_triggers"] != cap["point_pair_triggers"]:
            raise AssertionError("pair-cap incremental attribution diverged")
        if v3["triggers"] != v1["triggers"] + cap["triggers"]:
            raise AssertionError("v3 dose is not v1 plus incremental pair-cap")
        expected_changes = outer["triggers"] \
            if self.apply_incremental else 0
        expected_noops = 0 if self.apply_incremental else outer["triggers"]
        if outer["changes"] != expected_changes \
                or outer["matched_parent_noops"] != expected_noops:
            raise AssertionError("pair-cap incremental treatment dose diverged")

    def pair_cap_incremental_telemetry(self) -> dict[str, object]:
        snapshot = self.pair_cap_incremental_snapshot()
        self._validate(snapshot)
        return {
            "schema": "pair-cap-attacker-incremental-telemetry-v1",
            "mode": self.mode,
            "deterministic": True,
            "public_information_only": True,
            "exact_component_work": True,
            "components_are_counterfactual_analyses": True,
            "counters": snapshot,
        }

    def pair_cap_incremental_delta(
            self, before: dict[str, dict[str, int]]) -> dict[str, object]:
        after = self.pair_cap_incremental_snapshot()
        if set(before) != set(after):
            raise AssertionError("pair-cap incremental snapshot sections drifted")
        delta = {
            section: _subtract(after[section], before[section])
            for section in after
        }
        self._validate(delta)
        return {
            "schema": "pair-cap-attacker-incremental-decision-v1",
            "mode": self.mode,
            "deterministic": True,
            "public_information_only": True,
            "exact_component_work": True,
            "components_are_counterfactual_analyses": True,
            "before": before,
            "after": after,
            "delta": delta,
        }

    def _lead(self, rnd: Round, seat: int) -> list[str]:
        totals = self._incremental_totals
        totals["lead_calls"] += 1
        cap_before = self._v3.pair_cap_snapshot()
        v1_play = self._v1.decide_play(rnd, seat)
        v3_play = self._v3.decide_play(rnd, seat)
        cap_after = self._v3.pair_cap_snapshot()
        cap_delta = _subtract(cap_after, cap_before)

        differs = sorted(v1_play) != sorted(v3_play)
        if differs != (cap_delta["triggers"] == 1):
            raise AssertionError(
                "attacker pair-cap action change does not match component dose")
        if cap_delta["triggers"] not in (0, 1):
            raise AssertionError("one rollout lead produced multiple cap triggers")
        if not differs:
            self._validate(self.pair_cap_incremental_snapshot())
            return v1_play

        if not rnd.is_attacker(seat) or cap_delta["defender_triggers"]:
            raise AssertionError("attacker pair-cap changed a defender lead")
        totals["v1_v3_action_differences"] += 1
        totals["opportunities"] += 1
        totals["triggers"] += 1
        totals["attacker_triggers"] += 1
        if sum(points(card) for card in v3_play):
            totals["point_pair_triggers"] += 1
        if self.apply_incremental:
            totals["changes"] += 1
            result = v3_play
        else:
            totals["matched_parent_noops"] += 1
            result = v1_play
        self._validate(self.pair_cap_incremental_snapshot())
        return result


@lru_cache(maxsize=1)
def _experiment_bot_class(base_cls):
    class PairCapIncrementalExperimentBot(base_cls):
        def __init__(self, seed: int | None = None, *,
                     apply_incremental: bool):
            base_cls.__init__(self, seed=seed)
            self.rollout_policy = PairCapAttackerIncrementalRolloutPolicy(
                apply_incremental=apply_incremental)

        def decide_play(self, rnd: Round, seat: int) -> list[str]:
            before = self.rollout_policy.pair_cap_incremental_snapshot()
            played = base_cls.decide_play(self, rnd, seat)
            record = self.last_decision_record
            if record is not None:
                record["pair_cap_incremental_rollout_telemetry"] = \
                    self.rollout_policy.pair_cap_incremental_delta(before)
            return played

        def pair_cap_incremental_telemetry(self) -> dict[str, object]:
            return self.rollout_policy.pair_cap_incremental_telemetry()

    PairCapIncrementalExperimentBot.__name__ = \
        "PairCapAttackerIncrementalMCS0ReportLCB"
    PairCapIncrementalExperimentBot.__qualname__ = \
        "PairCapAttackerIncrementalMCS0ReportLCB"
    return PairCapIncrementalExperimentBot


def make_pair_cap_incremental_bot(*, treatment: bool,
                                  seed: int | None = None):
    """Construct the champion with an incremental v3-versus-v1 rollout arm."""
    from .registry import make_bot

    base_policy = PAIR_CAP_INCREMENTAL_POLICIES["base"]
    base = make_bot(base_policy, seed=seed)
    if type(base.rollout_policy) is not HeuristicBot:
        raise RuntimeError(
            f"pair-cap incremental base {base_policy!r} is not heuristic")
    if any(getattr(base, field, False) for field in
           ("MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME")):
        raise RuntimeError("pair-cap incremental base enables an S3 feature")
    cls = _experiment_bot_class(type(base))
    bot = cls(seed=seed, apply_incremental=treatment)
    bot.policy_name = PAIR_CAP_INCREMENTAL_POLICIES[
        "treatment" if treatment else "matched_parent"]
    bot.pair_cap_incremental_base_policy = base_policy
    return bot
