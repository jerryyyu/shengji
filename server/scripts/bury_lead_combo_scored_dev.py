#!/usr/bin/env python3
"""Exact two-fold scorer for the reviewed opened-DEV bury/S6 design.

This module is a library, not a launcher.  It reconstructs one reviewed public
banker-bury state, selects three fixed menu slots on a baseline-only world
fold, and evaluates those same slots on a disjoint common report fold under
the baseline, all-boss, and boss-near continuations.  The caller must seal the
returned outcome-bearing record; this module has no filesystem or process
surface and grants no execution, aggregation, strength, or deployment
authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
from collections.abc import Mapping
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import bury_lead_combo_exploration as EXPLORE  # noqa: E402
import bury_lead_combo_population as POPULATION  # noqa: E402
import bury_lead_combo_scored_dev_design as DESIGN  # noqa: E402
from shengji.ai.bury_lead_combo import build_bury_lead_combo_ballot  # noqa: E402
from shengji.ai.memory import Memory  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.ai.throw_rollout import (  # noqa: E402
    S6_ROLLOUT_COUNTER_FIELDS,
    S6ThrowRolloutPolicy,
    make_s6_continuation_policy,
)
from shengji.engine.round import Round, actual_play_after  # noqa: E402


SCHEMA = "bury-lead-combo-scored-dev-state-v1"
CHAMPION = POPULATION.CHAMPION
MODES = DESIGN.MODES
SLOTS = DESIGN.MENU_SLOTS
SAMPLER_FIELDS = frozenset({
    "sample_attempts", "accepted_worlds", "failed_worlds",
    "rejected_worlds", "impossible_worlds",
})
FORBIDDEN_AUTHORITY_KEYS = frozenset({
    "execution_authorized", "aggregation_authorized",
    "promotion_authorized", "deployment_authorized",
})


class ScoredDevRefused(RuntimeError):
    """The scorer cannot honor the reviewed population or work contract."""


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False, default=list).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _integer(value: object, *, minimum: int | None = None) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and (minimum is None or value >= minimum))


def _finite(value: object) -> bool:
    return (isinstance(value, (int, float))
            and not isinstance(value, bool) and math.isfinite(value))


def _sha(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _flatten(ballot):
    return [
        (group_index, lead_index, group, lead)
        for group_index, group in enumerate(ballot.groups)
        for lead_index, lead in enumerate(group.leads)
    ]


def _sampler_delta(bot, before: Mapping[str, int]) -> dict[str, int]:
    value = bot._sampler_delta(before)
    return {key: int(value[key]) for key in SAMPLER_FIELDS}


def _sample_worlds(rnd: Round, seat: int, *, bot, worlds: int,
                   attempt_factor: int) -> tuple[list[dict[int, list[str]]], dict]:
    if worlds != 30 or attempt_factor != DESIGN.ATTEMPT_FACTOR:
        raise ScoredDevRefused("fold sampler work differs from reviewed design")
    before_rng = bot.rng.getstate()
    before_sampler = bot._sampler_snapshot()
    memory = Memory(rnd, seat, own_kitty=True)
    accepted: list[dict[int, list[str]]] = []
    commitments: list[str] = []
    attempts = 0
    while len(accepted) < worlds and attempts < worlds * attempt_factor:
        attempts += 1
        sampled = bot._sample_hands(rnd, seat, memory)
        if sampled is None:
            continue
        hands, buried = sampled
        if buried:
            raise ScoredDevRefused("pre-bury sampler exposed a hidden kitty")
        copied = {int(actor): list(cards) for actor, cards in hands.items()}
        accepted.append(copied)
        commitments.append(digest({"hands": copied, "buried": []}))
    after_sampler = bot._sampler_snapshot()
    delta = _sampler_delta(bot, before_sampler)
    if (len(accepted) != worlds
            or delta["accepted_worlds"] != worlds
            or delta["sample_attempts"] != attempts
            or delta["sample_attempts"] != (
                delta["accepted_worlds"] + delta["failed_worlds"])
            or delta["rejected_worlds"] > delta["failed_worlds"]
            or delta["impossible_worlds"] != 0
            or len(commitments) != len(set(commitments))):
        raise ScoredDevRefused("fold sampler underfill or counter drift")
    return accepted, {
        "worlds": worlds,
        "attempts": attempts,
        "attempt_cap": worlds * attempt_factor,
        "pre_rng_sha256": digest(before_rng),
        "post_rng_sha256": digest(bot.rng.getstate()),
        "sampler_before_sha256": digest(before_sampler),
        "sampler_after_sha256": digest(after_sampler),
        "sampler_delta": delta,
        "world_commitments": commitments,
    }


def _rollout(bot, rnd: Round, seat: int, sampled: dict[int, list[str]],
             bury_cards, lead_cards, *, continuation_policy) -> dict:
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
    attempted = list(lead_cards)
    clone.play(seat, attempted)
    actual = list(actual_play_after(clone, seat, previous_last))
    while clone.phase == "play":
        exact = bot._exact_endgame_value(clone)
        if exact is not None:
            raise ScoredDevRefused(
                "reviewed exact-endgame=false scorer entered exact endgame")
        actor = clone.turn
        if actor is None:
            raise ScoredDevRefused("scored rollout lost acting seat")
        clone.play(actor, continuation_policy.decide_play(clone, actor))
    attacker_points = int(clone.attacker_points)
    value = -float(bot._score(attacker_points))
    if not math.isfinite(value):
        raise ScoredDevRefused("scored rollout produced a nonfinite value")
    return {
        "banker_value": value,
        "attacker_points": attacker_points,
        "attempted_lead": attempted,
        "actual_lead": actual,
        "lead_succeeded": sorted(attempted) == sorted(actual),
    }


def _menu_indices(combos) -> dict[str, list[int]]:
    live = [
        index for index, (group_index, _, _, lead) in enumerate(combos)
        if group_index == 0 and any(
            source.startswith("live_ballot") for source in lead.sources)
    ]
    widened = [
        index for index, (group_index, _, _, _) in enumerate(combos)
        if group_index == 0
    ]
    expanded = list(range(len(combos)))
    if not live or not set(live) <= set(widened) <= set(expanded):
        raise ScoredDevRefused("reviewed menu nesting or nonempty contract drift")
    return {
        "incumbent_live": live,
        "incumbent_widened": widened,
        "expanded": expanded,
    }


def _winner(indices: list[int], means: list[float]) -> int:
    # Higher banker value wins; exact ties choose the lowest canonical index.
    return max(indices, key=lambda index: (means[index], -index))


def _candidate(index: int, combo) -> dict:
    group_index, lead_index, group, lead = combo
    return {
        "index": index,
        "bury_index": group_index,
        "lead_index": lead_index,
        "bury_cards": list(group.bury.cards),
        "lead_cards": list(lead.cards),
        "bury_sources": list(group.bury.sources),
        "lead_sources": list(lead.sources),
        "incumbent_bury": group_index == 0,
        "live_lead": any(
            source.startswith("live_ballot") for source in lead.sources),
        "pair_lead": bool(lead.pair_lead),
        "structured_throw": bool(lead.structured_throw),
    }


def _sampler_problems(value: object, *, label: str) -> list[str]:
    if (not isinstance(value, Mapping)
            or set(value) != {
                "worlds", "attempts", "attempt_cap", "pre_rng_sha256",
                "post_rng_sha256", "sampler_before_sha256",
                "sampler_after_sha256", "sampler_delta",
                "world_commitments"}
            or value.get("worlds") != 30
            or isinstance(value.get("attempts"), bool)
            or not isinstance(value.get("attempts"), int)
            or not 30 <= value["attempts"] <= 30 * DESIGN.ATTEMPT_FACTOR
            or value.get("attempt_cap") != 30 * DESIGN.ATTEMPT_FACTOR
            or any(not isinstance(value.get(field), str)
                   or len(value[field]) != 64
                   or any(char not in "0123456789abcdef"
                          for char in value[field])
                   for field in (
                       "pre_rng_sha256", "post_rng_sha256",
                       "sampler_before_sha256", "sampler_after_sha256"))
            or not isinstance(value.get("world_commitments"), list)
            or len(value["world_commitments"]) != 30
            or any(not _sha(item) for item in value["world_commitments"])
            or len(set(value["world_commitments"])) != 30):
        return [f"{label} sampler identity drift"]
    delta = value.get("sampler_delta")
    if (not isinstance(delta, Mapping) or set(delta) != SAMPLER_FIELDS
            or any(isinstance(item, bool) or not isinstance(item, int)
                   or item < 0 for item in delta.values())
            or delta["accepted_worlds"] != 30
            or delta["sample_attempts"] != value["attempts"]
            or delta["sample_attempts"] != (
                delta["accepted_worlds"] + delta["failed_worlds"])
            or delta["rejected_worlds"] > delta["failed_worlds"]
            or delta["impossible_worlds"] != 0):
        return [f"{label} sampler counter drift"]
    return []


def _dose(policy, before, *, mode: str) -> dict:
    if mode == "baseline":
        return {
            "schema": "s6-throw-rollout-dose-v1", "mode": "baseline",
            "deterministic": True, "actor_visible": True,
            "recursive_mc": False, "exploration_only": True,
            "before": None, "after": None, "delta": None,
        }
    if not isinstance(policy, S6ThrowRolloutPolicy):
        raise ScoredDevRefused("nonbaseline continuation policy class drift")
    value = policy.delta(before)
    if value["delta"].get("play_calls", 0) <= 0:
        raise ScoredDevRefused("nonbaseline continuation did not execute")
    return value


def score_state(deal_seed: int, *, state_builder=POPULATION.build_bury_state,
                bot_factory=make_bot, rollout=_rollout) -> dict:
    """Return one outcome-bearing record for later immutable sealing."""
    expected = next(
        (row for row in DESIGN._selection_rows()
         if row["deal_seed"] == deal_seed), None)
    if expected is None:
        raise ScoredDevRefused("deal seed is outside the reviewed 64-state slice")
    rnd, incumbent, replay = state_builder(deal_seed, CHAMPION)
    seat = rnd.banker
    if rnd.phase != "bury" or seat not in range(4):
        raise ScoredDevRefused("reconstructed row is not an acting banker bury")
    census = POPULATION.census_state(
        deal_seed, state_builder=state_builder, bot_factory=bot_factory)
    if census["combo_count"] != expected["combo_count"]:
        raise ScoredDevRefused("reviewed row geometry drift")
    selection_bot = bot_factory(CHAMPION, seed=DESIGN.SELECTION_BASE_SEED)
    if (type(selection_bot).__name__ != "MCS0ReportLCB"
            or selection_bot.LEVEL_OBJECTIVE is not False
            or selection_bot.EXACT_ENDGAME is not False):
        raise ScoredDevRefused("reviewed scorer bot contract drift")
    ballot = build_bury_lead_combo_ballot(
        rnd, seat, incumbent, live_lead_ballot=selection_bot._candidates)
    combos = _flatten(ballot)
    if len(combos) != expected["combo_count"]:
        raise ScoredDevRefused("reviewed candidate geometry drift")

    selection_worlds, selection_sampler = _sample_worlds(
        rnd, seat, bot=selection_bot, worlds=DESIGN.SELECTION_WORLDS,
        attempt_factor=DESIGN.ATTEMPT_FACTOR)
    selection_policy = selection_bot.rollout_policy
    sums = [0.0] * len(combos)
    selection_values: list[list[float]] = []
    for world in selection_worlds:
        row = []
        for index, (_, _, group, lead) in enumerate(combos):
            value = rollout(
                selection_bot, rnd, seat, world, group.bury.cards, lead.cards,
                continuation_policy=selection_policy)["banker_value"]
            sums[index] += value
            row.append(value)
        selection_values.append(row)
    means = [total / DESIGN.SELECTION_WORLDS for total in sums]
    menus = _menu_indices(combos)
    selected = {slot: _winner(menus[slot], means) for slot in SLOTS}

    report_bot = bot_factory(CHAMPION, seed=DESIGN.REPORT_BASE_SEED)
    if (type(report_bot).__name__ != "MCS0ReportLCB"
            or report_bot.LEVEL_OBJECTIVE is not False
            or report_bot.EXACT_ENDGAME is not False):
        raise ScoredDevRefused("reviewed report bot contract drift")
    report_worlds, report_sampler = _sample_worlds(
        rnd, seat, bot=report_bot, worlds=DESIGN.REPORT_WORLDS,
        attempt_factor=DESIGN.ATTEMPT_FACTOR)
    if set(selection_sampler["world_commitments"]).intersection(
            report_sampler["world_commitments"]):
        raise ScoredDevRefused("selection and report world folds overlap")

    reports = {}
    for mode in MODES:
        policy = make_s6_continuation_policy(
            mode, baseline=report_bot.rollout_policy)
        before = (policy.snapshot()
                  if isinstance(policy, S6ThrowRolloutPolicy) else None)
        rows = []
        for commitment, world in zip(
                report_sampler["world_commitments"], report_worlds,
                strict=True):
            outcomes = []
            for slot in SLOTS:
                index = selected[slot]
                _, _, group, lead = combos[index]
                outcomes.append({
                    "slot": slot,
                    "candidate_index": index,
                    **rollout(
                        report_bot, rnd, seat, world, group.bury.cards,
                        lead.cards, continuation_policy=policy),
                })
            rows.append({"world_commitment": commitment,
                         "slot_outcomes": outcomes})
        reports[mode] = {
            "mode": mode,
            "world_commitments": list(
                report_sampler["world_commitments"]),
            "rows": rows,
            "continuation_dose": _dose(policy, before, mode=mode),
        }

    value = {
        "schema": SCHEMA,
        "design_id": DESIGN.DESIGN_ID,
        "population_id": DESIGN.POPULATION_ID,
        "state_id": census["state_id"],
        "source_state_id": census["source_state_id"],
        "deal_seed": deal_seed,
        "banker": seat,
        "source_input_sha256": census["source_input_sha256"],
        "source_replay_sha256": census["source_replay_sha256"],
        "ballot_sha256": POPULATION.stable_digest(ballot.record()),
        "candidate_count": len(combos),
        "selection": {
            "base_seed": DESIGN.SELECTION_BASE_SEED,
            "sampler": selection_sampler,
            "candidate_values": selection_values,
            "candidate_means": means,
            "candidate_metadata": [
                _candidate(index, combo)
                for index, combo in enumerate(combos)
            ],
            "selected_indices": selected,
            "selected_candidates": {
                slot: _candidate(selected[slot], combos[selected[slot]])
                for slot in SLOTS
            },
            "candidate_rollouts": len(combos) * DESIGN.SELECTION_WORLDS,
        },
        "report": {
            "base_seed": DESIGN.REPORT_BASE_SEED,
            "sampler": report_sampler,
            "modes": reports,
            "candidate_rollouts_per_mode":
                len(SLOTS) * DESIGN.REPORT_WORLDS,
        },
        "work": {
            "selection_candidate_rollouts":
                len(combos) * DESIGN.SELECTION_WORLDS,
            "report_candidate_rollouts_per_mode":
                len(SLOTS) * DESIGN.REPORT_WORLDS,
            "total_candidate_rollouts":
                len(combos) * DESIGN.SELECTION_WORLDS
                + len(MODES) * len(SLOTS) * DESIGN.REPORT_WORLDS,
            "exact_complete": True,
        },
        "exploration_only": True,
        "confirmatory_inference": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    value["internal_sha256"] = digest(value)
    problems = record_problems(value, expected_seed=deal_seed)
    if problems:
        raise ScoredDevRefused("; ".join(problems))
    return value


def record_problems(value: object, *, expected_seed: int) -> list[str]:
    if not isinstance(value, Mapping):
        return ["scored record is not an object"]
    problems = []
    expected_fields = {
        "schema", "design_id", "population_id", "state_id",
        "source_state_id", "deal_seed", "banker", "source_input_sha256",
        "source_replay_sha256", "ballot_sha256", "candidate_count",
        "selection", "report", "work", "exploration_only",
        "confirmatory_inference", "strength_claim", "training_authorized",
        "production_promotion", "production_deployment", "internal_sha256",
    }
    if set(value) != expected_fields:
        problems.append("scored record field population drift")
    material = dict(value)
    observed = material.pop("internal_sha256", None)
    if observed != digest(material):
        problems.append("scored record internal digest drift")
    expected = next(
        (row for row in DESIGN._selection_rows()
         if row["deal_seed"] == expected_seed), None)
    if (expected is None or value.get("schema") != SCHEMA
            or value.get("design_id") != DESIGN.DESIGN_ID
            or value.get("population_id") != DESIGN.POPULATION_ID
            or value.get("deal_seed") != expected_seed
            or value.get("candidate_count") != expected["combo_count"]):
        problems.append("scored record identity/geometry drift")
    banker = value.get("banker")
    if (not _integer(banker) or banker not in range(4)
            or value.get("state_id") != (
                f"{DESIGN.POPULATION_ID}:deal:{expected_seed}:banker:{banker}")
            or value.get("source_state_id") != (
                f"s3a-bury-pilot-v2:deal:{expected_seed}:banker:{banker}")):
        problems.append("scored record state identity drift")
    for field in (
            "source_input_sha256", "source_replay_sha256", "ballot_sha256"):
        if not _sha(value.get(field)):
            problems.append(f"scored record {field} drift")
    if (value.get("exploration_only") is not True
            or value.get("confirmatory_inference") is not False
            or value.get("strength_claim") is not False
            or value.get("training_authorized") is not False
            or value.get("production_promotion") is not False
            or value.get("production_deployment") is not False):
        problems.append("scored record authority drift")
    selection = value.get("selection")
    report = value.get("report")
    work = value.get("work")
    selected_lookup = (
        selection.get("selected_indices")
        if isinstance(selection, Mapping)
        and isinstance(selection.get("selected_indices"), Mapping)
        else {})
    metadata_lookup = (
        selection.get("candidate_metadata")
        if isinstance(selection, Mapping)
        and isinstance(selection.get("candidate_metadata"), list)
        else [])
    count = value.get("candidate_count")
    if not isinstance(count, int) or isinstance(count, bool):
        return sorted(set(problems + ["scored record candidate count drift"]))
    if (not isinstance(selection, Mapping)
            or set(selection) != {
                "base_seed", "sampler", "candidate_values",
                "candidate_means", "candidate_metadata", "selected_indices",
                "selected_candidates", "candidate_rollouts"}
            or selection.get("base_seed") != DESIGN.SELECTION_BASE_SEED
            or selection.get("candidate_rollouts")
            != count * DESIGN.SELECTION_WORLDS):
        problems.append("selection fold contract drift")
    else:
        problems.extend(_sampler_problems(
            selection.get("sampler"), label="selection"))
        rows = selection.get("candidate_values")
        means = selection.get("candidate_means")
        metadata = selection.get("candidate_metadata")
        indices = selection.get("selected_indices")
        candidates = selection.get("selected_candidates")
        if (not isinstance(rows, list) or len(rows) != DESIGN.SELECTION_WORLDS
                or any(not isinstance(row, list) or len(row) != count
                       or any(isinstance(item, bool)
                              or not isinstance(item, (int, float))
                              or not math.isfinite(item) for item in row)
                       for row in rows)
                or not isinstance(means, list) or len(means) != count
                or any(not _finite(item) for item in means)
                or any(abs(means[index] - sum(row[index] for row in rows)
                            / DESIGN.SELECTION_WORLDS) > 1e-12
                       for index in range(count))):
            problems.append("selection values/means drift")
        if (not isinstance(metadata, list) or len(metadata) != count
                or any(not isinstance(item, Mapping)
                       or set(item) != {
                           "index", "bury_index", "lead_index",
                           "bury_cards", "lead_cards", "bury_sources",
                           "lead_sources", "incumbent_bury", "live_lead",
                           "pair_lead", "structured_throw"}
                       or item.get("index") != index
                       or not _integer(item.get("bury_index"), minimum=0)
                       or not _integer(item.get("lead_index"), minimum=0)
                       or not isinstance(item.get("bury_cards"), list)
                       or not isinstance(item.get("lead_cards"), list)
                       or not item["bury_cards"] or not item["lead_cards"]
                       or any(not isinstance(card, str)
                              for card in item["bury_cards"])
                       or any(not isinstance(card, str)
                              for card in item["lead_cards"])
                       or not isinstance(item.get("bury_sources"), list)
                       or not isinstance(item.get("lead_sources"), list)
                       or not item["bury_sources"] or not item["lead_sources"]
                       or any(not isinstance(source, str) or not source
                              for source in item["bury_sources"])
                       or any(not isinstance(source, str) or not source
                              for source in item["lead_sources"])
                       or item.get("incumbent_bury") is not (
                           item["bury_index"] == 0)
                       or item.get("live_lead") is not any(
                           source.startswith("live_ballot")
                           for source in item["lead_sources"])
                       or type(item.get("pair_lead")) is not bool
                       or type(item.get("structured_throw")) is not bool
                       for index, item in enumerate(metadata))):
            problems.append("selection candidate metadata drift")
        if (not isinstance(indices, Mapping) or set(indices) != set(SLOTS)
                or not isinstance(candidates, Mapping)
                or set(candidates) != set(SLOTS)
                or any(isinstance(indices.get(slot), bool)
                       or not isinstance(indices.get(slot), int)
                       or not 0 <= indices[slot] < count
                       for slot in SLOTS)
                or any(not isinstance(candidates.get(slot), Mapping)
                       or candidates[slot].get("index") != indices[slot]
                       for slot in SLOTS)):
            problems.append("selection fixed-slot drift")
        elif isinstance(metadata, list) and len(metadata) == count \
                and all(isinstance(item, Mapping)
                        and _integer(item.get("index"))
                        and item["index"] in range(count)
                        for item in metadata) \
                and isinstance(means, list) and len(means) == count \
                and all(_finite(item) for item in means):
            menus = {
                "incumbent_live": [
                    item["index"] for item in metadata
                    if item.get("incumbent_bury") is True
                    and item.get("live_lead") is True],
                "incumbent_widened": [
                    item["index"] for item in metadata
                    if item.get("incumbent_bury") is True],
                "expanded": list(range(count)),
            }
            if (any(not menus[slot] for slot in SLOTS)
                    or not set(menus["incumbent_live"]) <= set(
                        menus["incumbent_widened"])
                    or any(indices[slot] != _winner(menus[slot], means)
                           for slot in SLOTS)
                    or any(dict(candidates[slot])
                           != dict(metadata[indices[slot]]) for slot in SLOTS)):
                problems.append("selection winner/menu reconstruction drift")
    if (not isinstance(report, Mapping)
            or set(report) != {
                "base_seed", "sampler", "modes",
                "candidate_rollouts_per_mode"}
            or report.get("base_seed") != DESIGN.REPORT_BASE_SEED
            or report.get("candidate_rollouts_per_mode")
            != len(SLOTS) * DESIGN.REPORT_WORLDS
            or not isinstance(report.get("modes"), Mapping)
            or list(report["modes"]) != list(MODES)):
        problems.append("report fold contract drift")
    else:
        problems.extend(_sampler_problems(
            report.get("sampler"), label="report"))
        selection_commitments = (
            selection["sampler"].get("world_commitments")
            if isinstance(selection, Mapping)
            and isinstance(selection.get("sampler"), Mapping) else None)
        report_commitments = (
            report["sampler"].get("world_commitments")
            if isinstance(report.get("sampler"), Mapping) else None)
        if (isinstance(selection_commitments, list)
                and all(_sha(item) for item in selection_commitments)
                and isinstance(report_commitments, list)
                and all(_sha(item) for item in report_commitments)
                and set(selection_commitments).intersection(
                    report_commitments)):
            problems.append("selection/report world-fold overlap")
        commitments = None
        for mode in MODES:
            arm = report["modes"].get(mode)
            if (not isinstance(arm, Mapping)
                    or set(arm) != {
                        "mode", "world_commitments", "rows",
                        "continuation_dose"}
                    or arm.get("mode") != mode
                    or not isinstance(arm.get("world_commitments"), list)
                    or len(arm["world_commitments"]) != DESIGN.REPORT_WORLDS
                    or not isinstance(arm.get("rows"), list)
                    or len(arm["rows"]) != DESIGN.REPORT_WORLDS):
                problems.append(f"report {mode} contract drift")
                continue
            if commitments is None:
                commitments = arm["world_commitments"]
            elif arm["world_commitments"] != commitments:
                problems.append("report common-world commitment drift")
            if (isinstance(report_commitments, list)
                    and arm["world_commitments"] != report_commitments):
                problems.append("report sampler/world commitment drift")
            for row_index, row in enumerate(arm["rows"]):
                outcomes = row.get("slot_outcomes") if isinstance(row, Mapping) else None
                if (not isinstance(row, Mapping)
                        or set(row) != {"world_commitment", "slot_outcomes"}
                        or not isinstance(outcomes, list)
                        or [outcome.get("slot") for outcome in outcomes
                            if isinstance(outcome, Mapping)] != list(SLOTS)):
                    problems.append(f"report {mode} row drift")
                    break
                if (row["world_commitment"]
                        != arm["world_commitments"][row_index]
                        or any(not isinstance(outcome, Mapping)
                               or set(outcome) != {
                                   "slot", "candidate_index", "banker_value",
                                   "attacker_points", "attempted_lead",
                                   "actual_lead", "lead_succeeded"}
                               or outcome.get("candidate_index")
                               != selected_lookup.get(
                                   outcome.get("slot"))
                               or not _integer(
                                   outcome.get("candidate_index"), minimum=0)
                               or outcome["candidate_index"] >= len(
                                   metadata_lookup)
                               or not isinstance(
                                   metadata_lookup[outcome["candidate_index"]],
                                   Mapping)
                               or not _finite(outcome.get("banker_value"))
                               or isinstance(outcome.get("attacker_points"), bool)
                               or not isinstance(outcome.get("attacker_points"), int)
                               or outcome["attacker_points"] < 0
                               or outcome["banker_value"] != -float(
                                   outcome["attacker_points"])
                               or not isinstance(outcome.get("attempted_lead"), list)
                               or not isinstance(outcome.get("actual_lead"), list)
                               or not outcome["attempted_lead"]
                               or not outcome["actual_lead"]
                               or any(not isinstance(card, str)
                                      for card in outcome["attempted_lead"])
                               or any(not isinstance(card, str)
                                      for card in outcome["actual_lead"])
                               or outcome["attempted_lead"] !=
                                   metadata_lookup[
                                       outcome["candidate_index"]].get(
                                           "lead_cards")
                               or any(outcome["actual_lead"].count(card)
                                      > outcome["attempted_lead"].count(card)
                                      for card in set(outcome["actual_lead"]))
                               or outcome.get("lead_succeeded") is not (
                                   sorted(outcome["attempted_lead"])
                                   == sorted(outcome["actual_lead"]))
                               for outcome in outcomes)):
                    problems.append(f"report {mode} outcome drift")
                    break
            dose = arm.get("continuation_dose")
            if (not isinstance(dose, Mapping)
                    or dose.get("schema") != "s6-throw-rollout-dose-v1"
                    or dose.get("mode") != mode
                    or dose.get("deterministic") is not True
                    or dose.get("actor_visible") is not True
                    or dose.get("recursive_mc") is not False
                    or dose.get("exploration_only") is not True):
                problems.append(f"report {mode} continuation-dose drift")
            elif mode == "baseline":
                if (dose.get("before"), dose.get("after"), dose.get("delta")) \
                        != (None, None, None):
                    problems.append("report baseline continuation-dose drift")
            else:
                fields = set(S6_ROLLOUT_COUNTER_FIELDS)
                before, after, delta = (
                    dose.get("before"), dose.get("after"), dose.get("delta"))
                if (any(not isinstance(item, Mapping) or set(item) != fields
                        for item in (before, after, delta))
                        or any(isinstance(number, bool)
                               or not isinstance(number, int) or number < 0
                               for item in (before, after, delta)
                               for number in item.values())
                        or any(before[field] != 0 for field in fields)
                        or any(after[field] != delta[field] for field in fields)
                        or delta.get("play_calls", 0) <= 0):
                    problems.append(f"report {mode} continuation-dose drift")
    if (not isinstance(work, Mapping)
            or work != {
                "selection_candidate_rollouts":
                    count * DESIGN.SELECTION_WORLDS,
                "report_candidate_rollouts_per_mode":
                    len(SLOTS) * DESIGN.REPORT_WORLDS,
                "total_candidate_rollouts":
                    count * DESIGN.SELECTION_WORLDS
                    + len(MODES) * len(SLOTS) * DESIGN.REPORT_WORLDS,
                "exact_complete": True,
            }):
        problems.append("scored record exact work drift")
    if any(key in value for key in FORBIDDEN_AUTHORITY_KEYS):
        problems.append("scored record foreign authority field")
    return sorted(set(problems))
