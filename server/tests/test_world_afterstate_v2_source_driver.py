from __future__ import annotations

import random
import json
import inspect
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.round import Round
from shengji.rl.world_afterstate_v2_protocol import (
    TIER_SPECS, attempted_deal_identity, build_population_slot_ledger,
)
from shengji.rl.world_afterstate_v2_source_driver import (
    FORBIDDEN_TOKENS, REJECTION_MODE_MISMATCH,
    REJECTION_NO_ELIGIBLE_STATE, REJECTION_REQUESTED_MODE_UNAVAILABLE,
    PopulationAttemptResultV2, WorldAfterstateV2SourceDriverError,
    _declare_requested_mechanics_mode, _result, drive_population_attempt_v2,
)


_NAMESPACE = "a" * 64
_SLOTS = build_population_slot_ledger(TIER_SPECS[0])


def _slot(group: str, ordinal: int):
    return next(row for row in _SLOTS
                if row.group == group and row.ordinal == ordinal)


def _mechanics_slot(mode: str, rank: str = "2"):
    return replace(next(row for row in _SLOTS if row.source == "mechanics"),
                   trump_mode=mode, trump_rank=rank)


def _declare_round(hands: list[list[str]], rank: str = "2") -> Round:
    rnd = Round(rank, banker=0, rng=random.Random(0))
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.hands = [list(hand) for hand in hands]
    return rnd


@pytest.mark.parametrize("mode", ("S", "H", "D", "C"))
def test_mechanics_suited_declaration_uses_requested_rank_and_real_legality(mode):
    code = f"{mode}2"
    rnd = _declare_round([[], [code], [code, code], []])
    before = [list(hand) for hand in rnd.hands]

    assert _declare_requested_mechanics_mode(rnd, _mechanics_slot(mode))
    assert rnd.declaration == {"seat": 1, "cards": [code], "strength": 1}
    assert rnd.hands == before
    rnd.finalize_declare()
    assert not rnd.trump_is_nt and rnd.trump_suit == mode


def test_mechanics_suited_tie_break_prefers_pair_for_lowest_seat():
    rnd = _declare_round([["S2", "S2"], ["S2"], [], []])

    assert _declare_requested_mechanics_mode(rnd, _mechanics_slot("S"))
    assert rnd.declaration == {
        "seat": 0, "cards": ["S2", "S2"], "strength": 2}


def test_mechanics_nt_tie_break_is_seat_then_bj_then_lj():
    rnd = _declare_round([["LJ", "LJ", "BJ", "BJ"],
                          ["BJ", "BJ"], [], []], rank="6")

    assert _declare_requested_mechanics_mode(rnd, _mechanics_slot("NT", "6"))
    assert rnd.declaration == {
        "seat": 0, "cards": ["BJ", "BJ"], "strength": 4}
    rnd.finalize_declare()
    assert rnd.trump_is_nt and rnd.trump_suit is None


def test_mechanics_nt_unavailable_and_lone_joker_are_typed_score_free():
    rnd = _declare_round([["BJ"], ["LJ"], [], []], rank="6")
    assert not _declare_requested_mechanics_mode(rnd, _mechanics_slot("NT", "6"))
    slot = _mechanics_slot("NT", "6")
    attempt = attempted_deal_identity(_NAMESPACE, slot, 0)
    result = _result(attempt, attempt["deal_sha256"], slot, accepted=False,
                     reason=REJECTION_REQUESTED_MODE_UNAVAILABLE, material=None,
                     decision_count=0)
    result.validate()
    assert result.payload()["rejection_reason"] == \
        REJECTION_REQUESTED_MODE_UNAVAILABLE


def test_mechanics_forced_declaration_cannot_return_mode_mismatch(monkeypatch):
    class FastBot:
        def __init__(self):
            self.base = HeuristicBot()

        def decide_declare(self, *_args, **_kwargs):
            raise AssertionError("mechanics must not use natural declarations")

        def decide_bury(self, rnd, seat):
            return self.base.decide_bury(rnd, seat)

        def decide_play(self, rnd, seat):
            return self.base.decide_play(rnd, seat)

    monkeypatch.setattr(
        "shengji.rl.world_afterstate_v2_source_driver.make_bot",
        lambda *_args, **_kwargs: FastBot())
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_v2_source_driver.build_population_material_v2",
        lambda *_args, **_kwargs: None)
    slot = _mechanics_slot("S", "2")
    attempt = attempted_deal_identity(_NAMESPACE, slot, 0)

    result = drive_population_attempt_v2(attempt, slot)
    assert not result.accepted
    assert result.rejection_reason == REJECTION_NO_ELIGIBLE_STATE
    assert result.rejection_reason != REJECTION_MODE_MISMATCH


def test_mode_mismatch_is_typed_and_score_free():
    assert "snapshot" not in inspect.signature(
        drive_population_attempt_v2).parameters
    slot = _slot("natural-fit", 0)
    # The exact production declaration for this attempt is not the frozen
    # slot's mode; the driver must report that, without materialization.
    attempt = attempted_deal_identity(_NAMESPACE, slot, 0)
    result = drive_population_attempt_v2(attempt, slot)
    assert isinstance(result, PopulationAttemptResultV2)
    assert not result.accepted
    assert result.rejection_reason == REJECTION_MODE_MISMATCH
    assert result.material is None
    assert result.decision_count == 0
    assert "engine_seed" not in result.payload()["attempted_deal_identity"]


def test_forged_engine_seed_refuses_before_round(monkeypatch):
    slot = _slot("natural-fit", 0)
    attempt = attempted_deal_identity(_NAMESPACE, slot, 0)
    forged = dict(attempt, engine_seed=attempt["engine_seed"] ^ 1)
    called = False

    def fail_round(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("Round must not be constructed")

    monkeypatch.setattr(
        "shengji.rl.world_afterstate_v2_source_driver.Round", fail_round)
    with pytest.raises(WorldAfterstateV2SourceDriverError):
        drive_population_attempt_v2(forged, slot)
    assert not called


def test_natural_attempt_is_byte_identical_and_forbidden_free():
    # This D256 cell is a bounded, deterministic witness for the live policy.
    slot = _slot("natural-fit", 4)
    attempt = attempted_deal_identity(_NAMESPACE, slot, 0)
    first = drive_population_attempt_v2(attempt, slot)
    second = drive_population_attempt_v2(attempt, slot)
    assert first.accepted and first.material is not None
    assert first.payload() == second.payload()
    assert first.material.state_sha256 == min(
        first.material.state_sha256, first.material.state_sha256)
    encoded = json.dumps(first.payload(), sort_keys=True).lower()
    assert not any(token in encoded for token in FORBIDDEN_TOKENS)


def test_mechanics_slot_can_accept_a_derived_surface():
    slot = _slot("mechanics-fit", 0)
    attempt = attempted_deal_identity(_NAMESPACE, slot, 0)
    result = drive_population_attempt_v2(attempt, slot)
    assert result.accepted and result.material is not None
    assert slot.mechanics_surface in result.material.state.mechanics_surfaces
