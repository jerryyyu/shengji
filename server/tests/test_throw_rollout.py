"""Bounded actor-visible contracts for later S6 rollout sensitivity."""
from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import REGISTRY
from shengji.ai.throw_rollout import (S6_ROLLOUT_COUNTER_FIELDS,
                                      S6ThrowRolloutPolicy,
                                      make_s6_continuation_policy)
from shengji.engine.cards import Ordering
from shengji.engine.round import Round, Trick
from shengji.rl.replay_log import rebuild_round


FIXTURE = Path(__file__).with_name("data") / \
    "s6_kesp_throw_witnesses.v1.json"


def _kesp_state(witness_id: str):
    fixture = json.loads(FIXTURE.read_text())
    for round_record in fixture["rounds"]:
        witness = next((item for item in round_record["witnesses"]
                        if item["id"] == witness_id), None)
        if witness is None:
            continue
        rnd = rebuild_round(round_record["events"])
        target = tuple(sorted(witness["human_action"]))
        for event in round_record["events"]:
            if event["e"] != "play" or rnd.phase != "play":
                continue
            if (event["seat"] == witness["seat"]
                    and tuple(sorted(event["cards"])) == target):
                assert rnd.turn == witness["seat"]
                assert rnd.trick is not None and not rnd.trick.plays
                return rnd, witness
            rnd.play(event["seat"], list(event["cards"]))
    raise AssertionError(f"unknown KESP witness {witness_id}")


def _all_boss_throw_state() -> Round:
    """AA + K + QQ: three separate components, all publicly boss."""
    rnd = Round("7", 0, random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", "7")
    rnd.trump_suit = "H"
    rnd.trump_is_nt = False
    rnd.turn = 0
    rnd.hands = [
        ["CA", "CA", "CK", "CQ", "CQ"],
        ["S2"] * 5,
        ["D2"] * 5,
        ["H2"] * 5,
    ]
    rnd.buried = []
    rnd.history = []
    rnd.trick = Trick(leader=0)
    return rnd


def test_boss_near_mode_recovers_named_kesp_action_but_safe_mode_declines():
    rnd, witness = _kesp_state("KESP:r4:jerry:partial-near-boss")
    seat = witness["seat"]
    target = sorted(witness["human_action"])
    baseline = HeuristicBot().decide_play(rnd, seat)
    assert sorted(baseline) != target

    safe = S6ThrowRolloutPolicy(mode="safe")
    near = S6ThrowRolloutPolicy(mode="boss_near")
    assert safe.decide_play(copy.deepcopy(rnd), seat) == baseline
    assert sorted(near.decide_play(copy.deepcopy(rnd), seat)) == target

    safe_t = safe.telemetry()
    near_t = near.telemetry()
    assert safe_t["near_candidates"] >= 1 and safe_t["changes"] == 0
    assert near_t["near_candidates"] >= 1 and near_t["changes"] == 1
    assert near_t["early_changes"] == near_t["defender_changes"] == 1


def test_safe_mode_plays_a_publicly_proven_multi_component_boss_throw():
    rnd = _all_boss_throw_state()
    baseline = HeuristicBot().decide_play(rnd, 0)
    assert sorted(baseline) == ["CA", "CA"]
    policy = S6ThrowRolloutPolicy(mode="safe")
    assert sorted(policy.decide_play(rnd, 0)) == \
        ["CA", "CA", "CK", "CQ", "CQ"]
    record = policy.telemetry()
    assert record["safe_candidates"] >= 1
    assert record["eligible_leads"] == record["changes"] == 1
    assert record["defender_changes"] == record["early_changes"] == 1


def test_public_ruff_risk_declines_even_an_all_boss_bundle():
    rnd, witness = _kesp_state(
        "KESP:r5:jerry:boss-bundle-under-ruff-risk")
    seat = witness["seat"]
    baseline = HeuristicBot().decide_play(rnd, seat)
    for mode in ("safe", "boss_near"):
        policy = S6ThrowRolloutPolicy(mode=mode)
        assert policy.decide_play(copy.deepcopy(rnd), seat) == baseline
        telemetry = policy.telemetry()
        assert telemetry["ruff_risk_declines"] >= 1
        assert telemetry["changes"] == 0


def test_choice_is_invariant_to_sampled_hidden_hands_deck_and_kitty():
    rnd, witness = _kesp_state("KESP:r4:jerry:partial-near-boss")
    seat = witness["seat"]
    first = S6ThrowRolloutPolicy(mode="boss_near").decide_play(rnd, seat)
    altered = copy.deepcopy(rnd)
    for other in range(4):
        if other != seat:
            altered.hands[other] = ["BJ"] * len(altered.hands[other])
    altered.deck = ["LJ"] * len(altered.deck)
    altered.kitty = ["BJ"] * len(altered.kitty)
    second = S6ThrowRolloutPolicy(mode="boss_near").decide_play(
        altered, seat)
    assert second == first


def test_follow_is_literal_heuristic_and_delta_reconciles():
    rnd, witness = _kesp_state("KESP:r4:jerry:partial-near-boss")
    lead_seat = witness["seat"]
    rnd.play(lead_seat, list(witness["human_action"]))
    seat = rnd.turn
    assert seat is not None
    policy = S6ThrowRolloutPolicy(mode="boss_near")
    before = policy.snapshot()
    assert policy.decide_play(copy.deepcopy(rnd), seat) == \
        HeuristicBot().decide_play(copy.deepcopy(rnd), seat)
    dose = policy.delta(before)
    assert set(dose["delta"]) == set(S6_ROLLOUT_COUNTER_FIELDS)
    assert dose["delta"]["play_calls"] == 1
    assert dose["delta"]["lead_calls"] == dose["delta"]["changes"] == 0


def test_factory_preserves_literal_baseline_and_registers_no_policy():
    baseline = HeuristicBot()
    assert make_s6_continuation_policy(
        "baseline", baseline=baseline) is baseline
    assert isinstance(make_s6_continuation_policy(
        "safe", baseline=baseline), S6ThrowRolloutPolicy)
    with pytest.raises(ValueError, match="continuation mode"):
        make_s6_continuation_policy("recursive_mc", baseline=baseline)
    assert not any("s6-rollout" in name for name in REGISTRY)
