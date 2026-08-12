#!/usr/bin/env python3
"""Reusable-DEV scorer for joint bury and first-lead candidates.

This module deliberately has no launch CLI and no strength authority.  It is
the cheap exploration tier for the hand-shape hypothesis: build the bounded
actor-visible ballot in :mod:`shengji.ai.bury_lead_combo`, evaluate every combo
on identical sampled worlds, and retain partial diagnostic work when sampling
cannot fill the requested count.  Any later whole-game claim needs a separate
reviewed controller, population, matched null, and multiplicity-safe rule.
"""
from __future__ import annotations

import copy
import math
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SERVER))

from shengji.ai.bury_lead_combo import (  # noqa: E402
    BuryLeadComboBallot,
    build_bury_lead_combo_ballot,
)
from shengji.ai.memory import Memory  # noqa: E402
from shengji.engine.round import Round, actual_play_after  # noqa: E402


SCHEMA = "bury-first-lead-combo-state-exploration-v1"
DEFAULT_WORLDS = 30
DEFAULT_ATTEMPT_FACTOR = 40
DEFAULT_MAX_CANDIDATE_ROLLOUTS = 200_000


class ComboExplorationRefused(RuntimeError):
    """The requested diagnostic cannot honor its declared work contract."""


def _flatten(ballot: BuryLeadComboBallot):
    return [
        (group_index, lead_index, group, lead)
        for group_index, group in enumerate(ballot.groups)
        for lead_index, lead in enumerate(group.leads)
    ]


def _rollout_bury_lead(bot, rnd: Round, seat: int,
                       sampled: dict[int, list[str]], bury_cards,
                       lead_cards) -> tuple[float, bool]:
    """Play one attempted combo in one complete determinized world."""
    clone: Round = copy.copy(rnd)
    clone.hands = bot._complete_determinized_hands(
        rnd, seat, sampled, buried=[])
    clone.buried = []
    clone.trick = None
    clone.last_trick = None
    clone.history = []
    clone.message = None
    clone.bury(seat, list(bury_cards))
    clone._trusted_rollout = True
    clone._determinized_world = True

    previous_last = clone.last_trick
    clone.play(seat, list(lead_cards))
    actual = actual_play_after(clone, seat, previous_last)
    lead_succeeded = sorted(actual) == sorted(lead_cards)

    policy = bot.rollout_policy
    while clone.phase == "play":
        exact = bot._exact_endgame_value(clone)
        if exact is not None:
            return float(exact), lead_succeeded
        actor = clone.turn
        if actor is None:
            raise ComboExplorationRefused("combo rollout lost acting seat")
        clone.play(actor, policy.decide_play(clone, actor))
    return float(clone.attacker_points), lead_succeeded


def _paired_se(delta_sum: float, delta_sq: float, n: int) -> float:
    if n < 2:
        return float("inf")
    mean = delta_sum / n
    variance = max(0.0, delta_sq / n - mean * mean) * n / (n - 1)
    return math.sqrt(variance / n)


def _raw_winner(indices: list[int], means: list[float | None]) -> int | None:
    if not indices or means[indices[0]] is None:
        return None
    return max(indices, key=lambda index: means[index])


def _descriptive_contrast(world_values: list[list[float]], treatment: int | None,
                          reference: int | None) -> dict[str, object]:
    """Paired raw contrast with no post-selection coverage claim."""
    if treatment is None or reference is None:
        return {"mean": None, "se": None, "worlds": 0}
    deltas = [row[treatment] - row[reference] for row in world_values]
    total = sum(deltas)
    squared = sum(delta * delta for delta in deltas)
    return {
        "mean": total / len(deltas),
        "se": _paired_se(total, squared, len(deltas)),
        "worlds": len(deltas),
    }


def score_state(
    rnd: Round,
    seat: int,
    *,
    bot,
    incumbent_bury,
    worlds: int = DEFAULT_WORLDS,
    attempt_factor: int = DEFAULT_ATTEMPT_FACTOR,
    max_candidate_rollouts: int = DEFAULT_MAX_CANDIDATE_ROLLOUTS,
) -> dict:
    """Score one public bury state without turning it into a strength claim.

    All combos see exactly the same accepted worlds.  A sampler underfill keeps
    its completed diagnostic rows and publishes ``PARTIAL_EXPLORATION`` rather
    than discarding them or pretending the registered work completed.  The raw
    empirical winner and paired gaps are descriptive only: selecting the best
    of hundreds of combos is not covered by a single-candidate interval.
    """
    for value, label in ((worlds, "worlds"),
                         (attempt_factor, "attempt_factor"),
                         (max_candidate_rollouts, "max_candidate_rollouts")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{label} must be a positive integer")
    if rnd.phase != "bury" or rnd.banker != seat:
        raise ValueError("combo scorer requires the acting banker bury state")

    ballot = build_bury_lead_combo_ballot(
        rnd, seat, incumbent_bury, live_lead_ballot=bot._candidates)
    combos = _flatten(ballot)
    requested_rollouts = worlds * len(combos)
    if requested_rollouts > max_candidate_rollouts:
        raise ComboExplorationRefused(
            f"requested {requested_rollouts} candidate-worlds exceeds cap "
            f"{max_candidate_rollouts}")

    pre_rng_state = bot.rng.getstate()
    sampler_before = bot._sampler_snapshot()
    memory = Memory(rnd, seat, own_kitty=True)
    sums = [0.0] * len(combos)
    delta_sums = [0.0] * len(combos)
    delta_squares = [0.0] * len(combos)
    successful_leads = [0] * len(combos)
    world_values: list[list[float]] = []
    used = 0
    attempts = 0
    attempt_cap = worlds * attempt_factor

    while used < worlds and attempts < attempt_cap:
        attempts += 1
        sampled = bot._sample_hands(rnd, seat, memory)
        if sampled is None:
            continue
        hands, _ = sampled
        values = []
        successes = []
        for _, _, group, lead in combos:
            attacker_points, succeeded = _rollout_bury_lead(
                bot, rnd, seat, hands, group.bury.cards, lead.cards)
            # Banker maximises the negative attacker score, using the same
            # objective knob as ordinary MC for comparability.
            value = -float(bot._score(attacker_points))
            values.append(value)
            successes.append(succeeded)
        baseline = values[0]
        for index, (value, succeeded) in enumerate(zip(
                values, successes, strict=True)):
            sums[index] += value
            delta = value - baseline
            delta_sums[index] += delta
            delta_squares[index] += delta * delta
            successful_leads[index] += int(succeeded)
        world_values.append(values)
        used += 1

    complete = used == worlds
    if used:
        means = [total / used for total in sums]
        raw_winner = max(range(len(combos)), key=lambda index: means[index])
    else:
        means = [None] * len(combos)
        raw_winner = None

    incumbent_live_indices = [
        index for index, (group_index, _, _, lead) in enumerate(combos)
        if group_index == 0 and any(
            source.startswith("live_ballot") for source in lead.sources)
    ]
    incumbent_widened_indices = [
        index for index, (group_index, _, _, _) in enumerate(combos)
        if group_index == 0
    ]
    raw_incumbent_live = _raw_winner(incumbent_live_indices, means)
    raw_incumbent_widened = _raw_winner(incumbent_widened_indices, means)

    candidate_records = []
    for index, ((group_index, lead_index, group, lead), mean) in enumerate(
            zip(combos, means, strict=True)):
        gap = delta_sums[index] / used if used else None
        candidate_records.append({
            "index": index,
            "bury_index": group_index,
            "lead_index": lead_index,
            "bury_cards": list(group.bury.cards),
            "lead_cards": list(lead.cards),
            "bury_sources": list(group.bury.sources),
            "lead_sources": list(lead.sources),
            "incumbent_bury": group_index == 0,
            "live_lead": any(
                source.startswith("live_ballot")
                for source in lead.sources),
            "pair_lead": lead.pair_lead,
            "structured_throw": lead.structured_throw,
            "mean_banker_value": mean,
            "paired_gap_vs_candidate_zero": gap,
            "paired_se_vs_candidate_zero": (
                _paired_se(delta_sums[index], delta_squares[index], used)
                if used else None),
            "worlds": used,
            "attempted_lead_successes": successful_leads[index],
            "attempted_lead_failures": used - successful_leads[index],
        })

    status = ("COMPLETE_EXPLORATION" if complete else
              "PARTIAL_EXPLORATION" if used else
              "NO_WORLD_EXPLORATION")
    sampler_after = bot._sampler_snapshot()
    result = {
        "schema": SCHEMA,
        "status": status,
        "score_free": False,
        "exploration_only": True,
        "confirmatory_inference": False,
        "winner_selection_corrected": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "rng_state": pre_rng_state,
        "scoring_contract": {
            "bot_class": type(bot).__name__,
            "rollout_policy_class": type(bot.rollout_policy).__name__,
            "level_objective": bool(bot.LEVEL_OBJECTIVE),
            "exact_endgame": bool(bot.EXACT_ENDGAME),
            "perspective": "banker_value_is_negative_attacker_objective",
        },
        "ballot": ballot.record(),
        "candidate_count": len(combos),
        "candidate_zero_index": 0,
        "reference_contract": {
            "candidate_zero": (
                "incumbent heuristic bury plus live ballot candidate zero; "
                "not the production bot's final searched first lead"),
            "incumbent_live_menu": (
                "all original live-ballot leads after the incumbent bury"),
            "incumbent_widened_menu": (
                "original, retained-pair, and S6 leads after the incumbent "
                "bury"),
            "expanded_menu": "all sourced bury and first-lead combinations",
        },
        "raw_winner_index": raw_winner,
        "raw_gap_vs_candidate_zero": (
            means[raw_winner] - means[0]
            if raw_winner is not None else None),
        "raw_descriptive_winners": {
            "incumbent_live_menu_index": raw_incumbent_live,
            "incumbent_widened_menu_index": raw_incumbent_widened,
            "expanded_menu_index": raw_winner,
            "widened_lead_minus_live_lead": _descriptive_contrast(
                world_values, raw_incumbent_widened, raw_incumbent_live),
            "expanded_minus_incumbent_widened": _descriptive_contrast(
                world_values, raw_winner, raw_incumbent_widened),
            "expanded_minus_incumbent_live": _descriptive_contrast(
                world_values, raw_winner, raw_incumbent_live),
            "post_selection_coverage": False,
        },
        "candidates": candidate_records,
        "work": {
            "worlds_requested": worlds,
            "worlds_used": used,
            "attempts": attempts,
            "attempt_cap": attempt_cap,
            "candidate_rollouts": used * len(combos),
            "requested_candidate_rollouts": requested_rollouts,
            "candidate_rollout_cap": max_candidate_rollouts,
            "common_worlds": True,
            "complete": complete,
        },
        "sampler_counters": {
            "before": sampler_before,
            "after": sampler_after,
            "delta": bot._sampler_delta(sampler_before),
        },
    }
    if result["work"]["candidate_rollouts"] > max_candidate_rollouts:
        raise AssertionError("combo scorer exceeded candidate-world cap")
    if complete is not (status == "COMPLETE_EXPLORATION"):
        raise AssertionError("combo scorer status drift")
    return result
