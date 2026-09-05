"""Executable contract for the ``shengji.teacher_v1`` module (streams, deal
split, state replay, targets, tensor validation).

These tests were split out of ``test_teacher_v1.py`` on 2026-09-05 when the
teacher_v1 campaign scripts were removed; the module itself stays because
``shengji.rl.value_afterstate`` imports it.
"""
from __future__ import annotations

import random

import pytest

from shengji.ai.registry import make_bot
from shengji.engine.game import Game
from shengji.teacher_v1 import (EXPERIMENT, SEED_START, derive_stream,
                                replay_state, split_for_deal, targets,
                                tensor_problems)


def raw_state(seed=SEED_START + 123, *, follow=False):
    rnd = Game(random.Random(seed)).start_round()
    bots = [make_bot("smart", seed=seed + seat) for seat in range(4)]
    declarations = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({"stage": "deal", "deal_pos": rnd._deal_pos,
                                 "seat": seat, "cards": list(cards)})
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({"stage": "final", "deal_pos": rnd._deal_pos,
                                 "seat": seat, "cards": list(cards)})
    rnd.finalize_declare()
    assert rnd.banker is not None
    buried = bots[rnd.banker].decide_bury(rnd, rnd.banker)
    final = None if rnd.declaration is None else {
        "seat": rnd.declaration["seat"], "cards": list(rnd.declaration["cards"]),
        "strength": rnd.declaration["strength"],
    }
    setup = {
        "deck": list(rnd.deck), "initial_banker": None,
        "trump_rank": rnd.trump_rank, "banker": rnd.banker,
        "trump_suit": rnd.trump_suit, "trump_is_nt": rnd.trump_is_nt,
        "declarations": declarations, "final_declaration": final,
        "buried": list(buried),
    }
    rnd.bury(rnd.banker, buried)
    plays = []
    if follow:
        seat = rnd.turn
        play = bots[seat].decide_play(rnd, seat)
        rnd.play(seat, play)
        plays.append({"seat": seat, "cards": list(play)})
    seat = rnd.turn
    row = {
        "schema": STATE_SCHEMA, "experiment_id": EXPERIMENT,
        "seed": seed, "seat": seat, "ply": len(plays), "trick": 0,
        "phase": "early", "decision": "follow" if follow else "lead",
        "role": "attacker" if rnd.is_attacker(seat) else "defender",
        "split": split_for_deal(EXPERIMENT, seed),
        "selector_pool": "representative", "kind": "representative",
        "selection_probability": 0.5, "setup": setup, "plays": plays,
    }
    row["state_id"] = f"{seed}:{len(plays)}:{seat}"
    return row


def test_named_streams_are_replayable_and_domain_separated():
    identity = dict(experiment_id=EXPERIMENT, deal_seed=SEED_START + 1,
                    state_id="s", purpose="belief", fold="selection")
    assert derive_stream(**identity) == derive_stream(**identity)
    assert derive_stream(**identity)["seed"] != derive_stream(
        **{**identity, "fold": "report"})["seed"]
    with pytest.raises(ValueError, match="common across candidates"):
        derive_stream(**identity, candidate=2)


def test_split_is_deal_disjoint_and_approximately_70_15_15():
    got = [split_for_deal(EXPERIMENT, SEED_START + i) for i in range(2000)]
    assert 1300 < got.count("train") < 1500
    assert 240 < got.count("tune") < 360
    assert 240 < got.count("holdout") < 360


@pytest.mark.parametrize("follow", [False, True])
def test_teacher_state_round_trips_lead_and_follow(follow):
    row = raw_state(follow=follow)
    rnd = replay_state(row)
    assert rnd.turn == row["seat"]
    assert bool(rnd.trick.plays) is follow


def test_targets_keep_attacker_raw_and_flip_acting_team():
    assert targets(80, True) == {
        "attacker_points": 80, "signed_points": 80,
        "bracket": 0, "signed_level_utility": 0.5,
    }
    assert targets(0, False) == {
        "attacker_points": 0, "signed_points": 0,
        "bracket": -3, "signed_level_utility": 3.5,
    }
    assert targets(120, False)["signed_level_utility"] == -1.5
    # House rules are uncapped.  A +3 training clip, if added later, must be a
    # separately named target rather than silently changing this teacher.
    assert targets(240, True)["bracket"] == 4
    assert targets(240, True)["signed_level_utility"] == 4.5


def test_tensor_validator_requires_full_world_by_candidate_shape():
    fold = {
        "requested_worlds": 2, "draw_ids": ["a", "b"],
        "world_digests": ["x", "y"],
        "tensor": {name: [[0, 1], [2, 3]] for name in (
            "attacker_points", "signed_points", "bracket",
            "signed_level_utility")},
    }
    assert tensor_problems(fold, 2, 2) == []
    fold["tensor"]["bracket"][1].pop()
    assert any("bracket tensor shape" in p for p in tensor_problems(fold, 2, 2))

