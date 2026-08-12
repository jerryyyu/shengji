#!/usr/bin/env python3
"""Core whole-round evaluator for the S6 shuai-pai source.

This file deliberately has no launch CLI yet.  It supplies the deterministic
three-arm gameplay, telemetry validation, and clustered aggregate that a
separately reviewed packet/controller will wrap.  Keeping execution authority
out of the core makes it impossible to mistake source readiness for permission
to spend a fresh population.
"""
from __future__ import annotations

import math
import random
import sys
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SERVER))

from shengji.ai.env import play_round  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.ai.throw_policy import (  # noqa: E402
    S6_THROW_COUNTER_FIELDS,
    S6_THROW_POLICIES,
    empty_s6_throw_telemetry,
    make_s6_throw_bot,
)
from shengji.engine.game import Game  # noqa: E402
from shengji.evaluation import counters, paired_by_seed  # noqa: E402


SCHEMA = "s6-throw-duel-core-v1"
AGGREGATE_SCHEMA = "s6-throw-duel-aggregate-v1"
CHAMPION = S6_THROW_POLICIES["base"]
OPPONENT = CHAMPION
LABELS = {
    "treatment": S6_THROW_POLICIES["treatment"],
    "matched_null": S6_THROW_POLICIES["matched_null"],
    "champion": CHAMPION,
}
LABEL_ORDER = tuple(LABELS)
POLICY_ROLE_OFFSETS = (0, 500_000)
OPPONENT_ROLE_OFFSETS = (1_000_000, 1_500_000)
ROOT_WORLDS = 30
REPORT_WORLDS = 300
MAX_ATTACKER_POINTS = 4_120
MAX_LEVEL_CHANGE = 101


class S6ProtocolRefused(RuntimeError):
    """The proposed S6 artifact cannot support its stated comparison."""


def make_arm(label: str, seed: int):
    if label == "treatment":
        return make_s6_throw_bot(treatment=True, seed=seed)
    if label == "matched_null":
        return make_s6_throw_bot(treatment=False, seed=seed)
    if label == "champion":
        return make_bot(CHAMPION, seed=seed)
    raise S6ProtocolRefused(f"unknown S6 arm {label!r}")


def s6_telemetry(bots: list, *, mode: str) -> dict[str, object]:
    if mode == "off":
        if any(hasattr(bot, "s6_throw_telemetry") for bot in bots):
            raise S6ProtocolRefused(
                "feature-off arm unexpectedly exposes S6 telemetry")
        return empty_s6_throw_telemetry(mode="off")
    totals = Counter({field: 0 for field in S6_THROW_COUNTER_FIELDS})
    for bot in bots:
        payload = bot.s6_throw_telemetry()
        if payload.get("mode") != mode:
            raise S6ProtocolRefused("S6 bot telemetry mode drift")
        totals.update({field: payload[field]
                       for field in S6_THROW_COUNTER_FIELDS})
    merged = {
        "schema": "s6-throw-source-cumulative-telemetry-v1",
        "mode": mode,
        "deterministic_source": True,
        "exact_work_complete": totals["short_searches"] == 0,
        **{field: int(totals[field]) for field in S6_THROW_COUNTER_FIELDS},
    }
    problems = telemetry_problems(merged, expected_mode=mode)
    if problems:
        raise S6ProtocolRefused(
            "invalid merged S6 telemetry: " + "; ".join(problems))
    return merged


def _record(run_id: str, label: str, seed: int, flip: int, log,
            arm_bots: list, opp_bots: list) -> dict:
    policy_team = 0 if flip == 0 else 1
    won = int(log.winner_team == policy_team)
    utility = (1 if won else -1) * max(1, int(log.level_change))
    mode = {"treatment": "treatment", "matched_null": "matched_null",
            "champion": "off"}[label]
    return {
        "run": run_id,
        "label": label,
        "policy": LABELS[label],
        "opponent": OPPONENT,
        "seed": seed,
        "flip": flip,
        "banker": int(log.banker),
        "attacker_points": int(log.attacker_points),
        "winner_team": int(log.winner_team),
        "level_change": int(log.level_change),
        "won": won,
        "level_utility": utility,
        "arm": {
            **counters(arm_bots),
            "s6_throw": s6_telemetry(arm_bots, mode=mode),
        },
        "opp": {
            **counters(opp_bots),
            "s6_throw": s6_telemetry(opp_bots, mode="off"),
        },
    }


def play_arm_cluster(label: str, seed: int, *, run_id: str) -> list[dict]:
    """Play both mirrored flips for one arm on one common deal seed."""
    records = []
    for flip in (0, 1):
        a1 = make_arm(label, seed + POLICY_ROLE_OFFSETS[0])
        a2 = make_arm(label, seed + POLICY_ROLE_OFFSETS[1])
        b1 = make_bot(OPPONENT, seed=seed + OPPONENT_ROLE_OFFSETS[0])
        b2 = make_bot(OPPONENT, seed=seed + OPPONENT_ROLE_OFFSETS[1])
        policies = ([a1, b1, a2, b2] if flip == 0
                    else [b1, a1, b2, a2])
        log = play_round(Game(random.Random(seed)), policies)
        records.append(_record(
            run_id, label, seed, flip, log, [a1, a2], [b1, b2]))
    return records


def telemetry_problems(value: object, *, expected_mode: str) -> list[str]:
    if not isinstance(value, dict):
        return ["S6 telemetry is not an object"]
    expected_fields = {
        "schema", "mode", "deterministic_source", "exact_work_complete",
        *S6_THROW_COUNTER_FIELDS,
    }
    problems = []
    if set(value) != expected_fields:
        problems.append("S6 telemetry field population")
    if (value.get("schema") != "s6-throw-source-cumulative-telemetry-v1"
            or value.get("mode") != expected_mode
            or value.get("deterministic_source") is not True
            or value.get("exact_work_complete") is not True):
        problems.append("S6 telemetry identity")
    if not all(
            isinstance(value.get(field), int)
            and not isinstance(value.get(field), bool)
            and value[field] >= 0 for field in S6_THROW_COUNTER_FIELDS):
        problems.append("S6 telemetry counters")
        return sorted(set(problems))
    if value["eligible_leads"] > value["lead_calls"] \
            or value["lead_calls"] > value["play_calls"]:
        problems.append("S6 lead accounting")
    if value["new_candidate_triggers"] > value["eligible_leads"]:
        problems.append("S6 triggers exceed eligible leads")
    if value["new_candidate_triggers"] != (
            value["searched_triggers"] + value["tractor_lock_skips"]):
        problems.append("S6 trigger paths")
    if value["searched_triggers"] != (
            value["attacker_triggers"] + value["defender_triggers"]):
        problems.append("S6 trigger roles")
    if value["tractor_lock_bypasses"] > value["searched_triggers"]:
        problems.append("S6 tractor bypass accounting")
    if value["new_candidates"] < value["new_candidate_triggers"] \
            or value["source_candidates"] < value["new_candidates"]:
        problems.append("S6 candidate accounting")
    if value["base_candidate_count"] > value["widened_candidate_count"]:
        problems.append("S6 widened ballot shrank")
    if value["treatment_overrides"] > value["searched_triggers"]:
        problems.append("S6 overrides exceed searched triggers")
    if expected_mode == "treatment":
        if value["matched_noops"] != 0:
            problems.append("S6 treatment recorded null noops")
    elif expected_mode == "matched_null":
        if value["treatment_overrides"] != 0 \
                or value["matched_noops"] != value["searched_triggers"]:
            problems.append("S6 matched-null dose")
    elif any(value[field] != 0 for field in S6_THROW_COUNTER_FIELDS):
        problems.append("feature-off S6 telemetry is nonzero")
    return sorted(set(problems))


def counter_problems(value: object, *, expected_mode: str) -> list[str]:
    if not isinstance(value, dict):
        return ["counter payload is not an object"]
    expected_fields = set(counters([])) | {"s6_throw"}
    problems = []
    if set(value) != expected_fields:
        problems.append("counter field population")
    for name in set(counters([])) - {"search_secs"}:
        item = value.get(name)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            problems.append(f"counter {name} is not a non-negative integer")
    seconds = value.get("search_secs")
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or seconds < 0):
        problems.append("counter search_secs is not non-negative finite")
    if (isinstance(value.get("sample_attempts"), int)
            and isinstance(value.get("accepted_worlds"), int)
            and isinstance(value.get("failed_worlds"), int)
            and value["sample_attempts"] !=
            value["accepted_worlds"] + value["failed_worlds"]):
        problems.append("sampler counters do not reconcile")
    if (isinstance(value.get("rejected_worlds"), int)
            and isinstance(value.get("failed_worlds"), int)
            and value["rejected_worlds"] > value["failed_worlds"]):
        problems.append("rejected worlds exceed failed worlds")
    if (isinstance(value.get("searches"), int)
            and isinstance(value.get("accepted_worlds"), int)):
        expected_worlds = (ROOT_WORLDS + REPORT_WORLDS) * value["searches"]
        if value["accepted_worlds"] != expected_worlds:
            problems.append("accepted report-LCB dose")
    for name in (
            "void_fallbacks", "short_searches", "zero_world",
            "exact_endgames", "exact_endgame_attempts",
            "exact_endgame_refusals", "exact_endgame_budget_exceeded",
            "exact_endgame_sessions", "exact_endgame_nodes",
            "exact_endgame_cache_hits"):
        if value.get(name) != 0:
            problems.append(f"forbidden counter {name} is nonzero")
    problems.extend(telemetry_problems(
        value.get("s6_throw"), expected_mode=expected_mode))
    return sorted(set(problems))


def expected_round_outcome(*, banker: int,
                           attacker_points: int) -> tuple[int, int]:
    if (isinstance(banker, bool) or not isinstance(banker, int)
            or not 0 <= banker < 4):
        raise ValueError("banker must be a seat")
    if (isinstance(attacker_points, bool)
            or not isinstance(attacker_points, int)
            or not 0 <= attacker_points <= MAX_ATTACKER_POINTS
            or attacker_points % 5 != 0):
        raise ValueError("attacker points outside physical house bound")
    banker_team = banker % 2
    if attacker_points >= 80:
        return 1 - banker_team, (attacker_points - 80) // 40
    gain = 3 if attacker_points == 0 else (2 if attacker_points < 40 else 1)
    return banker_team, gain


def record_problems(record: object, *, expected_label: str,
                    expected_seed: int, expected_flip: int,
                    expected_run_id: str) -> list[str]:
    if not isinstance(record, dict):
        return ["record is not an object"]
    expected_fields = {
        "run", "label", "policy", "opponent", "seed", "flip", "banker",
        "attacker_points", "winner_team", "level_change", "won",
        "level_utility", "arm", "opp",
    }
    problems = []
    if set(record) != expected_fields:
        problems.append("record field population")
    if (record.get("run") != expected_run_id
            or record.get("label") != expected_label
            or record.get("policy") != LABELS[expected_label]
            or record.get("opponent") != OPPONENT
            or record.get("seed") != expected_seed
            or record.get("flip") != expected_flip):
        problems.append("record identity")
    try:
        winner, gain = expected_round_outcome(
            banker=record.get("banker"),
            attacker_points=record.get("attacker_points"))
    except ValueError as exc:
        problems.append(str(exc))
        winner = gain = None
    policy_team = 0 if expected_flip == 0 else 1
    won = int(winner == policy_team) if winner in (0, 1) else None
    utility = ((1 if won else -1) * max(1, gain)
               if won in (0, 1) and isinstance(gain, int) else None)
    if (isinstance(record.get("winner_team"), bool)
            or record.get("winner_team") not in (0, 1)
            or record.get("winner_team") != winner):
        problems.append("record winner")
    if (isinstance(record.get("level_change"), bool)
            or not isinstance(record.get("level_change"), int)
            or not 0 <= record.get("level_change", -1) <= MAX_LEVEL_CHANGE
            or record.get("level_change") != gain):
        problems.append("record level change")
    if (isinstance(record.get("won"), bool)
            or record.get("won") not in (0, 1)
            or record.get("won") != won
            or isinstance(record.get("level_utility"), bool)
            or not isinstance(record.get("level_utility"), int)
            or not 1 <= abs(record.get("level_utility", 0)) <= MAX_LEVEL_CHANGE
            or record.get("level_utility") != utility):
        problems.append("record signed utility")
    mode = {"treatment": "treatment", "matched_null": "matched_null",
            "champion": "off"}[expected_label]
    problems.extend(f"arm: {problem}" for problem in counter_problems(
        record.get("arm"), expected_mode=mode))
    problems.extend(f"opp: {problem}" for problem in counter_problems(
        record.get("opp"), expected_mode="off"))
    return sorted(set(problems))


def _sum_telemetry(records: list[dict], side: str) -> dict:
    totals = Counter({field: 0 for field in S6_THROW_COUNTER_FIELDS})
    modes = set()
    for record in records:
        value = record[side]["s6_throw"]
        modes.add(value["mode"])
        totals.update({field: value[field]
                       for field in S6_THROW_COUNTER_FIELDS})
    if len(modes) != 1:
        raise S6ProtocolRefused("aggregate S6 mode drift")
    return {"mode": next(iter(modes)), **dict(totals)}


def _contrast(records: dict[str, list[dict]], a: str, b: str) -> dict:
    mean, half, clusters = paired_by_seed(records[a], records[b])
    return {
        "a": a, "b": b, "mean": mean, "half_width95": half,
        "lcb95": mean - half, "ucb95": mean + half, "clusters": clusters,
    }


def build_aggregate(records: dict[str, list[dict]], *,
                    expected_clusters: int) -> dict:
    expected_records = 2 * expected_clusters
    if set(records) != set(LABEL_ORDER) or any(
            len(records[label]) != expected_records for label in LABEL_ORDER):
        raise S6ProtocolRefused("S6 aggregate record population")
    keys = {
        label: [(record["seed"], record["flip"])
                for record in records[label]] for label in LABEL_ORDER
    }
    if any(len(set(value)) != expected_records for value in keys.values()) \
            or any(value != keys["champion"] for value in keys.values()):
        raise S6ProtocolRefused("S6 aggregate CRN/order population")
    run_ids = {record.get("run") for values in records.values()
               for record in values}
    if len(run_ids) != 1 or not all(isinstance(run, str) and run
                                    for run in run_ids):
        raise S6ProtocolRefused("S6 aggregate run identity")
    run_id = next(iter(run_ids))
    for label in LABEL_ORDER:
        for record, (seed, flip) in zip(
                records[label], keys["champion"], strict=True):
            problems = record_problems(
                record, expected_label=label, expected_seed=seed,
                expected_flip=flip, expected_run_id=run_id)
            if problems:
                raise S6ProtocolRefused(
                    f"invalid {label} record {seed}/{flip}: "
                    + "; ".join(problems))

    stats = {
        "treatment_champion": _contrast(records, "treatment", "champion"),
        "treatment_matched_null": _contrast(
            records, "treatment", "matched_null"),
        "matched_null_champion": _contrast(
            records, "matched_null", "champion"),
    }
    telemetry = {
        label: {"arm": _sum_telemetry(values, "arm"),
                "opp": _sum_telemetry(values, "opp")}
        for label, values in records.items()
    }
    treatment = telemetry["treatment"]["arm"]
    null = telemetry["matched_null"]["arm"]
    outcome_fields = (
        "banker", "attacker_points", "winner_team", "level_change", "won",
        "level_utility",
    )
    null_exact = all(
        tuple(left[field] for field in outcome_fields)
        == tuple(right[field] for field in outcome_fields)
        for left, right in zip(
            records["matched_null"], records["champion"], strict=True))
    exact_work = all(
        not counter_problems(
            record[side], expected_mode=(
                {"treatment": "treatment", "matched_null": "matched_null",
                 "champion": "off"}[record["label"]]
                if side == "arm" else "off"))
        for values in records.values() for record in values
        for side in ("arm", "opp"))
    criteria = {
        "treatment_champion_lcb_gt_zero":
            stats["treatment_champion"]["lcb95"] > 0,
        "treatment_matched_null_lcb_gt_zero":
            stats["treatment_matched_null"]["lcb95"] > 0,
        "matched_null_champion_exact_outcomes": null_exact,
        "treatment_triggered_both_roles": (
            treatment["attacker_triggers"] > 0
            and treatment["defender_triggers"] > 0),
        "matched_null_triggered_both_roles": (
            null["attacker_triggers"] > 0
            and null["defender_triggers"] > 0),
        "treatment_overrode": treatment["treatment_overrides"] > 0,
        "matched_null_dose_exact": (
            null["treatment_overrides"] == 0
            and null["matched_noops"] == null["searched_triggers"]),
        "all_records_exact_work": exact_work,
    }
    criteria["all"] = all(criteria.values())
    return {
        "schema": AGGREGATE_SCHEMA,
        "complete": True,
        "clusters": expected_clusters,
        "records_per_arm": expected_records,
        "labels": LABELS,
        "opponent": OPPONENT,
        "stats": stats,
        "telemetry": telemetry,
        "criteria": criteria,
        "status": ("AUTHORIZE_CONFIRM_PACKET_REVIEW" if criteria["all"]
                   else "SELECT_NONE"),
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
