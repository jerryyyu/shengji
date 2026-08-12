#!/usr/bin/env python3
"""Whole-round evaluation core for the pair-aware rollout experiment.

This module deliberately has no launch CLI.  It supplies deterministic
champion-anchored gameplay, exact-work validation, pair-aware telemetry, and
natural root-action dose accounting for a separately reviewed controller.
Nothing here grants execution, strength, promotion, or deployment authority.
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
from shengji.ai.pair_aware_rollout import (  # noqa: E402
    PAIR_AWARE_COUNTER_FIELDS,
    PAIR_AWARE_POLICIES,
    empty_pair_aware_telemetry,
    make_pair_aware_bot,
)
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.cards import make_deck  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.evaluation import counters  # noqa: E402


SCHEMA = "pair-aware-rollout-duel-core-v1"
CHAMPION = PAIR_AWARE_POLICIES["base"]
OPPONENT = CHAMPION
LABELS = {
    "treatment": PAIR_AWARE_POLICIES["treatment"],
    "matched_null": PAIR_AWARE_POLICIES["matched_null"],
    "champion": CHAMPION,
}
LABEL_ORDER = tuple(LABELS)
POLICY_ROLE_OFFSETS = (0, 500_000)
OPPONENT_ROLE_OFFSETS = (1_000_000, 1_500_000)
ROOT_WORLDS = 30
REPORT_WORLDS = 300
MAX_ATTACKER_POINTS = 4_120
MAX_LEVEL_CHANGE = 101
PHYSICAL_DECK = Counter(make_deck())


class PairProtocolRefused(RuntimeError):
    """The pair-aware runtime cannot support its bounded claim."""


def make_arm(label: str, seed: int):
    if label == "treatment":
        return make_pair_aware_bot(treatment=True, seed=seed)
    if label == "matched_null":
        return make_pair_aware_bot(treatment=False, seed=seed)
    if label == "champion":
        return make_bot(CHAMPION, seed=seed)
    raise PairProtocolRefused(f"unknown pair-aware arm {label!r}")


def pair_telemetry(bots: list, *, mode: str) -> dict[str, object]:
    if mode == "off":
        if any(hasattr(bot, "pair_aware_telemetry") for bot in bots):
            raise PairProtocolRefused(
                "feature-off arm unexpectedly exposes pair telemetry")
        return empty_pair_aware_telemetry(mode="off")
    totals = Counter({field: 0 for field in PAIR_AWARE_COUNTER_FIELDS})
    for bot in bots:
        payload = bot.pair_aware_telemetry()
        if payload.get("mode") != mode:
            raise PairProtocolRefused("pair-aware bot telemetry mode drift")
        totals.update({field: payload[field]
                       for field in PAIR_AWARE_COUNTER_FIELDS})
    merged = {
        "schema": "pair-aware-rollout-telemetry-v1",
        "mode": mode,
        "deterministic": True,
        "public_information_only": True,
        "exact_work_complete": True,
        **{field: int(totals[field]) for field in PAIR_AWARE_COUNTER_FIELDS},
    }
    problems = telemetry_problems(merged, expected_mode=mode)
    if problems:
        raise PairProtocolRefused(
            "invalid merged pair telemetry: " + "; ".join(problems))
    return merged


def _normalise_history(history: list) -> list[dict[str, object]]:
    return [
        {"seat": int(seat), "cards": list(cards)}
        for seat, cards in history
    ]


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
        "history": _normalise_history(log.history),
        "arm": {
            **counters(arm_bots),
            "pair_aware": pair_telemetry(arm_bots, mode=mode),
        },
        "opp": {
            **counters(opp_bots),
            "pair_aware": pair_telemetry(opp_bots, mode="off"),
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
        log = play_round(Game(random.Random(seed)), policies, record=True)
        records.append(_record(
            run_id, label, seed, flip, log, [a1, a2], [b1, b2]))
    return records


def telemetry_problems(value: object, *, expected_mode: str) -> list[str]:
    if not isinstance(value, dict):
        return ["pair telemetry is not an object"]
    expected_fields = {
        "schema", "mode", "deterministic", "public_information_only",
        "exact_work_complete", *PAIR_AWARE_COUNTER_FIELDS,
    }
    problems = []
    if set(value) != expected_fields:
        problems.append("pair telemetry field population")
    if (value.get("schema") != "pair-aware-rollout-telemetry-v1"
            or value.get("mode") != expected_mode
            or value.get("deterministic") is not True
            or value.get("public_information_only") is not True
            or value.get("exact_work_complete") is not True):
        problems.append("pair telemetry identity")
    if not all(
            isinstance(value.get(field), int)
            and not isinstance(value.get(field), bool)
            and value[field] >= 0 for field in PAIR_AWARE_COUNTER_FIELDS):
        problems.append("pair telemetry counters")
        return sorted(set(problems))
    if value["single_baseline_leads"] > value["lead_calls"]:
        problems.append("pair single-lead accounting")
    if value["promoted_boss_pairs"] > value["pair_candidates_checked"]:
        problems.append("pair promotion accounting")
    if value["ruff_safe_promoted_pairs"] > value["promoted_boss_pairs"]:
        problems.append("pair ruff-safety accounting")
    if value["triggers"] != value["opportunities"]:
        problems.append("pair opportunity accounting")
    if value["triggers"] != (
            value["attacker_triggers"] + value["defender_triggers"]):
        problems.append("pair role accounting")
    if value["point_pair_triggers"] > value["triggers"]:
        problems.append("pair point-trigger accounting")
    if expected_mode == "treatment":
        if (value["changes"] != value["triggers"]
                or value["matched_noops"] != 0):
            problems.append("pair treatment dose")
    elif expected_mode == "matched_null":
        if (value["changes"] != 0
                or value["matched_noops"] != value["triggers"]):
            problems.append("pair matched-null dose")
    elif any(value[field] != 0 for field in PAIR_AWARE_COUNTER_FIELDS):
        problems.append("feature-off pair telemetry is nonzero")
    return sorted(set(problems))


def counter_problems(value: object, *, expected_mode: str) -> list[str]:
    if not isinstance(value, dict):
        return ["counter payload is not an object"]
    expected_fields = set(counters([])) | {"pair_aware"}
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
        value.get("pair_aware"), expected_mode=expected_mode))
    return sorted(set(problems))


def _expected_round_outcome(*, banker: int,
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


def history_problems(history: object) -> list[str]:
    """Validate that a serialized history is one complete 100-card round.

    A throw or tractor can consume several cards per action, so a real round
    need not contain 100 action rows.  Completeness is instead proved from the
    physical cards: every seat must play exactly 25 cards, each trick must have
    four cyclic seats playing the same width, and no card code may exceed the
    two-deck inventory.
    """
    if (not isinstance(history, list) or not 4 <= len(history) <= 100
            or len(history) % 4 != 0):
        return ["record play history"]
    for row in history:
        if (not isinstance(row, dict) or set(row) != {"seat", "cards"}
                or isinstance(row.get("seat"), bool)
                or not isinstance(row.get("seat"), int)
                or not 0 <= row["seat"] < 4
                or not isinstance(row.get("cards"), list)
                or not row["cards"]
                or any(not isinstance(card, str)
                       or card not in PHYSICAL_DECK for card in row["cards"])):
            return ["record play history"]

    problems = []
    seat_cards = Counter()
    played_cards = Counter()
    for start in range(0, len(history), 4):
        trick = history[start:start + 4]
        leader = trick[0]["seat"]
        if [row["seat"] for row in trick] != [
                (leader + offset) % 4 for offset in range(4)]:
            problems.append("record play order")
        width = len(trick[0]["cards"])
        if any(len(row["cards"]) != width for row in trick):
            problems.append("record trick width")
        for row in trick:
            seat_cards[row["seat"]] += len(row["cards"])
            played_cards.update(row["cards"])
    if seat_cards != Counter({seat: 25 for seat in range(4)}):
        problems.append("record seat card completeness")
    if sum(played_cards.values()) != 100 or any(
            count > PHYSICAL_DECK[card]
            for card, count in played_cards.items()):
        problems.append("record physical deck completeness")
    return sorted(set(problems))


def record_problems(record: object, *, expected_label: str,
                    expected_seed: int, expected_flip: int,
                    expected_run_id: str) -> list[str]:
    if not isinstance(record, dict):
        return ["record is not an object"]
    expected_fields = {
        "run", "label", "policy", "opponent", "seed", "flip", "banker",
        "attacker_points", "winner_team", "level_change", "won",
        "level_utility", "history", "arm", "opp",
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
    history = record.get("history")
    problems.extend(history_problems(history))
    try:
        winner, gain = _expected_round_outcome(
            banker=record.get("banker"),
            attacker_points=record.get("attacker_points"))
    except ValueError as exc:
        problems.append(str(exc))
        winner = gain = None
    policy_team = 0 if expected_flip == 0 else 1
    won = int(winner == policy_team) if winner in (0, 1) else None
    utility = ((1 if won else -1) * max(1, gain)
               if won in (0, 1) and isinstance(gain, int) else None)
    if record.get("winner_team") != winner:
        problems.append("record winner")
    if record.get("level_change") != gain:
        problems.append("record level change")
    if (isinstance(record.get("won"), bool)
            or record.get("won") not in (0, 1)
            or record.get("won") != won
            or isinstance(record.get("level_utility"), bool)
            or record.get("level_utility") != utility):
        problems.append("record signed utility")
    mode = {"treatment": "treatment", "matched_null": "matched_null",
            "champion": "off"}[expected_label]
    problems.extend(f"arm: {problem}" for problem in counter_problems(
        record.get("arm"), expected_mode=mode))
    problems.extend(f"opp: {problem}" for problem in counter_problems(
        record.get("opp"), expected_mode="off"))
    return sorted(set(problems))


def _phase_band(play_index: int) -> str:
    trick_index = play_index // 4
    if trick_index <= 7:
        return "early"
    if trick_index <= 16:
        return "mid"
    return "late"


def natural_root_dose(treatment: dict, matched_null: dict) -> dict:
    """Compare only the shared trajectory, stopping at its first divergence."""
    for field in ("seed", "flip", "banker"):
        if treatment.get(field) != matched_null.get(field):
            raise PairProtocolRefused(f"pair dose {field} identity drift")
    left = treatment.get("history")
    right = matched_null.get("history")
    if history_problems(left) or history_problems(right):
        raise PairProtocolRefused("pair dose history population drift")
    divergence = next(
        (index for index, (a, b) in enumerate(zip(left, right))
         if a != b), None)
    if divergence is None:
        # Equal actions deterministically create equal engine states, so one
        # complete trajectory cannot end before the other without an earlier
        # differing action. Refuse instead of inventing an end-of-list dose.
        if len(left) != len(right):
            raise PairProtocolRefused(
                "equal shared action prefix has different terminal length")
        return {
            "shared_prefix_plays": len(left),
            "root_action_changed": False,
            "change_play_index": None,
            "change_phase": None,
            "change_role": None,
        }
    a = left[divergence]
    b = right[divergence]
    if a["seat"] != b["seat"]:
        raise PairProtocolRefused("shared trajectory changed acting seat")
    policy_team = 0 if treatment["flip"] == 0 else 1
    if a["seat"] % 2 != policy_team:
        raise PairProtocolRefused(
            "first pair-aware divergence was not a treatment-team action")
    banker_team = treatment["banker"] % 2
    return {
        "shared_prefix_plays": divergence,
        "root_action_changed": True,
        "change_play_index": divergence,
        "change_phase": _phase_band(divergence),
        "change_role": (
            "defender" if a["seat"] % 2 == banker_team else "attacker"),
    }


def matched_null_champion_problems(matched_null: dict,
                                   champion: dict) -> list[str]:
    fields = (
        "banker", "attacker_points", "winner_team", "level_change", "won",
        "level_utility", "history",
    )
    return ([] if all(matched_null.get(field) == champion.get(field)
                      for field in fields)
            else ["matched null differs from champion"])
