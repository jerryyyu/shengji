"""Cheap S6-aware continuation policies for reusable-DEV exploration.

The root S6 treatment can afford a second report-LCB search before replacing
the live champion's lead.  Putting that search recursively inside every MC
rollout would multiply work and make the evaluator call itself.  The bury
exploration still needs to answer a narrower question: does a hand shape look
better when later leaders are at least capable of cashing the ``shuai pai`` it
preserved?

These deterministic rollout policies provide two sensitivity arms without
registering a bot or changing the production rollout:

``safe``
    Lead only an S6 boss-component bundle that public information proves is
    ruff-safe and whose every component is currently boss.

``boss_near``
    Also permit the source's bounded near-boss pair/tractor component.  This
    is deliberately the more aggressive exploratory arm; the real root S6
    policy uses search to decide whether to take that risk.

Both policies read only the acting hand, public trick history and (for the
banker) its own kitty through :class:`Memory`.  They never inspect a sampled
opponent hand to choose an action.  Results produced with either mode remain
reusable-DEV diagnostics, not strength or deployment evidence.
"""
from __future__ import annotations

from collections import Counter

from ..engine.cards import points
from ..engine.combos import decompose
from ..engine.round import Round
from .heuristic import HeuristicBot
from .memory import Memory
from .throw_sourcing import BOSS_NEAR_BUNDLE, structured_throw_ballot


S6_CONTINUATION_MODES = ("baseline", "safe", "boss_near")
S6_ROLLOUT_COUNTER_FIELDS = (
    "play_calls",
    "lead_calls",
    "sourced_leads",
    "source_candidates",
    "boss_near_candidates",
    "ruff_risk_declines",
    "safe_candidates",
    "near_candidates",
    "eligible_leads",
    "changes",
    "attacker_changes",
    "defender_changes",
    "early_changes",
    "mid_changes",
    "late_changes",
)


def _phase(rnd: Round) -> str:
    tricks = len(rnd.history)
    return "early" if tricks < 5 else "mid" if tricks < 12 else "late"


def _all_components_boss(cards, memory: Memory) -> bool:
    components = decompose(list(cards), memory.o).components
    if len(components) < 2:
        raise AssertionError("S6 rollout source emitted a non-throw")
    for component in components:
        top = max(component.cards, key=memory.o.level)
        boss = (memory.pair_is_boss(top) if component.pair_len
                else memory.is_boss(top))
        if not boss:
            return False
    return True


class S6ThrowRolloutPolicy(HeuristicBot):
    """Historical rollout plus one deterministic actor-visible lead seam."""

    def __init__(self, *, mode: str):
        if mode not in {"safe", "boss_near"}:
            raise ValueError("S6 rollout mode must be 'safe' or 'boss_near'")
        self.mode = mode
        self._s6_rollout_totals = Counter(
            {name: 0 for name in S6_ROLLOUT_COUNTER_FIELDS})

    def snapshot(self) -> dict[str, int]:
        return {
            name: int(self._s6_rollout_totals[name])
            for name in S6_ROLLOUT_COUNTER_FIELDS
        }

    def telemetry(self) -> dict[str, object]:
        counters = self.snapshot()
        self._validate(counters)
        return {
            "schema": "s6-throw-rollout-telemetry-v1",
            "mode": self.mode,
            "deterministic": True,
            "actor_visible": True,
            "recursive_mc": False,
            "exploration_only": True,
            **counters,
        }

    def delta(self, before: dict[str, int]) -> dict[str, object]:
        if set(before) != set(S6_ROLLOUT_COUNTER_FIELDS):
            raise AssertionError("S6 rollout snapshot field drift")
        after = self.snapshot()
        counters = {name: after[name] - int(before[name]) for name in after}
        self._validate(counters)
        return {
            "schema": "s6-throw-rollout-dose-v1",
            "mode": self.mode,
            "deterministic": True,
            "actor_visible": True,
            "recursive_mc": False,
            "exploration_only": True,
            "before": dict(before),
            "after": after,
            "delta": counters,
        }

    @staticmethod
    def _validate(counters: dict[str, int]) -> None:
        if set(counters) != set(S6_ROLLOUT_COUNTER_FIELDS):
            raise AssertionError("S6 rollout counter population drift")
        if any(isinstance(value, bool) or not isinstance(value, int)
               or value < 0 for value in counters.values()):
            raise AssertionError("S6 rollout counters must be nonnegative ints")
        if not (counters["changes"] <= counters["eligible_leads"]
                <= counters["sourced_leads"] <= counters["lead_calls"]
                <= counters["play_calls"]):
            raise AssertionError("S6 rollout lead paths do not reconcile")
        if counters["changes"] != (
                counters["attacker_changes"]
                + counters["defender_changes"]):
            raise AssertionError("S6 rollout role paths do not reconcile")
        if counters["changes"] != (
                counters["early_changes"] + counters["mid_changes"]
                + counters["late_changes"]):
            raise AssertionError("S6 rollout phase paths do not reconcile")
        if counters["safe_candidates"] + counters["near_candidates"] > \
                counters["boss_near_candidates"]:
            raise AssertionError("S6 rollout candidate classes do not reconcile")
        if counters["boss_near_candidates"] > counters["source_candidates"]:
            raise AssertionError("S6 rollout filtered more candidates than sourced")

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        self._s6_rollout_totals["play_calls"] += 1
        return super().decide_play(rnd, seat)

    def _lead(self, rnd: Round, seat: int) -> list[str]:
        baseline = super()._lead(rnd, seat)
        totals = self._s6_rollout_totals
        totals["lead_calls"] += 1
        ballot = structured_throw_ballot(rnd, seat, own_kitty=True)
        totals["source_candidates"] += len(ballot.candidates)
        if ballot.candidates:
            totals["sourced_leads"] += 1

        memory = Memory(rnd, seat, own_kitty=True)
        qualified = []
        for candidate in ballot.candidates:
            if BOSS_NEAR_BUNDLE not in candidate.sources:
                continue
            totals["boss_near_candidates"] += 1
            if candidate.ruff_risk:
                totals["ruff_risk_declines"] += 1
                continue
            all_boss = _all_components_boss(candidate.cards, memory)
            totals["safe_candidates" if all_boss
                   else "near_candidates"] += 1
            if self.mode == "safe" and not all_boss:
                continue
            # Prefer certainty, then shedding more cards/components.  The last
            # two fields make ties stable while exposing fewer own points when
            # a near component can still fail.
            qualified.append((
                0 if all_boss else 1,
                -len(candidate.cards),
                -candidate.component_count,
                sum(points(card) for card in candidate.cards),
                candidate.cards,
            ))
        if not qualified:
            return baseline

        totals["eligible_leads"] += 1
        selected = list(min(qualified)[-1])
        if sorted(selected) == sorted(baseline):
            return baseline
        totals["changes"] += 1
        totals["attacker_changes" if rnd.is_attacker(seat)
               else "defender_changes"] += 1
        totals[f"{_phase(rnd)}_changes"] += 1
        return selected


def make_s6_continuation_policy(mode: str, *, baseline: HeuristicBot):
    """Return the literal baseline or a bounded S6 sensitivity policy."""
    if mode not in S6_CONTINUATION_MODES:
        raise ValueError(
            f"continuation mode must be one of {S6_CONTINUATION_MODES}")
    if mode == "baseline":
        return baseline
    if type(baseline) is not HeuristicBot:
        raise ValueError("S6 continuation sensitivity requires HeuristicBot")
    return S6ThrowRolloutPolicy(mode=mode)
