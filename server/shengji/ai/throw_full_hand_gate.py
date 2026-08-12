"""Experiment-only S6 search gate for full-hand boss/near throws.

The complete structured source remains available for inspection, but the
expensive second report-LCB probe receives only a genuinely new boss/near
candidate that consumes every card remaining in the actor's hand.  This gate
is actor-visible and was frozen after a disjoint exact action-set replication;
it is not registered as a production policy.
"""
from __future__ import annotations

from functools import lru_cache

from .throw_policy import S6_THROW_POLICIES, make_s6_throw_bot
from .throw_sourcing import BOSS_NEAR_BUNDLE


FULL_HAND_BOSS_NEAR_GATE = "full_hand_boss_near"
S6_FULL_HAND_POLICIES = {
    "base": S6_THROW_POLICIES["base"],
    "treatment": "mc-s0-report-lcb-s6-full-hand-search",
    "matched_null": "mc-s0-report-lcb-s6-full-hand-search-null",
}


def _action_key(cards) -> tuple[str, ...]:
    return tuple(sorted(cards))


@lru_cache(maxsize=1)
def _gated_bot_class(broad_cls):
    class S6FullHandSearchBot(broad_cls):
        def _source_plan(self, rnd, seat):
            plan = broad_cls._source_plan(self, rnd, seat)
            base_count = int(plan["base_count"])
            broad_widened = tuple(plan["widened_candidates"])
            ballot = plan["ballot"]
            full_hand_keys = {
                candidate.cards for candidate in ballot.candidates
                if (BOSS_NEAR_BUNDLE in candidate.sources
                    and len(candidate.cards) == len(rnd.hands[seat]))
            }
            gated_additions = tuple(
                candidate for candidate in broad_widened[base_count:]
                if _action_key(candidate) in full_hand_keys
            )
            gated_widened = (
                tuple(broad_widened[:base_count]) + gated_additions)
            added_indices = tuple(range(base_count, len(gated_widened)))
            return {
                **plan,
                # Preserve the full structured ballot for Xray/coverage while
                # narrowing only the separately searched suffix.
                "widened_candidates": gated_widened,
                "added_indices": added_indices,
                "added_keys": tuple(
                    _action_key(gated_widened[index])
                    for index in added_indices),
                "search_gate": FULL_HAND_BOSS_NEAR_GATE,
                "broad_added_count": len(broad_widened) - base_count,
                "gated_added_count": len(gated_additions),
            }

        def decide_play(self, rnd, seat):
            played = broad_cls.decide_play(self, rnd, seat)
            record = self.last_s6_throw_record
            if record is not None:
                ballot = record.get("ballot") or {"candidates": []}
                decision = self.last_decision_record or {}
                probe_candidates = decision.get("candidates") or []
                if record.get("searched"):
                    if not probe_candidates:
                        raise AssertionError(
                            "searched S6 gate lost its incumbent candidate")
                    incumbent_played = list(probe_candidates[0])
                else:
                    incumbent_played = list(played)
                record["search_gate"] = FULL_HAND_BOSS_NEAR_GATE
                record["source_candidate_count"] = len(ballot["candidates"])
                record["searched_candidate_count"] = max(
                    0, int(record["secondary_candidate_count"]) - 1)
                record["incumbent_played"] = incumbent_played
                if self.last_decision_record is not None:
                    self.last_decision_record["s6_throw_sourcing"] = record
            return played

    S6FullHandSearchBot.__name__ = "S6FullHandSearchMCS0ReportLCB"
    S6FullHandSearchBot.__qualname__ = "S6FullHandSearchMCS0ReportLCB"
    return S6FullHandSearchBot


def make_s6_full_hand_bot(*, treatment: bool, seed: int | None = None):
    """Construct the champion-anchored full-hand treatment or matched null."""
    broad = make_s6_throw_bot(treatment=treatment, seed=seed)
    cls = _gated_bot_class(type(broad))
    bot = cls(seed=seed, apply_treatment=treatment)
    bot.policy_name = S6_FULL_HAND_POLICIES[
        "treatment" if treatment else "matched_null"]
    bot.s6_throw_base_policy = S6_FULL_HAND_POLICIES["base"]
    bot.s6_throw_search_gate = FULL_HAND_BOSS_NEAR_GATE
    return bot
