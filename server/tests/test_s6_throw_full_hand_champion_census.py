"""Score-free contracts for the live-champion S6 prevalence census."""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_full_hand_champion_census as S  # noqa: E402


def _shard(index: int, *, git: str = "test") -> dict:
    start = S.SEED0 + index * S.DEALS_PER_SHARD
    payload = {
        "schema": S.SHARD_SCHEMA,
        "git": git,
        "tree_dirty": False,
        "source_sha256s": S.source_sha256s(),
        "runtime": S.runtime_snapshot(),
        "design": {
            "policy": S.POLICY,
            "shard_index": index,
            "seed_start": start,
            "seed_end_exclusive": start + S.DEALS_PER_SHARD,
            "deals": S.DEALS_PER_SHARD,
            "score_free": True,
        },
        "counts": {
            "deals": S.DEALS_PER_SHARD,
            "leads": 100,
            "triggered_deals": 1,
            "triggered_leads": 1,
            "new_candidates": 1,
            "cells": {"attacker:late": 1},
            "by_hand_cards": {"4": 1},
        },
        "score_free": True,
        "outcomes_published": False,
        "strength_claim": False,
        "whole_game_execution_authorized": False,
        "production_deployment": False,
    }
    payload["internal_sha256"] = S.stable_digest(payload)
    return payload


def test_design_is_bounded_parallel_and_score_free():
    assert S.POLICY == "mc-s0-report-lcb"
    assert S.SEED0 == 438_000_000
    assert S.SHARDS == 8
    assert S.DEALS_PER_SHARD == 64
    assert S.TOTAL_DEALS == 512


def test_aggregate_recomputes_complete_disjoint_population():
    payload = S.aggregate_payload(
        [_shard(index) for index in range(S.SHARDS)], expected_git="test")
    assert payload["counts"]["deals"] == 512
    assert payload["counts"]["triggered_deals"] == 8
    assert payload["counts"]["triggered_leads"] == 8
    assert payload["rates"]["triggered_deals"] == 8 / 512
    assert payload["score_free"] is True
    assert payload["outcomes_published"] is False
    assert payload["strength_claim"] is False
    assert payload["whole_game_execution_authorized"] is False
    assert S.score_free_problems(payload) == []


def test_aggregate_refuses_seed_overlap_even_with_forged_self_hash():
    shards = [_shard(index) for index in range(S.SHARDS)]
    bad = deepcopy(shards[1])
    bad["design"]["seed_start"] = S.SEED0
    bad.pop("internal_sha256")
    bad["internal_sha256"] = S.stable_digest(bad)
    shards[1] = bad
    with pytest.raises(S.CensusRefused, match="shard 1 drift"):
        S.aggregate_payload(shards, expected_git="test")


def test_score_free_validator_rejects_nested_outcome():
    value = {"score_free": True, "outcomes_published": False,
             "hidden": {"winner_team": 1}}
    assert S.score_free_problems(value) == [
        "forbidden field hidden.winner_team"]
