"""Experiment-only search-spend gate for the broad S6 throw source.

The underlying source remains unchanged and records every legal structured
early/mid/late proposal.  This wrapper narrows only the expensive second
report-LCB probe to genuinely new boss/near-boss component bundles.  Generic
whole-suit and whole-trump evacuations therefore remain visible in the source
ballot while costing no second search in this bounded experiment.
"""
from __future__ import annotations

from functools import lru_cache

from .throw_policy import S6_THROW_POLICIES, make_s6_throw_bot
from .throw_sourcing import BOSS_NEAR_BUNDLE


BOSS_NEAR_GATE = "boss_near_first"
S6_BOSS_NEAR_POLICIES = {
    "base": S6_THROW_POLICIES["base"],
    "treatment": "mc-s0-report-lcb-s6-boss-near-search",
    "matched_null": "mc-s0-report-lcb-s6-boss-near-search-null",
}


def _action_key(cards) -> tuple[str, ...]:
    return tuple(sorted(cards))


@lru_cache(maxsize=1)
def _gated_bot_class(broad_cls):
    class S6BossNearSearchBot(broad_cls):
        def _source_plan(self, rnd, seat):
            plan = broad_cls._source_plan(self, rnd, seat)
            base_count = int(plan["base_count"])
            broad_widened = tuple(plan["widened_candidates"])
            ballot = plan["ballot"]
            boss_keys = {
                candidate.cards for candidate in ballot.candidates
                if BOSS_NEAR_BUNDLE in candidate.sources
            }
            gated_additions = tuple(
                candidate for candidate in broad_widened[base_count:]
                if _action_key(candidate) in boss_keys
            )
            gated_widened = (
                tuple(broad_widened[:base_count]) + gated_additions)
            added_indices = tuple(range(base_count, len(gated_widened)))
            return {
                **plan,
                # Keep the complete source ballot in ``plan`` for coverage and
                # Xray-style inspection; narrow only the second-search suffix.
                "widened_candidates": gated_widened,
                "added_indices": added_indices,
                "added_keys": tuple(
                    _action_key(gated_widened[index])
                    for index in added_indices),
                "search_gate": BOSS_NEAR_GATE,
                "broad_added_count": len(broad_widened) - base_count,
                "gated_added_count": len(gated_additions),
            }

        def decide_play(self, rnd, seat):
            played = broad_cls.decide_play(self, rnd, seat)
            record = self.last_s6_throw_record
            if record is not None:
                ballot = record.get("ballot") or {"candidates": []}
                record["search_gate"] = BOSS_NEAR_GATE
                record["source_candidate_count"] = len(ballot["candidates"])
                record["searched_candidate_count"] = max(
                    0, int(record["secondary_candidate_count"]) - 1)
                if self.last_decision_record is not None:
                    self.last_decision_record["s6_throw_sourcing"] = record
            return played

    S6BossNearSearchBot.__name__ = "S6BossNearSearchMCS0ReportLCB"
    S6BossNearSearchBot.__qualname__ = "S6BossNearSearchMCS0ReportLCB"
    return S6BossNearSearchBot


def make_s6_boss_near_bot(*, treatment: bool, seed: int | None = None):
    """Construct the broad S6 arm with only its second-search suffix gated."""
    broad = make_s6_throw_bot(treatment=treatment, seed=seed)
    cls = _gated_bot_class(type(broad))
    bot = cls(seed=seed, apply_treatment=treatment)
    bot.policy_name = S6_BOSS_NEAR_POLICIES[
        "treatment" if treatment else "matched_null"]
    bot.s6_throw_base_policy = S6_BOSS_NEAR_POLICIES["base"]
    bot.s6_throw_search_gate = BOSS_NEAR_GATE
    return bot
