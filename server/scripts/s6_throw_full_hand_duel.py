#!/usr/bin/env python3
"""Whole-round evaluator core for the selective S6 full-hand gate.

The mature broad-S6 evaluator owns validation and aggregation.  This module
changes only the explicit experiment factories and policy labels, then
normalizes those labels while delegating every record/utility check to the
shared core.  It has no launch CLI or execution authority.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import s6_throw_duel as BASE  # noqa: E402
from shengji.ai.env import play_round  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.ai.throw_full_hand_gate import (  # noqa: E402
    S6_FULL_HAND_POLICIES,
    make_s6_full_hand_bot,
)
from shengji.engine.game import Game  # noqa: E402


SCHEMA = "s6-throw-full-hand-duel-core-v1"
AGGREGATE_SCHEMA = "s6-throw-full-hand-duel-aggregate-v1"
CHAMPION = S6_FULL_HAND_POLICIES["base"]
OPPONENT = CHAMPION
LABELS = {
    "treatment": S6_FULL_HAND_POLICIES["treatment"],
    "matched_null": S6_FULL_HAND_POLICIES["matched_null"],
    "champion": CHAMPION,
}
LABEL_ORDER = tuple(LABELS)


class FullHandProtocolRefused(RuntimeError):
    """The selective S6 population cannot support its stated comparison."""


def make_arm(label: str, seed: int):
    if label == "treatment":
        return make_s6_full_hand_bot(treatment=True, seed=seed)
    if label == "matched_null":
        return make_s6_full_hand_bot(treatment=False, seed=seed)
    if label == "champion":
        return make_bot(CHAMPION, seed=seed)
    raise FullHandProtocolRefused(f"unknown full-hand S6 arm {label!r}")


def _record(run_id: str, label: str, seed: int, flip: int, log,
            arm_bots: list, opp_bots: list) -> dict:
    record = BASE._record(
        run_id, label, seed, flip, log, arm_bots, opp_bots)
    record["policy"] = LABELS[label]
    return record


def play_arm_cluster(label: str, seed: int, *, run_id: str) -> list[dict]:
    records = []
    for flip in (0, 1):
        a1 = make_arm(label, seed + BASE.POLICY_ROLE_OFFSETS[0])
        a2 = make_arm(label, seed + BASE.POLICY_ROLE_OFFSETS[1])
        b1 = make_bot(OPPONENT, seed=seed + BASE.OPPONENT_ROLE_OFFSETS[0])
        b2 = make_bot(OPPONENT, seed=seed + BASE.OPPONENT_ROLE_OFFSETS[1])
        policies = ([a1, b1, a2, b2] if flip == 0
                    else [b1, a1, b2, a2])
        log = play_round(Game(random.Random(seed)), policies)
        records.append(_record(
            run_id, label, seed, flip, log, [a1, a2], [b1, b2]))
    return records


def _normalized_record(record: dict) -> dict:
    normalized = dict(record)
    label = normalized.get("label")
    if label in BASE.LABELS and normalized.get("policy") == LABELS[label]:
        normalized["policy"] = BASE.LABELS[label]
    return normalized


def record_problems(record: object, *, expected_label: str,
                    expected_seed: int, expected_flip: int,
                    expected_run_id: str) -> list[str]:
    if not isinstance(record, dict):
        return ["record is not an object"]
    if record.get("policy") != LABELS.get(expected_label):
        return ["record identity"]
    return BASE.record_problems(
        _normalized_record(record), expected_label=expected_label,
        expected_seed=expected_seed, expected_flip=expected_flip,
        expected_run_id=expected_run_id)


def counter_problems(value: object, *, expected_mode: str) -> list[str]:
    return BASE.counter_problems(value, expected_mode=expected_mode)


def build_aggregate(records: dict[str, list[dict]], *,
                    expected_clusters: int) -> dict:
    normalized = {
        label: [_normalized_record(record) for record in values]
        for label, values in records.items()
    }
    try:
        result = BASE.build_aggregate(
            normalized, expected_clusters=expected_clusters)
    except BASE.S6ProtocolRefused as exc:
        raise FullHandProtocolRefused(str(exc)) from exc
    result["schema"] = AGGREGATE_SCHEMA
    result["labels"] = LABELS
    result["opponent"] = OPPONENT
    return result
