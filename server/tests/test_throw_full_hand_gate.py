"""Contracts for the actor-visible S6 full-hand search gate."""
from __future__ import annotations

import sys
from pathlib import Path

from shengji.ai.registry import REGISTRY
from shengji.ai.throw_full_hand_gate import (
    FULL_HAND_BOSS_NEAR_GATE,
    S6_FULL_HAND_POLICIES,
    make_s6_full_hand_bot,
)
from shengji.engine.ballot import mc_ballot


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_exact_shape_exploration as EXACT


def _state(seed: int, tricks: int, seat: int):
    rnd, actors = EXACT._start_round(seed)
    while rnd.phase == "play":
        if (rnd.turn == seat and len(rnd.history) == tricks
                and not rnd.trick.plays):
            return rnd
        actor = rnd.turn
        rnd.play(actor, actors[actor].decide_play(rnd, actor))
    raise AssertionError("named state disappeared")


def test_factory_is_explicit_unregistered_and_champion_anchored():
    treatment = make_s6_full_hand_bot(treatment=True, seed=7)
    null = make_s6_full_hand_bot(treatment=False, seed=7)
    assert S6_FULL_HAND_POLICIES["treatment"] not in REGISTRY
    assert S6_FULL_HAND_POLICIES["matched_null"] not in REGISTRY
    assert treatment.s6_throw_search_gate == FULL_HAND_BOSS_NEAR_GATE
    assert null.s6_throw_search_gate == FULL_HAND_BOSS_NEAR_GATE
    assert mc_ballot(treatment).digest == mc_ballot(null).digest


def test_gate_keeps_named_full_hand_winner_in_second_search():
    rnd = _state(432_000_152, 15, 3)
    bot = make_s6_full_hand_bot(treatment=True, seed=7)
    plan = bot._source_plan(rnd, 3)
    additions = plan["widened_candidates"][plan["base_count"]:]
    assert additions == (("H5", "H8", "HK", "HQ"),)
    assert plan["search_gate"] == FULL_HAND_BOSS_NEAR_GATE
    assert plan["gated_added_count"] == 1
    assert len(plan["ballot"].candidates) >= 1


def test_gate_rejects_partial_boss_near_without_hiding_source():
    rnd = _state(432_000_050, 19, 0)
    bot = make_s6_full_hand_bot(treatment=True, seed=7)
    plan = bot._source_plan(rnd, 0)
    assert plan["broad_added_count"] >= 1
    assert plan["gated_added_count"] == 0
    assert plan["added_indices"] == ()
    assert any(candidate.cards == ("C8", "C9", "CQ")
               for candidate in plan["ballot"].candidates)
